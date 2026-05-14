"""
危机告警服务 — 高危事件入队 + Admin 后台拉取与处理

数据模型（Redis）：
  crisis_alerts:pending  (sorted set, score=timestamp_ms)
      member = event_id（uuid4）
  crisis_alerts:resolved (sorted set, score=resolved_timestamp_ms, TTL 90 天)
      member = event_id
  crisis_alert:{event_id} (hash, 完整事件详情, TTL pending=∞ / resolved=90 天)
      fields:
        event_id, user_id, session_id, level, types(json), message,
        created_at(ISO), status(pending|resolved),
        ack_operator, ack_note, resolved_at(ISO)
"""
import json
import time
import uuid
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from infra.redis_client import redis_client


# ===== Redis Keys =====
KEY_PENDING = "crisis_alerts:pending"
KEY_RESOLVED = "crisis_alerts:resolved"
KEY_EVENT_PREFIX = "crisis_alert:"

# 已处理事件保留 90 天
TTL_RESOLVED_SECONDS = 90 * 24 * 3600
# 未处理事件本身不过期（除非主动 ack）；但 hash 仍设个 365 天兜底防 Redis 内存泄露
TTL_PENDING_FALLBACK = 365 * 24 * 3600

# 截断用户原文，防止过长消息撑爆 Redis
MAX_MESSAGE_PREVIEW = 500


def _event_key(event_id: str) -> str:
    return f"{KEY_EVENT_PREFIX}{event_id}"


