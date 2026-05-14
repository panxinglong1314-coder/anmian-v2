"""
crisis_alert 服务单元测试
覆盖：
- emit → pending 队列写入正确
- unread_count 与 pending 长度一致
- ack 流转：pending → resolved + hash 状态更新 + TTL 切换
- 重复 ack 防御
- get_event / get_history / get_stats
- emit 异常情况下不抛错
"""
import pytest
import json


# 自动 patch crisis_alert 模块的 redis_client 为 fakeredis
@pytest.fixture
def crisis_redis(fake_redis):
    import services.crisis_alert as ca
    orig = ca.redis_client
    ca.redis_client = fake_redis
    yield fake_redis
    ca.redis_client = orig


class TestEmit:
    def test_emit_writes_to_pending_zset(self, crisis_redis):
        from services.crisis_alert import emit_crisis_alert, get_unread_count
        eid = emit_crisis_alert(
            user_id="wx_test_user_001",
            session_id="sess_001",
            level="high",
            types=["suicide"],
            message="我想死了",
        )
        assert eid is not None
        assert isinstance(eid, str) and len(eid) >= 8
        assert get_unread_count() == 1

    def test_emit_multiple_events(self, crisis_redis):
        from services.crisis_alert import emit_crisis_alert, get_unread_count
        for i in range(5):
            emit_crisis_alert(f"u{i}", f"s{i}", "medium", ["suicide"], f"msg{i}")
        assert get_unread_count() == 5

    def test_emit_persists_event_hash(self, crisis_redis):
        from services.crisis_alert import emit_crisis_alert, get_event
        eid = emit_crisis_alert("u1", "s1", "high", ["suicide", "self_harm"], "原话内容")
        ev = get_event(eid)
        assert ev is not None
        assert ev["user_id"] == "u1"
        assert ev["session_id"] == "s1"
        assert ev["level"] == "high"
        assert "suicide" in ev["types"]
        assert "self_harm" in ev["types"]
        assert ev["message"] == "原话内容"
        assert ev["status"] == "pending"

    def test_emit_truncates_long_message(self, crisis_redis):
        from services.crisis_alert import emit_crisis_alert, get_event, MAX_MESSAGE_PREVIEW
        long_msg = "a" * 1000
        eid = emit_crisis_alert("u1", "s1", "high", ["suicide"], long_msg)
        ev = get_event(eid)
        assert len(ev["message"]) == MAX_MESSAGE_PREVIEW

    def test_emit_with_extra_payload(self, crisis_redis):
        from services.crisis_alert import emit_crisis_alert, get_event
        eid = emit_crisis_alert("u1", "s1", "high", ["suicide"], "msg",
                                extra={"anxiety_level": "severe", "total_turns": 5})
        ev = get_event(eid)
        assert ev.get("extra", {}).get("anxiety_level") == "severe"
        assert ev.get("extra", {}).get("total_turns") == 5


class TestGetPending:
    def test_empty_returns_empty_list(self, crisis_redis):
        from services.crisis_alert import get_pending_alerts
        assert get_pending_alerts() == []

    def test_pending_sorted_newest_first(self, crisis_redis):
        """zrevrange 应按 score（时间）倒序"""
        import time
        from services.crisis_alert import emit_crisis_alert, get_pending_alerts
        emit_crisis_alert("u_a", "s_a", "high", ["suicide"], "first")
        time.sleep(0.01)
        emit_crisis_alert("u_b", "s_b", "medium", ["violence"], "second")
        alerts = get_pending_alerts()
        assert len(alerts) == 2
        # 第二条（更晚）应在前
        assert alerts[0]["user_id"] == "u_b"
        assert alerts[1]["user_id"] == "u_a"

    def test_pending_respects_limit(self, crisis_redis):
        from services.crisis_alert import emit_crisis_alert, get_pending_alerts
        for i in range(10):
            emit_crisis_alert(f"u{i}", f"s{i}", "high", ["suicide"], "x")
        assert len(get_pending_alerts(limit=3)) == 3


class TestAck:
    def test_ack_moves_to_resolved(self, crisis_redis):
        from services.crisis_alert import emit_crisis_alert, ack_alert, get_unread_count, get_history
        eid = emit_crisis_alert("u1", "s1", "high", ["suicide"], "msg")
        assert get_unread_count() == 1

        result = ack_alert(eid, operator="张三", note="已电话联系")
        assert result["success"] is True
        assert get_unread_count() == 0

        history = get_history(days=30)
        assert len(history) == 1
        assert history[0]["status"] == "resolved"
        assert history[0]["ack_operator"] == "张三"
        assert history[0]["ack_note"] == "已电话联系"
        assert history[0]["resolved_at"]  # 非空

    def test_ack_unknown_event_returns_error(self, crisis_redis):
        from services.crisis_alert import ack_alert
        result = ack_alert("nonexistent_event_id", operator="x", note="y")
        assert result["success"] is False
        assert "不存在" in result["error"] or "过期" in result["error"]

    def test_double_ack_is_rejected(self, crisis_redis):
        from services.crisis_alert import emit_crisis_alert, ack_alert
        eid = emit_crisis_alert("u1", "s1", "high", ["suicide"], "msg")
        ack_alert(eid, "operator1", "first ack")
        result = ack_alert(eid, "operator2", "second ack")
        assert result["success"] is False
        assert "已被" in result["error"] or "已处理" in result["error"]

    def test_ack_truncates_long_note(self, crisis_redis):
        from services.crisis_alert import emit_crisis_alert, ack_alert, get_event
        eid = emit_crisis_alert("u1", "s1", "high", ["suicide"], "msg")
        long_note = "x" * 2000
        ack_alert(eid, "op", long_note)
        ev = get_event(eid)
        assert len(ev["ack_note"]) == 1000


class TestStats:
    def test_stats_empty(self, crisis_redis):
        from services.crisis_alert import get_stats
        s = get_stats(days=7)
        assert s["pending"] == 0
        assert s["resolved_recent"] == 0
        assert s["by_level"]["high"] == 0

    def test_stats_after_emit_and_ack(self, crisis_redis):
        from services.crisis_alert import emit_crisis_alert, ack_alert, get_stats
        # 5 高危 + 3 中危
        eids_high = [emit_crisis_alert(f"uh{i}", f"sh{i}", "high", ["suicide"], "msg") for i in range(5)]
        eids_med = [emit_crisis_alert(f"um{i}", f"sm{i}", "medium", ["violence"], "msg") for i in range(3)]
        # 全部处理掉
        for e in eids_high + eids_med:
            ack_alert(e, "op", "test")

        s = get_stats(days=7)
        assert s["pending"] == 0
        assert s["resolved_recent"] == 8
        assert s["by_level"]["high"] == 5
        assert s["by_level"]["medium"] == 3
        assert s["by_type"]["suicide"] == 5
        assert s["by_type"]["violence"] == 3


class TestResilience:
    def test_emit_when_redis_is_none_returns_none(self, monkeypatch):
        """Redis 不可用时 emit 应返回 None 而不是抛错"""
        import services.crisis_alert as ca
        monkeypatch.setattr(ca, "redis_client", None)
        result = ca.emit_crisis_alert("u", "s", "high", ["suicide"], "msg")
        assert result is None

    def test_unread_count_when_redis_is_none(self, monkeypatch):
        import services.crisis_alert as ca
        monkeypatch.setattr(ca, "redis_client", None)
        assert ca.get_unread_count() == 0
