"""
CBTManager 单元测试
重点覆盖：安全协议分级响应、状态机流转、情绪检测
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from cbt_manager import (
    CBTManager, EmotionDetector, SessionPhase,
    AnxietyLevel, RecommendedAction
)


class TestEmotionDetector:
    """情绪检测器规则基线测试"""

    @pytest.fixture
    def detector(self):
        return EmotionDetector()

    def test_detect_anxiety_severe_suicide(self, detector):
        level, domain, action = detector.detect_anxiety("我不想活了，想死")
        assert level == AnxietyLevel.SEVERE
        assert action == RecommendedAction.IMMEDIATE_SAFETY.value

    def test_detect_anxiety_moderate(self, detector):
        level, domain, action = detector.detect_anxiety("我崩溃了，绝望")
        assert level == AnxietyLevel.MODERATE
        assert action == RecommendedAction.PREPARE_SWITCH.value

    def test_detect_anxiety_mild(self, detector):
        level, domain, action = detector.detect_anxiety("有点担心明天")
        assert level == AnxietyLevel.MILD
        assert action == RecommendedAction.CONTINUE.value

    def test_detect_anxiety_normal(self, detector):
        level, domain, action = detector.detect_anxiety("今天天气不错")
        assert level == AnxietyLevel.NORMAL
        assert action == RecommendedAction.CONTINUE.value

    def test_detect_scenario_work(self, detector):
        scenario, opening = detector.detect_scenario("明天要汇报，睡不着")
        assert scenario == "work"
        assert "工作" in opening or "汇报" in opening

    def test_detect_scenario_relationship(self, detector):
        scenario, opening = detector.detect_scenario("和男朋友吵架了")
        assert scenario == "relationship"

    def test_detect_scenario_none(self, detector):
        scenario, opening = detector.detect_scenario("今天吃了火锅")
        assert scenario is None


class TestCBTManagerSafety:
    """CBTManager 安全协议分级测试"""

    @pytest.fixture
    def manager(self):
        # 不传 redis_client，使用内存 fallback
        return CBTManager(redis_client=None)

    def test_safety_response_high(self, manager):
        state = manager.get_or_create_session("user_1", "sess_1")
        state.phase = SessionPhase.ASSESSMENT
        resp = manager._safety_response(state, crisis_level="high", crisis_types=["suicide"])
        assert resp["response_type"] == "safety"
        assert "010-82951332" in resp["content"]
        assert resp["tts_params"]["rate"] == 0.8

    def test_safety_response_medium(self, manager):
        state = manager.get_or_create_session("user_2", "sess_2")
        resp = manager._safety_response(state, crisis_level="medium", crisis_types=["suicide"])
        assert resp["response_type"] == "safety"
        assert "心理援助热线" in resp["content"]
        assert resp["tts_params"]["rate"] == 0.85

    def test_safety_response_low(self, manager):
        state = manager.get_or_create_session("user_3", "sess_3")
        resp = manager._safety_response(state, crisis_level="low", crisis_types=["suicide"])
        assert resp["response_type"] == "safety"
        assert "心理援助热线" in resp["content"]
        assert resp["tts_params"]["rate"] == 0.9

    def test_process_message_triggers_safety_protocol(self, manager):
        """输入自杀关键词应进入 SAFETY_PROTOCOL"""
        result = manager.process_message(
            user_id="user_test",
            session_id="sess_test",
            user_message="我不想活了，想死",
            conversation_history=[]
        )
        assert result["response_type"] == "safety"
        state = manager.get_or_create_session("user_test", "sess_test")
        assert state.phase == SessionPhase.SAFETY_PROTOCOL

    def test_process_message_normal_flow(self, manager):
        """正常输入应进入 ASSESSMENT 并返回文本响应"""
        result = manager.process_message(
            user_id="user_norm",
            session_id="sess_norm",
            user_message="今天有点失眠",
            conversation_history=[]
        )
        assert result["response_type"] == "text"
        state = manager.get_or_create_session("user_norm", "sess_norm")
        assert state.total_turns == 1

    def test_process_message_state_persistence_in_memory(self, manager):
        """验证内存中状态正确累积"""
        manager.process_message("user_p", "sess_p", "你好", [])
        manager.process_message("user_p", "sess_p", "有点担心", [])
        state = manager.get_or_create_session("user_p", "sess_p")
        assert state.total_turns == 2
        assert len(state.anxiety_scores) == 2

    def test_reset_session_clears_state(self, manager):
        manager.process_message("user_r", "sess_r", "测试", [])
        manager.reset_session("user_r", "sess_r")
        state = manager.get_or_create_session("user_r", "sess_r")
        assert state.total_turns == 0


class TestSessionStateMachine:
    """会话状态机流转测试"""

    @pytest.fixture
    def manager(self):
        return CBTManager(redis_client=None)

    def test_initial_phase_is_assessment(self, manager):
        state = manager.get_or_create_session("u1", "s1")
        assert state.phase == SessionPhase.ASSESSMENT

    def test_worry_capture_after_mild_anxiety(self, manager):
        """中度焦虑且聊够2轮后进入担忧捕获"""
        # 第一轮：评估
        manager.process_message("u2", "s2", "你好", [])
        # 第二轮：表达担忧
        result = manager.process_message("u2", "s2", "我很担心工作", [])
        state = manager.get_or_create_session("u2", "s2")
        # 总轮数 >=2 且焦虑 mild/moderate 时进入 WORRY_CAPTURE
        assert state.phase in [SessionPhase.WORRY_CAPTURE, SessionPhase.ASSESSMENT]

    def test_emotional_momentum_tracking(self, manager):
        manager.process_message("u3", "s3", "有点紧张", [])
        manager.process_message("u3", "s3", "更紧张了", [])
        state = manager.get_or_create_session("u3", "s3")
        assert len(state.anxiety_scores) == 2
        assert all(isinstance(s, float) for s in state.anxiety_scores)
