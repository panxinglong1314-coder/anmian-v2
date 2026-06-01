"""
services/org_report.py 测试。

注意: weasyprint 不一定在 CI 装,test 用 monkeypatch 把 _html_to_pdf
换成假实现,只验证流程 + insufficient_data 路径。
"""
import json
import pytest


@pytest.fixture(autouse=True)
def _patch_redis(monkeypatch, fake_redis):
    import infra.redis_client as rc
    monkeypatch.setattr(rc, "redis_client", fake_redis)
    for mod_name in ("services.org", "services.org_insights", "services.org_report"):
        try:
            mod = __import__(mod_name, fromlist=["redis_client"])
            monkeypatch.setattr(mod, "redis_client", fake_redis)
        except (ImportError, AttributeError):
            pass
    yield


@pytest.fixture
def _stub_pdf(monkeypatch):
    """避免实际跑 weasyprint(避免 native lib 依赖)。
    同时 patch TEMPLATES_DIR — 在 pytest 下 Path(__file__).parent.parent.parent
    路径解析会怪异(同 main.py 静态挂载问题),需手动指到 repo root。"""
    import services.org_report as rpt
    from pathlib import Path as _Path
    monkeypatch.setattr(rpt, "_html_to_pdf",
                        lambda html: b"%PDF-FAKE\n" + html.encode("utf-8", errors="ignore"))
    # 解析正确路径: org_report.py 的 parent.parent.parent
    real_root = _Path(rpt.__file__).resolve().parent.parent.parent
    monkeypatch.setattr(rpt, "TEMPLATES_DIR", real_root / "static" / "templates")
    yield


def _seed_org(fake_redis, n_users, org_name="Acme"):
    from services.org import create_org, create_invite_code, bind_user_to_org
    oid = create_org(org_name, seat_quota=max(n_users * 2, 10))
    code = create_invite_code(oid, max_uses=n_users * 2)
    uids = []
    for i in range(n_users):
        uid = f"em_report_{org_name.lower()}_{i:03d}"
        bind_user_to_org(uid, code)
        uids.append(uid)
    return oid, uids


def test_ym_validation():
    from services.org_report import generate_monthly_report
    with pytest.raises(ValueError):
        generate_monthly_report("org_x", "2026/05")
    with pytest.raises(ValueError):
        generate_monthly_report("org_x", "26-05")
    with pytest.raises(ValueError):
        generate_monthly_report("org_x", "2026-13")


def test_org_not_found():
    from services.org_report import generate_monthly_report
    with pytest.raises(ValueError):
        generate_monthly_report("org_nonexistent", "2026-05", use_cache=False)


def test_insufficient_data_still_renders(fake_redis, _stub_pdf):
    """3 人小团队 < k=5 → 应渲染但 'insufficient' 提示。"""
    from services.org_report import generate_monthly_report
    oid, _ = _seed_org(fake_redis, 3)
    pdf = generate_monthly_report(oid, "2026-05", use_cache=False)
    assert pdf.startswith(b"%PDF-FAKE")
    # ZH "数据不足" 中文 marker(模板含)
    assert "数据不足".encode("utf-8") in pdf


def test_full_report_renders_with_5_users(fake_redis, _stub_pdf):
    from services.org_report import generate_monthly_report
    oid, uids = _seed_org(fake_redis, 5)
    # 给每个用户一些睡眠 + worry 数据
    for u in uids:
        fake_redis.hset(f"sleep_diary:{u}:2026-05-15",
                        mapping={"se": "0.82", "tst": "7", "sol": "12", "waso": "10", "quality": "7"})
        fake_redis.set(f"user:memory:{u}",
                       json.dumps({"session_count": 4, "triggers": {"work": 3, "health": 1}}))
    pdf = generate_monthly_report(oid, "2026-05", use_cache=False)
    assert pdf.startswith(b"%PDF-FAKE")


def test_pdf_cache_hit_returns_same_bytes(fake_redis, _stub_pdf):
    from services.org_report import generate_monthly_report
    oid, _ = _seed_org(fake_redis, 5)
    pdf1 = generate_monthly_report(oid, "2026-05", use_cache=True)
    pdf2 = generate_monthly_report(oid, "2026-05", use_cache=True)
    assert pdf1 == pdf2
    # nocache 应重生成(同样会得到一样的 bytes,但确认不抛错)
    pdf3 = generate_monthly_report(oid, "2026-05", use_cache=False)
    assert pdf3.startswith(b"%PDF-FAKE")


def test_locale_en_branch(fake_redis, _stub_pdf):
    """locale=en 走 EN labels 模板,不抛错。"""
    from services.org_report import generate_monthly_report
    oid, _ = _seed_org(fake_redis, 5)
    pdf = generate_monthly_report(oid, "2026-05", locale="en", use_cache=False)
    assert pdf.startswith(b"%PDF-FAKE")


def test_strip_user_identity_in_template_context():
    """sanity: 模板渲染不应漏 user_id 字段。"""
    from services.org_report import _labels
    en_labels = _labels("en")
    zh_labels = _labels("zh")
    # 标签里不应含 user_id / 邮箱
    for v in {**en_labels, **zh_labels}.values():
        assert "user_id" not in str(v).lower()
        assert "@" not in str(v) or "988" in str(v)  # 988 hotline 字符串允许
