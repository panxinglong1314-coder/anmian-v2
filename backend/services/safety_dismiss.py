"""
安全事件软删除 (soft-dismiss)。

设计:
- 安全事件本身来自 evaluation_tracking/bias_*.jsonl, 是审计资产, **绝不真删**
- 用户(运营)点"删除"只意味着"从列表里隐藏" → 维护一个 Redis set
  safety:dismissed:{session_id}
- get_safety_events 在 admin_routes.py 里需要过滤这个 set
- 真要做"重新审视已处理事件"还能恢复

Redis key: safety:dismissed (set, member=session_id)
"""
from __future__ import annotations
from typing import Set

from infra.redis_client import redis_client


KEY_DISMISSED = "safety:dismissed"


def dismiss_safety_event(session_id: str) -> bool:
    """把一个 session_id 加入"已处理"集合, 后续列表不再展示。"""
    if not redis_client or not session_id:
        return False
    redis_client.sadd(KEY_DISMISSED, session_id)
    return True


def restore_safety_event(session_id: str) -> bool:
    """恢复 (从隐藏集合移除)。"""
    if not redis_client or not session_id:
        return False
    return bool(redis_client.srem(KEY_DISMISSED, session_id))


def list_dismissed() -> Set[str]:
    """返回所有被隐藏的 session_id 集合。空 set 若 Redis 不可用。"""
    if not redis_client:
        return set()
    raw = redis_client.smembers(KEY_DISMISSED) or set()
    return {(x.decode() if isinstance(x, bytes) else x) for x in raw}


def is_dismissed(session_id: str) -> bool:
    if not redis_client or not session_id:
        return False
    return bool(redis_client.sismember(KEY_DISMISSED, session_id))
