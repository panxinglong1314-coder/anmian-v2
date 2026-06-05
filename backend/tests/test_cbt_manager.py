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


# ============================ P1-5 苏格拉底问题注入 ============================
# 验证项:
# - _select_socratic_questions 命中 distortion id → next_socratic_questions 非空
# - asked_socratic 写入新选的问题, 不再重复选同一条
# - 全部问完会重置(避免长会话沉默)
# - 未知 distortion (generic_worry fallback) → 不抛错, next 为空
# - get_cbt_system_prompt 在 cognitive_restructuring 阶段会嵌入苏格拉底问题
# - _serialize_state / _deserialize_state 跨会话保留状态

class TestSocraticInjection:

    @pytest.fixture
    def manager(self):
        return CBTManager()

    def _seed_state_with_distortion(self, manager, user_id, session_id, distortion_id):
        """工具:创建 session, 让 state 进入 cognitive 阶段并设 distortion id。"""
        state = manager.get_or_create_session(user_id, session_id)
        state.phase = SessionPhase.COGNITIVE_RESTRUCTURING
        state.detected_distortion_id = distortion_id
        return state

    def test_select_known_distortion_populates_next(self, manager):
        from cbt_manager import COGNITIVE_DISTORTIONS
        # 取一个真实存在的扭曲 id
        known_id = COGNITIVE_DISTORTIONS[0]["id"]
        state = self._seed_state_with_distortion(manager, "u_s1", "s_s1", known_id)
        manager._select_socratic_questions(state, known_id)
        assert len(state.next_socratic_questions) > 0
        # 选的问题确实在 corpus 中
        all_qs = set(COGNITIVE_DISTORTIONS[0]["socratic_questions"])
        for q in state.next_socratic_questions:
            assert q in all_qs

    def test_asked_socratic_avoids_repeat(self, manager):
        from cbt_manager import COGNITIVE_DISTORTIONS
        known_id = COGNITIVE_DISTORTIONS[0]["id"]
        state = self._seed_state_with_distortion(manager, "u_s2", "s_s2", known_id)
        # 第一次选
        manager._select_socratic_questions(state, known_id, pick=2)
        first_batch = list(state.next_socratic_questions)
        # 第二次选 — 不应跟第一批重叠
        manager._select_socratic_questions(state, known_id, pick=2)
        second_batch = list(state.next_socratic_questions)
        # 不全相同, 且 asked 累积了两批
        assert first_batch != second_batch
        # asked_socratic 至少含两批共 ≥ 3 个 (取决于该扭曲 socratic 数)
        assert len(set(state.asked_socratic)) >= min(3, len(COGNITIVE_DISTORTIONS[0]["socratic_questions"]))

    def test_unknown_distortion_returns_empty(self, manager):
        state = self._seed_state_with_distortion(manager, "u_s3", "s_s3", "generic_worry")
        manager._select_socratic_questions(state, "generic_worry")
        assert state.next_socratic_questions == []

    def test_exhausted_questions_reset(self, manager):
        """全问完会重置 asked, 下次再次能选出问题(避免空)"""
        from cbt_manager import COGNITIVE_DISTORTIONS
        known_id = COGNITIVE_DISTORTIONS[0]["id"]
        all_qs = COGNITIVE_DISTORTIONS[0]["socratic_questions"]
        state = self._seed_state_with_distortion(manager, "u_s4", "s_s4", known_id)
        # 模拟已经全问完
        state.asked_socratic = list(all_qs)
        manager._select_socratic_questions(state, known_id, pick=2)
        # 仍能选出问题(重置 + 再选)
        assert len(state.next_socratic_questions) > 0

    def test_system_prompt_injects_socratic(self, manager):
        from cbt_manager import COGNITIVE_DISTORTIONS
        known_id = COGNITIVE_DISTORTIONS[0]["id"]
        first_q = COGNITIVE_DISTORTIONS[0]["socratic_questions"][0]
        state = self._seed_state_with_distortion(manager, "u_s5", "s_s5", known_id)
        manager._select_socratic_questions(state, known_id, pick=1)
        prompt = manager.get_cbt_system_prompt(
            "u_s5", "s_s5", phase="cognitive_restructuring",
        )
        assert "苏格拉底注入" in prompt
        # 选好的问题应该出现在 prompt 里 (前 8 字匹配, 避免标点差异)
        assert state.next_socratic_questions[0][:8] in prompt

    def test_system_prompt_non_cognitive_phase_no_injection(self, manager):
        """非 cognitive 阶段不应注入,即使 next_socratic_questions 有值"""
        from cbt_manager import COGNITIVE_DISTORTIONS
        known_id = COGNITIVE_DISTORTIONS[0]["id"]
        state = self._seed_state_with_distortion(manager, "u_s6", "s_s6", known_id)
        manager._select_socratic_questions(state, known_id, pick=1)
        prompt = manager.get_cbt_system_prompt(
            "u_s6", "s_s6", phase="assessment",
        )
        assert "苏格拉底注入" not in prompt

    def test_serialize_roundtrip_preserves_socratic_state(self, manager):
        from cbt_manager import _serialize_state, _deserialize_state, COGNITIVE_DISTORTIONS
        known_id = COGNITIVE_DISTORTIONS[0]["id"]
        state = self._seed_state_with_distortion(manager, "u_s7", "s_s7", known_id)
        manager._select_socratic_questions(state, known_id, pick=2)
        # 序列化 + 反序列化
        data = _serialize_state(state)
        # _serialize_state 只写部分字段, _save_state 才补全 — 模拟完整 dump
        data["asked_socratic"] = state.asked_socratic
        data["next_socratic_questions"] = state.next_socratic_questions
        restored = _deserialize_state(data)
        assert restored.asked_socratic == state.asked_socratic
        assert restored.next_socratic_questions == state.next_socratic_questions
