"""
焦虑检测模块
基于关键词 + 反刍检测 + 焦虑密度的综合检测
"""

import re
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Tuple, Set, Optional
import numpy as np

# 延迟导入 sklearn（可选依赖）
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


class AnxietyLevel(Enum):
    NORMAL = "normal"
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


class DetectionTrigger(Enum):
    NONE = "none"
    KEYWORD_LEVEL1 = "keyword_level1"
    KEYWORD_LEVEL2 = "keyword_level2"
    KEYWORD_LEVEL3 = "keyword_level3"
    RUMINATION = "rumination"
    ANXIETY_DENSITY = "anxiety_density"
    COMPOUND = "compound"


@dataclass
class AnxietyDetectionResult:
    level: AnxietyLevel
    trigger: DetectionTrigger
    confidence: float
    detected_keywords: List[Tuple[str, int]]
    anxiety_density: float
    rumination_score: float
    recommended_action: str
    explanation: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConversationContext:
    user_messages: List[str] = field(default_factory=list)
    anxiety_levels: List[AnxietyLevel] = field(default_factory=list)
    rumination_flags: List[bool] = field(default_factory=list)


class AnxietyKeywordLibrary:
    """焦虑关键词词库"""

    LEVEL1_KEYWORDS = {
        "担心": 1, "害怕": 1, "怕": 1, "万一": 1,
        "不确定": 1, "不安": 1, "焦虑": 1, "烦恼": 1,
        "发愁": 1, "犯愁": 1, "紧张": 1,
        "睡不着": 1, "睡不着觉": 1, "失眠": 1,
        "脑子停不下来": 1, "脑子转不停": 1,
        "静不下心": 1, "心静不下来": 1,
        "烦躁": 1, "烦躁不安": 1, "心里堵": 1,
        "压力": 1, "压力大": 1, "压力好大": 1,
    }

    LEVEL2_KEYWORDS = {
        "心跳快": 2, "心跳有点快": 2, "心跳加速": 2,
        "胸口闷": 2, "胸闷": 2, "胸口堵": 2,
        "肩膀紧": 2, "肩膀酸": 2,
        "手心出汗": 2, "手心湿": 2,
        "停不下来": 2, "一直想": 2, "控制不住": 2,
        "反复": 2, "翻来覆去": 2, "忍不住想": 2,
        "很难受": 2, "受不了": 2, "快要崩溃": 2,
        "很烦躁": 2, "非常焦虑": 2,
        "好烦": 2, "太烦了": 2,
    }

    LEVEL3_KEYWORDS = {
        "活不下去": 3, "活着没意思": 3, "不想活了": 3,
        "死了算了": 3, "活着好累": 3,
        "完了": 3, "彻底完了": 3, "彻底完蛋": 3, "完蛋了": 3,
        "没救了": 3, "彻底没救了": 3,
        "想死": 3, "想自杀": 3,
        "自残": 3, "伤害自己": 3,
        "喘不过气": 3, "要窒息": 3,
        "濒死感": 3, "快要死了": 3,
        "手在抖": 3, "全身发抖": 3,
        "彻底崩溃": 3, "彻底失控": 3,
    }

    NEGATION_WORDS = {"不", "没", "不是", "不会", "没有", "不会的", "应该不会"}


class KeywordDetector:
    """关键词检测器"""

    def __init__(self, library: AnxietyKeywordLibrary):
        self.library = library
        self._build_index()

    def _build_index(self):
        self.keyword_to_level = {}
        for kw, level in self.library.LEVEL1_KEYWORDS.items():
            self.keyword_to_level[kw] = level
        for kw, level in self.library.LEVEL2_KEYWORDS.items():
            self.keyword_to_level[kw] = level
        for kw, level in self.library.LEVEL3_KEYWORDS.items():
            self.keyword_to_level[kw] = level

    def detect(self, text: str) -> Tuple[List[Tuple[str, int]], int, float]:
        if not text:
            return [], 0, 0.0

        detected = []
        for keyword, base_level in self.keyword_to_level.items():
            if keyword in text:
                adjusted_level = self._check_negation(keyword, text, base_level)
                if adjusted_level > 0:
                    detected.append((keyword, adjusted_level))

        if not detected:
            return [], 0, 0.0

        max_level = max(d[1] for d in detected)
        confidence = min(0.99, 0.3 + len(detected) * 0.1 + max_level * 0.2)

        return detected, max_level, confidence

    def _check_negation(self, keyword: str, text: str, base_level: int) -> int:
        if base_level < 3:
            return base_level

        pos = text.find(keyword)
        if pos == -1:
            return base_level

        prefix = text[max(0, pos - 15):pos]
        for neg in self.library.NEGATION_WORDS:
            if neg in prefix:
                return 2
        return base_level


