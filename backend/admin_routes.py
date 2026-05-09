"""
知眠轻量运营后台 API
仪表盘 / 安全中心 / AI 质量监控 / 用户管理
"""
import json
import os
import glob
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

LOG_DIR = Path(__file__).parent.parent / "conversation_logs"
EVAL_TRACK_DIR = Path(__file__).parent.parent / "evaluation_tracking"


def _list_session_logs(days: int = 30) -> List[Dict]:
    """读取最近 N 天的会话日志"""
    logs = []
    cutoff = datetime.now() - timedelta(days=days)
    for fpath in sorted(glob.glob(str(LOG_DIR / "sess_*.json"))):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            if mtime < cutoff:
                continue
            with open(fpath, 'r', encoding='utf-8') as f:
                log = json.load(f)
            log["_mtime"] = mtime.isoformat()
            logs.append(log)
        except Exception:
            continue
    return logs


# ==================== 仪表盘 ====================

def get_dashboard_stats(days: int = 7, limit: int = 500) -> Dict[str, Any]:
    """仪表盘核心指标"""
    logs = _list_session_logs(days=days)
    if not logs:
        return {"message": "暂无数据", "period_days": days}

    # 活跃用户（去重）
    active_users = set()
    total_turns = 0
    session_durations = []
    night_sessions = 0  # 22:00-06:00
    ratings = []
    outcomes = {}

    for log in logs:
        active_users.add(log.get("user_id", "unknown"))
        turns = log.get("turns", [])
        total_turns += len(turns)

        # 会话时长
        start = log.get("start_time", "")
        end = log.get("end_time", "")
        if start and end:
            try:
                s = datetime.fromisoformat(start)
                e = datetime.fromisoformat(end)
                duration = (e - s).total_seconds() / 60.0
                session_durations.append(duration)
            except Exception:
                pass

        # 夜间使用占比
        if start:
            try:
                hour = datetime.fromisoformat(start).hour
                if hour >= 22 or hour < 6:
                    night_sessions += 1
            except Exception:
                pass

        # 用户评分
        r = log.get("rating")
        if r:
            ratings.append(r)

        # 结局分布
        o = log.get("outcome", "unknown")
        outcomes[o] = outcomes.get(o, 0) + 1

    # 评估评级分布
    rating_dist = {"🟢优秀": 0, "🟡良好": 0, "🟠需改进": 0, "🔴不合格": 0}
    for log in logs:
        r = log.get("quality_evaluation", {}).get("report", {}).get("overall_rating", "")
        if r in rating_dist:
            rating_dist[r] += 1

    return {
        "period_days": days,
        "total_sessions": len(logs),
        "active_users": len(active_users),
        "avg_turns_per_session": round(total_turns / len(logs), 1) if logs else 0,
        "avg_duration_min": round(sum(session_durations) / len(session_durations), 1) if session_durations else 0,
        "night_ratio": round(night_sessions / len(logs), 2) if logs else 0,
        "rating_distribution": rating_dist,
        "user_rating_avg": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "outcome_distribution": outcomes,
    }


# ==================== 安全中心 ====================

def get_safety_events(days: int = 30, limit: int = 500) -> List[Dict]:
    """安全事件列表"""
    logs = _list_session_logs(days=days)
    events = []
    for log in logs:
        report = log.get("quality_evaluation", {}).get("report", {})
        safety = report.get("safety", {})
        if safety.get("crisis_status") != "未触发" or safety.get("bad_advice_found"):
            events.append({
                "session_id": log.get("session_id"),
                "user_id": log.get("user_id"),
                "timestamp": log.get("_mtime"),
                "crisis_status": safety.get("crisis_status"),
                "bad_advice_found": safety.get("bad_advice_found", False),
                "safety_pass": safety.get("pass", False),
                "overall_rating": report.get("overall_rating", ""),
                "top_suggestion": report.get("top_suggestion", ""),
                "handled": False,  # 运营可手动标记
            })
    return events


# ==================== AI 质量监控 ====================

