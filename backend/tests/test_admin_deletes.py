"""
4 个 admin 删除操作的服务层测试。
端点测试受 python-multipart 限制不写,只测纯服务函数。
"""
import json
import pytest


# ============== Sales lead 删除 ==============

@pytest.fixture(autouse=True)
def _patch_redis(monkeypatch, fake_redis):
    """把所有 services 的 redis_client 替换成 fake。"""
    import infra.redis_client as rc
    monkeypatch.setattr(rc, "redis_client", fake_redis)
    for mod_name in ("services.sales_lead", "services.feedback_service",
                     "services.org", "services.safety_dismiss"):
        try:
            mod = __import__(mod_name, fromlist=["redis_client"])
            monkeypatch.setattr(mod, "redis_client", fake_redis, raising=False)
        except (ImportError, AttributeError):
            pass


def test_delete_sales_lead_clears_hash_and_both_indices(fake_redis):
    from services.sales_lead import submit_lead, delete_lead, get_lead
    rec = submit_lead(
        company_name="Acme", contact_name="HR",
        contact_email="hr@acme.com", source="enterprise_page",
    )
    lid = rec["lead_id"]
    assert fake_redis.exists(f"sales_lead:{lid}") == 1
    assert fake_redis.zscore("sales_leads:pending", lid) is not None

    ok = delete_lead(lid)
    assert ok is True
    assert fake_redis.exists(f"sales_lead:{lid}") == 0
    assert fake_redis.zscore("sales_leads:pending", lid) is None
    assert fake_redis.zscore("sales_leads:archived", lid) is None
    assert get_lead(lid) is None


def test_delete_sales_lead_nonexistent_returns_false():
    from services.sales_lead import delete_lead
    assert delete_lead("nonexistent_lead_id") is False


# ============== Feedback 删除 ==============

def test_delete_feedback_clears_item_and_zset_index(fake_redis):
    from services.feedback_service import submit_feedback, delete_feedback
    rec = submit_feedback("u_test_001", "好用,很助眠")
    fid = rec["feedback_id"]
    assert fake_redis.exists(f"feedback:{fid}") == 1
    assert fake_redis.zscore("feedback:all", fid) is not None

    assert delete_feedback(fid) is True
    assert fake_redis.exists(f"feedback:{fid}") == 0
    assert fake_redis.zscore("feedback:all", fid) is None


def test_delete_feedback_can_clean_zset_residue_when_item_already_expired(fake_redis):
    """item TTL 过期但 zset 残留 → delete 应清掉 zset 残留。"""
    from services.feedback_service import delete_feedback
    fake_redis.zadd("feedback:all", {"orphan_fid": 1700000000000})
    # item key 故意不存在
    assert delete_feedback("orphan_fid") is True
    assert fake_redis.zscore("feedback:all", "orphan_fid") is None


def test_delete_feedback_nonexistent_returns_false():
    from services.feedback_service import delete_feedback
    assert delete_feedback("never_seen") is False


# ============== Org 级联删除 ==============

def test_delete_org_cascades_meta_teams_invites_indices_role(fake_redis):
    from services.org import (
        create_org, create_team, create_invite_code,
        bind_user_to_org, set_user_role, get_user_role, delete_org,
        k_org, k_org_users, k_user_org, k_org_invite,
    )
    oid = create_org("Acme", seat_quota=10)
    tid = create_team(oid, "Engineering")
    code = create_invite_code(oid, team_id=tid, role="hr_admin")

    bind_user_to_org("u_alpha", code)
    set_user_role("u_alpha", "hr_admin")
    # 第二个员工用普通码
    code2 = create_invite_code(oid, role="user")
    bind_user_to_org("u_beta", code2)

    # 假写一些 reports 缓存键
    fake_redis.set(f"org:report:{oid}:2026-05", "PDF_BYTES_BASE64")
    fake_redis.set(f"org:billing:{oid}", json.dumps({"plan": "trial"}))

    # 前置断言:数据都在
    assert fake_redis.exists(k_org(oid)) == 1
    assert fake_redis.exists(k_user_org("u_alpha")) == 1
    assert fake_redis.exists(k_org_invite(code)) == 1
    assert get_user_role("u_alpha") == "hr_admin"

    stats = delete_org(oid)

    # 级联清理生效
    assert stats["org_meta"] == 1
    assert stats["teams"] >= 1
    assert stats["invites"] >= 2
    assert stats["users_unbound"] == 2
    assert stats["reports"] >= 1

    assert fake_redis.exists(k_org(oid)) == 0
    assert fake_redis.exists(k_org_users(oid)) == 0
    assert fake_redis.exists(k_user_org("u_alpha")) == 0
    assert fake_redis.exists(k_user_org("u_beta")) == 0
    assert fake_redis.exists(k_org_invite(code)) == 0
    # HR 角色应该已降级
    assert get_user_role("u_alpha") == "user"

    # 用户的个人数据 (这里不存在,但反向索引清干净就是安全)
    # 注:test 不模拟 user_profile 等 B2C 数据存在性,只验证 org 索引被清


# ============== Safety 软删除 ==============

def test_safety_dismiss_and_filter(fake_redis):
    from services.safety_dismiss import (
        dismiss_safety_event, list_dismissed, is_dismissed, restore_safety_event,
    )

    assert dismiss_safety_event("sess_xyz_001") is True
    assert "sess_xyz_001" in list_dismissed()
    assert is_dismissed("sess_xyz_001") is True
    assert is_dismissed("not_dismissed") is False

    # restore
    assert restore_safety_event("sess_xyz_001") is True
    assert "sess_xyz_001" not in list_dismissed()


def test_safety_dismiss_empty_session_id_returns_false():
    from services.safety_dismiss import dismiss_safety_event
    assert dismiss_safety_event("") is False
