"""
B2B v2.5 路由测试: /auth/org/register, /auth/org/join, /auth/org/leave

复用 FastAPI TestClient + fakeredis (与现有 test_cbt_manager 同模式)。
不调真实 Resend, 邮件验证码直接预写到 redis。
"""
import json
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, fake_redis, tmp_path):
    """启动 FastAPI app 时, 把 redis_client 全局换成 fakeredis。
    并解决 main.py mount('/admin', StaticFiles(...)) 路径问题:
    pytest 下 Path(__file__).parent.parent 解到 tests/ 不存在,需准备 stub 目录。"""
    import os
    # 准备 stub 静态目录,避免 main 启动失败
    stub_root = tmp_path / "anmian_stub"
    (stub_root / "static" / "admin").mkdir(parents=True)
    (stub_root / "static" / "admin" / "index.html").write_text("<html></html>")
    (stub_root / "static").mkdir(exist_ok=True)
    # main.py 用 Path(__file__).parent.parent / "static/admin" 取目录,
    # 把它 monkeypatch 成 stub
    monkeypatch.setenv("ANMIAN_STATIC_ROOT", str(stub_root))

    import infra.redis_client as rc
    monkeypatch.setattr(rc, "redis_client", fake_redis)
    import services.org as org_mod
    monkeypatch.setattr(org_mod, "redis_client", fake_redis)
    # 关键:把 starlette.staticfiles.StaticFiles 替换成 no-op,
    # 这样 mount() 不报错;我们不测 /admin 静态服务,只测 API
    from starlette.staticfiles import StaticFiles
    _orig_init = StaticFiles.__init__
    def _patched_init(self, *args, **kwargs):
        kwargs["directory"] = str(stub_root / "static")
        kwargs.pop("html", None)
        return _orig_init(self, **kwargs)
    monkeypatch.setattr(StaticFiles, "__init__", _patched_init)

    import main as _main
    monkeypatch.setattr(_main, "redis_client", fake_redis)
    return TestClient(_main.app)


def _make_org_with_invite(fake_redis, max_uses=5, seat=10):
    """工具: 直接调 services.org 创一企业+邀请码,返回 (org_id, code)。"""
    from services.org import create_org, create_invite_code
    oid = create_org("Acme Corp", seat_quota=seat)
    code = create_invite_code(oid, max_uses=max_uses)
    return oid, code


def test_org_register_happy_path(client, fake_redis):
    """新用户邮箱 + 验证码 + 邀请码 一步完成。"""
    oid, code = _make_org_with_invite(fake_redis)
    fake_redis.setex("email_code:alice@acme.com", 600, "123456")
    r = client.post("/api/v1/auth/org/register", json={
        "email": "alice@acme.com",
        "code": "123456",
        "invite_code": code,
    })
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["is_new_user"] is True
    assert j["org"]["org_id"] == oid
    assert j["org"]["org_name"] == "Acme Corp"
    assert j["token"]
    # JWT 应可被 verify 出 org_id
    from services.auth import verify_jwt_token
    u = verify_jwt_token(j["token"])
    assert u.org_id == oid


def test_org_register_rejects_bad_code(client, fake_redis):
    oid, code = _make_org_with_invite(fake_redis)
    fake_redis.setex("email_code:alice@acme.com", 600, "999999")
    r = client.post("/api/v1/auth/org/register", json={
        "email": "alice@acme.com",
        "code": "000000",
        "invite_code": code,
    })
    assert r.status_code == 401


def test_org_register_rejects_bad_invite(client, fake_redis):
    fake_redis.setex("email_code:bob@acme.com", 600, "111111")
    r = client.post("/api/v1/auth/org/register", json={
        "email": "bob@acme.com",
        "code": "111111",
        "invite_code": "INVALID",
    })
    assert r.status_code == 400
    assert "无效" in r.json()["detail"] or "过期" in r.json()["detail"]


def test_org_register_rejects_when_seat_full(client, fake_redis):
    oid, code = _make_org_with_invite(fake_redis, max_uses=5, seat=1)
    # 先占满
    fake_redis.setex("email_code:a@acme.com", 600, "111111")
    client.post("/api/v1/auth/org/register", json={
        "email": "a@acme.com", "code": "111111", "invite_code": code,
    })
    # 第二个应被拒
    fake_redis.setex("email_code:b@acme.com", 600, "222222")
    r = client.post("/api/v1/auth/org/register", json={
        "email": "b@acme.com", "code": "222222", "invite_code": code,
    })
    assert r.status_code == 400
    assert "席位已满" in r.json()["detail"]


def test_org_join_with_existing_user(client, fake_redis):
    """已 B2C 注册的用户用 /auth/org/join 加入企业。"""
    from services.auth import create_jwt_for_user, verify_jwt_token
    oid, code = _make_org_with_invite(fake_redis)
    # 现有 B2C 用户(模拟一个已存在 JWT)
    user_id = "em_existing01"
    jwt_tok = create_jwt_for_user(user_id, openid="existing@personal.com")
    r = client.post(
        "/api/v1/auth/org/join",
        json={"invite_code": code},
        headers={"Authorization": f"Bearer {jwt_tok}"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["user_id"] == user_id   # 不变
    assert j["org"]["org_id"] == oid
    # 新 token 应带 org_id
    u = verify_jwt_token(j["token"])
    assert u.org_id == oid


def test_org_join_requires_auth(client):
    """无 JWT 应被中间件拦截。"""
    r = client.post("/api/v1/auth/org/join", json={"invite_code": "ABC123"})
    assert r.status_code == 401


def test_org_leave_unbinds_and_returns_clean_token(client, fake_redis):
    """员工退订: 重签 JWT 去掉 org_id,user:profile 等个人数据不动。"""
    from services.auth import create_jwt_for_user, verify_jwt_token
    from services.org import bind_user_to_org

    oid, code = _make_org_with_invite(fake_redis)
    user_id = "em_employee01"
    bind_user_to_org(user_id, code)
    # 预写个人数据,验证 leave 不动它
    fake_redis.set(f"user:profile:{user_id}", json.dumps({"avg_anxiety": 3.0}))
    fake_redis.set(f"user:memory:{user_id}", json.dumps({"session_count": 8}))

    org_tok = create_jwt_for_user(user_id, openid="emp@acme.com", org_id=oid)
    r = client.post(
        "/api/v1/auth/org/leave",
        headers={"Authorization": f"Bearer {org_tok}"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["was_in_org"] is True
    # 新 token 应不含 org_id
    u = verify_jwt_token(j["token"])
    assert u.org_id is None
    # 个人数据完整保留
    assert fake_redis.exists(f"user:profile:{user_id}") == 1
    assert fake_redis.exists(f"user:memory:{user_id}") == 1


def test_org_leave_idempotent_for_non_org_user(client, fake_redis):
    """B2C 用户没绑过企业,leave 返回 was_in_org=False,不抛错。"""
    from services.auth import create_jwt_for_user
    tok = create_jwt_for_user("em_solo", openid="solo@personal.com")
    r = client.post(
        "/api/v1/auth/org/leave",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert r.json()["was_in_org"] is False
