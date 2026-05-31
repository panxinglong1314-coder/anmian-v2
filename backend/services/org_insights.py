"""
B2B 团队健康洞察聚合层 (阶段 2)

设计要点:
- **k-anonymity 守护**: 默认 k_min=5。任何聚合接口先调 k_anonymous_aggregate
  检查队列人数,< k_min 则返回 {"status":"insufficient_data","n":N,"k_min":K}
  而非真实数字。运营可在 admin/abconfig 调阈值。
- **org / team scope**: 所有 metric 严格只扫该 org_id 下的 user_id 集合
  (来自 services.org.list_org_users / list_team_users),从不跨 org 泄漏。
- **不返身份字段**: 任何端点的返回 dict **绝不包含 user_id**。
  内部计算可见,但响应层过滤掉。
- **只读**: 本模块只读取 Redis / conversation_logs,不写。

数据源:
- sleep_diary:{user_id}:{date}       hash w/ se/tst/sol/waso/quality
- user:memory:{user_id}              json w/ triggers, session_count
- user_profile:{user_id}             json w/ avg_anxiety_recovery_turns
- evaluation_tracking/bias_YYYYMM.jsonl  含 auto_empathy / microskills_used
- crisis_alert:{event_id}            hash w/ org_id (v2.5 起)
- conversation_logs/sess_*.json      w/ outcome
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Iterable

from infra.redis_client import redis_client


DEFAULT_K_MIN = 5
LOG_DIR = Path(__file__).parent.parent.parent / "conversation_logs"
EVAL_DIR = Path(__file__).parent.parent.parent / "evaluation_tracking"


# =========================================================================
# k-anonymity gate
# =========================================================================

def k_anonymous_aggregate(
    user_ids: List[str],
    metric_fn: Callable[[List[str]], Dict[str, Any]],
    k_min: int = DEFAULT_K_MIN,
) -> Dict[str, Any]:
    """统一聚合守护。若样本数 < k_min 直接拒绝返回真实数据。

    Returns:
        若 N >= k_min: {"status":"ok", "n":N, **metric_fn(user_ids)}
        否则: {"status":"insufficient_data", "n":N, "k_min":k_min}
    """
    n = len(user_ids)
    if n < k_min:
        return {"status": "insufficient_data", "n": n, "k_min": k_min}
    try:
        metric = metric_fn(user_ids) or {}
    except Exception as e:
        return {"status": "error", "n": n, "error": str(e)}
    # 保险: 剥掉任何意外混入的 user_id 字段
    metric = _strip_user_identity(metric)
    return {"status": "ok", "n": n, **metric}


def _strip_user_identity(d: Any) -> Any:
    """递归从字典/列表中删除 user_id / openid / email / session_id 字段。"""
    if isinstance(d, dict):
        return {
            k: _strip_user_identity(v)
            for k, v in d.items()
            if k not in ("user_id", "openid", "email", "session_id")
        }
    if isinstance(d, list):
        return [_strip_user_identity(x) for x in d]
    return d


# =========================================================================
# Period parser
# =========================================================================

def parse_period(period: str) -> timedelta:
    """支持 '7d' / '30d' / '90d' 等;非法默认 30 天。"""
    if not period or not isinstance(period, str):
        return timedelta(days=30)
    period = period.strip().lower()
    try:
        if period.endswith("d"):
            return timedelta(days=int(period[:-1]))
        if period.endswith("w"):
            return timedelta(weeks=int(period[:-1]))
    except Exception:
        pass
    return timedelta(days=30)


def _within_period(iso_or_ts: str, cutoff: datetime) -> bool:
    if not iso_or_ts:
        return False
    try:
        dt = datetime.fromisoformat(iso_or_ts.replace("Z", "").split("+")[0])
        return dt >= cutoff
    except Exception:
        return False


# =========================================================================
# Per-user data loaders (内部)
# =========================================================================

def _get(key: str) -> Optional[str]:
    if not redis_client:
        return None
    v = redis_client.get(key)
    if isinstance(v, bytes):
        v = v.decode()
    return v


def _hgetall(key: str) -> Dict[str, str]:
    if not redis_client:
        return {}
    raw = redis_client.hgetall(key) or {}
    out = {}
    for k, v in raw.items():
        if isinstance(k, bytes): k = k.decode()
        if isinstance(v, bytes): v = v.decode()
        out[k] = v
    return out


def _load_user_memory(user_id: str) -> Dict[str, Any]:
    raw = _get(f"user:memory:{user_id}")
    if not raw:
        return {}
    try: return json.loads(raw)
    except Exception: return {}


def _load_user_profile(user_id: str) -> Dict[str, Any]:
    raw = _get(f"user_profile:{user_id}")
    if not raw:
        return {}
    try: return json.loads(raw)
    except Exception: return {}


def _load_sleep_entries(user_id: str, cutoff: datetime) -> List[Dict[str, Any]]:
    """扫该用户最近 N 天的 sleep_diary 条目。"""
    if not redis_client:
        return []
    entries = []
    pattern = f"sleep_diary:{user_id}:*"
    for key in redis_client.scan_iter(match=pattern, count=200):
        if isinstance(key, bytes): key = key.decode()
        date_str = key.rsplit(":", 1)[-1]
        try:
            dt = datetime.fromisoformat(date_str)
            if dt < cutoff:
                continue
        except Exception:
            continue
        h = _hgetall(key)
        if not h:
            continue
        try:
            entries.append({
                "date": date_str,
                # SE 在 Redis 存 0-1 fraction,这里维持 fraction,展示层 ×100
                "se": float(h.get("se") or h.get("SE") or 0),
                "tst": float(h.get("tst") or h.get("TST") or 0),
                "sol": float(h.get("sol") or h.get("SOL") or 0),
                "waso": float(h.get("waso") or h.get("WASO") or 0),
                "quality": float(h.get("quality") or h.get("sleep_quality") or 0),
            })
        except Exception:
            continue
    return entries


# =========================================================================
# 6 个聚合 metric_fn
# =========================================================================

def metric_sleep(user_ids: List[str], cutoff: datetime) -> Dict[str, Any]:
    """睡眠聚合: TST / SE / SE<70% 占比 / TST<6h 占比 / SE 分布。"""
    all_entries = []
    users_with_data = 0
    for uid in user_ids:
        entries = _load_sleep_entries(uid, cutoff)
        if entries:
            users_with_data += 1
            all_entries.extend(entries)
    if not all_entries:
        return {"users_with_data": 0, "avg_tst_hours": None, "avg_se_pct": None,
                "low_se_ratio": None, "short_tst_ratio": None, "se_distribution": {}}
    tst_list = [e["tst"] for e in all_entries if e["tst"] > 0]
    se_list = [e["se"] for e in all_entries if e["se"] > 0]
    low_se = sum(1 for s in se_list if s < 0.70)
    short_tst = sum(1 for t in tst_list if t < 6.0)
    # SE 分布(5 桶)
    buckets = {"<60%": 0, "60-70%": 0, "70-80%": 0, "80-90%": 0, ">=90%": 0}
    for s in se_list:
        pct = s * 100
        if pct < 60: buckets["<60%"] += 1
        elif pct < 70: buckets["60-70%"] += 1
        elif pct < 80: buckets["70-80%"] += 1
        elif pct < 90: buckets["80-90%"] += 1
        else: buckets[">=90%"] += 1
    return {
        "users_with_data": users_with_data,
        "total_entries": len(all_entries),
        "avg_tst_hours": round(sum(tst_list) / len(tst_list), 2) if tst_list else None,
        "avg_se_pct": round(sum(se_list) / len(se_list) * 100, 1) if se_list else None,
        "low_se_ratio": round(low_se / len(se_list) * 100, 1) if se_list else None,
        "short_tst_ratio": round(short_tst / len(tst_list) * 100, 1) if tst_list else None,
        "se_distribution": buckets,
    }


def metric_anxiety(user_ids: List[str], cutoff: datetime) -> Dict[str, Any]:
    """焦虑聚合: 平均 anxiety_recovery_turns / momentum 分布。"""
    recovery_turns = []
    momentum_count = {"improving": 0, "stable": 0, "deteriorating": 0, "unknown": 0}
    users_with_data = 0
    for uid in user_ids:
        prof = _load_user_profile(uid)
        avg = prof.get("avg_anxiety_recovery_turns")
        if avg and avg > 0:
            recovery_turns.append(float(avg))
            users_with_data += 1
        # momentum trend (from user:memory.last_session_*)
        mem = _load_user_memory(uid)
        mom = (mem.get("last_session_momentum") or "unknown").lower()
        if mom not in momentum_count:
            mom = "unknown"
        momentum_count[mom] += 1
    return {
        "users_with_data": users_with_data,
        "avg_recovery_turns": round(sum(recovery_turns) / len(recovery_turns), 2) if recovery_turns else None,
        "momentum_distribution": momentum_count,
    }


def metric_worry_domains(user_ids: List[str], cutoff: datetime) -> Dict[str, Any]:
    """worry 域聚合: 各 domain 出现次数总计 + 占比。"""
    domain_counts: Dict[str, int] = {}
    users_with_data = 0
    for uid in user_ids:
        mem = _load_user_memory(uid)
        triggers = mem.get("triggers") or {}
        if not triggers:
            continue
        users_with_data += 1
        for d, c in triggers.items():
            try:
                domain_counts[d] = domain_counts.get(d, 0) + int(c)
            except Exception:
                continue
    total = sum(domain_counts.values())
    distribution = {d: round(c / total * 100, 1) for d, c in domain_counts.items()} if total else {}
    sorted_top = sorted(domain_counts.items(), key=lambda kv: -kv[1])
    top_domain = sorted_top[0][0] if sorted_top else None
    return {
        "users_with_data": users_with_data,
        "total_worry_records": total,
        "distribution_pct": distribution,
        "top_domain": top_domain,
        "raw_counts": domain_counts,
    }


def metric_crisis(user_ids: List[str], cutoff: datetime, org_id: str = "") -> Dict[str, Any]:
    """危机事件聚合: 各 level 计数 + 趋势,**绝不返 user_id / message**。

    扫 crisis_alerts:pending + resolved 两个 zset,按 org_id 过滤,
    再按时间窗口过滤。
    """
    if not redis_client:
        return {"high": 0, "medium": 0, "low": 0, "total": 0, "weekly_trend": []}
    counts = {"high": 0, "medium": 0, "low": 0}
    user_ids_set = set(user_ids)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    # 收集 event_id, 用 byscore 过滤时间
    seen = set()
    for key in ("crisis_alerts:pending", "crisis_alerts:resolved"):
        for member in redis_client.zrangebyscore(key, cutoff_ms, "+inf"):
            if isinstance(member, bytes): member = member.decode()
            if member in seen: continue
            seen.add(member)
            ev = _hgetall(f"crisis_alert:{member}")
            if not ev: continue
            # 双重过滤: 优先看事件里的 org_id (v2.5 起带);老事件 fallback 到 user_id ∈ org users
            ev_org = ev.get("org_id", "")
            if ev_org and ev_org != org_id:
                continue
            if not ev_org and ev.get("user_id", "") not in user_ids_set:
                continue
            level = ev.get("level", "low").lower()
            if level in counts:
                counts[level] += 1
    total = sum(counts.values())
    return {
        **counts,
        "total": total,
        # 简版趋势:按周聚合(留前端画)
        "weekly_trend": [],  # 留空,前端可以 query period=7d 多次得到趋势
    }


def metric_engagement(user_ids: List[str], cutoff: datetime, org_id: str = "") -> Dict[str, Any]:
    """参与度聚合: 活跃员工/总人数 + 会话总数 + 完成率。"""
    total_users = len(user_ids)
    active_users = 0
    total_sessions = 0
    for uid in user_ids:
        mem = _load_user_memory(uid)
        last_time = mem.get("last_session_time", "")
        sc = int(mem.get("session_count", 0) or 0)
        if last_time and _within_period(last_time, cutoff):
            active_users += 1
        total_sessions += sc
    activation_rate = round(active_users / total_users * 100, 1) if total_users else 0

    # 从 conversation_logs 算 closure 完成率(仅 org 内 user_ids)
    closure = interrupted = idle = sleep_rep = unknown = 0
    if LOG_DIR.exists():
        user_set = set(user_ids)
        for fp in LOG_DIR.glob("sess_*.json"):
            try:
                mtime = datetime.fromtimestamp(fp.stat().st_mtime)
                if mtime < cutoff: continue
                d = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                continue
            if d.get("user_id") not in user_set:
                continue
            out = (d.get("outcome") or "unknown").lower()
            if out == "completed_closure": closure += 1
            elif out == "sleep_reported": sleep_rep += 1
            elif out == "interrupted": interrupted += 1
            elif out == "idle_timeout": idle += 1
            else: unknown += 1
    n_outcomes = closure + interrupted + idle + sleep_rep + unknown
    completion_rate = round((closure + sleep_rep) / n_outcomes * 100, 1) if n_outcomes else None
    return {
        "total_users": total_users,
        "active_users": active_users,
        "activation_rate": activation_rate,
        "total_sessions": total_sessions,
        "completion_rate": completion_rate,
        "outcome_distribution": {
            "completed_closure": closure,
            "sleep_reported": sleep_rep,
            "interrupted": interrupted,
            "idle_timeout": idle,
            "unknown": unknown,
        },
    }


def metric_overview(user_ids: List[str], cutoff: datetime, org_id: str = "") -> Dict[str, Any]:
    """总览: 把其它指标的核心点聚到一屏。"""
    eng = metric_engagement(user_ids, cutoff, org_id)
    sleep = metric_sleep(user_ids, cutoff)
    anx = metric_anxiety(user_ids, cutoff)
    worry = metric_worry_domains(user_ids, cutoff)
    crisis = metric_crisis(user_ids, cutoff, org_id)
    return {
        "engagement": {
            "active_users": eng["active_users"],
            "total_users": eng["total_users"],
            "activation_rate": eng["activation_rate"],
            "completion_rate": eng["completion_rate"],
        },
        "sleep": {
            "avg_se_pct": sleep["avg_se_pct"],
            "avg_tst_hours": sleep["avg_tst_hours"],
            "low_se_ratio": sleep["low_se_ratio"],
            "users_with_data": sleep["users_with_data"],
        },
        "anxiety": {
            "avg_recovery_turns": anx["avg_recovery_turns"],
            "momentum_distribution": anx["momentum_distribution"],
        },
        "worry": {
            "top_domain": worry["top_domain"],
            "total_records": worry["total_worry_records"],
        },
        "crisis": {
            "total": crisis["total"],
            "high": crisis["high"],
            "medium": crisis["medium"],
            "low": crisis["low"],
        },
    }


# =========================================================================
# 公共门面: 6 个 insights
# =========================================================================

def get_users_for_scope(org_id: str, team_id: Optional[str] = None) -> List[str]:
    """按 scope 拉成员列表。"""
    from services.org import list_org_users, list_team_users
    if team_id:
        return list_team_users(team_id)
    return list_org_users(org_id)


def insights_overview(org_id: str, team_id: Optional[str] = None,
                       period: str = "30d", k_min: int = DEFAULT_K_MIN) -> Dict[str, Any]:
    user_ids = get_users_for_scope(org_id, team_id)
    cutoff = datetime.now() - parse_period(period)
    return k_anonymous_aggregate(
        user_ids,
        lambda uids: metric_overview(uids, cutoff, org_id),
        k_min=k_min,
    )


def insights_sleep(org_id: str, team_id: Optional[str] = None,
                    period: str = "30d", k_min: int = DEFAULT_K_MIN) -> Dict[str, Any]:
    user_ids = get_users_for_scope(org_id, team_id)
    cutoff = datetime.now() - parse_period(period)
    return k_anonymous_aggregate(
        user_ids,
        lambda uids: metric_sleep(uids, cutoff),
        k_min=k_min,
    )


def insights_anxiety(org_id: str, team_id: Optional[str] = None,
                      period: str = "30d", k_min: int = DEFAULT_K_MIN) -> Dict[str, Any]:
    user_ids = get_users_for_scope(org_id, team_id)
    cutoff = datetime.now() - parse_period(period)
    return k_anonymous_aggregate(
        user_ids,
        lambda uids: metric_anxiety(uids, cutoff),
        k_min=k_min,
    )


def insights_worry(org_id: str, team_id: Optional[str] = None,
                    period: str = "30d", k_min: int = DEFAULT_K_MIN) -> Dict[str, Any]:
    user_ids = get_users_for_scope(org_id, team_id)
    cutoff = datetime.now() - parse_period(period)
    return k_anonymous_aggregate(
        user_ids,
        lambda uids: metric_worry_domains(uids, cutoff),
        k_min=k_min,
    )


def insights_crisis(org_id: str, team_id: Optional[str] = None,
                     period: str = "30d", k_min: int = DEFAULT_K_MIN) -> Dict[str, Any]:
    user_ids = get_users_for_scope(org_id, team_id)
    cutoff = datetime.now() - parse_period(period)
    return k_anonymous_aggregate(
        user_ids,
        lambda uids: metric_crisis(uids, cutoff, org_id),
        k_min=k_min,
    )


def insights_engagement(org_id: str, team_id: Optional[str] = None,
                         period: str = "30d", k_min: int = DEFAULT_K_MIN) -> Dict[str, Any]:
    user_ids = get_users_for_scope(org_id, team_id)
    cutoff = datetime.now() - parse_period(period)
    return k_anonymous_aggregate(
        user_ids,
        lambda uids: metric_engagement(uids, cutoff, org_id),
        k_min=k_min,
    )
