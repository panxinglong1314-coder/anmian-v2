"""
情感分析器单元测试
重点覆盖：危机关键词检测、自杀风险分级、情绪分类
"""
import pytest
from emotion_analyzer import EmotionAnalyzer, EmotionResult


class TestCrisisDetection:
    """分级危机关键词检测（不依赖外部语料库）"""

    @pytest.fixture
    def analyzer(self):
        return EmotionAnalyzer(corpus_path=None)

    def test_high_risk_suicide(self, analyzer):
        texts = ["我不想活了", "我想死", "活着没意思，死了算了", "自杀算了"]
        for t in texts:
            result = analyzer._detect_crisis(t)
            assert result["level"] == "high", f"'{t}' 应判定为 high 危机"
            assert "suicide" in result["types"]
            assert result["score"] > 0.3

    def test_medium_risk_suicide(self, analyzer):
        texts = ["活不下去了", "撑不下去了", "死了更好"]
        for t in texts:
            result = analyzer._detect_crisis(t)
            assert result["level"] == "medium", f"'{t}' 应判定为 medium 危机"
            assert "suicide" in result["types"]

    def test_low_risk(self, analyzer):
        texts = ["没意思", "没劲", "好累", "不想面对"]
        for t in texts:
            result = analyzer._detect_crisis(t)
            assert result["level"] == "low", f"'{t}' 应判定为 low 危机"

    def test_no_risk(self, analyzer):
        result = analyzer._detect_crisis("今天天气不错，心情很好")
        assert result["level"] == "none"
        assert result["score"] == 0
        assert result["types"] == []

    def test_self_harm_high(self, analyzer):
        result = analyzer._detect_crisis("我想自残，割腕")
        assert result["level"] == "high"
        assert "self_harm" in result["types"]

    def test_violence_medium(self, analyzer):
        result = analyzer._detect_crisis("想砸东西，控制不住暴力")
        assert result["level"] == "medium"
        assert "violence" in result["types"]

    def test_acute_psychosis_high(self, analyzer):
        result = analyzer._detect_crisis("脑子里有人说话，被监视")
        assert result["level"] == "high"
        assert "acute_psychosis" in result["types"]


class TestEmotionAnalyze:
    """完整情绪分析（使用空语料库，主要验证危机覆盖逻辑）"""

    @pytest.fixture
    def analyzer(self):
        return EmotionAnalyzer(corpus_path=None)

    def test_suicide_text_triggers_immediate_safety(self, analyzer):
        result = analyzer.analyze("我不想活了，活着没意思")
        assert result.risk_flag == "IMMEDIATE_SAFETY"
        assert result.primary == "sadness"
        assert result.level == "severe"
        assert result.suicide_risk > 0.3

    def test_medium_crisis_escalates(self, analyzer):
        result = analyzer.analyze("活不下去了，撑不住了")
        assert result.risk_flag == "CONTINUE_WITH_CARE"
        assert result.level in ["moderate", "severe"]

    def test_normal_text(self, analyzer):
        result = analyzer.analyze("今天天气不错")
        assert result.risk_flag == "CONTINUE"
        assert result.primary == "neutral"
        assert result.suicide_risk == 0

    def test_result_dataclass(self, analyzer):
        result = analyzer.analyze("测试")
        assert isinstance(result, EmotionResult)
        assert hasattr(result, "primary")
        assert hasattr(result, "suicide_risk")


class TestEmotionAnalyzerWithCorpus:
    """使用真实语料库的集成测试（若语料存在）"""

    def test_load_real_corpus(self, emotion_corpus_path):
        if emotion_corpus_path is None:
            pytest.skip("真实语料库不存在，跳过集成测试")
        analyzer = EmotionAnalyzer(corpus_path=emotion_corpus_path)
        assert analyzer.corpus is not None
        # 验证语料结构
        assert "emotion_categories" in analyzer.corpus or "worry_domains" in analyzer.corpus

    def test_analyze_with_real_corpus(self, emotion_corpus_path):
        if emotion_corpus_path is None:
            pytest.skip("真实语料库不存在，跳过集成测试")
        analyzer = EmotionAnalyzer(corpus_path=emotion_corpus_path)
        result = analyzer.analyze("我很焦虑，睡不着，脑子里停不下来")
        assert result.risk_flag in ["CONTINUE", "CONTINUE_WITH_CARE"]
        assert result.intensity >= 1
