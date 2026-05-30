"""
关系深化测试(v2.4):
- ZH + EN 档案块都注入了上次会话摘要 / 关系深度 / 主要担忧
- end_session 在任何 ≥3 用户轮的 finalize 都累加 session_count(不只是 closure)
"""
import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta


def test_zh_profile_block_for_returning_user():
    from user_profile_block import build_user_profile_block as _build_user_profile_block
    memory = {
        "session_count": 3,
        "last_session_summary": "用户因明天汇报焦虑,4-7-8 呼吸后稍放松",
        "last_session_time": (datetime.now() - timedelta(days=1)).isoformat(),
        "triggers": {"work": 4, "relationship": 1},
        "insomnia_subtype": "sleep_onset",
    }
    block = _build_user_profile_block(memory, locale="zh")
    assert "用户档案" in block
    assert "第 4 次见面" in block
    assert "工作压力" in block
    assert "汇报焦虑" in block
    assert "昨晚" in block  # 相对时间
    assert "老朋友重逢" in block  # 使用引导
    assert "严禁" in block  # 安全约束


def test_en_profile_block_for_returning_user():
    from user_profile_block import build_user_profile_block as _build_user_profile_block
    memory = {
        "session_count": 6,
        "last_session_summary": "user worried about layoff rumors at work; brief breath exercise helped",
        "last_session_time": (datetime.now() - timedelta(days=3)).isoformat(),
        "triggers": {"work": 5, "finance": 2},
        "insomnia_subtype": "sleep_onset",
    }
    block = _build_user_profile_block(memory, locale="en")
    assert "User profile" in block
    assert "familiar regular" in block
    assert "6 bedtime visits" in block
    assert "work stress" in block
    assert "money pressure" in block
    assert "layoff rumors" in block
    assert "3 days ago" in block
    assert "old friend" in block
    assert "NEVER quote" in block


def test_empty_memory_returns_empty():
    from user_profile_block import build_user_profile_block as _build_user_profile_block
    assert _build_user_profile_block({}, "zh") == ""
    assert _build_user_profile_block({}, "en") == ""


def test_brand_new_user_returns_empty():
    """新用户 session_count=0, 没历史 — 不应该假装是老朋友。"""
    from user_profile_block import build_user_profile_block as _build_user_profile_block
    memory = {"session_count": 0, "triggers": {}, "last_session_summary": ""}
    assert _build_user_profile_block(memory, "zh") == ""
    assert _build_user_profile_block(memory, "en") == ""


def test_first_returning_visit_zh():
    from user_profile_block import build_user_profile_block as _build_user_profile_block
    memory = {"session_count": 1, "triggers": {"work": 1}, "last_session_summary": "x"}
    block = _build_user_profile_block(memory, "zh")
    assert "第二次见面" in block


def test_first_returning_visit_en():
    from user_profile_block import build_user_profile_block as _build_user_profile_block
    memory = {"session_count": 1, "triggers": {"work": 1}, "last_session_summary": "x"}
    block = _build_user_profile_block(memory, "en")
    assert "second time" in block


def test_session_count_bumps_on_idle_timeout(monkeypatch):
    """关键测试:end_session(idle_timeout) 应该累加 session_count,
    让流失用户下次也被识别为'老朋友'。"""
    from session_logger import SessionLogger
    sl = SessionLogger()
    monkeypatch.setattr(sl, "_save_log", lambda *a, **k: None)
    import session_logger as mod
    monkeypatch.setattr(mod.dialogue_evaluator, "evaluate_session",
                        lambda *a, **k: MagicMock())
    monkeypatch.setattr(mod.dialogue_evaluator, "to_dict",
                        lambda *a, **k: {"report": {}})
    monkeypatch.setattr(mod, "send_alert", lambda *a, **k: None)
    monkeypatch.setattr(mod, "record_session_evaluation", lambda *a, **k: None)

    # Mock redis_client used by the bump branch
    fake_store = {}
    fake_rc = MagicMock()
    fake_rc.get = lambda k: fake_store.get(k)
    def _fake_setex(k, ttl, v):
        fake_store[k] = v
    fake_rc.setex = _fake_setex
    # 既要 patch import path,又要在测试中触发 import 重新求值
    import sys
    # 注入伪 infra.redis_client 模块,让 end_session 内的 `from infra.redis_client import redis_client as _rc`
    # 拿到这个 fake
    fake_mod = MagicMock()
    fake_mod.redis_client = fake_rc
    monkeypatch.setitem(sys.modules, "infra.redis_client", fake_mod)

    sl.start_session("user_X", "sess_X1")
    for i in range(3):
        sl.add_turn(role="user", content=f"msg {i}", user_id="user_X", session_id="sess_X1")
        sl.add_turn(role="assistant", content=f"resp {i}", user_id="user_X", session_id="sess_X1")

    sl.end_session(outcome="idle_timeout", user_id="user_X", session_id="sess_X1")

    raw = fake_store.get("user:memory:user_X")
    assert raw is not None, "user:memory key 应被写入"
    mem = json.loads(raw)
    assert mem.get("session_count") == 1, f"session_count 应 1, 实际 {mem.get('session_count')}"
    assert mem.get("last_session_time"), "last_session_time 应被设置"


def test_session_count_not_bumped_with_too_few_turns(monkeypatch):
    """空会话或只有 1-2 轮的不应该被算作"老朋友"。"""
    from session_logger import SessionLogger
    sl = SessionLogger()
    monkeypatch.setattr(sl, "_save_log", lambda *a, **k: None)
    import session_logger as mod
    monkeypatch.setattr(mod.dialogue_evaluator, "evaluate_session",
                        lambda *a, **k: MagicMock())
    monkeypatch.setattr(mod.dialogue_evaluator, "to_dict",
                        lambda *a, **k: {"report": {}})
    monkeypatch.setattr(mod, "send_alert", lambda *a, **k: None)
    monkeypatch.setattr(mod, "record_session_evaluation", lambda *a, **k: None)

    fake_store = {}
    fake_rc = MagicMock()
    fake_rc.get = lambda k: fake_store.get(k)
    fake_rc.setex = lambda k, ttl, v: fake_store.__setitem__(k, v)
    import sys
    fake_mod = MagicMock(); fake_mod.redis_client = fake_rc
    monkeypatch.setitem(sys.modules, "infra.redis_client", fake_mod)

    sl.start_session("user_Y", "sess_Y1")
    sl.add_turn(role="user", content="一句话", user_id="user_Y", session_id="sess_Y1")
    sl.add_turn(role="assistant", content="嗯", user_id="user_Y", session_id="sess_Y1")
    sl.end_session(outcome="interrupted", user_id="user_Y", session_id="sess_Y1")

    assert fake_store.get("user:memory:user_Y") is None, "1 轮会话不应触发 session_count bump"
