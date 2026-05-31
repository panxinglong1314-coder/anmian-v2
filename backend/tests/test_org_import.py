"""
services/org_import.py 单元测试 + /api/v1/org/admin/employees/import 端点测试。

CSV parsing 单测无需启动 FastAPI;端点测共享 test_auth_org_routes 的 client fixture
模式(stub StaticFiles + fakeredis)。
"""
import json
import asyncio
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _patch_redis(monkeypatch, fake_redis):
    import infra.redis_client as rc
    monkeypatch.setattr(rc, "redis_client", fake_redis)
    import services.org as org_mod
    monkeypatch.setattr(org_mod, "redis_client", fake_redis)
    import services.org_import as imp_mod
    monkeypatch.setattr(imp_mod, "redis_client", fake_redis)
    yield


# ---------- parse_csv 单测 ----------

def test_parse_csv_basic():
    from services.org_import import parse_csv
    csv_text = "email,name,team\nalice@acme.com,Alice,Eng\nbob@acme.com,Bob,Sales\n"
    rows, errors = parse_csv(csv_text)
    assert errors == []
    assert len(rows) == 2
    assert rows[0]["email"] == "alice@acme.com"
    assert rows[0]["name"] == "Alice"
    assert rows[0]["team_name"] == "Eng"


def test_parse_csv_accepts_chinese_headers():
    from services.org_import import parse_csv
    csv_text = "邮箱,姓名,部门\nlily@acme.com,Lily,工程部\n"
    rows, errors = parse_csv(csv_text)
    assert errors == []
    assert rows[0]["email"] == "lily@acme.com"
    assert rows[0]["team_name"] == "工程部"


def test_parse_csv_email_only():
    from services.org_import import parse_csv
    rows, errors = parse_csv("Email\nfoo@bar.com\n")
    assert errors == []
    assert rows[0]["email"] == "foo@bar.com"
    assert "team_name" not in rows[0]


def test_parse_csv_invalid_emails_reported():
    from services.org_import import parse_csv
    csv_text = "email\ngood@acme.com\nbad-no-at\n@oops.com\n"
    rows, errors = parse_csv(csv_text)
    assert len(rows) == 1
    assert rows[0]["email"] == "good@acme.com"
    assert len(errors) == 2


def test_parse_csv_skips_blank_lines():
    from services.org_import import parse_csv
    rows, _ = parse_csv("email\nalice@acme.com\n\nbob@acme.com\n,\n")
    assert {r["email"] for r in rows} == {"alice@acme.com", "bob@acme.com"}


def test_parse_csv_handles_bom():
    from services.org_import import parse_csv
    csv_text = "﻿email\nalice@acme.com\n"
    rows, errors = parse_csv(csv_text)
    assert errors == []
    assert rows[0]["email"] == "alice@acme.com"


def test_parse_csv_no_email_column_errors():
    from services.org_import import parse_csv
    rows, errors = parse_csv("name,team\nAlice,Eng\n")
    assert rows == []
    assert any("email" in e for e in errors)


def test_parse_csv_empty():
    from services.org_import import parse_csv
    rows, errors = parse_csv("")
    assert rows == []
    assert errors == ["CSV 内容为空"]


