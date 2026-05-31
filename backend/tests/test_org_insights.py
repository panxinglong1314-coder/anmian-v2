"""
services/org_insights.py + /api/v1/org/insights/* 测试

最关键的不变量:
1. k-anonymity 守护: 队列 < k_min 时 status='insufficient_data',不返真实数字
2. 任何端点都不返 user_id / email / openid / session_id / 对话内容
3. 跨 org 不漏数据: A 组的 user 数据不出现在 B 组聚合里
4. crisis 聚合仅给数字,绝不返身份
"""
import json
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _patch_redis(monkeypatch, fake_redis):
    import infra.redis_client as rc
    monkeypatch.setattr(rc, "redis_client", fake_redis)
    for mod_name in ("services.org", "services.org_insights",
                     "services.crisis_alert", "services.org_import"):
        try:
            mod = __import__(mod_name, fromlist=["redis_client"])
            monkeypatch.setattr(mod, "redis_client", fake_redis)
        except (ImportError, AttributeError):
            pass
    yield


def _seed_org_with_users(fake_redis, n_users, org_name="Acme"):
    """工具:创建 org + n 个 user 绑入,返 (org_id, user_ids)。"""
    from services.org import create_org, create_invite_code, bind_user_to_org
    oid = create_org(org_name, seat_quota=max(n_users * 2, 10))
    code = create_invite_code(oid, max_uses=n_users * 2)
    uids = []
    for i in range(n_users):
        uid = f"em_test_{org_name.lower()}_{i:03d}"
        bind_user_to_org(uid, code)
        uids.append(uid)
    return oid, uids


def _set_user_memory(fake_redis, user_id, mem: dict):
    fake_redis.set(f"user:memory:{user_id}", json.dumps(mem))


def _set_user_profile(fake_redis, user_id, prof: dict):
    fake_redis.set(f"user_profile:{user_id}", json.dumps(prof))


def _set_sleep_diary(fake_redis, user_id, date_str, **kv):
    fake_redis.hset(f"sleep_diary:{user_id}:{date_str}", mapping={
        k: str(v) for k, v in kv.items()
    })


# ============================ k-anonymity ============================

def test_insufficient_data_when_below_k_min(fake_redis):
    """4 人团队 (< k=5),所有端点都拒绝返 metric。"""
    from services.org_insights import insights_sleep
    oid, uids = _seed_org_with_users(fake_redis, 4)
    for u in uids:
        _set_sleep_diary(fake_redis, u, "2026-05-28", se=0.85, tst=7)
    res = insights_sleep(oid, period="30d", k_min=5)
    assert res["status"] == "insufficient_data"
    assert res["n"] == 4
    assert res["k_min"] == 5
    # 关键: 不应漏 metric 字段
    assert "avg_se_pct" not in res
    assert "avg_tst_hours" not in res


def test_metric_returned_when_at_or_above_k_min(fake_redis):
    from services.org_insights import insights_sleep
    oid, uids = _seed_org_with_users(fake_redis, 5)
    for u in uids:
        _set_sleep_diary(fake_redis, u, "2026-05-28", se=0.85, tst=7)
    res = insights_sleep(oid, period="30d", k_min=5)
    assert res["status"] == "ok"
    assert res["n"] == 5
    assert res["avg_se_pct"] is not None


def test_k_anonymity_aggregate_strips_user_identity(fake_redis):
    """即使 metric_fn 不小心返回了 user_id,聚合层也得剥掉。"""
    from services.org_insights import k_anonymous_aggregate
    uids = ["u1", "u2", "u3", "u4", "u5"]
    def bad_metric(_):
        return {"value": 42, "user_id": "u1", "details": {"openid": "x", "session_id": "s1"}}
    res = k_anonymous_aggregate(uids, bad_metric, k_min=5)
    assert res["status"] == "ok"
    assert "user_id" not in res
    assert "openid" not in res.get("details", {})
    assert "session_id" not in res.get("details", {})
    assert res["value"] == 42


# ============================ org scope 隔离 ============================

def test_cross_org_isolation_sleep(fake_redis):
    """A 公司用户的睡眠数据,不应出现在 B 公司聚合里。"""
    from services.org_insights import insights_sleep
    oid_a, uids_a = _seed_org_with_users(fake_redis, 5, "AcmeA")
    oid_b, uids_b = _seed_org_with_users(fake_redis, 5, "GlobeB")
    # A 用户睡眠很差,B 用户很好
    for u in uids_a:
        _set_sleep_diary(fake_redis, u, "2026-05-28", se=0.50, tst=4.5)
    for u in uids_b:
        _set_sleep_diary(fake_redis, u, "2026-05-28", se=0.92, tst=8)
    res_a = insights_sleep(oid_a, period="30d", k_min=5)
    res_b = insights_sleep(oid_b, period="30d", k_min=5)
    # A 的平均 SE 应低,B 的高,不混
    assert res_a["avg_se_pct"] < 60
    assert res_b["avg_se_pct"] > 85


# ============================ worry domain 聚合 ============================

def test_worry_domain_aggregation(fake_redis):
    from services.org_insights import insights_worry
    oid, uids = _seed_org_with_users(fake_redis, 5)
    # 5 个用户都有不同的 worry 域记录
    triggers = [
        {"work": 4, "relationship": 1},
        {"work": 3, "health": 1},
        {"work": 2, "family": 2},
        {"finance": 3, "work": 1},
        {"health": 2},
    ]
    for u, t in zip(uids, triggers):
        _set_user_memory(fake_redis, u, {"triggers": t})
    res = insights_worry(oid, period="30d", k_min=5)
    assert res["status"] == "ok"
    assert res["top_domain"] == "work"           # 4+3+2+1 = 10 次,最高
    assert "distribution_pct" in res
    # 各域占比和应 ≈ 100
    assert abs(sum(res["distribution_pct"].values()) - 100) < 0.5


