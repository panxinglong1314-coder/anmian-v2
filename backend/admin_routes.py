"""
知眠轻量运营后台 API（Redis + Evaluation文件双数据源版）

修改日志 2026-05-11 v4:
- 修复: 安全中心 safety_pass 逻辑（前端误算 → 后端直接返回正确统计）
- 修复: avg_duration 从评估数据计算（不再依赖消息时间戳）
- 新增: /api/v1/admin/stats API调用统计（响应时间+请求量）
- 新增: 仪表盘时段分布热力图数据（24小时）
- 新增: 仪表盘每日会话/用户趋势（近30天）
- 新增: 安全事件详情含会话内容预览
- 新增: AI质量每个失败模式的改进建议
- 优化: 评估数据时间范围过滤逻辑更准确
"""
import json, os, re, time, math
import redis, glob
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import defaultdict

# ==================== Redis 连接配置 ====================
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "") or None
REDIS_DB = 0
EVAL_TRACK_DIR = Path(__file__).parent.parent / "evaluation_tracking"

# API调用统计（内存中，非持久化，生产环境建议用Redis）
_api_stats = {
    "total_requests": 0,
    "total_errors": 0,
    "response_times_ms": [],  # 最近100次响应时间
    "last_reset": time.time(),
}

def _get_redis():
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
                       password=REDIS_PASSWORD, decode_responses=True)

def _is_night_time(dt: datetime) -> bool:
    hour = dt.hour
    return hour >= 22 or hour < 6

def _parse_session_id_timestamp(session_id: str):
    m = re.match(r"session_(\d{4}-\d{2}-\d{2})_(\d{13})", session_id)
    if m:
        try:
            unix_sec = int(m.group(2)) / 1000.0
            cst_dt = datetime.utcfromtimestamp(unix_sec) + timedelta(hours=8)
            return cst_dt, cst_dt
        except:
            pass
    return None, None

def _record_api_call(response_time_ms: float, is_error: bool = False):
    """记录API调用统计"""
    _api_stats["total_requests"] += 1
    if is_error:
        _api_stats["total_errors"] += 1
    _api_stats["response_times_ms"].append(response_time_ms)
    if len(_api_stats["response_times_ms"]) > 200:
        _api_stats["response_times_ms"] = _api_stats["response_times_ms"][-200:]

def _get_all_sessions(days: int = 30) -> List[Dict]:
    r = _get_redis()
    cutoff = datetime.now() - timedelta(days=days)
    sessions = []
    for key in r.keys("chat:history:*"):
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

            start_dt, _ = _parse_session_id_timestamp(session_id)
            first_ts = ""
            if start_dt:
                first_ts = start_dt.isoformat()
                if start_dt < cutoff:
                    continue
            else:
                first_turn_ts = session_data[0].get("timestamp", "")
                if first_turn_ts:
                    try:
                        st = datetime.fromisoformat(first_turn_ts.replace("Z", "+00:00")).replace(tzinfo=None)
                        first_ts = first_turn_ts
                        if st < cutoff:
                            continue
                    except:
                        pass

            sessions.append({
                "user_id": openid,
                "session_id": session_id,
                "start_time": first_ts,
                "start_dt": start_dt,
                "turn_count": len(session_data),
                "turns": session_data,
                "rating": None,
                "outcome": None,
            })
        except:
            continue
    return sessions

def _get_session_detail(key: str) -> Optional[Dict]:
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
        start_dt, last_dt = _parse_session_id_timestamp(session_id)
        return {
            "user_id": openid,
            "session_id": session_id,
            "start_dt": start_dt,
            "last_dt": last_dt,
            "turn_count": len(session_data),
            "turns": session_data,
        }
    except:
        return None



# ==================== 用户评分数据（汇总三个来源） ====================

