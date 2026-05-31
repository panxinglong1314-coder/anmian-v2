"""
services/auth.py v2.5 测试: B2B 字段(org_id/team_id/role)的 JWT 往返。

关键不变量:
- 老 token(无这些字段)继续工作,AuthUser 默认值正确
- B2B token 携带 org_id/team_id/role 可正确解析
"""
import pytest


def test_legacy_token_still_works():
    """旧调用方式(不传 org_id) → 仍能签发与验证,B2B 字段为默认。"""
    from services.auth import create_jwt_for_user, verify_jwt_token
    tok = create_jwt_for_user("wx_test123")
    u = verify_jwt_token(tok)
    assert u is not None
    assert u.user_id == "wx_test123"
    assert u.org_id is None
    assert u.team_id is None
    assert u.role == "user"


def test_b2b_token_round_trip():
    from services.auth import create_jwt_for_user, verify_jwt_token
    tok = create_jwt_for_user(
        "em_alice", openid="em_alice",
        org_id="org_acme01", team_id="tm_eng",
        role="hr_admin",
    )
    u = verify_jwt_token(tok)
    assert u.user_id == "em_alice"
    assert u.org_id == "org_acme01"
    assert u.team_id == "tm_eng"
    assert u.role == "hr_admin"


def test_b2b_token_without_team():
    """企业员工但无 team_id (公司只有 org 没分 team)。"""
    from services.auth import create_jwt_for_user, verify_jwt_token
    tok = create_jwt_for_user("em_bob", org_id="org_startup")
    u = verify_jwt_token(tok)
    assert u.org_id == "org_startup"
    assert u.team_id is None
    assert u.role == "user"


def test_role_default_user_not_emitted():
    """role='user' 是默认,不应写入 payload(节省 token 大小 + 向后兼容)。"""
    from services.auth import create_jwt_for_user
    import jwt as _jwt
    from infra.settings import settings
    tok = create_jwt_for_user("u1")
    payload = _jwt.decode(tok, settings.jwt_secret, algorithms=["HS256"])
    assert "role" not in payload  # 默认 'user' 不写
    assert "org_id" not in payload


def test_invalid_token_returns_none():
    from services.auth import verify_jwt_token
    assert verify_jwt_token("garbage") is None
    assert verify_jwt_token("") is None