# ============================ crisis 聚合(关键隐私) ============================

def test_crisis_returns_only_counts_no_identity(fake_redis):
    """crisis 端点必须返计数,不返 user_id / message / event_id 任何身份字段。"""
    from services.org_insights import insights_crisis
    from services.crisis_alert import emit_crisis_alert
    import time
    oid, uids = _seed_org_with_users(fake_redis, 5)
    # 关键: emit_crisis_alert 内部跳过测试用户 (em_test*),
    # 改用真名 user_id 才能写入
    real_uids = [f"em_real_{i:04d}" for i in range(5)]
    # 把这些 user 绑到 org 里
    from services.org import create_invite_code, bind_user_to_org
    code = create_invite_code(oid, max_uses=10)
    for u in real_uids:
        bind_user_to_org(u, code)
    # 发 3 起危机事件
    for i, lvl in enumerate(["high", "medium", "low"]):
        emit_crisis_alert(real_uids[i], f"sess_{i}", lvl,
                          types=["self_harm"], message="敏感原文")
    res = insights_crisis(oid, period="30d", k_min=5)
    assert res["status"] == "ok"
    assert res["high"] == 1
    assert res["medium"] == 1
    assert res["low"] == 1
    assert res["total"] == 3
    # 隐私守护:返回字典里不应有任何身份/原文字段
    import json as _json
    s = _json.dumps(res)
    for forbidden in ("em_real_", "user_id", "敏感原文", "event_id", "session_id"):
        assert forbidden not in s, f"crisis response leaked: {forbidden}"


def test_crisis_does_not_count_other_orgs(fake_redis):
    from services.org_insights import insights_crisis
    from services.crisis_alert import emit_crisis_alert
    from services.org import create_invite_code, bind_user_to_org
    oid_a, _ = _seed_org_with_users(fake_redis, 5, "AcmeA")
    oid_b, _ = _seed_org_with_users(fake_redis, 5, "GlobeB")
    # 给 A 加 5 个真用户 + 各发 1 起事件
    code_a = create_invite_code(oid_a, max_uses=10)
    for i in range(5):
        u = f"em_realA_{i}"
        bind_user_to_org(u, code_a)
        emit_crisis_alert(u, f"s_{i}", "high", types=[], message="x")
    res_b = insights_crisis(oid_b, period="30d", k_min=5)
    assert res_b["status"] == "ok"
    assert res_b["total"] == 0


# ============================ engagement / outcome ============================

def test_engagement_activation_rate(fake_redis):
    from services.org_insights import insights_engagement
    oid, uids = _seed_org_with_users(fake_redis, 5)
    # 3 人最近活跃,2 人 60 天前最后用
    recent = datetime.now().isoformat(timespec="seconds")
    old = (datetime.now() - timedelta(days=60)).isoformat(timespec="seconds")
    for i, u in enumerate(uids):
        _set_user_memory(fake_redis, u, {
            "session_count": 5,
            "last_session_time": recent if i < 3 else old,
        })
    res = insights_engagement(oid, period="30d", k_min=5)
    assert res["status"] == "ok"
    assert res["active_users"] == 3
    assert res["total_users"] == 5
    assert res["activation_rate"] == 60.0


# ============================ 端点 + role 守护 ============================

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


def test_endpoint_rejects_non_hr(client, fake_redis):
    from services.auth import create_jwt_for_user
    tok = create_jwt_for_user("em_normal_user", openid="x@y.com")
    r = client.get(
        "/api/v1/org/insights/sleep",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403


def test_endpoint_happy_path_k_anonymous(client, fake_redis):
    """HR 调端点,数据足够 → 返 ok。"""
    from services.auth import create_jwt_for_user
    oid, uids = _seed_org_with_users(fake_redis, 5)
    for u in uids:
        _set_sleep_diary(fake_redis, u, "2026-05-28", se=0.82, tst=7)
    tok = create_jwt_for_user("em_hr", openid="hr@acme.com",
                              org_id=oid, role="hr_admin")
    r = client.get(
        "/api/v1/org/insights/sleep?period=30d",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "ok"
    assert j["avg_se_pct"] is not None


def test_endpoint_client_cannot_specify_other_org(client, fake_redis):
    """HR 调 sleep 时,系统强制用 user.org_id;不能传 org_id query 偷别家数据。"""
    from services.auth import create_jwt_for_user
    oid_a, uids_a = _seed_org_with_users(fake_redis, 5, "AcmeA")
    oid_b, uids_b = _seed_org_with_users(fake_redis, 5, "GlobeB")
    for u in uids_a: _set_sleep_diary(fake_redis, u, "2026-05-28", se=0.50, tst=4.5)
    for u in uids_b: _set_sleep_diary(fake_redis, u, "2026-05-28", se=0.92, tst=8)
    # HR 属于 A,即使 url 加 ?org_id=B 也得拿 A 的数据
    tok = client_a_tok = create_jwt_for_user("em_hr_a", openid="hr@acmeA.com",
                                              org_id=oid_a, role="hr_admin")
    r = client.get(
        f"/api/v1/org/insights/sleep?period=30d&org_id={oid_b}",
        headers={"Authorization": f"Bearer {tok}"},
    )
    # FastAPI 端点签名只接 team_id,org_id query 被忽略 → 仍返 A 的数据
    assert r.status_code == 200
    assert r.json()["avg_se_pct"] < 60   # A 的低 SE
