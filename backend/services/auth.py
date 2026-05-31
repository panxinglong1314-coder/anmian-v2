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
    # v2.5: B2B 转型 — 若用户属于某企业,此处为 org_id;B2C 个人用户为 None
    org_id: Optional[str] = None
    # 若用户在企业的具体 team 下,记录 team_id;无 team 则 None
    team_id: Optional[str] = None
    # 角色:'user'(普通员工/个人) | 'hr_admin'(企业 HR 管理员)
    role: str = "user"


def create_jwt_token(openid: str) -> str:
    payload = {
        "openid": openid,
        "user_id": f"wx_{openid[:16]}",
        "exp": datetime.utcnow() + timedelta(days=30)
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_jwt_for_user(
    user_id: str,
    openid: Optional[str] = None,
    days: int = 30,
    org_id: Optional[str] = None,
    team_id: Optional[str] = None,
    role: str = "user",
) -> str:
    """通用 JWT 签发：显式指定 user_id（用于邮箱/Apple/Google 等非微信身份源）。

    v2.5: 可选附加 org_id/team_id/role,用于 B2B 转型。无这些字段时是 B2C 个人 token,
    向后兼容现有所有调用方。
    """
    payload = {
        "openid": openid or user_id,
        "user_id": user_id,
        "exp": datetime.utcnow() + timedelta(days=days),
    }
    if org_id:
        payload["org_id"] = org_id
    if team_id:
        payload["team_id"] = team_id
    if role and role != "user":
        payload["role"] = role
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def verify_jwt_token(token: str) -> Optional[AuthUser]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return AuthUser(
            openid=payload["openid"],
            user_id=payload["user_id"],
            org_id=payload.get("org_id"),
            team_id=payload.get("team_id"),
            role=payload.get("role", "user"),
        )
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
