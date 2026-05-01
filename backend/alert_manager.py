"""
知眠告警管理器
支持：企业微信/钉钉/飞书 Webhook
触发条件：🔴不合格 / 🟠需改进 / 安全漏报
"""
import json
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass

ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")
ALERT_ENABLED = os.getenv("ALERT_ENABLED", "true").lower() == "true"
ALERT_MIN_RATING = os.getenv("ALERT_MIN_RATING", "🟠需改进")

_alert_cache: Dict[str, float] = {}
_ALERT_COOLDOWN_SECONDS = 3600


def _should_alert(session_id: str) -> bool:
    last_alert = _alert_cache.get(session_id)
    if last_alert and (time.time() - last_alert) < _ALERT_COOLDOWN_SECONDS:
        return False
    _alert_cache[session_id] = time.time()
    return True


def _rating_level(rating: str) -> int:
    levels = {"🔴不合格": 0, "🟠需改进": 1, "🟡良好": 2, "🟢优秀": 3}
    return levels.get(rating, 4)


def send_alert(report: Dict[str, Any], session_log: Optional[Dict] = None) -> bool:
    if not ALERT_ENABLED or not ALERT_WEBHOOK_URL:
        return False

    session_id = report.get("session_id", "unknown")
    if not _should_alert(session_id):
        return False

    rating = report.get("overall_rating", "")
    if _rating_level(rating) > _rating_level(ALERT_MIN_RATING):
        return False

    safety = report.get("safety", {})
    empathy = report.get("empathy", {})
    technical = report.get("technical", {})
    coherence = report.get("coherence", {})

    title = "🔴【知眠】不合格会话告警" if rating == "🔴不合格" else "🟠【知眠】需改进会话告警"

    content = (
        f"**{title}**\n"
        f"> 会话ID：`{session_id}`\n"
        f"> 用户ID：`{report.get('user_id', 'unknown')}`\n"
        f"> 阶段：`{report.get('stage', 'unknown')}`\n"
        f"> 评级：**{rating}**\n\n"
        f"**各维度评分**\n"
        f"- 共情：{empathy.get('score', 0)}/5\n"
        f"- 技术有效性：{technical.get('total', 0)}/9\n"
        f"- 连贯性：{coherence.get('score', 0)}/5\n"
        f"- 安全：{'通过' if safety.get('pass') else '未通过'}（{safety.get('crisis_status', 'N/A')}）\n\n"
        f"**TOP建议**：{report.get('top_suggestion', '无')}\n"
    )

    if safety.get("bad_advice_found"):
        content += "\n⚠️ **检测到不当建议，需立即人工复核！**\n"

    payload = {
        "msgtype": "markdown",
        "markdown": {"content": content},
    }

    try:
        import requests
        resp = requests.post(
            ALERT_WEBHOOK_URL,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[AlertManager] 发送告警失败: {e}")
        return False


def send_daily_report(stats: Dict[str, Any]) -> bool:
    if not ALERT_ENABLED or not ALERT_WEBHOOK_URL:
        return False

    dist = stats.get("rating_distribution", {})
    content = (
        "📊 **知眠每日评估日报**\n\n"
        f"- 总会话数：{stats.get('session_count', 0)}\n"
        f"- 平均分：{stats.get('overall', {}).get('mean', 0)}\n"
        f"- 🟢优秀：{dist.get('🟢优秀', 0)}\n"
        f"- 🟡良好：{dist.get('🟡良好', 0)}\n"
        f"- 🟠需改进：{dist.get('🟠需改进', 0)}\n"
        f"- 🔴不合格：{dist.get('🔴不合格', 0)}\n"
    )

    if dist.get("🔴不合格", 0) > 0:
        content += "\n⚠️ 今日存在不合格会话，请关注！\n"

    payload = {
        "msgtype": "markdown",
        "markdown": {"content": content},
    }

    try:
        import requests
        resp = requests.post(
            ALERT_WEBHOOK_URL,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[AlertManager] 发送日报失败: {e}")
        return False
