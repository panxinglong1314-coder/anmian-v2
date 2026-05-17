"""
用户反馈服务 — 用户提交文字意见 + Admin 后台查看

数据模型（Redis）：
  feedback:all            (sorted set, score=timestamp_ms)
      member = feedback_id（uuid4 前 16 位）
  feedback:{feedback_id}  (string, JSON 完整记录, TTL 365 天兜底)
      字段：feedback_id, user_id, nickname, content, platform, created_at(ISO)

仅查看，无 pending/resolved 流转。
"""
import json
import time
import uuid
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

from infra.redis_client import redis_client

logger = logging.getLogger(__name__)

# ===== Redis Keys =====
KEY_ALL = "feedback:all"
KEY_ITEM_PREFIX = "feedback:"

# 单条反馈 TTL 兜底（1 年），防 Redis 内存泄露
TTL_ITEM_SECONDS = 365 * 24 * 3600
# feedback:all zset 最多保留最新 N 条
MAX_KEEP = 2000
# 单条反馈内容上限
MAX_CONTENT_LEN = 500
# 同用户同内容去重窗口（秒）
DEDUP_WINDOW_SECONDS = 60


def _item_key(feedback_id: str) -> str:
    return f"{KEY_ITEM_PREFIX}{feedback_id}"


def _get_nickname(user_id: str) -> str:
    """从 user_profile 取昵称，便于运营识别（取不到返回空串）"""
    try:
        raw = redis_client.get(f"user_profile:{user_id}")
        if raw:
            return (json.loads(raw).get("nickname") or "").strip()
    except Exception:
        pass
    return ""


def submit_feedback(user_id: str, content: str, platform: str = "") -> Dict[str, Any]:
    """
    用户提交一条文字反馈。返回写入的记录（含 feedback_id）。
    - content 去空白、截断到 MAX_CONTENT_LEN
    - 60 秒内同用户同内容 → 视为重复点击，返回已存记录不新建
    """
    content = (content or "").strip()
    if not content:
        raise ValueError("反馈内容不能为空")
    content = content[:MAX_CONTENT_LEN]

    if not redis_client:
        raise RuntimeError("Redis 不可用")

    now_ms = int(time.time() * 1000)

    # 去重：扫最近 20 条，命中 60s 内同用户同内容则直接返回
    try:
        cutoff_ms = now_ms - DEDUP_WINDOW_SECONDS * 1000
        recent_ids = redis_client.zrevrange(KEY_ALL, 0, 19)
        for fid in recent_ids:
            raw = redis_client.get(_item_key(fid))
            if not raw:
                continue
            rec = json.loads(raw)
            if (rec.get("user_id") == user_id
                    and rec.get("content") == content
                    and rec.get("_ts_ms", 0) >= cutoff_ms):
                return rec
    except Exception as e:
        logger.warning(f"[feedback] dedup check failed: {e}")

    feedback_id = uuid.uuid4().hex[:16]
    created_at = datetime.now().isoformat(timespec="seconds")
    record = {
        "feedback_id": feedback_id,
        "user_id": user_id,
        "nickname": _get_nickname(user_id),
        "content": content,
        "platform": (platform or "")[:32],
        "created_at": created_at,
        "_ts_ms": now_ms,
    }

    try:
        redis_client.set(
            _item_key(feedback_id),
            json.dumps(record, ensure_ascii=False),
            ex=TTL_ITEM_SECONDS,
        )
        redis_client.zadd(KEY_ALL, {feedback_id: now_ms})
        # 裁剪：只保留最新 MAX_KEEP 条
        total = redis_client.zcard(KEY_ALL)
        if total > MAX_KEEP:
            redis_client.zremrangebyrank(KEY_ALL, 0, total - MAX_KEEP - 1)
    except Exception as e:
        logger.error(f"[feedback] write failed: {e}")
        raise

    return record


def get_feedback_list(limit: int = 100, days: int = 0) -> List[Dict[str, Any]]:
    """
    获取反馈列表，按时间倒序。
    - limit：最多返回条数
    - days>0：只返回最近 N 天的
    """
    if not redis_client:
        return []
    try:
        if days and days > 0:
            min_score = int((time.time() - days * 24 * 3600) * 1000)
            ids = redis_client.zrevrangebyscore(KEY_ALL, "+inf", min_score, start=0, num=limit)
        else:
            ids = redis_client.zrevrange(KEY_ALL, 0, limit - 1)
        out: List[Dict[str, Any]] = []
        for fid in ids:
            raw = redis_client.get(_item_key(fid))
            if not raw:
                continue
            try:
                rec = json.loads(raw)
                rec.pop("_ts_ms", None)  # 内部字段不外露
                out.append(rec)
            except Exception:
                continue
        return out
    except Exception as e:
        logger.error(f"[feedback] list failed: {e}")
        return []


def get_feedback_stats() -> Dict[str, Any]:
    """反馈统计：总数 + 近 7 天数"""
    if not redis_client:
        return {"total": 0, "recent_7d": 0}
    try:
        total = redis_client.zcard(KEY_ALL) or 0
        seven_days_ago_ms = int((time.time() - 7 * 24 * 3600) * 1000)
        recent_7d = redis_client.zcount(KEY_ALL, seven_days_ago_ms, "+inf") or 0
        return {"total": total, "recent_7d": recent_7d}
    except Exception as e:
        logger.error(f"[feedback] stats failed: {e}")
        return {"total": 0, "recent_7d": 0}