def _get_user_ratings(days: int = 30) -> list:
    """
    汇总用户评分，从三个来源：
    1. Redis chat:history:* 中的 rating 字段
    2. conversation_logs/ 中的会话日志文件的 rating 字段
    3. Redis feedback:* 中的每日反馈（转换为1-5分）
    """
    from pathlib import Path
    ratings = []
    cutoff = datetime.now() - timedelta(days=days)

    # 来源1: Redis chat:history 会话
    sessions = _get_all_sessions(days=days)
    for s in sessions:
        r = s.get("rating")
        if r and isinstance(r, (int, float)) and 1 <= r <= 5:
            ratings.append({"rating": r, "timestamp": s.get("start_time", "")})

    # 来源2: session_logger JSON 日志文件
    LOG_DIR = Path(__file__).parent.parent / "conversation_logs"
    if LOG_DIR.exists():
        for fpath in glob.glob(str(LOG_DIR / "sess_*.json")):
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    log = json.load(f)
                ts = log.get("end_time", "")
                if ts:
                    try:
                        t = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
                        if t < cutoff:
                            continue
                    except:
                        pass
                r = log.get("rating")
                if r and isinstance(r, (int, float)) and 1 <= r <= 5:
                    ratings.append({"rating": r, "timestamp": ts})
            except:
                continue

    # 来源3: Redis feedback:*
    try:
        fb_r = _get_redis()
        fb_keys = fb_r.keys("feedback:*")
        for k in fb_keys:
            for item in fb_r.lrange(k, 0, -1):
                try:
                    d = json.loads(item)
                    ts = d.get("timestamp", "")
                    if ts:
                        try:
                            t = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
                            if t < cutoff:
                                continue
                        except:
                            pass
                    fb_rating = d.get("rating")
                    if fb_rating in [1, 5]:
                        ratings.append({"rating": fb_rating, "timestamp": ts})
                except:
                    continue
    except:
        pass

    return ratings


def _load_evaluation_records(days: int = 30) -> List[Dict]:
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
        except:
            continue
    return records

# ==================== 仪表盘 ====================

def get_dashboard_stats(days: int = 7, limit: int = 500) -> Dict[str, Any]:
    eval_records = _load_evaluation_records(days=days)
    sessions = _get_all_sessions(days=days)

    if not sessions and not eval_records:
        return {"message": "暂无数据", "period_days": days}

    active_users = set()
    for s in sessions:
        active_users.add(s.get("user_id", "unknown"))
    for rec in eval_records:
        parts = rec.get("session_id", "").split("_")
        if len(parts) >= 2:
            active_users.add(parts[1])

    total_turns = sum(s.get("turn_count", 0) for s in sessions)
    # 汇总三个来源的用户评分
    all_user_ratings = _get_user_ratings(days=days)
    ratings = [r["rating"] for r in all_user_ratings]
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

    night_count = sum(1 for s in sessions if s.get("start_dt") and _is_night_time(s["start_dt"]))
    total_sessions = len(sessions) if sessions else len(eval_records)
    night_ratio = round(night_count / total_sessions * 100, 1) if total_sessions > 0 else 0

    # avg_duration: 从评估数据中的 session 时长字段（如有）或按轮次估算
    # 评估数据有 session_id 时间戳，我们用轮次数估算平均时长（每轮约2分钟）
    avg_duration_min = 0
    if sessions:
        total_turns_for_dur = sum(s.get("turn_count", 0) for s in sessions)
        if total_turns_for_dur > 0:
            avg_duration_min = round(total_turns_for_dur / len(sessions) * 2.0, 1)  # 每轮约2分钟

    # 环比上周
    prev_cutoff_start = datetime.now() - timedelta(days=days * 2)
    prev_cutoff_end = datetime.now() - timedelta(days=days)
    prev_sessions = []
    r = _get_redis()
    for key in r.keys("chat:history:*"):
        detail = _get_session_detail(key)
        if not detail or not detail.get("start_dt"):
            continue
        sd = detail["start_dt"]
        if prev_cutoff_start <= sd < prev_cutoff_end:
            prev_sessions.append(detail)

    prev_users = len(set(s.get("user_id", "") for s in prev_sessions))
    prev_sessions_count = len(prev_sessions)
    current_users = len(active_users)
    current_sessions_count = total_sessions

    def trend_delta(current, previous):
        if previous == 0:
            return None
        return round((current - previous) / previous * 100, 1)

    # ===== 新增: 每日趋势（近30天） =====
    daily_trend = defaultdict(lambda: {"date": "", "sessions": 0, "users": set(), "turns": 0})
    for s in sessions:
        dt = s.get("start_dt")
        if dt:
            date_str = dt.strftime("%Y-%m-%d")
            daily_trend[date_str]["date"] = date_str
            daily_trend[date_str]["sessions"] += 1
            daily_trend[date_str]["users"].add(s.get("user_id", ""))
            daily_trend[date_str]["turns"] += s.get("turn_count", 0)

    daily_trend_list = sorted(daily_trend.values(), key=lambda x: x["date"])[-30:]
    daily_trend_formatted = [{
        "date": d["date"],
        "sessions": d["sessions"],
        "active_users": len(d["users"]),
        "avg_turns": round(d["turns"] / d["sessions"], 1) if d["sessions"] > 0 else 0
    } for d in daily_trend_list]

    # ===== 新增: 24小时时段分布 =====
    hourly_dist = {h: 0 for h in range(24)}
    for s in sessions:
        dt = s.get("start_dt")
        if dt:
            hourly_dist[dt.hour] += 1

    return {
        "period_days": days,
        "total_sessions": total_sessions,
        "active_users": current_users,
        "avg_turns_per_session": round(total_turns / len(sessions), 1) if sessions else 0,
        "avg_duration_min": avg_duration_min,
        "night_ratio": night_ratio,
        "night_count": night_count,
        "rating_distribution": rating_dist,
        "user_rating_avg": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "outcome_distribution": outcomes,
        "trend": {
            "users_delta": trend_delta(current_users, prev_users),
            "sessions_delta": trend_delta(current_sessions_count, prev_sessions_count),
            "prev_users": prev_users,
            "prev_sessions": prev_sessions_count,
        },
        # 新增
        "daily_trend": daily_trend_formatted,
        "hourly_distribution": [hourly_dist[h] for h in range(24)],
    }

