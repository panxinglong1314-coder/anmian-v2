"""
Admin 审计日志服务
记录敏感操作（删除用户、ack 危机、导出数据等）
"""
import json
from datetime import datetime
from infra.redis_client import redis_client

AUDIT_KEY_PREFIX = "admin:audit"
MAX_AUDIT_LOGS = 5000


def log_admin_action(action: str, operator: str, detail: dict):
    """记录一条审计日志到 Redis list"""
    try:
        entry = {
            "action": action,
            "operator": operator,
            "detail": detail,
            "timestamp": datetime.now().isoformat(),
        }
        redis_client.lpush(f"{AUDIT_KEY_PREFIX}:logs", json.dumps(entry, ensure_ascii=False))
        redis_client.ltrim(f"{AUDIT_KEY_PREFIX}:logs", 0, MAX_AUDIT_LOGS - 1)
    except Exception:
        pass


def get_recent_audit_logs(limit: int = 100) -> list:
    """获取最近审计日志"""
    try:
        raw = redis_client.lrange(f"{AUDIT_KEY_PREFIX}:logs", 0, limit - 1)
        return [json.loads(x) for x in raw]
    except Exception:
        return []