def get_quality_stats(days: int = 30, limit: int = 500) -> Dict[str, Any]:
    """AI 质量监控统计"""
    logs = _list_session_logs(days=days)
    if not logs:
        return {"message": "暂无数据"}

    empathy_scores = []
    tech_scores = []
    coherence_scores = []
    fragments = []

    for log in logs:
        report = log.get("quality_evaluation", {}).get("report", {})
        e = report.get("empathy", {})
        t = report.get("technical", {})
        c = report.get("coherence", {})
        if e.get("score") is not None:
            empathy_scores.append(e["score"])
        if t.get("total") is not None:
            tech_scores.append(t["total"])
        if c.get("score") is not None:
            coherence_scores.append(c["score"])
        fragments.extend(report.get("all_fragments", []))

    # 高频失败模式统计
    issue_counts = {}
    for f in fragments:
        issue = f.get("issue", "")
        if issue:
            # 简化归类
            key = issue
            if "模板化" in issue or "评判性" in issue:
                key = "模板化/评判性语言"
            elif "说教" in issue:
                key = "说教语气"
            elif "漂移" in issue:
                key = "话题漂移"
            elif "风格" in issue:
                key = "Persona风格不匹配"
            issue_counts[key] = issue_counts.get(key, 0) + 1

    top_issues = sorted(issue_counts.items(), key=lambda x: -x[1])[:10]

    return {
        "period_days": days,
        "total_evaluated": len(logs),
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
        "top_failure_modes": [{"issue": k, "count": v} for k, v in top_issues],
    }


# ==================== 用户管理（轻量） ====================

def get_user_list(days: int = 30, limit: int = 500) -> List[Dict]:
    """用户列表（去重）"""
    logs = _list_session_logs(days=days)
    users = {}
    for log in logs:
        uid = log.get("user_id", "unknown")
        if uid not in users:
            users[uid] = {
                "user_id": uid,
                "first_seen": log.get("start_time"),
                "last_seen": log.get("start_time"),
                "session_count": 0,
                "avg_rating": None,
                "latest_rating": log.get("rating"),
            }
        users[uid]["session_count"] += 1
        if log.get("start_time", "") > users[uid]["last_seen"]:
            users[uid]["last_seen"] = log.get("start_time")
        if log.get("start_time", "") < users[uid]["first_seen"]:
            users[uid]["first_seen"] = log.get("start_time")

    # 计算平均评分
    for uid, u in users.items():
        ratings = [l.get("rating") for l in logs if l.get("user_id") == uid and l.get("rating")]
        if ratings:
            u["avg_rating"] = round(sum(ratings) / len(ratings), 1)

    return list(users.values())


def get_user_detail(user_id: str, limit: int = 20) -> Dict[str, Any]:
    """用户详情"""
    logs = []
    for fpath in sorted(glob.glob(str(LOG_DIR / "sess_*.json"))):
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                log = json.load(f)
            if log.get("user_id") == user_id:
                logs.append(log)
        except Exception:
            continue

    logs.sort(key=lambda x: x.get("start_time", ""), reverse=True)

    return {
        "user_id": user_id,
        "total_sessions": len(logs),
        "sessions": [
            {
                "session_id": l.get("session_id"),
                "start_time": l.get("start_time"),
                "outcome": l.get("outcome"),
                "rating": l.get("rating"),
                "rating_label": l.get("quality_evaluation", {}).get("report", {}).get("overall_rating", ""),
                "turn_count": len(l.get("turns", [])),
            }
            for l in logs[:20]
        ],
    }


# ==================== 数据导出（CSV） ====================

import csv
import io

def export_users_csv(days: int = 30) -> str:
    users = get_user_list(days=days)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["用户ID", "首次使用", "最后活跃", "会话数", "平均评分"])
    for u in users:
        writer.writerow([
            u.get("user_id", ""),
            (u.get("first_seen") or "")[:19],
            (u.get("last_seen") or "")[:19],
            u.get("session_count", 0),
            u.get("avg_rating", ""),
        ])
    return output.getvalue()


def export_safety_csv(days: int = 30) -> str:
    events = get_safety_events(days=days)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["时间", "用户ID", "会话ID", "危机状态", "不当建议", "安全通过", "评级", "TOP建议"])
    for e in events:
        writer.writerow([
            (e.get("timestamp") or "")[:19],
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
    logs = _list_session_logs(days=days)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["时间", "会话ID", "用户ID", "评级", "共情", "技术", "连贯性", "安全", "用户评分", "TOP建议"])
    for log in logs:
        report = log.get("quality_evaluation", {}).get("report", {})
        writer.writerow([
            (log.get("start_time") or "")[:19],
            log.get("session_id", ""),
            log.get("user_id", ""),
            report.get("overall_rating", ""),
            report.get("empathy", {}).get("score", ""),
            report.get("technical", {}).get("total", ""),
            report.get("coherence", {}).get("score", ""),
            "通过" if report.get("safety", {}).get("pass") else "未通过",
            log.get("rating", ""),
            report.get("top_suggestion", ""),
        ])
    return output.getvalue()