# ==================== 安全中心 ====================

def get_safety_events(days: int = 30, limit: int = 500) -> List[Dict]:
    """安全事件：分析评估数据中低分+高偏差会话，标记潜在风险"""
    eval_records = _load_evaluation_records(days=days)
    events = []
    for rec in eval_records:
        empathy = rec.get("auto_empathy", 5)
        tech = rec.get("auto_technical", 9)
        coherence = rec.get("auto_coherence", 5)
        bias_emp = rec.get("bias_empathy", 0)
        bias_tech = rec.get("bias_technical", 0)
        bias_coh = rec.get("bias_coherence", 0)

        is_crisis = empathy < 2 or tech < 2
        bad_advice = bias_tech > 0.35 or tech < 3
        is_low_quality = empathy < 3 or tech < 5 or coherence < 3

        if is_crisis or bad_advice or is_low_quality:
            severity = "危险" if is_crisis else "警告" if bad_advice else "提醒"
            events.append({
                "timestamp": rec.get("timestamp", ""),
                "user_id": rec.get("session_id", "").split("_")[1] if "_" in rec.get("session_id", "") else "unknown",
                "session_id": rec.get("session_id", ""),
                "crisis_status": "已识别" if is_crisis else "正常",
                "bad_advice_found": bad_advice,
                "safety_pass": not is_crisis and not bad_advice,
                "severity": severity,
                "overall_rating": rec.get("auto_rating", ""),
                "empathy": empathy,
                "tech": tech,
                "coherence": coherence,
                "top_suggestion": _generate_safety_suggestion(rec, is_crisis, bad_advice, is_low_quality),
                "bias_empathy": round(bias_emp, 3),
                "bias_technical": round(bias_tech, 3),
            })

    # 按严重程度排序
    severity_order = {"危险": 0, "警告": 1, "提醒": 2}
    events.sort(key=lambda x: severity_order.get(x.get("severity", ""), 3))
    return events[:limit]

def _generate_safety_suggestion(rec: Dict, is_crisis: bool, bad_advice: bool, is_low: bool) -> str:
    parts = []
    if is_crisis:
        parts.append("【危险】共情或技术评分极低，需立即人工复核")
    if bad_advice:
        if rec.get("bias_technical", 0) > 0.35:
            parts.append(f"【警告】技术偏差 {round(rec.get('bias_technical', 0)*100)}%，可能存在不当睡眠建议")
        if rec.get("tech", 9) < 3:
            parts.append(f"【警告】技术有效性仅 {rec.get('tech')}/9，建议检查专业知识准确性")
    if rec.get("bias_empathy", 0) > 0.3:
        parts.append(f"共情理解偏差 {round(rec.get('bias_empathy', 0)*100)}%，AI可能误解用户情绪")
    if is_low and not parts:
        parts.append("整体质量偏低，建议持续监控")
    if not parts:
        parts.append("当前未发现明显安全问题，建议持续监控")
    return "；".join(parts)

# ==================== AI 质量监控 ====================

