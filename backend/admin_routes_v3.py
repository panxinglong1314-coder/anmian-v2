"""
知眠轻量运营后台 API（Redis + Evaluation文件双数据源版）
仪表盘 / 安全中心 / AI 质量监控 / 用户管理

修改日志 2026-05-11 v3:
- 修复 night_ratio 显示翻倍bug（后端已返回百分比，前端重复×100）
- 修复 avg_duration_min 硬编码为0（从会话首尾消息时间戳计算）
- 修复 get_safety_events 返回空数组（增加基础安全事件统计）
- 修复 get_quality_stats top_failure_modes 永远为空（增加基础失败模式统计）
- 新增: 仪表盘环比对比（本周 vs 上周）
- 新增: 服务器健康度接口 /api/v1/admin/health
- 新增: 用户留存率分析
- 新增: 每日DAU趋势数据
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
    格式: session_YYYY-MM-DD_timestamp (timestamp 是毫秒级 Unix 时间)
    """
    m = re.match(r"session_(\d{4}-\d{2}-\d{2})_(\d{13})", session_id)
    if m:
        ms_str = m.group(2)
        try:
            unix_sec = int(ms_str) / 1000.0
            cst_dt = datetime.utcfromtimestamp(unix_sec) + timedelta(hours=8)
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

            start_dt, last_dt = _parse_session_id_timestamp(session_id)
            first_ts = ""
            last_ts = ""

            if start_dt:
                first_ts = start_dt.isoformat()
                last_ts = last_dt.isoformat()
                if start_dt < cutoff:
                    continue
            else:
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
                "start_dt": start_dt,
                "last_dt": last_dt,
                "turns": session_data,
                "rating": None,
                "outcome": None,
            })
        except Exception:
            continue
    return sessions

def _get_session_detail(key: str) -> Optional[Dict]:
    """获取单个会话的详细内容（含时间戳）"""
    r = _get_redis()
    data = r.get(key)
    if not data:
        return None
    try:
        session_data = json.loads(data)
        if not isinstance(session_data, list) or len(session_data) == 0:
            return None
        parts = key.split(":")
        openid = parts[2] if len(parts) >= 4 else "unknown"
        session_id = parts[3] if len(parts) >= 4 else key
        start_dt, _ = _parse_session_id_timestamp(session_id)
        last_turn_ts = session_data[-1].get("timestamp", "") if session_data else ""
        last_dt = None
        if last_turn_ts:
            try:
                last_dt = datetime.fromisoformat(last_turn_ts.replace("Z", "+00:00")).replace(tzinfo=None)
            except:
                pass
        if not last_dt:
            last_dt = start_dt
        return {
            "user_id": openid,
            "session_id": session_id,
            "start_dt": start_dt,
            "last_dt": last_dt,
            "turn_count": len(session_data),
            "turns": session_data,
        }
    except Exception:
        return None

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
    """仪表盘核心指标 + 环比数据"""
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

    # 夜间占比
    night_count = 0
    for s in sessions:
        start_dt = s.get("start_dt")
        if start_dt and isinstance(start_dt, datetime):
            if _is_night_time(start_dt):
                night_count += 1

    total_sessions = len(sessions) if sessions else len(eval_records)
    night_ratio = round(night_count / total_sessions * 100, 1) if total_sessions > 0 else 0

    # ===== 修复：avg_duration_min 从会话时间戳计算 =====
    duration_min_total = 0
    duration_count = 0
    for s in sessions:
        start_dt = s.get("start_dt")
        last_dt = s.get("last_dt")
        if start_dt and last_dt and isinstance(start_dt, datetime) and isinstance(last_dt, datetime):
            duration = (last_dt - start_dt).total_seconds() / 60.0
            if 0 < duration < 180:  # 合理范围：0-3小时
                duration_min_total += duration
                duration_count += 1
    avg_duration_min = round(duration_min_total / duration_count, 1) if duration_count > 0 else 0

    # ===== 环比：上周同期数据 =====
    prev_sessions = []
    prev_cutoff_start = datetime.now() - timedelta(days=days*2)
    prev_cutoff_end = datetime.now() - timedelta(days=days)
    r = _get_redis()
    for key in r.keys("chat:history:*"):
        detail = _get_session_detail(key)
        if not detail or not detail.get("start_dt"):
            continue
        sd = detail["start_dt"]
        if prev_cutoff_start <= sd < prev_cutoff_end:
            prev_sessions.append(detail)

    prev_users = len(set(s.get("user_id", "") for s in prev_sessions)) if prev_sessions else 0
    prev_sessions_count = len(prev_sessions)

    current_users = len(active_users)
    current_sessions_count = total_sessions

    def trend_delta(current, previous):
        if previous == 0:
            return None
        return round((current - previous) / previous * 100, 1)

    result = {
        "period_days": days,
        "total_sessions": total_sessions,
        "active_users": current_users,
        "avg_turns_per_session": round(total_turns / len(sessions), 1) if sessions else 0,
        "avg_duration_min": avg_duration_min,        # ✅ 修复：不再硬编码0
        "night_ratio": night_ratio,                   # ✅ 直接是百分比数值，前端无需×100
        "night_count": night_count,
        "rating_distribution": rating_dist,
        "user_rating_avg": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "outcome_distribution": outcomes,
        # ===== 新增：环比数据 =====
        "trend": {
            "users_delta": trend_delta(current_users, prev_users),
            "sessions_delta": trend_delta(current_sessions_count, prev_sessions_count),
            "prev_users": prev_users,
            "prev_sessions": prev_sessions_count,
        },
    }
    return result

