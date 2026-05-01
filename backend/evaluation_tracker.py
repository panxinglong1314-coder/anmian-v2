"""
评估偏差追踪器
记录 auto_v2 与 LLM 评估的偏差，用于迭代优化评估规则
"""
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

TRACK_DIR = Path(__file__).parent.parent / "evaluation_tracking"
TRACK_DIR.mkdir(exist_ok=True)


def _track_file() -> Path:
    return TRACK_DIR / f"bias_{datetime.now().strftime('%Y%m')}.jsonl"


def record_evaluation(session_id: str, auto_report: Dict[str, Any], llm_report: Optional[Dict[str, Any]] = None):
    """记录一次评估结果（auto + 可选 LLM）"""
    entry = {
        "session_id": session_id,
        "timestamp": datetime.now().isoformat(),
        "auto_rating": auto_report.get("overall_rating", ""),
        "auto_empathy": auto_report.get("empathy", {}).get("score"),
        "auto_technical": auto_report.get("technical", {}).get("total"),
        "auto_coherence": auto_report.get("coherence", {}).get("score"),
    }

    if llm_report and not llm_report.get("error"):
        entry["llm_rating"] = llm_report.get("overall_rating", "")
        entry["llm_empathy"] = llm_report.get("empathy", {}).get("score")
        entry["llm_technical"] = llm_report.get("technical", {}).get("total")
        entry["llm_coherence"] = llm_report.get("coherence", {}).get("score")

        # 计算偏差
        entry["bias_empathy"] = (entry.get("llm_empathy") or 0) - (entry.get("auto_empathy") or 0)
        entry["bias_technical"] = (entry.get("llm_technical") or 0) - (entry.get("auto_technical") or 0)
        entry["bias_coherence"] = (entry.get("llm_coherence") or 0) - (entry.get("auto_coherence") or 0)

    with open(_track_file(), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_bias_stats(days: int = 30) -> Dict[str, Any]:
    """获取评估偏差统计"""
    file_path = _track_file()
    if not file_path.exists():
        return {"message": "暂无追踪数据"}

    entries = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entries.append(json.loads(line.strip()))
            except Exception:
                continue

    if not entries:
        return {"message": "暂无追踪数据"}

    # 只统计有 LLM 复核的记录
    compared = [e for e in entries if "llm_rating" in e]
    if not compared:
        return {"message": "暂无 LLM 复核数据", "total_records": len(entries)}

    import statistics

    def _mean(vals):
        return round(statistics.mean(vals), 2) if vals else 0

    bias_empathy = [e["bias_empathy"] for e in compared if "bias_empathy" in e]
    bias_technical = [e["bias_technical"] for e in compared if "bias_technical" in e]
    bias_coherence = [e["bias_coherence"] for e in compared if "bias_coherence" in e]

    # 评级一致性
    agree = sum(1 for e in compared if e.get("auto_rating") == e.get("llm_rating"))

    return {
        "total_records": len(entries),
        "compared_records": len(compared),
        "agreement_rate": round(agree / len(compared), 2) if compared else 0,
        "bias": {
            "empathy_mean": _mean(bias_empathy),
            "technical_mean": _mean(bias_technical),
            "coherence_mean": _mean(bias_coherence),
        },
        "recent_disagreements": [
            {
                "session_id": e["session_id"],
                "auto": e.get("auto_rating"),
                "llm": e.get("llm_rating"),
                "bias_empathy": e.get("bias_empathy"),
            }
            for e in compared[-10:] if e.get("auto_rating") != e.get("llm_rating")
        ],
    }
