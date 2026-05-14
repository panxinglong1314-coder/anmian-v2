"""
认证服务（从 main.py 提取）
JWT token 创建与验证
"""
from typing import Optional
from datetime import datetime, timedelta
import jwt
from pydantic import BaseModel

from infra.settings import settings


class AuthUser(BaseModel):
    openid: str
    user_id: str


def create_jwt_token(openid: str) -> str:
    payload = {
        "openid": openid,
        "user_id": f"wx_{openid[:16]}",
        "exp": datetime.utcnow() + timedelta(days=30)
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def verify_jwt_token(token: str) -> Optional[AuthUser]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return AuthUser(openid=payload["openid"], user_id=payload["user_id"])
    except jwt.PyJWTError:
        return None


# ===== Admin JWT Session =====

def create_admin_jwt() -> str:
    """签发 Admin JWT（4 小时有效期）"""
    payload = {
        "role": "admin",
        "exp": datetime.utcnow() + timedelta(hours=4),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def verify_admin_jwt(token: str) -> bool:
    """验证 Admin JWT"""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload.get("role") == "admin"
    except jwt.PyJWTError:
        return False