# ---------- import_employees 全流程 ----------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_import_employees_dry_run_no_resend(monkeypatch):
    """无 RESEND_API_KEY 时,send_emails=True 也只生成邀请码,不发邮件。"""
    from services.org import create_org
    from services.org_import import import_employees
    from infra.settings import settings
    monkeypatch.setattr(settings, "resend_api_key", "", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    oid = create_org("Acme", seat_quota=50)
    csv_text = "email,team\na@acme.com,Eng\nb@acme.com,Sales\nc@acme.com,Eng\n"
    res = _run(import_employees(oid, csv_text))
    assert res["total_rows"] == 3
    assert res["succeeded"] == 3
    assert res["emails_sent"] == 0     # 无 resend → 邮件没发
    # 3 个邀请码都生成
    codes = [it["code"] for it in res["items"] if it.get("code")]
    assert len(codes) == 3
    assert len(set(codes)) == 3        # 每人独享


def test_import_employees_creates_teams(monkeypatch):
    """CSV 含 team_name,自动按需创建 team。"""
    from services.org import create_org, list_teams, get_team
    from services.org_import import import_employees
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    oid = create_org("Acme")
    csv_text = "email,team\na@acme.com,Eng\nb@acme.com,Eng\nc@acme.com,Sales\n"
    res = _run(import_employees(oid, csv_text))
    teams = list_teams(oid)
    assert len(teams) == 2
    names = sorted(get_team(t)["team_name"] for t in teams)
    assert names == ["Eng", "Sales"]
    # 同名 team 复用,不会创建第二个
    eng_items = [it for it in res["items"] if it.get("status") == "invited"]
    eng_team_ids = {it["team_id"] for it in eng_items[:2]}
    assert len(eng_team_ids) == 1


def test_import_employees_skips_already_in_org(monkeypatch):
    from services.org import create_org, create_invite_code, bind_user_to_org
    from services.org_import import import_employees, _email_user_id
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    oid = create_org("Acme")
    code = create_invite_code(oid, max_uses=10)
    # 预先把 a@acme.com 绑到该 org
    bind_user_to_org(_email_user_id("a@acme.com"), code)
    csv_text = "email\na@acme.com\nb@acme.com\n"
    res = _run(import_employees(oid, csv_text))
    assert res["skipped_already_in_org"] == 1
    assert res["succeeded"] == 1
    a_item = next(it for it in res["items"] if it["email"] == "a@acme.com")
    assert a_item["status"] == "already_in_org"


def test_import_employees_skips_in_other_org(monkeypatch):
    from services.org import create_org, create_invite_code, bind_user_to_org
    from services.org_import import import_employees, _email_user_id
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    oid1 = create_org("Acme")
    oid2 = create_org("Globex")
    code1 = create_invite_code(oid1)
    # 绑到 oid1
    bind_user_to_org(_email_user_id("x@example.com"), code1)
    # 再尝试导入到 oid2
    res = _run(import_employees(oid2, "email\nx@example.com\n"))
    assert res["skipped_in_other_org"] == 1
    x_item = res["items"][0]
    assert x_item["status"] == "in_other_org"


def test_import_employees_reports_parse_errors(monkeypatch):
    from services.org import create_org
    from services.org_import import import_employees
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    oid = create_org("Acme")
    csv_text = "email\nvalid@acme.com\nbroken-email\n"
    res = _run(import_employees(oid, csv_text))
    assert res["total_rows"] == 1
    assert res["succeeded"] == 1
    assert len(res["parse_errors"]) == 1


# ---------- 端点测(JWT 守护) ----------

@pytest.fixture
def client(monkeypatch, fake_redis, tmp_path):
    """使用与 test_auth_org_routes 同款 fixture。"""
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


def test_import_endpoint_rejects_non_hr(client, fake_redis):
    """普通员工 JWT 调 import → 403。"""
    from services.auth import create_jwt_for_user
    tok = create_jwt_for_user("em_employee", openid="emp@acme.com", org_id="org_xxx")
    r = client.post(
        "/api/v1/org/admin/employees/import",
        json={"csv_text": "email\na@acme.com\n", "send_emails": False},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403
    assert "HR" in r.json()["detail"]


def test_import_endpoint_rejects_hr_without_org(client):
    """role=hr_admin 但没 org_id → 403。"""
    from services.auth import create_jwt_for_user
    tok = create_jwt_for_user("em_hr", openid="hr@acme.com", role="hr_admin")
    r = client.post(
        "/api/v1/org/admin/employees/import",
        json={"csv_text": "email\nx@acme.com\n", "send_emails": False},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403


def test_import_endpoint_happy_path(client, fake_redis, monkeypatch):
    from services.org import create_org
    from services.auth import create_jwt_for_user
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    oid = create_org("Acme Corp")
    tok = create_jwt_for_user(
        "em_hr", openid="hr@acme.com",
        org_id=oid, role="hr_admin",
    )
    r = client.post(
        "/api/v1/org/admin/employees/import",
        json={"csv_text": "email,team\na@acme.com,Eng\nb@acme.com,Sales\n",
              "send_emails": False, "expire_days": 14},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["succeeded"] == 2
    assert j["total_rows"] == 2