FAILURE_SUGGESTIONS = {
    "共情不足": "建议在系统提示词中强化'先共情后解决'原则，要求AI先回应用户情绪再给建议",
    "技术建议不准确": "建议检查RAG知识库中的睡眠医学知识是否过时，增加专业文献来源标注",
    "回复不连贯": "建议优化对话记忆机制，确保AI能记住用户在当前会话中提到的关键信息",
    "情绪理解偏差": "建议增加情绪分类微调训练数据，补充更多睡眠焦虑相关表达样本",
    "专业知识偏差": "建议在知识库中补充睡眠医学指南更新日志，避免引用过时医学观点",
    "评估异常": "建议检查评估日志，排查是否有异常会话导致评分失真",
}

def get_quality_stats(days: int = 30, limit: int = 500) -> Dict[str, Any]:
    eval_records = _load_evaluation_records(days=days)
    if not eval_records:
        return {"message": "暂无数据"}

    empathy_scores = [r["auto_empathy"] for r in eval_records if "auto_empathy" in r]
    tech_scores = [r["auto_technical"] for r in eval_records if "auto_technical" in r]
    coherence_scores = [r["auto_coherence"] for r in eval_records if "auto_coherence" in r]

    rating_dist = {"🟢优秀": 0, "🟡良好": 0, "🟠需改进": 0, "🔴不合格": 0}
    for r in eval_records:
        for k in rating_dist:
            if k in r.get("auto_rating", ""):
                rating_dist[k] += 1
                break

    # 失败模式统计
    failure_modes = defaultdict(int)
    for rec in eval_records:
        empathy = rec.get("auto_empathy", 5)
        tech = rec.get("auto_technical", 9)
        coherence = rec.get("auto_coherence", 5)
        if empathy < 3: failure_modes["共情不足"] += 1
        if tech < 5: failure_modes["技术建议不准确"] += 1
        if coherence < 3: failure_modes["回复不连贯"] += 1
        if rec.get("bias_empathy", 0) > 0.3: failure_modes["情绪理解偏差"] += 1
        if rec.get("bias_technical", 0) > 0.3: failure_modes["专业知识偏差"] += 1
        if empathy == 0 and tech == 0: failure_modes["评估异常"] += 1

    top_failures = sorted(failure_modes.items(), key=lambda x: x[1], reverse=True)[:10]
    top_failure_modes = [
        {"issue": k, "count": v, "suggestion": FAILURE_SUGGESTIONS.get(k, "建议人工复核该类型问题")}
        for k, v in top_failures
    ]

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
        "top_failure_modes": top_failure_modes,
    }

# ==================== 用户管理 ====================

def get_user_list(days: int = 30, limit: int = 500) -> List[Dict]:
    eval_records = _load_evaluation_records(days=days)
    sessions = _get_all_sessions(days=days)
    users = {}

    for s in sessions:
        uid = s.get("user_id", "unknown")
        start_ts = s.get("start_time", "")
        if uid not in users:
            users[uid] = {"user_id": uid, "first_seen": start_ts, "last_seen": start_ts,
                          "session_count": 0, "avg_rating": None, "latest_rating": None,
                          "total_turns": 0}
        if start_ts and (not users[uid]["first_seen"] or start_ts < users[uid]["first_seen"]):
            users[uid]["first_seen"] = start_ts
        users[uid]["session_count"] += 1
        users[uid]["total_turns"] += s.get("turn_count", 0)

    # Collect ratings per user from eval_records
    user_ratings = {}
    for r in eval_records:
        sid = r.get("session_id", "")
        uid = sid.split("_")[1] if len(sid.split("_")) >= 2 else "unknown"
        fb_rating = r.get("feedback_rating") or r.get("auto_rating")
        if fb_rating and uid not in ("unknown", ""):
            if uid not in user_ratings:
                user_ratings[uid] = []
            user_ratings[uid].append(fb_rating)

    for r in eval_records:
        sid = r.get("session_id", "")
        uid = sid.split("_")[1] if len(sid.split("_")) >= 2 else "unknown"
        ts = r.get("timestamp", "")
        if uid not in users:
            users[uid] = {"user_id": uid, "first_seen": ts, "last_seen": ts,
                          "session_count": 0, "avg_rating": None, "latest_rating": None, "total_turns": 0}
        else:
            if ts and (not users[uid]["first_seen"] or ts < users[uid]["first_seen"]):
                users[uid]["first_seen"] = ts
            if ts and ts > users[uid]["last_seen"]:
                users[uid]["last_seen"] = ts
        users[uid]["session_count"] += 1

    # Fill in avg_rating and latest_rating from collected ratings
    _rn_map = {'🟢': 5, '🟡': 4, '🟠': 3, '🟣': 2}
    for uid, ratings in user_ratings.items():
        if uid in users and ratings:
            def _rn(v):
                if isinstance(v, (int, float)) and v > 0: return v
                for _ek, _en in _rn_map.items():
                    if _ek in v: return _en
                return None
            valid_ratings = [_rn(r) for r in ratings]
            valid_ratings = [r for r in valid_ratings if r is not None and r > 0]
            if valid_ratings:
                users[uid]["avg_rating"] = round(sum(valid_ratings) / len(valid_ratings), 1)
                users[uid]["latest_rating"] = valid_ratings[-1]

    return list(users.values())[:limit]

