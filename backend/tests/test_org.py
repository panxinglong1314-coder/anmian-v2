"""
services/org.py 单元测试

覆盖:
- create_org / create_team / create_invite_code 正常路径
- bind_user_to_org: 正常 / 重复 / 邀请码无效 / 过期 / 用完 / seat_quota 满 /
  已在其它 org
- unbind_user: 清正反向索引,B2C 数据保持(测不动 user:profile)
- list_org_users / list_team_users / org_seat_usage
"""
import json
import time
import pytest
from datetime import datetime, timedelta


@pytest.fixture(autouse=True)
def _patch_redis(monkeypatch, fake_redis):
    """把 infra.redis_client.redis_client 换成 fakeredis。"""
    import infra.redis_client as rc
    monkeypatch.setattr(rc, "redis_client", fake_redis)
    # services.org 已 from infra.redis_client import redis_client (绑定时取值),
    # 需同时打 patch 让模块全局变量切换
    import services.org as org_mod
    monkeypatch.setattr(org_mod, "redis_client", fake_redis)
    yield


def test_create_org_and_get():
    from services.org import create_org, get_org
    oid = create_org(name="Acme Corp", industry="tech", seat_quota=50,
                     contact_hr_email="hr@acme.com")
    assert oid.startswith("org_")
    o = get_org(oid)
    assert o["name"] == "Acme Corp"
    assert o["industry"] == "tech"
    assert o["seat_quota"] == 50
    assert o["status"] == "active"


def test_create_team_under_org():
    from services.org import create_org, create_team, get_team, list_teams
    oid = create_org("Acme")
    tid = create_team(oid, "Engineering", manager_email="lead@acme.com")
    assert tid.startswith("tm_")
    t = get_team(tid)
    assert t["team_name"] == "Engineering"
    assert t["org_id"] == oid
    assert list_teams(oid) == [tid]


def test_create_team_rejects_unknown_org():
    from services.org import create_team
    with pytest.raises(ValueError):
        create_team("org_nonexistent", "X")


def test_invite_code_basic_round_trip():
    from services.org import create_org, create_invite_code, get_invite_code
    oid = create_org("Acme")
    code = create_invite_code(oid, expire_days=30, max_uses=5)
    assert len(code) == 6
    inv = get_invite_code(code)
    assert inv["org_id"] == oid
    assert inv["max_uses"] == 5
    assert inv["used"] == 0
    # 大小写不敏感
    assert get_invite_code(code.lower())["org_id"] == oid


def test_bind_user_to_org_happy_path():
    from services.org import (create_org, create_team, create_invite_code,
                              bind_user_to_org, get_user_org, get_user_team,
                              list_org_users, list_team_users)
    oid = create_org("Acme", seat_quota=10)
    tid = create_team(oid, "Eng")
    code = create_invite_code(oid, team_id=tid)
    ok, msg, info = bind_user_to_org("user_A", code)
    assert ok, msg
    assert info["org_id"] == oid
    assert info["team_id"] == tid
    assert get_user_org("user_A") == oid
    assert get_user_team("user_A") == tid
    assert list_org_users(oid) == ["user_A"]
    assert list_team_users(tid) == ["user_A"]


def test_bind_user_rejects_invalid_code():
    from services.org import bind_user_to_org
    ok, msg, _ = bind_user_to_org("user_A", "INVALID")
    assert not ok
    assert "无效" in msg or "过期" in msg


def test_bind_user_rejects_when_code_used_up():
    from services.org import create_org, create_invite_code, bind_user_to_org
    oid = create_org("Acme", seat_quota=10)
    code = create_invite_code(oid, max_uses=1)
    ok1, _, _ = bind_user_to_org("u1", code)
    assert ok1
    ok2, msg, _ = bind_user_to_org("u2", code)
    assert not ok2
    assert "用完" in msg