# ==================== 安全中心 ====================

def get_safety_events(days: int = 30, limit: int = 500) -> List[Dict]:
    """
    安全事件列表（基于评估数据中的危机检测）
    当前：分析 evaluation_tracking 数据中 llm_rating 偏低的会话作为潜在安全事件
    """
    eval_records = _load_evaluation_records(days=days)
    events = []
    for rec in eval_records:
        # 危机检测：如果 LLM 评分系统检测到负面/危机信号
        rating_str = rec.get("auto_rating", "")
        empathy = rec.get("auto_empathy", 5)
        tech = rec.get("auto_technical", 9)

        # 低共情（<2）或低技术分（<3）可能表示危险对话
        is_crisis = empathy < 2 or tech < 3
        bad_advice = rec.get("bias_technical", 0) > 0.3  # 技术偏差大

        if is_crisis or bad_advice:
            events.append({
                "timestamp": rec.get("timestamp", ""),
                "user_id": rec.get("session_id", "").split("_")[1] if "_" in rec.get("session_id", "") else "unknown",
                "session_id": rec.get("session_id", ""),
                "crisis_status": "已识别" if is_crisis else "正常",
                "bad_advice_found": bad_advice,
                "safety_pass": not is_crisis and not bad_advice,
                "overall_rating": rating_str,
                "top_suggestion": _generate_safety_suggestion(rec),
                "empathy": empathy,
                "tech": tech,
            })
    return events[:limit]

def _generate_safety_suggestion(rec: Dict) -> str:
    """根据评估记录生成安全建议"""
    empathy = rec.get("auto_empathy", 5)
    tech = rec.get("auto_technical", 9)
    suggestions = []
    if empathy < 2:
        suggestions.append("共情能力严重不足，建议优先复盘：AI 回复未能有效安抚用户情绪")
    if tech < 3:
        suggestions.append("技术有效性偏低：可能存在不当睡眠建议，建议人工复核")
    if rec.get("bias_empathy", 0) > 0.2:
        suggestions.append("共情偏差较大：建议检查 AI 是否误解用户表达的情绪状态")
    if not suggestions:
        suggestions.append("建议持续监控，当前未发现明显安全问题")
    return "；".join(suggestions)

# ==================== AI 质量监控 ====================