def emit_crisis_alert(
    user_id: str,
    session_id: str,
    level: str,
    types: List[str],
    message: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    写入一条高危告警事件。返回 event_id（若 Redis 不可用则返回 None）。
    此函数应在 try/except 包裹下调用，**永远不应阻塞主对话流**。
    """
    if not redis_client:
        return None
    try:
        event_id = uuid.uuid4().hex[:16]
        now_ms = int(time.time() * 1000)
        created_at = datetime.now().isoformat(timespec="seconds")

        event = {
            "event_id": event_id,
            "user_id": user_id,
            "session_id": session_id,
            "level": level,
            "types": json.dumps(types or [], ensure_ascii=False),
            "message": (message or "")[:MAX_MESSAGE_PREVIEW],
            "created_at": created_at,
            "status": "pending",
            "ack_operator": "",
            "ack_note": "",
            "resolved_at": "",
        }
        if extra:
            event["extra"] = json.dumps(extra, ensure_ascii=False)

        # 写 hash + zset
        key = _event_key(event_id)
        redis_client.hset(key, mapping=event)
        redis_client.expire(key, TTL_PENDING_FALLBACK)
        redis_client.zadd(KEY_PENDING, {event_id: now_ms})

        logging.warning(
            f"[CrisisAlert] EMIT level={level} types={types} "
            f"user={user_id[:16]} session={session_id} event={event_id}"
        )
        return event_id
    except Exception as e:
        logging.error(f"[CrisisAlert] emit 失败: {e}")
        return None


def get_unread_count() -> int:
    """轻量查询：未处理告警数量（前端轮询用）"""
    if not redis_client:
        return 0
    try:
        return int(redis_client.zcard(KEY_PENDING) or 0)
    except Exception:
        return 0


def _load_event(event_id: str) -> Optional[Dict[str, Any]]:
    """从 Redis 加载一条事件并解码"""
    key = _event_key(event_id)
    raw = redis_client.hgetall(key)
    if not raw:
        return None
    # decode_responses 已经在 redis client 配置了，但兜底
    out = {k.decode() if isinstance(k, bytes) else k:
           v.decode() if isinstance(v, bytes) else v
           for k, v in raw.items()}
    # types 字段是 JSON
    try:
        out["types"] = json.loads(out.get("types", "[]"))
    except Exception:
        out["types"] = []
    if "extra" in out:
        try:
            out["extra"] = json.loads(out["extra"])
        except Exception:
            pass
    return out


def get_pending_alerts(limit: int = 50) -> List[Dict[str, Any]]:
    """拉取未处理告警列表，按时间倒序"""
    if not redis_client:
        return []
    try:
        # 倒序拉前 limit 个
        ids = redis_client.zrevrange(KEY_PENDING, 0, limit - 1)
        ids = [i.decode() if isinstance(i, bytes) else i for i in ids]
        alerts = []
        for eid in ids:
            ev = _load_event(eid)
            if ev:
                alerts.append(ev)
        return alerts
    except Exception as e:
        logging.error(f"[CrisisAlert] get_pending 失败: {e}")
        return []


def get_history(days: int = 30, limit: int = 100) -> List[Dict[str, Any]]:
    """已处理历史"""
    if not redis_client:
        return []
    try:
        cutoff_ms = int((time.time() - days * 86400) * 1000)
        # zrangebyscore 取 cutoff 之后的，再倒序取前 limit
        ids = redis_client.zrevrangebyscore(KEY_RESOLVED, "+inf", cutoff_ms, start=0, num=limit)
        ids = [i.decode() if isinstance(i, bytes) else i for i in ids]
        alerts = []
        for eid in ids:
            ev = _load_event(eid)
            if ev:
                alerts.append(ev)
        return alerts
    except Exception as e:
        logging.error(f"[CrisisAlert] get_history 失败: {e}")
        return []


def ack_alert(event_id: str, operator: str = "admin", note: str = "") -> Dict[str, Any]:
    """
    标记已处理：
      - 从 pending zset 移除
      - 加入 resolved zset（score=now）
      - hash 状态字段更新
      - hash TTL 改为 90 天
    """
    if not redis_client:
        return {"success": False, "error": "Redis 不可用"}
    try:
        key = _event_key(event_id)
        if not redis_client.exists(key):
            return {"success": False, "error": "事件不存在或已过期"}

        # 检查是否已经处理过
        existing_status = redis_client.hget(key, "status")
        if isinstance(existing_status, bytes):
            existing_status = existing_status.decode()
        if existing_status == "resolved":
            return {"success": False, "error": "该事件已被其他运营标记处理"}

        now_ms = int(time.time() * 1000)
        resolved_at = datetime.now().isoformat(timespec="seconds")

        # 1. hash 更新
        redis_client.hset(key, mapping={
            "status": "resolved",
            "ack_operator": (operator or "admin")[:64],
            "ack_note": (note or "")[:1000],
            "resolved_at": resolved_at,
        })
        redis_client.expire(key, TTL_RESOLVED_SECONDS)

        # 2. zset 迁移：pending → resolved（原子操作组合）
        pipe = redis_client.pipeline()
        pipe.zrem(KEY_PENDING, event_id)
        pipe.zadd(KEY_RESOLVED, {event_id: now_ms})
        pipe.execute()

        logging.info(f"[CrisisAlert] ACK event={event_id} by={operator}")
        return {"success": True, "event_id": event_id, "resolved_at": resolved_at}
    except Exception as e:
        logging.error(f"[CrisisAlert] ack 失败: {e}")
        return {"success": False, "error": str(e)}


def get_event(event_id: str) -> Optional[Dict[str, Any]]:
    """单条事件详情查询"""
    if not redis_client:
        return None
    return _load_event(event_id)


def get_stats(days: int = 7) -> Dict[str, Any]:
    """统计：近 N 天告警分布（用于 Admin Dashboard 卡片）"""
    if not redis_client:
        return {"pending": 0, "resolved_recent": 0, "by_level": {}, "by_type": {}}
    try:
        cutoff_ms = int((time.time() - days * 86400) * 1000)
        pending_count = int(redis_client.zcard(KEY_PENDING) or 0)
        resolved_ids = redis_client.zrangebyscore(KEY_RESOLVED, cutoff_ms, "+inf")
        resolved_ids = [i.decode() if isinstance(i, bytes) else i for i in resolved_ids]
        resolved_count = len(resolved_ids)

        # 按 level / type 分类
        by_level = {"high": 0, "medium": 0, "low": 0}
        by_type: Dict[str, int] = {}
        for eid in resolved_ids:
            ev = _load_event(eid)
            if not ev:
                continue
            lvl = ev.get("level", "")
            if lvl in by_level:
                by_level[lvl] += 1
            for t in ev.get("types", []):
                by_type[t] = by_type.get(t, 0) + 1

        return {
            "pending": pending_count,
            "resolved_recent": resolved_count,
            "by_level": by_level,
            "by_type": by_type,
            "days": days,
        }
    except Exception as e:
        logging.error(f"[CrisisAlert] stats 失败: {e}")
        return {"pending": 0, "resolved_recent": 0, "by_level": {}, "by_type": {}}