def test_bind_user_rejects_seat_quota_exceeded():
    from services.org import create_org, create_invite_code, bind_user_to_org
    oid = create_org("Acme", seat_quota=2)
    code = create_invite_code(oid, max_uses=10)
    bind_user_to_org("u1", code)
    bind_user_to_org("u2", code)
    ok, msg, _ = bind_user_to_org("u3", code)
    assert not ok
    assert "席位已满" in msg


def test_bind_user_idempotent_same_org():
    from services.org import create_org, create_invite_code, bind_user_to_org
    oid = create_org("Acme", seat_quota=2)
    code = create_invite_code(oid, max_uses=10)
    ok1, _, _ = bind_user_to_org("u1", code)
    # 同用户再绑同 org 不应占新席位(used 仍会 +1, 但席位计数不动)
    ok2, _, _ = bind_user_to_org("u1", code)
    assert ok1 and ok2
    # 还能容纳一个新人(seat=2)
    ok3, _, _ = bind_user_to_org("u2", code)
    assert ok3


def test_bind_user_rejects_when_already_in_other_org():
    from services.org import create_org, create_invite_code, bind_user_to_org
    oid1 = create_org("Acme")
    oid2 = create_org("Globex")
    c1 = create_invite_code(oid1)
    c2 = create_invite_code(oid2)
    bind_user_to_org("u1", c1)
    ok, msg, _ = bind_user_to_org("u1", c2)
    assert not ok
    assert "已属于另一企业" in msg


def test_unbind_user_clears_indices():
    from services.org import (create_org, create_team, create_invite_code,
                              bind_user_to_org, unbind_user, get_user_org,
                              get_user_team, list_org_users, list_team_users)
    oid = create_org("Acme")
    tid = create_team(oid, "Eng")
    code = create_invite_code(oid, team_id=tid)
    bind_user_to_org("u1", code)
    assert get_user_org("u1") == oid
    ok = unbind_user("u1")
    assert ok
    assert get_user_org("u1") is None
    assert get_user_team("u1") is None
    assert list_org_users(oid) == []
    assert list_team_users(tid) == []


def test_unbind_user_does_not_touch_b2c_data(fake_redis):
    """关键: unbind 不删 user:profile / user:memory 等 B2C 数据。"""
    from services.org import create_org, create_invite_code, bind_user_to_org, unbind_user
    # 模拟现存 B2C 数据
    fake_redis.set("user:profile:u1", json.dumps({"avg_anxiety_recovery_turns": 3.5}))
    fake_redis.set("user:memory:u1", json.dumps({"session_count": 5}))
    oid = create_org("Acme")
    code = create_invite_code(oid)
    bind_user_to_org("u1", code)
    unbind_user("u1")
    # B2C 数据应该完整保留
    assert fake_redis.exists("user:profile:u1") == 1
    assert fake_redis.exists("user:memory:u1") == 1


def test_org_seat_usage():
    from services.org import (create_org, create_invite_code, bind_user_to_org,
                              org_seat_usage)
    oid = create_org("Acme", seat_quota=5)
    code = create_invite_code(oid, max_uses=10)
    assert org_seat_usage(oid) == (0, 5)
    bind_user_to_org("u1", code)
    bind_user_to_org("u2", code)
    assert org_seat_usage(oid) == (2, 5)


def test_invite_code_expired_rejected(fake_redis):
    """模拟邀请码过期(改写 hash 里的 expire_at 字段)。"""
    from services.org import create_org, create_invite_code, bind_user_to_org, k_org_invite
    oid = create_org("Acme")
    code = create_invite_code(oid, expire_days=30)
    # 倒推 expire_at 到 1 天前
    past = (datetime.utcnow() - timedelta(days=1)).isoformat(timespec="seconds") + "Z"
    fake_redis.hset(k_org_invite(code), "expire_at", past)
    ok, msg, _ = bind_user_to_org("u1", code)
    assert not ok
    assert "过期" in msg


def test_create_invite_rejects_unknown_org():
    from services.org import create_invite_code
    with pytest.raises(ValueError):
        create_invite_code("org_nonexistent")
