"""
session_logger v2.4 多用户隔离测试

确保:
- 不同 (user_id, session_id) 的 add_turn 不互相覆盖
- 同一用户多个 session 不互相覆盖
- end_session 只关掉指定的那一个
- finalize_if_idle 跨所有 active 会话扫描,只关空转的
"""
import time
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def fresh_logger(monkeypatch):
    """每次测试给一个干净的 SessionLogger。
    mock 掉 save / eval / 告警避免副作用。"""
    from session_logger import SessionLogger
    sl = SessionLogger()
    monkeypatch.setattr(sl, "_save_log", lambda *a, **k: None)
    import session_logger as mod
    # 让 evaluator 直接返回空 dict
    monkeypatch.setattr(mod.dialogue_evaluator, "evaluate_session",
                        lambda *a, **k: MagicMock())
    monkeypatch.setattr(mod.dialogue_evaluator, "to_dict",
                        lambda *a, **k: {"report": {}})
    monkeypatch.setattr(mod, "send_alert", lambda *a, **k: None)
    monkeypatch.setattr(mod, "record_session_evaluation", lambda *a, **k: None)
    return sl


def test_two_users_do_not_clobber(fresh_logger):
    sl = fresh_logger
    # User A 开始 session 1
    sl.start_session("user_A", "sess_A1")
    sl.add_turn(role="user", content="A 的第一句", user_id="user_A", session_id="sess_A1")
    # User B 同时开始 session 2(关键:在 A 没结束时)
    sl.start_session("user_B", "sess_B1")
    sl.add_turn(role="user", content="B 的第一句", user_id="user_B", session_id="sess_B1")
    # User A 继续说第二句
    sl.add_turn(role="user", content="A 的第二句", user_id="user_A", session_id="sess_A1")

    sess_A = sl._active_sessions[("user_A", "sess_A1")]
    sess_B = sl._active_sessions[("user_B", "sess_B1")]

    assert len(sess_A.turns) == 2, f"A 应有 2 轮,实际 {len(sess_A.turns)}"
    assert len(sess_B.turns) == 1, f"B 应有 1 轮,实际 {len(sess_B.turns)}"
    assert sess_A.turns[0].content == "A 的第一句"
    assert sess_A.turns[1].content == "A 的第二句"
    assert sess_B.turns[0].content == "B 的第一句"


def test_same_user_two_sessions_isolated(fresh_logger):
    """同一用户开两个 session(比如手机+桌面同时开),互不串扰。"""
    sl = fresh_logger
    sl.start_session("user_A", "sess_morning")
    sl.start_session("user_A", "sess_evening")
    sl.add_turn(role="user", content="早", user_id="user_A", session_id="sess_morning")
    sl.add_turn(role="user", content="晚", user_id="user_A", session_id="sess_evening")
    assert sl._active_sessions[("user_A", "sess_morning")].turns[0].content == "早"
    assert sl._active_sessions[("user_A", "sess_evening")].turns[0].content == "晚"


def test_end_session_only_closes_target(fresh_logger):
    sl = fresh_logger
    sl.start_session("user_A", "sess_A1")
    sl.start_session("user_B", "sess_B1")
    sl.add_turn(role="user", content="A", user_id="user_A", session_id="sess_A1")
    sl.add_turn(role="user", content="B", user_id="user_B", session_id="sess_B1")

    sl.end_session(outcome="completed_closure", user_id="user_A", session_id="sess_A1")

    assert ("user_A", "sess_A1") not in sl._active_sessions
    assert ("user_B", "sess_B1") in sl._active_sessions
    assert len(sl._active_sessions) == 1


def test_finalize_if_idle_scans_all(fresh_logger):
    sl = fresh_logger
    sl.start_session("user_A", "sess_A1")
    sl.start_session("user_B", "sess_B1")
    sl.start_session("user_C", "sess_C1")
    sl.add_turn(role="user", content="A", user_id="user_A", session_id="sess_A1")
    sl.add_turn(role="user", content="B", user_id="user_B", session_id="sess_B1")
    sl.add_turn(role="user", content="C", user_id="user_C", session_id="sess_C1")

    # 给 A 和 C 把 last_activity 倒退 20 分钟
    from datetime import datetime, timedelta
    stale_ts = (datetime.now() - timedelta(minutes=20)).isoformat()
    sl._active_sessions[("user_A", "sess_A1")]._last_activity = stale_ts
    sl._active_sessions[("user_C", "sess_C1")]._last_activity = stale_ts

    n = sl.finalize_if_idle(max_idle_minutes=15)
    assert n == 2, f"应 finalize 2 个,实际 {n}"
    assert ("user_A", "sess_A1") not in sl._active_sessions
    assert ("user_C", "sess_C1") not in sl._active_sessions
    assert ("user_B", "sess_B1") in sl._active_sessions


def test_most_recent_for_user(fresh_logger):
    sl = fresh_logger
    sl.start_session("user_A", "sess_old")
    sl.add_turn(role="user", content="x", user_id="user_A", session_id="sess_old")
    time.sleep(0.01)
    sl.start_session("user_A", "sess_new")
    sl.add_turn(role="user", content="y", user_id="user_A", session_id="sess_new")
    recent = sl._most_recent_for_user("user_A")
    assert recent is not None
    assert recent.session_id == "sess_new"
    # 不会返回别人的
    assert sl._most_recent_for_user("user_B") is None


def test_start_session_idempotent(fresh_logger):
    """同 key 两次 start_session 不会清掉现有数据。"""
    sl = fresh_logger
    sl.start_session("user_A", "sess_A1")
    sl.add_turn(role="user", content="第一句", user_id="user_A", session_id="sess_A1")
    sl.start_session("user_A", "sess_A1")  # 再开一次
    assert len(sl._active_sessions[("user_A", "sess_A1")].turns) == 1


def test_add_turn_without_ids_is_safe_noop(fresh_logger):
    """缺 user_id/session_id 的 add_turn 不应抛错或污染。"""
    sl = fresh_logger
    sl.start_session("user_A", "sess_A1")
    sl.add_turn(role="user", content="安全", user_id=None, session_id=None)
    assert len(sl._active_sessions[("user_A", "sess_A1")].turns) == 0


def test_empty_session_idle_dropped_not_evaluated(fresh_logger):
    """空会话(只 start 没 add_turn)空转后直接丢,不走评估。"""
    sl = fresh_logger
    sl.start_session("user_A", "sess_empty")
    from datetime import datetime, timedelta
    # 没有 _last_activity 时用 start_time 兜底
    sl._active_sessions[("user_A", "sess_empty")].start_time = \
        (datetime.now() - timedelta(minutes=30)).isoformat()
    n = sl.finalize_if_idle(max_idle_minutes=15)
    assert n == 0  # 不算 finalize
    assert ("user_A", "sess_empty") not in sl._active_sessions  # 但已清掉
