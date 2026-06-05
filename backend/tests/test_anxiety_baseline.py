"""
P0-1 anxiety_baseline 服务单测。
关键不变量:
1. record_anxiety 在 Redis 不可用时静默,不抛错
2. 不到 MIN_SAMPLES_FOR_BASELINE 不算 baseline (冷启动保护)
3. 满足样本后 compute_deviation 返 z_score + deviation_class
4. 偏离超 2σ 标记 alert=True
5. 老数据 (>14 天) 自动从 zset 修剪
"""
import time
import pytest


@pytest.fixture(autouse=True)
def _patch_redis(monkeypatch, fake_redis):
    """把 anxiety_baseline 的 redis_client 替换为 fake."""
    import infra.redis_client as rc
    monkeypatch.setattr(rc, "redis_client", fake_redis)
    yield


def test_record_without_redis_silently_noops(monkeypatch):
    """Redis 不可用时不抛错。"""
    import infra.redis_client as rc
    monkeypatch.setattr(rc, "redis_client", None)
    from services import anxiety_baseline as ab
    ab.record_anxiety("u_test", "moderate")  # 不应抛错
    assert ab.get_baseline("u_test") is None


def test_cold_start_returns_no_baseline(fake_redis):
    from services import anxiety_baseline as ab
    # 写几次 (< MIN_SAMPLES_FOR_BASELINE = 10)
    for _ in range(5):
        ab.record_anxiety("u_cold", "mild")
    # baseline 不应该可用
    assert ab.get_baseline("u_cold") is None
    # compute_deviation 也返 None
    assert ab.compute_deviation("u_cold", "moderate") is None


def test_baseline_populated_after_min_samples(fake_redis):
    from services import anxiety_baseline as ab
    # 15 轮稳定的 mild 焦虑
    for _ in range(15):
        ab.record_anxiety("u_pop", "mild")
    ab.recompute_baseline("u_pop")  # 强制重算
    baseline = ab.get_baseline("u_pop")
    assert baseline is not None
    assert baseline["n"] >= 10
    # mean 应该约等 1 (mild=1)
    assert 0.5 <= baseline["mean"] <= 1.5


def test_deviation_alerts_when_above_2sigma(fake_redis):
    from services import anxiety_baseline as ab
    # 历史 15 轮全 normal (0)
    for _ in range(15):
        ab.record_anxiety("u_dev", "normal")
    ab.recompute_baseline("u_dev")
    # 当前来一个 severe (3) — std 太小,会被 0.5 兜底, z = 3/0.5 = 6 → 远超 2
    dev = ab.compute_deviation("u_dev", "severe")
    assert dev is not None
    assert dev["alert"] is True
    assert dev["deviation_class"] == "higher"
    assert dev["z_score"] >= 2


def test_deviation_within_baseline_no_alert(fake_redis):
    from services import anxiety_baseline as ab
    # 历史:moderate 为主, 偶尔 mild / severe
    pattern = ["moderate"] * 10 + ["mild"] * 3 + ["severe"] * 2
    for p in pattern:
        ab.record_anxiety("u_within", p)
    ab.recompute_baseline("u_within")
    # 当前 moderate (跟均值近) → 不应该 alert
    dev = ab.compute_deviation("u_within", "moderate")
    assert dev is not None
    assert dev["alert"] is False


def test_lower_deviation_class(fake_redis):
    from services import anxiety_baseline as ab
    # 历史: 全是 severe (3)
    for _ in range(15):
        ab.record_anxiety("u_low", "severe")
    ab.recompute_baseline("u_low")
    # 当前 normal — 远低于
    dev = ab.compute_deviation("u_low", "normal")
    assert dev is not None
    assert dev["deviation_class"] == "lower"
    assert dev["z_score"] <= -2


def test_zset_keeps_recent_window(fake_redis):
    """老数据 (超 14 天) 应被修剪。"""
    from services import anxiety_baseline as ab
    user_id = "u_window"
    # 手动塞 1 条 30 天前的老数据
    old_ms = int((time.time() - 30 * 86400) * 1000)
    fake_redis.zadd(ab._scores_key(user_id), {f"{old_ms}:3": old_ms})
    # 再 record 一条新数据 (会触发修剪)
    ab.record_anxiety(user_id, "mild")
    # 老数据应已被 zremrangebyscore 干掉
    scores = ab._load_scores(fake_redis, user_id)
    assert all(s <= 3 for s in scores)
    # 只剩 1 条新的
    assert len(scores) == 1


def test_level_to_int_normalizes_inputs():
    from services.anxiety_baseline import level_to_int
    assert level_to_int("severe") == 3
    assert level_to_int("MILD") == 1
    assert level_to_int(2) == 2
    assert level_to_int(99) == 3   # 上限
    assert level_to_int(-1) == 0   # 下限
    assert level_to_int(None) == 0
    # 模拟 AnxietyLevel enum (.value)
    class _Fake:
        value = "moderate"
    assert level_to_int(_Fake()) == 2
