"""
知眠轻量运营后台 API（Redis + Evaluation文件双数据源版）
仪表盘 / 安全中心 / AI 质量监控 / 用户管理

修改日志 2026-05-11 v2:
- 从 session_id key 中解析毫秒时间戳（如 session_2026-05-08_1778229174573）
- 之前版本 start_time/last_time 为空，因为 Redis 数据结构没有 turn 级 timestamp
- 修复夜间占比计算
"""
import json
import os
import re
import redis
import glob
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

# ==================== Redis 连接配置 ====================
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "") or None
REDIS_DB = 0

EVAL_TRACK_DIR = Path(__file__).parent.parent / "evaluation_tracking"

def _get_redis():
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
                       password=REDIS_PASSWORD, decode_responses=True)

def _is_night_time(dt: datetime) -> bool:
    """判断时间是否在夜间区间 22:00 - 06:00（北京时间）"""
    hour = dt.hour
    return hour >= 22 or hour < 6

def _parse_session_id_timestamp(session_id: str) -> tuple:
    """
    从 session_id 解析时间戳，返回 (start_dt, last_dt)
    格式: session_YYYY-MM-DD_timestamp
    timestamp 是毫秒级的 Unix 时间
    """
    # 匹配 session_2026-05-08_1778229174573
    m = re.match(r"session_(\d{4}-\d{2}-\d{2})_(\d{13})", session_id)
    if m:
        date_str = m.group(1)  # "2026-05-08"
        ms_str = m.group(2)    # "1778229174573"
        try:
            unix_sec = int(ms_str) / 1000.0
            # 毫秒时间戳 → UTC datetime
            utc_dt = datetime.utcfromtimestamp(unix_sec)
            # 转为北京时间（+8小时）
            cst_dt = utc_dt.replace(tzinfo=None) + timedelta(hours=8)
            return cst_dt, cst_dt
        except Exception:
            pass
    return None, None

def _get_all_sessions(days: int = 30) -> List[Dict]:
    """从 Redis 读取最近 N 天的会话数据"""
    r = _get_redis()
    cutoff = datetime.now() - timedelta(days=days)
    history_keys = r.keys("chat:history:*")
    sessions = []
    for key in history_keys:
        data = r.get(key)
        if not data:
            continue
        try:
            session_data = json.loads(data)
            if not isinstance(session_data, list) or len(session_data) == 0:
                continue
            parts = key.split(":")
            openid = parts[2] if len(parts) >= 4 else "unknown"
            session_id = parts[3] if len(parts) >= 4 else key

            # 优先从 session_id 解析时间（Redis 无 turn 级 timestamp）
            start_dt, last_dt = _parse_session_id_timestamp(session_id)
            first_ts = ""
            last_ts = ""

            if start_dt:
                first_ts = start_dt.isoformat()
                last_ts = last_dt.isoformat()
                # 按日期过滤
                if start_dt < cutoff:
                    continue
            else:
                # 回退：从第一个 turn 读 timestamp（如有）
                first_turn_ts = session_data[0].get("timestamp", "")
                last_turn_ts = session_data[-1].get("timestamp", "") if len(session_data) > 1 else first_turn_ts
                if first_turn_ts:
                    try:
                        start_dt = datetime.fromisoformat(first_turn_ts.replace("Z", "+00:00")).replace(tzinfo=None)
                        last_dt = datetime.fromisoformat(last_turn_ts.replace("Z", "+00:00")).replace(tzinfo=None)
                        first_ts = first_turn_ts
                        last_ts = last_turn_ts
                        if start_dt < cutoff:
                            continue
                    except Exception:
                        pass

            sessions.append({
                "user_id": openid,
                "session_id": session_id,
                "start_time": first_ts,
                "last_time": last_ts,
                "start_dt": start_dt,     # 用于夜间计算
                "turns": session_data,
                "rating": None,
                "outcome": None,
            })
        except Exception:
            continue
    return sessions

