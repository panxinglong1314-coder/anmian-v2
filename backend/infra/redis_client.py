"""
Redis 客户端（从 main.py 提取）
"""
from typing import Optional
import redis

from infra.settings import settings

# 同步 Redis 客户端
redis_client = redis.Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    db=settings.redis_db,
    password=settings.redis_password or None,
    decode_responses=True
)

# 异步 Redis 客户端（由 lifespan 初始化）
async_redis_client: Optional[redis.asyncio.Redis] = None
