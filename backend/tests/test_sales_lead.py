"""
services/sales_lead.py + /api/v1/sales/lead 端点测试。

关键不变量:
- submit_lead 校验 email + 截断超长字段
- 状态迁移(pending → contacted → closed_won)队列移动正确
- list_leads 倒序(最新在前)
- IP 限速 1 小时 5 条
"""
import json
import time
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _patch_redis(monkeypatch, fake_redis):
    import infra.redis_client as rc
    monkeypatch.setattr(rc, "redis_client", fake_redis)
    import services.sales_lead as sl_mod
    monkeypatch.setattr(sl_mod, "redis_client", fake_redis)
    yield


# ============================ submit_lead 单测 ============================

def test_submit_lead_happy():
    from services.sales_lead import submit_lead, get_lead
    rec = submit_lead(
        company_name="Acme Corp",
        contact_name="HR Alice",
        contact_email="hr@acme.com",
        team_size="50-200",
        message="想了解定价",
    )
    assert rec["status"] == "pending"
    assert rec["company_name"] == "Acme Corp"
    assert rec["lead_id"]
    # round-trip 从 redis 读
    fetched = get_lead(rec["lead_id"])
    assert fetched["company_name"] == "Acme Corp"
    assert fetched["contact_email"] == "hr@acme.com"


def test_submit_lead_rejects_invalid_email():
    from services.sales_lead import submit_lead
    with pytest.raises(ValueError):
        submit_lead(company_name="X", contact_email="bad-email")


def test_submit_lead_rejects_empty_company():
    from services.sales_lead import submit_lead
    with pytest.raises(ValueError):
        submit_lead(company_name="", contact_email="hr@acme.com")


def test_submit_lead_truncates_long_fields():
    from services.sales_lead import submit_lead, get_lead
    rec = submit_lead(
        company_name="A" * 500,
        contact_email="hr@acme.com",
        message="X" * 5000,
    )
    fetched = get_lead(rec["lead_id"])
    assert len(fetched["company_name"]) <= 100
    assert len(fetched["message"]) <= 2000


def test_submit_lead_normalizes_email_case():
    from services.sales_lead import submit_lead
    rec = submit_lead(company_name="X", contact_email="HR@ACME.COM")
    assert rec["contact_email"] == "hr@acme.com"


# ============================ list / state machine ============================

def test_list_pending_newest_first():
    from services.sales_lead import submit_lead, list_leads
    submit_lead(company_name="A", contact_email="a@a.com")
    time.sleep(0.01)
    submit_lead(company_name="B", contact_email="b@b.com")
    time.sleep(0.01)
    submit_lead(company_name="C", contact_email="c@c.com")
    leads = list_leads("pending")
    assert [l["company_name"] for l in leads] == ["C", "B", "A"]


def test_update_status_moves_to_archived():
    from services.sales_lead import submit_lead, update_lead, list_leads
    rec = submit_lead(company_name="A", contact_email="a@a.com")
    # 关闭 → 移到 archived
    updated = update_lead(rec["lead_id"], status="closed_won", notes="签了")
    assert updated["status"] == "closed_won"
    assert updated["notes"] == "签了"
    assert list_leads("pending") == []
    archived = list_leads("archived")
    assert len(archived) == 1


def test_reopen_moves_back_to_pending():
    from services.sales_lead import submit_lead, update_lead, list_leads
    rec = submit_lead(company_name="A", contact_email="a@a.com")
    update_lead(rec["lead_id"], status="closed_lost")
    assert list_leads("pending") == []
    update_lead(rec["lead_id"], status="pending")
    assert len(list_leads("pending")) == 1
    assert list_leads("archived") == []


def test_update_unknown_lead_returns_none():
    from services.sales_lead import update_lead
    assert update_lead("nonexistent", status="contacted") is None


def test_update_rejects_invalid_status():
    from services.sales_lead import submit_lead, update_lead
    rec = submit_lead(company_name="A", contact_email="a@a.com")
    with pytest.raises(ValueError):
        update_lead(rec["lead_id"], status="garbage")


def test_get_stats_breaks_down_by_status():
    from services.sales_lead import submit_lead, update_lead, get_stats
    rec_a = submit_lead(company_name="A", contact_email="a@a.com")
    rec_b = submit_lead(company_name="B", contact_email="b@b.com")
    rec_c = submit_lead(company_name="C", contact_email="c@c.com")
    update_lead(rec_b["lead_id"], status="contacted")
    update_lead(rec_c["lead_id"], status="closed_won")
    s = get_stats()
    assert s["pending_count"] == 2
    assert s["archived_count"] == 1
    assert s["by_status"]["pending"] == 1
    assert s["by_status"]["contacted"] == 1
    assert s["by_status"]["closed_won"] == 1


# ============================ 端点测(端到端) ============================

@pytest.fixture
def client(monkeypatch, fake_redis, tmp_path):
    stub_root = tmp_path / "anmian_stub"
    (stub_root / "static" / "admin").mkdir(parents=True)
    (stub_root / "static" / "admin" / "index.html").write_text("<html></html>")
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


def test_public_submit_endpoint_no_auth(client):
    """匿名访客也能提交线索(白名单端点)。"""
    r = client.post("/api/v1/sales/lead", json={
        "company_name": "Acme Corp",
        "contact_name": "HR Alice",
        "contact_email": "hr@acme.com",
        "team_size": "200",
        "message": "想了解定价",
    })
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "ok"
    assert j["lead_id"]


def test_submit_endpoint_rejects_bad_email(client):
    r = client.post("/api/v1/sales/lead", json={
        "company_name": "Acme",
        "contact_email": "bad-email",
    })
    assert r.status_code == 400


def test_submit_endpoint_rate_limited(client, fake_redis):
    """同 IP 1 小时 5 条 → 第 6 次返 429。"""
    for i in range(5):
        r = client.post("/api/v1/sales/lead", json={
            "company_name": f"Co {i}",
            "contact_email": f"hr{i}@co.com",
        })
        assert r.status_code == 200
    r6 = client.post("/api/v1/sales/lead", json={
        "company_name": "Late",
        "contact_email": "late@co.com",
    })
    assert r6.status_code == 429


def test_admin_list_endpoint(client):
    """admin 端点能拉队列(已被 AdminAuthMiddleware 保护;这里仅验路由 reachable)。"""
    # 先提交一条
    client.post("/api/v1/sales/lead", json={
        "company_name": "Acme",
        "contact_email": "hr@acme.com",
    })
    # 不带 admin token → 401
    r = client.get("/api/v1/admin/sales/leads")
    assert r.status_code in (401, 503)  # 503 = ADMIN_TOKEN 未配置时


def test_admin_update_endpoint_requires_token(client):
    r = client.patch("/api/v1/admin/sales/leads/abc123", json={"status": "contacted"})
    assert r.status_code in (401, 503)