class SimpleRuminationDetector:
    """简化版反刍检测器（无需 sklearn）"""

    def __init__(self, threshold: float = 0.6):
        self.threshold = threshold
        self.history: List[str] = []
        self.word_patterns = {
            r"^就是", r"^万一", r"^感觉", r"^觉得", r"^特别", r"^总是",
        }
        self.anxiety_phrases = {"怎么办", "万一", "害怕", "担心", "怕"}

    def add_message(self, text: str):
        self.history.append(text)
        if len(self.history) > 10:
            self.history.pop(0)

    def detect(self, current_text: str) -> Tuple[float, bool, str]:
        if len(self.history) < 2:
            return 0.0, False, "消息不足"

        self.add_message(current_text)

        # 方法1：检查是否重复相同的担忧句式
        recent = self.history[-3:] if len(self.history) >= 3 else self.history

        # 计算焦虑词重复
        anxiety_counts = []
        for msg in recent:
            count = sum(1 for phrase in self.anxiety_phrases if phrase in msg)
            anxiety_counts.append(count)

        # 如果连续2条焦虑词数量相同且都较高
        if len(anxiety_counts) >= 2:
            if anxiety_counts[-1] > 0 and anxiety_counts[-1] == anxiety_counts[-2]:
                return 0.75, True, "检测到重复担忧"

        # 方法2：句式结构相似
        current_start = self._get_sentence_start(current_text)
        prev_start = self._get_sentence_start(self.history[-2]) if len(self.history) >= 2 else ""

        if current_start and prev_start and current_start == prev_start:
            return 0.8, True, "句式重复"

        return 0.2, False, "无反刍迹象"

    def _get_sentence_start(self, text: str) -> Optional[str]:
        for pattern in self.word_patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        return None


class AnxietyDetector:
    """综合焦虑检测器"""

    def __init__(self):
        self.keyword_library = AnxietyKeywordLibrary()
        self.keyword_detector = KeywordDetector(self.keyword_library)
        self.rumination_detector = SimpleRuminationDetector()
        self.contexts: dict = {}  # user_id -> ConversationContext

    def detect(self, user_message: str, conversation_turns: int = 0, user_id: str = "default") -> AnxietyDetectionResult:
        # 关键词检测
        keywords, max_level, keyword_confidence = self.keyword_detector.detect(user_message)

        # 反刍检测
        rumination_score, is_rumination, rumination_reason = \
            self.rumination_detector.detect(user_message)

        # 焦虑密度计算
        anxiety_density = self._calculate_density(user_message, keywords)

        # 综合评估
        final_level, trigger, explanation = self._comprehensive_assessment(
            max_level=max_level,
            keywords=keywords,
            rumination_score=rumination_score,
            is_rumination=is_rumination,
            anxiety_density=anxiety_density,
            conversation_turns=conversation_turns
        )

        # 确定建议动作
        action = self._determine_action(final_level, conversation_turns)

        return AnxietyDetectionResult(
            level=final_level,
            trigger=trigger,
            confidence=max(keyword_confidence, rumination_score),
            detected_keywords=keywords,
            anxiety_density=anxiety_density,
            rumination_score=rumination_score,
            recommended_action=action,
            explanation=explanation
        )

    def _calculate_density(self, text: str, keywords: List[Tuple[str, int]]) -> float:
        if not text:
            return 0.0

        # 简化：关键词数量 / 总字符数
        keyword_chars = sum(len(kw) for kw, _ in keywords)
        density = keyword_chars / max(len(text), 1)

        return min(1.0, density * 3)

    def _comprehensive_assessment(
        self,
        max_level: int,
        keywords: List[Tuple[str, int]],
        rumination_score: float,
        is_rumination: bool,
        anxiety_density: float,
        conversation_turns: int
    ) -> Tuple[AnxietyLevel, DetectionTrigger, str]:

        # 优先级1: Level 3 关键词
        if max_level >= 3:
            return (
                AnxietyLevel.SEVERE,
                DetectionTrigger.KEYWORD_LEVEL3,
                f"检测到重度焦虑关键词"
            )

        # 优先级2: 高反刍分数
        if is_rumination and rumination_score >= 0.75:
            return (
                AnxietyLevel.SEVERE,
                DetectionTrigger.RUMINATION,
                f"连续反刍思维，分数 {rumination_score:.2f}"
            )

        # 优先级3: Level 2 + 高密度
        if max_level >= 2 and anxiety_density >= 0.4:
            return (
                AnxietyLevel.MODERATE,
                DetectionTrigger.COMPOUND,
                f"中度焦虑关键词 + 焦虑密度升高"
            )

        # 优先级4: Level 2 关键词
        if max_level >= 2:
            return (
                AnxietyLevel.MODERATE,
                DetectionTrigger.KEYWORD_LEVEL2,
                f"检测到中度焦虑关键词"
            )

        # 优先级5: 反刍迹象
        if is_rumination:
            return (
                AnxietyLevel.MILD,
                DetectionTrigger.RUMINATION,
                f"轻微反刍迹象"
            )

        # 优先级6: Level 1 关键词
        if max_level >= 1:
            return (
                AnxietyLevel.MILD,
                DetectionTrigger.KEYWORD_LEVEL1,
                f"检测到轻度焦虑关键词"
            )

        return (
            AnxietyLevel.NORMAL,
            DetectionTrigger.NONE,
            "未检测到焦虑迹象"
        )

    def _determine_action(self, level: AnxietyLevel, conversation_turns: int) -> str:
        if level == AnxietyLevel.SEVERE:
            return "IMMEDIATE_SWITCH"
        if level == AnxietyLevel.MODERATE:
            if conversation_turns >= 4:
                return "PREPARE_SWITCH"
            return "CONTINUE_WITH_CARE"
        if level == AnxietyLevel.MILD:
            return "CONTINUE"
        return "CONTINUE"