def _load_evaluation_records(days: int = 30) -> List[Dict]:
    """从 evaluation_tracking 目录加载评估记录"""
    cutoff = datetime.now() - timedelta(days=days)
    records = []
    for fpath in sorted(glob.glob(str(EVAL_TRACK_DIR / "bias_*.jsonl"))):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            if mtime < cutoff:
                continue
        except:
            pass
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        ts = rec.get("timestamp", "")
                        if ts:
                            try:
                                t = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
                                if t < cutoff:
                                    continue
                            except:
                                pass
                        records.append(rec)
                    except:
                        continue
        except Exception:
            continue
    return records

# ==================== 仪表盘 ====================

def get_dashboard_stats(days: int = 7, limit: int = 500) -> Dict[str, Any]:
    """仪表盘核心指标"""
    eval_records = _load_evaluation_records(days=days)
    sessions = _get_all_sessions(days=days)

    if not sessions and not eval_records:
        return {"message": "暂无数据", "period_days": days}

    active_users = set()
    for s in sessions:
        active_users.add(s.get("user_id", "unknown"))
    for rec in eval_records:
        sid = rec.get("session_id", "")
        parts = sid.split("_")
        if len(parts) >= 2:
            active_users.add(parts[1])

    total_turns = sum(len(s.get("turns", [])) for s in sessions)
    ratings = [s.get("rating") for s in sessions if s.get("rating")]
    outcomes = {}
    for s in sessions:
        o = s.get("outcome", "unknown")
        outcomes[o] = outcomes.get(o, 0) + 1

    empathy_scores = [r["auto_empathy"] for r in eval_records if "auto_empathy" in r]
    tech_scores = [r["auto_technical"] for r in eval_records if "auto_technical" in r]
    coherence_scores = [r["auto_coherence"] for r in eval_records if "auto_coherence" in r]

    rating_dist = {"🟢优秀": 0, "🟡良好": 0, "🟠需改进": 0, "🔴不合格": 0}
    for r in eval_records:
        rating = r.get("auto_rating", "")
        for k in rating_dist:
            if k in rating:
                rating_dist[k] += 1
                break

    # ===== 夜间对话占比 =====
    night_count = 0
    for s in sessions:
        start_dt = s.get("start_dt")
        if start_dt and isinstance(start_dt, datetime):
            if _is_night_time(start_dt):
                night_count += 1

    total_sessions = len(sessions) if sessions else len(eval_records)
    night_ratio = round(night_count / total_sessions * 100, 1) if total_sessions > 0 else 0

    return {
        "period_days": days,
        "total_sessions": total_sessions,
        "active_users": len(active_users),
        "avg_turns_per_session": round(total_turns / len(sessions), 1) if sessions else 0,
        "avg_duration_min": 0,
        "night_ratio": night_ratio,
        "night_count": night_count,
        "rating_distribution": rating_dist,
        "user_rating_avg": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "outcome_distribution": outcomes,
    }

# ==================== 安全中心 ====================

def get_safety_events(days: int = 30, limit: int = 500) -> List[Dict]:
    return []

# ==================== AI 质量监控 ====================

def get_quality_stats(days: int = 30, limit: int = 500) -> Dict[str, Any]:
    """AI 质量监控统计（基于 evaluation_tracking）"""
    eval_records = _load_evaluation_records(days=days)
    if not eval_records:
        return {"message": "暂无数据"}

    empathy_scores = [r["auto_empathy"] for r in eval_records if "auto_empathy" in r]
    tech_scores = [r["auto_technical"] for r in eval_records if "auto_technical" in r]
    coherence_scores = [r["auto_coherence"] for r in eval_records if "auto_coherence" in r]

    rating_dist = {"🟢优秀": 0, "🟡良好": 0, "🟠需改进": 0, "🔴不合格": 0}
    for r in eval_records:
        rating = r.get("auto_rating", "")
        for k in rating_dist:
            if k in rating:
                rating_dist[k] += 1
                break

    return {
        "period_days": days,
        "total_evaluated": len(eval_records),
        "empathy": {
            "mean": round(sum(empathy_scores) / len(empathy_scores), 1) if empathy_scores else 0,
            "distribution": {i: empathy_scores.count(i) for i in range(6)} if empathy_scores else {},
        },
        "technical": {
            "mean": round(sum(tech_scores) / len(tech_scores), 1) if tech_scores else 0,
            "distribution": {i: tech_scores.count(i) for i in range(10)} if tech_scores else {},
        },
        "coherence": {
            "mean": round(sum(coherence_scores) / len(coherence_scores), 1) if coherence_scores else 0,
            "distribution": {i: coherence_scores.count(i) for i in range(6)} if coherence_scores else {},
        },
        "top_failure_modes": [],
    }