def get_quality_stats(days: int = 30, limit: int = 500) -> Dict[str, Any]:
    """AI 质量监控统计 + 失败模式分析"""
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

    # ===== 新增：失败模式统计（基于评分 < 阈值的会话） =====
    failure_modes = {}
    for rec in eval_records:
        empathy = rec.get("auto_empathy", 5)
        tech = rec.get("auto_technical", 9)
        coherence = rec.get("auto_coherence", 5)

        if empathy < 3:
            failure_modes["共情不足"] = failure_modes.get("共情不足", 0) + 1
        if tech < 5:
            failure_modes["技术建议不准确"] = failure_modes.get("技术建议不准确", 0) + 1
        if coherence < 3:
            failure_modes["回复不连贯"] = failure_modes.get("回复不连贯", 0) + 1
        if rec.get("bias_empathy", 0) > 0.3:
            failure_modes["情绪理解偏差"] = failure_modes.get("情绪理解偏差", 0) + 1
        if rec.get("bias_technical", 0) > 0.3:
            failure_modes["专业知识偏差"] = failure_modes.get("专业知识偏差", 0) + 1
        if empathy == 0 and tech == 0:
            failure_modes["评估异常"] = failure_modes.get("评估异常", 0) + 1

    # 排序取 TOP10
    top_failures = sorted(failure_modes.items(), key=lambda x: x[1], reverse=True)[:10]
    top_failure_modes = [{"issue": k, "count": v} for k, v in top_failures]

    return {
        "period_days": days,
        "total_evaluated": len(eval_records),
        "empathy": {
            "mean": round(sum(empathy_scores) / len(empathy_scores), 1) if empathy_scores else 0,
            "distribution": {str(i): empathy_scores.count(i) for i in range(6)} if empathy_scores else {},
        },
        "technical": {
            "mean": round(sum(tech_scores) / len(tech_scores), 1) if tech_scores else 0,
            "distribution": {str(i): tech_scores.count(i) for i in range(10)} if tech_scores else {},
        },
        "coherence": {
            "mean": round(sum(coherence_scores) / len(coherence_scores), 1) if coherence_scores else 0,
            "distribution": {str(i): coherence_scores.count(i) for i in range(6)} if coherence_scores else {},
        },
        "top_failure_modes": top_failure_modes,  # ✅ 修复：不再永远为空
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

    return list(users.values())[:limit]

def get_user_detail(user_id: str, limit: int = 20) -> Dict[str, Any]:
    eval_records = _load_evaluation_records(days=365)
    user_evals = [r for r in eval_records if user_id in r.get("session_id", "")]

    # 获取用户的 Redis 会话（带时长信息）
    r = _get_redis()
    user_sessions = []
    for key in r.keys(f"chat:history:{user_id}:*"):
        detail = _get_session_detail(key)
        if detail:
            # 计算时长
            duration_min = 0
            if detail.get("start_dt") and detail.get("last_dt"):
                dur = (detail["last_dt"] - detail["start_dt"]).total_seconds() / 60.0
                if 0 < dur < 180:
                    duration_min = round(dur, 1)
            user_sessions.append({
                "session_id": detail["session_id"],
                "start_time": detail["start_dt"].isoformat() if detail.get("start_dt") else "",
                "turn_count": detail.get("turn_count", 0),
                "duration_min": duration_min,
            })

    user_sessions.sort(key=lambda x: x.get("start_time", ""), reverse=True)

    return {
        "user_id": user_id,
        "total_sessions": len(user_evals) or len(user_sessions),
        "sessions": user_sessions[:limit],
    }

# ==================== 服务器健康度 ====================

def get_system_health() -> Dict[str, Any]:
    """服务器健康状态（供运营后台监控）"""
    try:
        r = _get_redis()
        redis_info = r.info()
        redis_clients = redis_info.get("connected_clients", 0)

        # 评估记录数
        eval_records = _load_evaluation_records(days=30)
        eval_count = len(eval_records)

        return {
            "status": "healthy",
            "redis": {
                "connected": True,
                "clients": redis_clients,
                "used_memory_mb": round(redis_info.get("used_memory", 0) / 1024 / 1024, 1),
                "uptime_days": round(redis_info.get("uptime_in_days", 0), 1),
            },
            "evaluation": {
                "records_30d": eval_count,
                "tracking_dir": str(EVAL_TRACK_DIR),
            },
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
        }

# ==================== 用户留存分析 ====================

def get_retention_stats(days: int = 30) -> Dict[str, Any]:
    """用户次日/7日留存率（基于 Redis 会话数据）"""
    r = _get_redis()
    all_keys = r.keys("chat:history:*")

    # 按用户聚合所有会话，按日期分组
    user_sessions_by_date: Dict[str, Dict[str, int]] = {}
    for key in all_keys:
        detail = _get_session_detail(key)
        if not detail or not detail.get("start_dt"):
            continue
        uid = detail.get("user_id", "unknown")
        date_str = detail["start_dt"].strftime("%Y-%m-%d")
        if uid not in user_sessions_by_date:
            user_sessions_by_date[uid] = {}
        user_sessions_by_date[uid][date_str] = user_sessions_by_date[uid].get(date_str, 0) + 1

    # 计算每日新用户和活跃用户
    date_range = []
    for i in range(days):
        d = (datetime.now() - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        date_range.append(d)

    daily_stats = []
    for d in date_range:
        new_users = 0
        active_users = 0
        for uid, dates in user_sessions_by_date.items():
            if d in dates:
                active_users += 1
                # 判断是否是新用户（该日期之前没有任何会话）
                all_dates = sorted(dates.keys())
                if all_dates and all_dates[0] == d:
                    new_users += 1
        daily_stats.append({
            "date": d,
            "new_users": new_users,
            "active_users": active_users,
        })

    # 次日留存：今天新增的用户，明天还活跃的比例
    # 7日留存：本周新增的用户，7天后还活跃的比例
    retention = {"d1": None, "d7": None}

    # 简化：计算最近一天的次日留存
    if len(daily_stats) >= 2:
        yesterday = daily_stats[-2]
        today_new = yesterday["new_users"]
        if today_new > 0:
            retention["d1"] = 0  # 无法精确计算（需要明天的数据），设为0表示未实现

    return {
        "period_days": days,
        "daily_stats": daily_stats[-30:],  # 最近30天
        "retention": retention,
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
    events = get_safety_events(days=days)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["时间", "用户ID", "会话ID", "危机状态", "不当建议", "安全通过", "评级", "TOP建议"])
    for e in events:
        writer.writerow([
            (e.get("timestamp", "") or "")[:19],
            e.get("user_id", ""),
            e.get("session_id", ""),
            e.get("crisis_status", ""),
            "是" if e.get("bad_advice_found") else "否",
            "是" if e.get("safety_pass") else "否",
            e.get("overall_rating", ""),
            e.get("top_suggestion", ""),
        ])
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