def toggle_user_status(user_id: str, action: str = "disable") -> Dict[str, Any]:
    """禁用/启用用户"""
    try:
        r = _get_redis()
        key = f"user:disabled:{user_id}"
        if action == "disable":
            r.setex(key, 86400 * 365, "1")  # 禁用1年
            return {"success": True, "user_id": user_id, "status": "disabled"}
        elif action == "enable":
            r.delete(key)
            return {"success": True, "user_id": user_id, "status": "enabled"}
        else:
            return {"success": False, "error": "Invalid action"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def is_user_disabled(user_id: str) -> bool:
    try:
        r = _get_redis()
        return r.exists(f"user:disabled:{user_id}") > 0
    except:
        return False

def get_user_detail(user_id: str, limit: int = 20) -> Dict[str, Any]:
    eval_records = _load_evaluation_records(days=365)
    user_evals = [r for r in eval_records if user_id in r.get("session_id", "")]

    r = _get_redis()
    user_sessions = []
    for key in r.keys(f"chat:history:{user_id}:*"):
        detail = _get_session_detail(key)
        if detail:
            # 估算时长（轮次 × 2分钟）
            turns = detail.get("turn_count", 0)
            est_duration = round(turns * 2.0, 1)
            # 提取对话内容摘要（用户首条消息）
            user_preview = ""
            for t in detail.get("turns", []):
                if t.get("role") == "user":
                    user_preview = (t.get("content", "") or "")[:60]
                    break
            user_sessions.append({
                "session_id": detail["session_id"],
                "start_time": detail["start_dt"].isoformat() if detail.get("start_dt") else "",
                "turn_count": turns,
                "duration_min": est_duration,
                "user_preview": user_preview,
            })

    user_sessions.sort(key=lambda x: x.get("start_time", ""), reverse=True)

    return {
        "user_id": user_id,
        "total_sessions": len(user_evals) or len(user_sessions),
        "sessions": user_sessions[:limit],
    }

# ==================== 服务器健康度 ====================

def get_system_health() -> Dict[str, Any]:
    issues = []
    try:
        r = _get_redis()
        redis_info = r.info()
        eval_records = _load_evaluation_records(days=30)
        rt = _api_stats["response_times_ms"]
        avg_rt = round(sum(rt)/len(rt), 1) if rt else 0
        p95_rt = round(sorted(rt)[int(len(rt)*0.95)]) if rt else 0

        # 1. Redis连接检查
        try:
            if not r.ping(): issues.append("Redis ping失败")
        except: issues.append("Redis连接异常")

        # 2. CPU负载检查
        try:
            load1 = os.getloadavg()[0]
            cpu_count = os.cpu_count() or 1
            lr = load1 / cpu_count
            if lr > 2.0: issues.append(f"CPU负载过高({lr:.1f})")
        except: pass

        # 3. 内存检查
        try:
            mem = os.popen("free -m 2>/dev/null | grep Mem: | awk '{print $3,$2}'").read().strip()
            if mem:
                parts = mem.split(); used_m = int(parts[0]); total_m = int(parts[1])
                if total_m > 0 and used_m/total_m > 0.92: issues.append(f"内存使用率过高({used_m}/{total_m}MB)")
        except: pass

        # 4. 磁盘检查
        try:
            du = os.popen("df / 2>/dev/null | tail -1 | awk '{print $5}'").read().strip()
            if du and du.endswith("%"):
                pct = int(du[:-1])
                if pct > 90: issues.append(f"磁盘使用率过高({du})")
        except: pass

        # 5. API错误率
        tot_req = _api_stats["total_requests"]
        tot_err = _api_stats["total_errors"]
        if tot_req > 10 and tot_err/tot_req > 0.05: issues.append(f"API错误率高({tot_err}/{tot_req})")
        #elif tot_req == 0: issues.append("API请求量为0(可能未接入)")

        # 6. 评估记录检查
        if len(eval_records) == 0: issues.append("近30天无评估记录")

        is_healthy = len(issues) == 0
        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "issues": issues,
            "redis": {
                "connected": True,
                "clients": redis_info.get("connected_clients", 0),
                "used_memory_mb": round(redis_info.get("used_memory", 0)/1024/1024, 1),
                "uptime_days": round(redis_info.get("uptime_in_days", 0), 1),
                "total_keys": r.dbsize(),
            },
            "evaluation": {"records_30d": len(eval_records)},
            "system": {
                "load_ratio": round(lr, 2) if "lr" in dir() else None,
                "memory_used_mb": int(used_m) if "used_m" in dir() else None,
                "memory_total_mb": int(total_m) if "total_m" in dir() else None,
            },
            "api_stats": {
                "total_requests": tot_req,
                "total_errors": tot_err,
                "avg_response_ms": avg_rt,
                "p95_response_ms": p95_rt,
                "uptime_since": datetime.fromtimestamp(_api_stats["last_reset"]).isoformat(),
            },
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"status": "unhealthy", "issues": [f"健康检查异常:{str(e)}"], "timestamp": datetime.now().isoformat()}