# ==================== 用户管理 ====================

def get_user_list(days: int = 30, limit: int = 500) -> List[Dict]:
    eval_records = _load_evaluation_records(days=days)
    sessions = _get_all_sessions(days=days)
    users = {}

    for s in sessions:
        uid = s.get("user_id", "unknown")
        start_ts = s.get("start_time", "")
        last_ts = s.get("last_time", start_ts)
        if uid not in users:
            users[uid] = {
                "user_id": uid,
                "first_seen": start_ts,
                "last_seen": last_ts,
                "session_count": 0,
                "avg_rating": None,
                "latest_rating": s.get("rating"),
            }
        else:
            if start_ts and (not users[uid]["first_seen"] or start_ts < users[uid]["first_seen"]):
                users[uid]["first_seen"] = start_ts
            if last_ts and (not users[uid]["last_seen"] or last_ts > users[uid]["last_seen"]):
                users[uid]["last_seen"] = last_ts
        users[uid]["session_count"] += 1

    for r in eval_records:
        sid = r.get("session_id", "")
        uid = sid.split("_")[1] if len(sid.split("_")) >= 2 else "unknown"
        ts = r.get("timestamp", "")
        if uid not in users:
            users[uid] = {
                "user_id": uid,
                "first_seen": ts,
                "last_seen": ts,
                "session_count": 0,
                "avg_rating": None,
                "latest_rating": None,
            }
        else:
            if ts and (not users[uid]["first_seen"] or ts < users[uid]["first_seen"]):
                users[uid]["first_seen"] = ts
            if ts and (not users[uid]["last_seen"] or ts > users[uid]["last_seen"]):
                users[uid]["last_seen"] = ts
        users[uid]["session_count"] += 1

    return list(users.values())

def get_user_detail(user_id: str, limit: int = 20) -> Dict[str, Any]:
    eval_records = _load_evaluation_records(days=365)
    user_evals = [r for r in eval_records if user_id in r.get("session_id", "")]
    return {
        "user_id": user_id,
        "total_sessions": len(user_evals),
        "sessions": [{"session_id": r.get("session_id"), "start_time": r.get("timestamp", ""),
                      "rating": r.get("auto_rating", ""), "turn_count": 0} for r in user_evals[:limit]],
    }

# ==================== 数据导出 ====================
import csv, io

def export_users_csv(days: int = 30) -> str:
    users = get_user_list(days=days)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["用户ID", "首次使用", "最后活跃", "会话数", "平均评分"])
    for u in users:
        writer.writerow([u.get("user_id", ""), (u.get("first_seen") or "")[:19],
                         (u.get("last_seen") or "")[:19], u.get("session_count", 0), u.get("avg_rating", "")])
    return output.getvalue()

def export_safety_csv(days: int = 30) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["时间", "用户ID", "会话ID", "危机状态", "不当建议", "安全通过", "评级", "TOP建议"])
    return output.getvalue()

def export_evaluations_csv(days: int = 30) -> str:
    eval_records = _load_evaluation_records(days=days)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["时间", "会话ID", "评级", "共情", "技术", "连贯性"])
    for r in eval_records:
        writer.writerow([(r.get("timestamp", "") or "")[:19], r.get("session_id", ""),
                         r.get("auto_rating", ""), r.get("auto_empathy", ""),
                         r.get("auto_technical", ""), r.get("auto_coherence", "")])
    return output.getvalue()
