"""
评估偏差追踪器 v2 — 按会话粒度评估，关联晨间睡眠数据
"""
import json
import os
import redis
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

TRACK_DIR = Path(__file__).parent.parent / "evaluation_tracking"
TRACK_DIR.mkdir(exist_ok=True)

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "") or None

_r = None
def _redis():
    global _r
    if _r is None:
        _r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0,
                         password=REDIS_PASSWORD, decode_responses=True)
    return _r


def _track_file() -> Path:
    return TRACK_DIR / f"bias_{datetime.now().strftime('%Y%m')}.jsonl"


def _get_morning_data(user_id: str, session_date: str) -> Optional[Dict]:
    """
    获取指定用户在 session 日期之后最近的晨间数据。
    session_date 格式: 'YYYY-MM-DD'（CST 日期）
    晨间数据 key: morning:{user_id}:{date}（date 为晨间早起日期，即入睡日的次日）
    所以 2026-05-09 的会话，次日晨间是 2026-05-10
    """
    try:
        r = _redis()
        # 晨间数据是次日早上提交，所以找 session_date + 1 天
        session_dt = datetime.strptime(session_date, "%Y-%m-%d")
        next_day = (session_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        key = f"morning:{user_id}:{next_day}"
        data = r.get(key)
        if data:
            return json.loads(data)
        # 如果没有精确匹配，找前后3天内最近的
        for delta in range(1, 4):
            prev = (session_dt - timedelta(days=delta)).strftime("%Y-%m-%d")
            key = f"morning:{user_id}:{prev}"
            data = r.get(key)
            if data:
                return json.loads(data)
        return None
    except Exception:
        return None


def _parse_session_date(session_id: str) -> Optional[str]:
    """从 session_id 提取 CST 日期字符串，如 'session_2026-05-09_...' → '2026-05-09'"""
    import re
    m = re.match(r"session_(\d{4}-\d{2}-\d{2})_", session_id)
    if m:
        return m.group(1)
    return None


def record_session_evaluation(
    session_id: str,
    auto_report: Dict[str, Any],
    user_id: Optional[str] = None,
    llm_report: Optional[Dict[str, Any]] = None,
):
    """
    记录完整会话评估（只调用一次，按会话粒度）。
    自动关联晨间睡眠数据作为 ground truth。

    Args:
        session_id: 会话ID
        auto_report: dialogue_evaluator 输出的完整报告（包含 .report）
        user_id: 用户openid（从 session_id 可推断）
        llm_report: 可选，LLM-as-Judge 复核结果
    """
    report = auto_report.get("report", {}) if isinstance(auto_report, dict) else auto_report

    entry = {
        "session_id": session_id,
        "timestamp": datetime.now().isoformat(),
        "auto_rating": report.get("overall_rating", ""),
        "auto_empathy": report.get("empathy", {}).get("score"),
        "auto_technical": report.get("technical", {}).get("total"),
        "auto_coherence": report.get("coherence", {}).get("score"),
        "auto_empathy_raw": report.get("empathy", {}).get("score"),
        "auto_technical_raw": report.get("technical", {}).get("total"),
    }

    # 推断 user_id 和 session_date
    if not user_id:
        # session_id 格式: chat:history:{user_id}:session_{date}_{ts}
        # 或直接: session_{date}_{ts}
        parts = session_id.split("_")
        if len(parts) >= 4:
            user_id = parts[1] if parts[0] in ("wx", "user", "stream", "test") else None

    session_date = _parse_session_date(session_id)

    # 关联晨间睡眠数据（ground truth）
    if user_id and session_date:
        morning = _get_morning_data(user_id, session_date)
        if morning:
            entry["morning_sleep_quality"] = morning.get("sleep_quality")  # 1-4
            entry["morning_se"] = morning.get("se")                         # 0-100
            entry["morning_tst_minutes"] = morning.get("tst_minutes")       # 实际睡眠时长
            entry["morning_bed_time"] = morning.get("bed_time_estimate")
            entry["morning_wake_time"] = morning.get("wake_time_estimate")
            entry["morning_fatigue_level"] = morning.get("fatigue_level")    # 1-5
            entry["morning_waso"] = morning.get("waso_minutes", 0)            # 半夜醒来分钟

    # LLM 复核偏差
    if llm_report and not llm_report.get("error"):
        llm_rep = llm_report.get("report", llm_report)
        entry["llm_rating"] = llm_rep.get("overall_rating", "")
        entry["llm_empathy"] = llm_rep.get("empathy", {}).get("score")
        entry["llm_technical"] = llm_rep.get("technical", {}).get("total")
        entry["llm_coherence"] = llm_rep.get("coherence", {}).get("score")

        def _bias(auto, llm):
            return round((llm or 0) - (auto or 0), 3)

        entry["bias_empathy"] = _bias(entry.get("auto_empathy"), entry.get("llm_empathy"))
        entry["bias_technical"] = _bias(entry.get("auto_technical"), entry.get("llm_technical"))
        entry["bias_coherence"] = _bias(entry.get("auto_coherence"), entry.get("llm_coherence"))

    with open(_track_file(), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def get_evaluation_stats(days: int = 30) -> Dict[str, Any]:
    """获取评估统计（含晨间睡眠关联分析）"""
    file_path = _track_file()
    if not file_path.exists():
        return {"message": "暂无追踪数据"}

    entries = []
    cutoff = datetime.now() - timedelta(days=days)
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line.strip())
                ts = e.get("timestamp", "")
                if ts:
                    t = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
                    if t < cutoff:
                        continue
                entries.append(e)
            except Exception:
                continue

    if not entries:
        return {"message": "暂无追踪数据", "period_days": days}

    # 基本统计
    auto_emp = [e["auto_empathy"] for e in entries if e.get("auto_empathy") is not None]
    auto_tech = [e["auto_technical"] for e in entries if e.get("auto_technical") is not None]

    import statistics
    def mean(vals):
        return round(statistics.mean(vals), 2) if vals else None

    stats = {
        "period_days": days,
        "total_sessions": len(entries),
        "auto_empathy_mean": mean(auto_emp),
        "auto_technical_mean": mean(auto_tech),
        "rating_dist": {
            k: sum(1 for e in entries if e.get("auto_rating") == k)
            for k in ["🟢优秀", "🟡良好", "🟠需改进", "🔴不合格"]
        },
    }

    # 晨间睡眠关联分析
    with_morning = [e for e in entries if e.get("morning_sleep_quality") is not None]
    if with_morning:
        sq_vals = [e["morning_sleep_quality"] for e in with_morning]
        stats["morning_associated"] = {
            "count": len(with_morning),
            "avg_sleep_quality": mean(sq_vals),
            "correlation_example": [
                {
                    "session": e["session_id"][-30:],
                    "auto_rating": e.get("auto_rating", ""),
                    "sleep_quality": e.get("morning_sleep_quality"),
                    "se": e.get("morning_se"),
                }
                for e in with_morning[-10:]
            ]
        }

    # LLM 偏差
    compared = [e for e in entries if "llm_rating" in e]
    if compared:
        bias_emp = [e["bias_empathy"] for e in compared if "bias_empathy" in e]
        bias_tech = [e["bias_technical"] for e in compared if "bias_technical" in e]
        agree = sum(1 for e in compared if e.get("auto_rating") == e.get("llm_rating"))
        stats["llm_bias"] = {
            "compared_count": len(compared),
            "agreement_rate": round(agree / len(compared), 2),
            "empathy_bias_mean": mean(bias_emp),
            "technical_bias_mean": mean(bias_tech),
        }

    return stats


# ── 兼容旧接口 ──────────────────────────────────────────────────────────────
def record_evaluation(session_id: str, auto_report: Dict[str, Any], llm_report: Optional[Dict[str, Any]] = None):
    """兼容旧接口：透传到新版"""
    return record_session_evaluation(session_id, auto_report, llm_report=llm_report)

# 兼容旧接口
def get_bias_stats(days=30):
    return get_evaluation_stats(days=days)