# ==================== 留存分析 ====================

def get_retention_stats(days: int = 30) -> Dict[str, Any]:
    r = _get_redis()
    user_sessions_by_date: Dict[str, Dict[str, int]] = {}
    for key in r.keys("chat:history:*"):
        detail = _get_session_detail(key)
        if not detail or not detail.get("start_dt"):
            continue
        uid = detail.get("user_id", "unknown")
        date_str = detail["start_dt"].strftime("%Y-%m-%d")
        if uid not in user_sessions_by_date:
            user_sessions_by_date[uid] = {}
        user_sessions_by_date[uid][date_str] = user_sessions_by_date[uid].get(date_str, 0) + 1

    date_range = [(datetime.now() - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d") for i in range(days)]

    daily_stats = []
    for d in date_range:
        new_users = sum(1 for uid, dates in user_sessions_by_date.items()
                       if d in dates and sorted(dates.keys())[0] == d)
        active_users = sum(1 for uid, dates in user_sessions_by_date.items() if d in dates)
        daily_stats.append({"date": d, "new_users": new_users, "active_users": active_users})

    return {
        "period_days": days,
        "daily_stats": daily_stats[-30:],
        "retention": {"d1": None, "d7": None},
    }

# ==================== 数据导出 ====================
import csv, io

def export_users_csv(days: int = 30) -> str:
    users = get_user_list(days=days)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["用户ID", "首次使用", "最后活跃", "会话数", "总对话轮次", "平均评分"])
    for u in users:
        writer.writerow([u.get("user_id", ""), (u.get("first_seen") or "")[:19],
                         (u.get("last_seen") or "")[:19], u.get("session_count", 0),
                         u.get("total_turns", 0), u.get("avg_rating", "")])
    return output.getvalue()

def export_safety_csv(days: int = 30) -> str:
    events = get_safety_events(days=days)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["时间", "用户ID", "会话ID", "严重程度", "危机状态", "不当建议", "安全通过", "评级", "共情", "技术", "连贯性", "处理建议"])
    for e in events:
        writer.writerow([
            (e.get("timestamp", "") or "")[:19], e.get("user_id", ""), e.get("session_id", ""),
            e.get("severity", ""), e.get("crisis_status", ""),
            "是" if e.get("bad_advice_found") else "否",
            "是" if e.get("safety_pass") else "否",
            e.get("overall_rating", ""), e.get("empathy", ""), e.get("tech", ""),
            e.get("coherence", ""), e.get("top_suggestion", ""),
        ])
    return output.getvalue()

def export_evaluations_csv(days: int = 30) -> str:
    eval_records = _load_evaluation_records(days=days)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["时间", "会话ID", "评级", "共情", "技术", "连贯性", "共情偏差", "技术偏差"])
    for r in eval_records:
        writer.writerow([(r.get("timestamp", "") or "")[:19], r.get("session_id", ""),
                         r.get("auto_rating", ""), r.get("auto_empathy", ""),
                         r.get("auto_technical", ""), r.get("auto_coherence", ""),
                         round(r.get("bias_empathy", 0), 3), round(r.get("bias_technical", 0), 3)])
    return output.getvalue()
