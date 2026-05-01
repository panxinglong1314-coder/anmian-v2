"""
CBT-I 会话管理器 v2
动态 LLM + CBT-I 状态机 + 情绪自适应

基于完整 CBT-I 协议，支持动态语言生成（非固定脚本）
"""

import json
import re
import time
import asyncio
import numpy as np
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, AsyncGenerator, Tuple
from pathlib import Path

# ============ 加载语料库 ============

CORPUS_DIR = Path(__file__).parent.parent / "corpus"

def load_corpus(filename: str) -> dict:
    path = CORPUS_DIR / filename
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}

COGNITIVE_DISTORTIONS = load_corpus("cognitive_distortions.json").get("cognitive_distortions", [])
EMOTION_KEYWORDS = load_corpus("emotion_keywords.json")
BREATHING_SCRIPTS = load_corpus("breathing_scripts.json").get("breathing_scripts", {})
MINDFULNESS_SCRIPTS = load_corpus("breathing_scripts.json").get("mindfulness_scripts", {})
PARADOXICAL_INTENTION = load_corpus("breathing_scripts.json").get("paradoxical_intention", {})
PMR_SCRIPTS = load_corpus("pmr_scripts.json").get("pmr_scripts", {})
CLOSURE_RITUALS = load_corpus("closure_rituals.json")
CLOSURE_VARIANTS_15 = load_corpus("closure_rituals.json").get("closure_variants_15", {}).get("variants", [])
CLOSURE_INTENSITY_DEF = load_corpus("closure_rituals.json").get("closure_variants_15", {}).get("intensity_definitions", {})
FEWSHOT_EXAMPLES = load_corpus("closure_rituals.json").get("fewshot_examples", {}).get("examples", [])
WORRY_SCENARIOS = load_corpus("worry_scenarios.json").get("worry_scenarios", {})

# ============ 状态定义 ============

class SessionPhase(Enum):
    ASSESSMENT = "assessment"           # 睡眠评估
    WORRY_CAPTURE = "worry_capture"      # 担忧捕获
    COGNITIVE_RESTRUCTURING = "cognitive" # 认知重构
    RELAXATION_INDUCTION = "relaxation"  # 放松诱导
    CLOSURE = "closure"                  # 关闭仪式
    NORMAL_CHAT = "normal_chat"          # 正常闲聊
    SAFETY_PROTOCOL = "safety"           # 安全协议

class AnxietyLevel(Enum):
    NORMAL = "normal"
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"

class RecommendedAction(Enum):
    CONTINUE = "CONTINUE"
    CONTINUE_WITH_CARE = "CONTINUE_WITH_CARE"
    PREPARE_SWITCH = "PREPARE_SWITCH"
    IMMEDIATE_SWITCH = "IMMEDIATE_SWITCH"
    IMMEDIATE_SAFETY = "IMMEDIATE_SAFETY"
    CLOSE_SESSION = "CLOSE_SESSION"

class EmotionalMomentum(Enum):
    IMPROVING = "improving"    # 越来越放松
    STABLE = "stable"          # 平稳
    DETERIORATING = "deteriorating"  # 越来越紧张
    UNKNOWN = "unknown"

class UserStyle(Enum):
    HIGHLY_ANXIOUS = "highly_anxious"   # 情绪浓烈，句子短
    ANALYTICAL = "analytical"           # 爱问问题，句长中等
    VENTING = "venting"                 # 倾诉型，句长 > 20字
    AVOIDANT = "avoidant"              # 回避型，回避感受话题
    NORMAL = "normal"

@dataclass
class SessionState:
    """CBT-I 会话状态"""
    user_id: str
    session_id: str
    phase: SessionPhase = SessionPhase.ASSESSMENT
    anxiety_level: AnxietyLevel = AnxietyLevel.NORMAL
    
    # 担忧处理
    worry_topic: Optional[str] = None
    worry_expressed: bool = False
    worry_write_confirmed: bool = False
    
    # 认知重构
    detected_distortion_id: Optional[str] = None
    distortion_challenged: bool = False
    logical_chain: List[str] = field(default_factory=list)  # 苏格拉底推理链
    
    # 放松
    relaxation_technique: Optional[str] = None
    relaxation_cycles_completed: int = 0
    technique_effectiveness: Dict[str, float] = field(default_factory=dict)  # 技术名→有效性评分
    
    # 轮次追踪
    turns_in_phase: int = 0
    total_turns: int = 0
    consecutive_rumination: int = 0
    
    # 情绪节奏追踪（新增）
    emotional_momentum: EmotionalMomentum = EmotionalMomentum.UNKNOWN
    anxiety_scores: List[float] = field(default_factory=list)  # 最近N轮焦虑分数序列
    
    # 用户风格识别（新增）
    user_style: UserStyle = UserStyle.NORMAL
    user_sentence_lengths: List[int] = field(default_factory=list)
    user_question_ratio: float = 0.0  # 疑问句比例
    
    # 历史
    conversation_history: List[Dict] = field(default_factory=list)
    session_start_time: float = field(default_factory=time.time)
    
    # 元数据
    last_topic: Optional[str] = None
    triggers: Dict[str, int] = field(default_factory=dict)
    
    # 场景感知（新增）
    detected_scenario: Optional[str] = None  # work/relationship/health/none

# ============ 焦虑检测 ============

class EmotionDetector:
    """增强版情绪检测（关键词 + 语义向量兜底 + 认知扭曲识别）"""

    # 语义向量配置（延迟初始化）
    _embedding_model = None
    _embedding_available = None
    
    # 隐式焦虑语义模板
    IMPLICIT_ANXIETY_PATTERNS = [
        {"template": "明天要{}，今晚脑子停不下来", "signals": ["汇报", "演讲", "面试", "考试"], "anxiety_type": "anticipatory", "level": AnxietyLevel.MILD},
        {"template": "感觉{}会影响我的{}", "signals": ["领导", "同事", "客户"], "anxiety_type": "social_evaluation", "level": AnxietyLevel.MODERATE},
        {"template": "如果{}不行，我就完了", "signals": ["这次", "这次汇报", "这次面试", "这个项目"], "anxiety_type": "catastrophic", "level": AnxietyLevel.MODERATE},
    ]
    
    SCENARIO_PATTERNS = {
        "work": {"signals": ["工作", "上班", "领导", "同事", "老板", "汇报", "面试", "辞职", "加班", "KPI", "年终", "项目", "职场"], "opening": "是工作上的事让你放不下吗？"},
        "relationship": {"signals": ["对象", "女朋友", "男朋友", "老婆", "老公", "吵架", "分手", "感情", "约会", "相亲", "暧昧", "朋友"], "opening": "是人际关系的事让你心情不太好？"},
        "health": {"signals": ["身体", "生病", "医院", "体检", "指标", "血压", "心脏", "头疼", "不舒服"], "opening": "最近身体有没有哪里不舒服？"},
        "finance": {"signals": ["钱", "房贷", "欠债", "投资", "亏损", "工资", "省钱", "经济"], "opening": "是为钱的事操心吗？"},
    }

    def __init__(self):
        self.catastrophizing_kw = ["万一", "完了", "彻底完了", "一切完蛋", "灾难"]
        self.severe_kw = ["活不下去", "活着没意思", "不想活了", "死了算了", "彻底崩溃", "想死", "想自杀", "自残"]
        self.moderate_kw = ["崩溃", "绝望", "完蛋了", "极度恐慌", "喘不过气", "要窒息"]
        self.mild_kw = ["担心", "焦虑", "害怕", "紧张", "不安", "睡不着", "脑子停不下来", "静不下来", "难过", "伤心", "郁闷", "烦躁", "压力"]
        self.domain_kw = EMOTION_KEYWORDS.get("worry_domains", {})
        self.distortion_signals = EMOTION_KEYWORDS.get("cognitive_distortion_signals", {})
        self._clue_rules = WORRY_SCENARIOS.get("clue_phrase_matching", {}).get("matching_rules", [])

    @classmethod
    def _check_embedding_available(cls) -> bool:
        """延迟检测 embedding 模型是否可用"""
        if cls._embedding_available is not None:
            return cls._embedding_available
        try:
            import numpy as np
            from sentence_transformers import SentenceTransformer
            cls._embedding_model = SentenceTransformer('/home/ubuntu/all-MiniLM-L6-v2')
            cls._embedding_available = True
        except Exception:
            cls._embedding_available = False
        return cls._embedding_available

    def _semantic_similarity(self, text: str, pattern: str) -> float:
        """计算文本与语义的余弦相似度（0-1）"""
        if not self._check_embedding_available():
            return 0.0
        try:
            import numpy as np
            vec1 = self._embedding_model.encode(text, convert_to_numpy=True)
            vec2 = self._embedding_model.encode(pattern, convert_to_numpy=True)
            similarity = float(np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2)))
            return max(0.0, min(1.0, similarity))
        except Exception:
            return 0.0

    def detect_scenario(self, text: str) -> Tuple[Optional[str], str]:
        """检测睡前场景（工作/人际/健康/财务/无特定）"""
        text_lower = text.lower()
        for scenario, pattern in self.SCENARIO_PATTERNS.items():
            for signal in pattern["signals"]:
                if signal in text_lower:
                    return scenario, pattern["opening"]
        if self._check_embedding_available():
            for scenario, pattern in self.SCENARIO_PATTERNS.items():
                for signal in pattern["signals"]:
                    sim = self._semantic_similarity(text, signal)
                    if sim > 0.75:
                        return scenario, pattern["opening"]
        return None, ""

    def detect_implicit_anxiety(self, text: str) -> Tuple[bool, AnxietyLevel, str]:
        """检测隐式焦虑（没有直接情绪词，但语义上表达焦虑）"""
        text_lower = text.lower()
        for pattern in self.IMPLICIT_ANXIETY_PATTERNS:
            for signal in pattern["signals"]:
                if signal in text_lower:
                    for signal2 in pattern["signals"]:
                        if self._semantic_similarity(text, f"{signal2}相关焦虑") > 0.65:
                            return True, pattern["level"], pattern["anxiety_type"]
        if len(text) > 15 and any(verb in text for verb in ["担心", "害怕", "怕", "紧张"]):
            if self._semantic_similarity(text, "焦虑压力情绪") > 0.6:
                return True, AnxietyLevel.MILD, "general_anxiety"
        return False, AnxietyLevel.NORMAL, ""

    def detect_anxiety(self, text: str) -> Tuple[AnxietyLevel, str, str]:
        """检测焦虑等级、触发领域和行动建议（关键词 + 语义兜底）"""
        text_lower = text.lower()
        for kw in self.severe_kw:
            if kw in text_lower:
                return AnxietyLevel.SEVERE, self._detect_domain(text), RecommendedAction.IMMEDIATE_SAFETY.value
        for kw in self.moderate_kw:
            if kw in text_lower:
                return AnxietyLevel.MODERATE, self._detect_domain(text), RecommendedAction.PREPARE_SWITCH.value
        mild_count = sum(1 for kw in self.mild_kw if kw in text_lower)
        if mild_count > 0:
            level = AnxietyLevel.MODERATE if mild_count >= 2 else AnxietyLevel.MILD
            action = RecommendedAction.CONTINUE_WITH_CARE.value if level == AnxietyLevel.MODERATE else RecommendedAction.CONTINUE.value
            return level, self._detect_domain(text), action
        is_implicit, impl_level, impl_type = self.detect_implicit_anxiety(text)
        if is_implicit:
            return impl_level, self._detect_domain(text), RecommendedAction.CONTINUE_WITH_CARE.value
        return AnxietyLevel.NORMAL, "general", RecommendedAction.CONTINUE.value

    def detect_distortion(self, text: str) -> Optional[Dict]:
        """检测认知扭曲类型（关键词 + 语义兜底）"""
        text_lower = text.lower()
        for distortion in COGNITIVE_DISTORTIONS:
            kw_list = self.distortion_signals.get(distortion["id"], [])
            for kw in kw_list:
                if kw in text_lower:
                    return distortion
        if self._check_embedding_available():
            for distortion in COGNITIVE_DISTORTIONS:
                name_sim = self._semantic_similarity(text, distortion.get("name", ""))
                desc_sim = self._semantic_similarity(text, distortion.get("description", ""))
                if max(name_sim, desc_sim) > 0.75:
                    return distortion
        return None

    def detect_rumination(self, history: List[Dict], current_text: str) -> bool:
        """检测反刍思维"""
        if len(history) < 2:
            return False
        recent = history[-3:]
        starts = set()
        for msg in recent:
            content = msg.get("content", "")
            for kw in ["万一", "就是", "感觉", "我觉得", "特别", "总是"]:
                if content.startswith(kw):
                    starts.add(kw)
        if current_text.strip().startswith(tuple(starts)) if starts else False:
            return True
        recent_keywords = set()
        for msg in recent:
            for kw in self.mild_kw + self.moderate_kw:
                if kw in msg.get("content", "").lower():
                    recent_keywords.add(kw)
        current_keywords = set()
        for kw in self.mild_kw + self.moderate_kw:
            if kw in current_text.lower():
                current_keywords.add(kw)
        return len(current_keywords & recent_keywords) >= 2

    def detect_user_style(self, text: str, history: List[Dict]) -> UserStyle:
        """根据用户输入特征识别对话风格"""
        sentence_len = len(text.strip())
        if sentence_len < 10 and any(kw in text for kw in self.mild_kw + self.moderate_kw):
            return UserStyle.HIGHLY_ANXIOUS
        avoidant_signals = ["不知道", "没什么", "也还好", "说不上来", "没啥"]
        if any(signal in text for signal in avoidant_signals):
            return UserStyle.AVOIDANT
        if history:
            recent_lens = [len(m.get("content", "")) for m in history[-3:]]
            avg_sentence_len = sum(recent_lens) / len(recent_lens) if recent_lens else sentence_len
        else:
            avg_sentence_len = sentence_len
        if avg_sentence_len > 20 and any(pronoun in text for pronoun in ["我", "我的", "自己"]):
            return UserStyle.VENTING
        question_count = text.count("?") + text.count("？")
        question_ratio = question_count / max(1, len(text) / 10)
        if question_ratio > 0.3:
            return UserStyle.ANALYTICAL
        return UserStyle.NORMAL

    def calculate_emotional_momentum(self, anxiety_scores: List[float]) -> EmotionalMomentum:
        """根据最近N轮焦虑分数计算情绪趋势（线性回归斜率）"""
        if len(anxiety_scores) < 3:
            return EmotionalMomentum.UNKNOWN
        try:
            import numpy as np
            recent = anxiety_scores[-5:]
            n = len(recent)
            x = np.arange(n)
            y = np.array(recent)
            if np.std(y) == 0:
                return EmotionalMomentum.STABLE
            slope = np.polyfit(x, y, 1)[0]
            if slope < -0.15:
                return EmotionalMomentum.IMPROVING
            elif slope > 0.15:
                return EmotionalMomentum.DETERIORATING
            return EmotionalMomentum.STABLE
        except Exception:
            return EmotionalMomentum.STABLE

    def _detect_domain(self, text: str) -> str:
        """检测担忧领域"""
        text_lower = text.lower()
        for rule in self._clue_rules:
            clue_keywords = rule.get("if_contains_any", [])
            for kw in clue_keywords:
                if kw in text_lower:
                    return rule.get("assign_category", "general")
        for domain, keywords in self.domain_kw.items():
            for kw in keywords:
                if kw in text_lower:
                    return domain
        return "general"

    def _get_scenario_routing(self, worry_category: str) -> Dict[str, Any]:
        """根据担忧类别返回推荐的技术路由"""
        return self._scenario_routing.get(worry_category, {})

# ============ CBT 会话管理器 ============

class CBTManager:
    """
    CBT-I 动态会话管理器
    
    主要职责：
    1. 管理会话状态机
    2. 根据状态和情绪生成动态响应
    3. 协调 LLM 调用
    4. 输出结构化的 TTS 参数
    """
    
    # 系统提示词模板（完整 CBT-I 版）
    CBT_SYSTEM_PROMPT_V2 = """你是「知眠」，一个沉稳、有经验的心理睡眠陪伴师。你不急于安慰，也不急于解决问题。

【绝对禁止】
- 禁止输出任何标签或标记，如 [emotion:xxx]、[speed:xxx] 等
- 禁止模板化回复，如"声音在"、"我在"、"我在听"
- 禁止每句话都提到"今晚""睡觉""焦虑"
- 禁止重复用户的话作为回复

【回复风格】
- 像真人一样自然对话，有语气变化，不机械
- 回复长度灵活：简单问候可以很短（5-15字），复杂情绪可以稍长（20-40字）
- 可以用第一人称"我"，让对话更自然
- 不用过度柔软的词汇（如"抱抱"、"摸摸头"）
- 不评判情绪（禁止"没关系"、"不用硬撑"、"别怕"等）
- 不追问"为什么"、不给建议、不分析具体问题

【安全红线】
- 用户提到自杀/自伤，立即说"全国心理援助热线 010-82951332，24小时"。

示例正确（仅供参考，不要照搬）：
- 用户："有点难过" → "现在不用急着好起来。"
- 用户："你好" → "你好呀，还没睡？"
- 用户："焦虑得睡不着" → "先不急着解决。"
"""

    # TTS 参数映射

    # TTS 参数映射
    # ── 语音参数：按焦虑等级（兜底）───────────────────────────
    TTS_PARAMS_BY_ANXIETY = {
        AnxietyLevel.SEVERE:   {"voice": "female_warm", "speed": -2, "pitch": "-2st", "volume": 0.9, "pause_ms": 1500},
        AnxietyLevel.MODERATE: {"voice": "female_warm", "speed": -2, "pitch": "-1st", "volume": 0.95, "pause_ms": 1000},
        AnxietyLevel.MILD:     {"voice": "female_warm", "speed": -1, "pitch": "0st",  "volume": 1.0,  "pause_ms": 500},
        AnxietyLevel.NORMAL:   {"voice": "female_warm", "speed": -1, "pitch": "0st",  "volume": 1.0,  "pause_ms": 300},
    }

    # ── 语音参数：按响应类型（覆盖焦虑等级）─────────────────────
    # 优先级：response_type > anxiety_level
    TTS_PARAMS_BY_RESPONSE_TYPE = {
        "breathing":     {"voice": "female_warm", "speed": -2, "pitch": "-2st", "volume": 0.85, "pause_ms": 2000},
        "pmr":           {"voice": "female_warm", "speed": -2, "pitch": "-2st", "volume": 0.85, "pause_ms": 1500},
        "worry_capture": {"voice": "female_warm", "speed": -1, "pitch": "-1st", "volume": 0.95, "pause_ms": 1000},
        "cognitive":     {"voice": "female_warm", "speed": -1, "pitch": "-1st", "volume": 0.95, "pause_ms": 800},
        "closure":       {"voice": "female_young", "speed": -2, "pitch": "-2st", "volume": 0.8, "pause_ms": 2000},
        "safety":        {"voice": "female_young", "speed": -2, "pitch": "-2st", "volume": 0.8, "pause_ms": 2000},
        "normal":        {"voice": "female_warm", "speed": 0, "pitch": "0st",  "volume": 1.0,  "pause_ms": 300},
        "llm_stream":    {"voice": "female_warm", "speed": 0, "pitch": "0st", "volume": 0.95, "pause_ms": 600},
    }

    # ── 语音参数：按用户风格微调（叠加到焦虑等级之上）────────────────
    TTS_ADJUSTMENTS_BY_USER_STYLE = {
        UserStyle.HIGHLY_ANXIOUS: {"speed": -2, "pause_ms": 1500},
        UserStyle.VENTING:        {"speed": -1, "pause_ms": 800},
        UserStyle.ANALYTICAL:     {"speed": 0,  "pause_ms": 500},
        UserStyle.AVOIDANT:       {"speed": -1, "pause_ms": 1000},
        UserStyle.NORMAL:         {},
    }

    def __init__(self):
        self.emotion_detector = EmotionDetector()
        self._sessions: Dict[str, SessionState] = {}
        self._worry_scenarios = WORRY_SCENARIOS.get("scenarios", [])
        self._scenario_routing = WORRY_SCENARIOS.get("scenario_to_technique_routing", {})
        self._clue_rules = WORRY_SCENARIOS.get("clue_phrase_matching", {}).get("matching_rules", [])

    def get_or_create_session(self, user_id: str, session_id: str) -> SessionState:
        key = f"{user_id}:{session_id}"
        if key not in self._sessions:
            self._sessions[key] = SessionState(user_id=user_id, session_id=session_id)
        return self._sessions[key]

    def process_message(self, user_id: str, session_id: str, user_message: str, 
                        conversation_history: List[Dict],
                        profile: Dict = None) -> Dict[str, Any]:
        """
        处理用户消息，返回响应指令和状态更新（含情绪节奏追踪 + L3心理教育 + L4档案）
        
        Args:
            profile: 用户档案（来自 UserProfileManager），用于个性化阈值和语气调整
        """
        state = self.get_or_create_session(user_id, session_id)
        last_phase = state.phase  # L3: 记录上一个phase，用于心理教育时机判断
        state.conversation_history = conversation_history
        state.turns_in_phase += 1
        state.total_turns += 1

        # ── 1. 情绪检测（关键词 + 语义兜底）─────────────────
        anxiety_level, domain, action = self.emotion_detector.detect_anxiety(user_message)
        state.anxiety_level = anxiety_level
        
        # ── 2. 焦虑分数序列（用于情绪节奏追踪）──────────────
        ANXIETY_SCORE_MAP = {AnxietyLevel.NORMAL: 1.0, AnxietyLevel.MILD: 2.5, 
                             AnxietyLevel.MODERATE: 4.0, AnxietyLevel.SEVERE: 5.0}
        state.anxiety_scores.append(ANXIETY_SCORE_MAP.get(anxiety_level, 1.0))
        state.anxiety_scores = state.anxiety_scores[-10:]  # 只保留最近10轮
        
        # ── 3. 情绪节奏计算（线性回归斜率）────────────────
        state.emotional_momentum = self.emotion_detector.calculate_emotional_momentum(state.anxiety_scores)
        
        # ── 4. 场景感知（首次进入时）──────────────────────
        if state.total_turns == 1 and state.phase == SessionPhase.ASSESSMENT:
            scenario, scenario_opening = self.emotion_detector.detect_scenario(user_message)
            if scenario:
                state.detected_scenario = scenario
        
        # ── 5. 用户风格识别 ──────────────────────────────
        state.user_style = self.emotion_detector.detect_user_style(user_message, conversation_history)
        
        # ── 6. 担忧统计更新 ─────────────────────────────
        worry_category = domain if domain != "general" else (state.last_topic or "general")
        if domain != "general":
            state.triggers[domain] = state.triggers.get(domain, 0) + 1
            state.last_topic = domain

        state.conversation_history.append({"role": "user", "content": user_message})

        # ===== 安全协议 =====
        if anxiety_level == AnxietyLevel.SEVERE or action == RecommendedAction.IMMEDIATE_SAFETY.value:
            state.phase = SessionPhase.SAFETY_PROTOCOL
            return self._safety_response(state)

        # ===== 情绪节奏自适应：越来越紧张 → 回退到接住 =====
        if state.emotional_momentum == EmotionalMomentum.DETERIORATING:
            if state.phase in [SessionPhase.RELAXATION_INDUCTION, SessionPhase.CLOSURE]:
                # 技术在进行中但情绪恶化 → 回退到接住阶段
                state.phase = SessionPhase.ASSESSMENT
                state.turns_in_phase = 0
                return self._build_response("text", "嗯，我在。继续说。", state)

        # ===== 反刍检测 =====
        if self.emotion_detector.detect_rumination(conversation_history, user_message):
            state.consecutive_rumination += 1
            if state.consecutive_rumination >= 4:
                state.phase = SessionPhase.CLOSURE
                return self._closure_response(state, user_message, worry_category)
        else:
            state.consecutive_rumination = 0

        # ===== 担忧处理（至少聊2轮后才进入担忧捕获） =====
        if anxiety_level in [AnxietyLevel.MILD, AnxietyLevel.MODERATE] and state.phase == SessionPhase.ASSESSMENT:
            if not state.worry_expressed and state.total_turns >= 2:
                state.worry_topic = domain
                state.phase = SessionPhase.WORRY_CAPTURE
                return self._worry_capture_response(state, user_message)
        
        # ===== 认知重构触发 =====
        distortion = self.emotion_detector.detect_distortion(user_message)
        if distortion and state.phase in [SessionPhase.WORRY_CAPTURE, SessionPhase.COGNITIVE_RESTRUCTURING]:
            state.detected_distortion_id = distortion["id"]
            state.phase = SessionPhase.COGNITIVE_RESTRUCTURING
            # 记录逻辑链（苏格拉底追问用）
            state.logical_chain.append(user_message)
            return self._cognitive_restructure_response(state, distortion)

        # ===== 放松诱导（动态阈值：基于用户历史平均焦虑消退轮数）=====
        # 从用户档案读取个性化阈值，无历史数据则回退到默认4轮
        personalized_relax_threshold = 4
        if profile:
            avg_recovery = profile.get("avg_anxiety_recovery_turns", 0.0)
            if avg_recovery > 0:
                # 允许在平均值的 0.8~1.2 倍范围内波动，最少2轮最多6轮
                personalized_relax_threshold = max(2, min(6, round(avg_recovery * 0.9)))
        
        if state.phase in [SessionPhase.WORRY_CAPTURE, SessionPhase.COGNITIVE_RESTRUCTURING]:
            if state.turns_in_phase >= personalized_relax_threshold:
                state.phase = SessionPhase.RELAXATION_INDUCTION
                state.relaxation_technique = self._select_relaxation_technique(
                    anxiety_level, worry_category=worry_category, 
                    user_style=state.user_style, scenario=state.detected_scenario
                )
                return self._relaxation_response(state)

        # ===== 情绪节奏加速：越来越放松 → 可提前关闭 =====
        # 关闭阈值也基于用户历史动态调整（历史平均 + 1 轮缓冲）
        personalized_close_threshold = 5
        if profile:
            avg_recovery = profile.get("avg_anxiety_recovery_turns", 0.0)
            if avg_recovery > 0:
                personalized_close_threshold = max(3, min(8, round(avg_recovery + 1)))
        
        should_close = (
            state.total_turns >= 10 or
            state.turns_in_phase >= personalized_close_threshold or
            (anxiety_level == AnxietyLevel.NORMAL and state.emotional_momentum == EmotionalMomentum.IMPROVING and state.total_turns >= 8)
        )
        
        if should_close and state.phase != SessionPhase.CLOSURE:
            state.phase = SessionPhase.CLOSURE
            # ── L4: 设置档案更新标记（由调用方在会话结束时异步处理）────────
            response = self._closure_response(state, user_message, worry_category)
            response["_meta"] = {
                "should_update_profile": True,
                "session_summary": {
                    "worry_type": worry_category,
                    "detected_distortion": state.detected_distortion_id or "",
                    "technique_used": state.relaxation_technique or "",
                    "anxiety_recovery_turns": state.turns_in_phase,
                    "effectiveness_score": self._estimate_technique_effectiveness(state),
                    "emotional_momentum": state.emotional_momentum.value,
                    "total_turns": state.total_turns,
                    "date": time.strftime("%Y-%m-%d"),
                }
            }
            # ── L3: 心理教育插入（关闭仪式前的最后时机）─────────────
            psy_insert, psy_key = PsychoeducationManager.should_insert(
                user_message, last_phase, SessionPhase.CLOSURE, state.detected_distortion_id
            )
            if psy_insert:
                psy_content = PsychoeducationManager.get_content(psy_key)
                if psy_content:
                    response["content"] = psy_content + " " + response["content"]
                    response["_meta"]["psychoeducation_inserted"] = psy_key
            return response

        # ===== 正常闲聊（评估状态）=====
        if state.phase == SessionPhase.ASSESSMENT:
            return self._assessment_response(state)

        # ===== 默认：呼吸引导 =====
        if state.phase == SessionPhase.RELAXATION_INDUCTION:
            return self._relaxation_response(state)

        # ===== 继续当前阶段 =====
        return self._continue_phase_response(state, user_message)

    def _worry_capture_response(self, state: SessionState, user_message: str) -> Dict[str, Any]:
        """担忧捕获阶段的响应——由 LLM 动态生成，此处仅更新状态"""
        if state.turns_in_phase == 1:
            state.worry_expressed = True
        elif state.turns_in_phase == 3:
            state.worry_write_confirmed = True
        return self._build_response("text", "[worry_capture]", state)

    def _estimate_technique_effectiveness(self, state: SessionState) -> float:
        """
        L4: 估算本次会话中技术的有效性（1-5分）
        基于情绪节奏 + 消退速度估算
        """
        if not state.relaxation_technique:
            return 3.0  # 默认中等
        
        # 情绪节奏向上 + 关闭顺利 → 高效
        if state.emotional_momentum == EmotionalMomentum.IMPROVING:
            return 4.5
        elif state.emotional_momentum == EmotionalMomentum.STABLE:
            return 3.5
        elif state.emotional_momentum == EmotionalMomentum.DETERIORATING:
            return 2.0
        return 3.0

    def _cognitive_restructure_response(self, state: SessionState, distortion: Dict) -> Dict[str, Any]:
        """认知重构阶段的响应——由 LLM 动态生成，此处仅更新状态"""
        state.logical_chain.append(distortion.get("name", ""))
        return self._build_response("text", "[cognitive_restructuring]", state)

    def _select_relaxation_technique(self, anxiety_level: AnxietyLevel, insomnia_subtype: str = "mixed", 
                                     worry_category: str = "general", 
                                     user_style: UserStyle = UserStyle.NORMAL,
                                     scenario: Optional[str] = None) -> str:
        """
        根据焦虑等级 + 失眠亚型 + 担忧类别 + 用户风格 + 场景选择放松技术
        基于 2025 CBT-I 指南证据等级 + 用户风格自适应
        """
        # ── 重度焦虑：最快路径 ───────────────────────────
        if anxiety_level == AnxietyLevel.SEVERE:
            return "pmr_tiny"

        # ── 矛盾意向优先（入睡困难型 + 睡眠努力过度）───
        if insomnia_subtype == "sleep_onset":
            if anxiety_level in (AnxietyLevel.MODERATE, AnxietyLevel.SEVERE):
                return "paradoxical_intention"
            return "478"

        # ── 用户风格自适应 ──────────────────────────────
        # 回避型 → 不直接说放松，从身体扫描慢慢来
        if user_style == UserStyle.AVOIDANT:
            return "body_scan"  # 身体扫描对回避型最温和
        
        # 分析型 → 可以用478呼吸（有科学感）
        if user_style == UserStyle.ANALYTICAL:
            if anxiety_level in (AnxietyLevel.MODERATE, AnxietyLevel.MILD):
                return "478"  # 478有明确数字框架，分析型喜欢
            return "body_scan"
        
        # 倾诉型 → 已经说很多了，直接上 PMR 短版
        if user_style == UserStyle.VENTING:
            if anxiety_level == AnxietyLevel.MODERATE:
                return "pmr_short"
        
        # 高度焦虑型 → 优先 PMR_tiny 或 box_breathing（有结构感）
        if user_style == UserStyle.HIGHLY_ANXIOUS:
            return "pmr_tiny" if anxiety_level == AnxietyLevel.SEVERE else "box_breathing"

        # ── 场景自适应 ──────────────────────────────────
        if scenario == "relationship":
            return "loving_kindness"  # 人际场景优先慈心冥想
        if scenario == "health":
            return "body_scan"  # 健康焦虑对身体感觉敏感

        # ── 中度焦虑：PMR 短版（默认）──────────────────
        if anxiety_level == AnxietyLevel.MODERATE:
            if worry_category == "relationship":
                return "loving_kindness"
            return "pmr_short"

        # ── 轻度焦虑：身体扫描 ─────────────────────────
        if anxiety_level == AnxietyLevel.MILD:
            if worry_category == "relationship":
                return "loving_kindness"
            if worry_category == "health":
                return "body_scan"
            return "body_scan"

        # ── 无焦虑：478（默认）──────────────────────────
        return "478"

    def _select_pmr_version(self, anxiety_level: AnxietyLevel) -> str:
        """
        选择 PMR 版本：full_body / pmr_short / pmr_tiny
        pmr_tiny → 90秒，2部位（急性焦虑）
        pmr_short → 3分钟，5部位（轻中度焦虑，默认）
        full_body → 15分钟，14部位（有时间+深度需求）
        """
        if anxiety_level == AnxietyLevel.SEVERE:
            return "pmr_tiny"
        if anxiety_level in (AnxietyLevel.MODERATE, AnxietyLevel.MILD):
            return "pmr_short"  # 默认选短版
        return "pmr_short"  # 包括 NORMAL

    def _relaxation_response(self, state: SessionState) -> Dict[str, Any]:
        """放松诱导响应"""
        technique = state.relaxation_technique or "breathing"
        
        if technique == "478":
            script = BREATHING_SCRIPTS.get("478", {})
            if "intro_script" in script and state.relaxation_cycles_completed == 0:
                content = script["intro_script"]
            elif state.relaxation_cycles_completed < 4:
                cycle = state.relaxation_cycles_completed + 1
                instructions = script.get("instructions", [])
                if instructions:
                    phase = instructions[state.relaxation_cycles_completed % 3]
                    content = f"第{cycle}轮：{phase['physical_guide']}"
                else:
                    content = "继续呼吸引导..."
            else:
                content = script.get("outro_script", "很好，我们进入下一个阶段。").format(n=4)
            
            state.relaxation_cycles_completed += 1
            
            if state.relaxation_cycles_completed >= 4:
                return self._build_response("text", "好，我们继续保持这个节奏。现在，轻轻地闭上眼睛...", state)
            
            return {
                "response_type": "breathing",
                "content": content,
                "breathing_data": script.get("instructions", [])[state.relaxation_cycles_completed % 3] if state.relaxation_cycles_completed < 4 else None,
                "tts_params": self.TTS_PARAMS_BY_ANXIETY[state.anxiety_level],
                "state_update": _serialize_state(state),
                "next_phase": SessionPhase.RELAXATION_INDUCTION.value,
                "should_close": False
            }
        
        elif technique == "paradoxical_intention":
            # 矛盾意向法（1A推荐，2025指南）
            script = PARADOXICAL_INTENTION
            if state.relaxation_cycles_completed == 0:
                content = script.get("intro_script", "接下来这个技术，可能会让你觉得奇怪，但它有非常强的科学证据支持。")
            elif state.relaxation_cycles_completed == 1:
                content = script.get("instructions", [{}])[0].get("guide", "你知道吗？越'努力'入睡，反而越睡不着。")
            elif state.relaxation_cycles_completed == 2:
                content = script.get("instructions", [{}])[1].get("guide", "现在，轻轻地把眼睛睁开一点，对自己说：'今晚我不会强迫自己入睡，我只是在休息。'")
            elif state.relaxation_cycles_completed == 3:
                content = script.get("instructions", [{}])[2].get("guide", "睡眠不是需要赢得的奖杯，而是身体会自动发生的事。你不需要做任何事。")
            else:
                content = "很好。现在，就这样躺着，不需要做任何事。睡眠来的时候，跟随它。"
            state.relaxation_cycles_completed += 1
            return {
                "response_type": "breathing",  # 复用breathing类型，前端显示引导
                "content": content,
                "breathing_data": {"type": "paradoxical", "phase": "instruction"},
                "tts_params": {**self.TTS_PARAMS_BY_ANXIETY[state.anxiety_level], "rate": 0.85},
                "state_update": _serialize_state(state),
                "next_phase": SessionPhase.RELAXATION_INDUCTION.value,
                "should_close": False
            }

        elif technique == "body_scan":
            # 正念身体扫描（2A推荐，第三波CBT）
            script = MINDFULNESS_SCRIPTS.get("body_scan", {})
            instructions = script.get("instructions", [])
            if state.relaxation_cycles_completed == 0:
                content = script.get("intro_script", "我们来做一个身体扫描。这是一种正念练习，不改变任何东西，只是觉察。")
            elif state.relaxation_cycles_completed < len(instructions) + 1:
                idx = state.relaxation_cycles_completed - 1
                if idx < len(instructions):
                    step = instructions[idx]
                    content = step.get("guide", f"现在，感受{step.get('body_part', '身体')}...")
                else:
                    content = script.get("outro_script", "整个身体已经充分休息了。现在，让注意力停留在身体上。")
            else:
                content = "很好。现在，身体已经完全沉入休息。睡眠来的时候，跟随它。"
            state.relaxation_cycles_completed += 1
            return {
                "response_type": "breathing",
                "content": content,
                "breathing_data": {"type": "body_scan", "body_part": instructions[min(state.relaxation_cycles_completed - 1, len(instructions) - 1)].get("body_part", "") if state.relaxation_cycles_completed > 0 and state.relaxation_cycles_completed <= len(instructions) else ""},
                "tts_params": self.TTS_PARAMS_BY_ANXIETY[state.anxiety_level],
                "state_update": _serialize_state(state),
                "next_phase": SessionPhase.RELAXATION_INDUCTION.value,
                "should_close": False
            }

        elif technique == "open_awareness":
            # 开放觉察（2A推荐，第三波CBT-ACT融合）
            script = MINDFULNESS_SCRIPTS.get("open_awareness", {})
            instructions = script.get("instructions", [])
            if state.relaxation_cycles_completed == 0:
                content = script.get("intro_script", "接下来，我们做一个不同的练习——不是聚焦，而是向一切体验敞开。")
            elif state.relaxation_cycles_completed <= len(instructions):
                idx = state.relaxation_cycles_completed - 1
                step = instructions[idx] if idx < len(instructions) else instructions[-1]
                content = step.get("guide", "现在，对一切体验保持开放的觉察...")
            else:
                content = "很好。无论刚才发生了什么——思绪纷飞或完全平静——都是完美的。这就是正念。"
            state.relaxation_cycles_completed += 1
            return {
                "response_type": "breathing",
                "content": content,
                "breathing_data": {"type": "open_awareness", "step": state.relaxation_cycles_completed},
                "tts_params": {**self.TTS_PARAMS_BY_ANXIETY[state.anxiety_level], "rate": 0.8},
                "state_update": _serialize_state(state),
                "next_phase": SessionPhase.RELAXATION_INDUCTION.value,
                "should_close": False
            }

        elif technique == "loving_kindness":
            # 慈心冥想（2B推荐，用于人际型反刍）
            script = MINDFULNESS_SCRIPTS.get("loving_kindness", {})
            instructions = script.get("instructions", [])
            if state.relaxation_cycles_completed == 0:
                content = script.get("intro_script", "如果你今晚的担忧与人际关系有关，我们做一个善意练习。准备好了吗？")
            elif state.relaxation_cycles_completed <= len(instructions):
                idx = state.relaxation_cycles_completed - 1
                step = instructions[idx] if idx < len(instructions) else instructions[-1]
                content = step.get("guide", "现在，把温暖的注意力送给自己...")
            else:
                content = "很好。你今晚已经送出了善意。现在，让自己安静下来。"
            state.relaxation_cycles_completed += 1
            return {
                "response_type": "breathing",
                "content": content,
                "breathing_data": {"type": "loving_kindness"},
                "tts_params": {**self.TTS_PARAMS_BY_ANXIETY[state.anxiety_level], "rate": 0.85},
                "state_update": _serialize_state(state),
                "next_phase": SessionPhase.RELAXATION_INDUCTION.value,
                "should_close": False
            }

        elif technique == "box_breathing":
            script = BREATHING_SCRIPTS.get("box_breathing", {})
            instructions = script.get("instructions", [])
            if state.relaxation_cycles_completed == 0:
                content = script.get("intro_script", "我们来做一个方形呼吸法。每一步4秒，像画一个正方形。准备好了吗？")
            elif state.relaxation_cycles_completed < 6:  # 默认6个循环
                phase_idx = state.relaxation_cycles_completed % 4
                phase_names = ["吸气", "屏息", "呼气", "暂停"]
                phase = instructions[phase_idx] if phase_idx < len(instructions) else instructions[0]
                content = f"{phase_names[phase_idx]}：{phase.get('physical_guide', '')}"
            else:
                content = script.get("outro_script", "很好，你已经完成了方形呼吸练习。现在，让呼吸自然进行。")
            state.relaxation_cycles_completed += 1
            return {
                "response_type": "breathing",
                "content": content,
                "breathing_data": {"type": "box_breathing", "cycle": state.relaxation_cycles_completed},
                "tts_params": self.TTS_PARAMS_BY_ANXIETY[state.anxiety_level],
                "state_update": _serialize_state(state),
                "next_phase": SessionPhase.RELAXATION_INDUCTION.value,
                "should_close": False
            }

        elif technique == "diaphragmatic":
            script = BREATHING_SCRIPTS.get("diaphragmatic", {})
            instructions = script.get("instructions", [])
            if state.relaxation_cycles_completed == 0:
                content = script.get("intro_script", "我们来学习腹式呼吸——最自然的呼吸方式。把手放在腹部，感受它的起伏。")
            elif state.relaxation_cycles_completed < 5:
                phase_idx = state.relaxation_cycles_completed % 2
                phase = instructions[phase_idx] if phase_idx < len(instructions) else instructions[0]
                content = phase.get("physical_guide", "继续呼吸...")
            else:
                content = "很好，腹式呼吸已经很自然了。现在，让呼吸变得平稳和缓慢。"
            state.relaxation_cycles_completed += 1
            return {
                "response_type": "breathing",
                "content": content,
                "breathing_data": {"type": "diaphragmatic", "cycle": state.relaxation_cycles_completed},
                "tts_params": self.TTS_PARAMS_BY_ANXIETY[state.anxiety_level],
                "state_update": _serialize_state(state),
                "next_phase": SessionPhase.RELAXATION_INDUCTION.value,
                "should_close": False
            }

        elif technique in ("pmr", "pmr_short", "pmr_tiny"):
            # 自动选择 PMR 版本
            pmr_version = technique if technique != "pmr" else self._select_pmr_version(state.anxiety_level)
            
            if pmr_version == "pmr_tiny":
                script_tiny = PMR_SCRIPTS.get("pmr_tiny", {})
                regions = script_tiny.get("regions", [])
                intro = script_tiny.get("intro_script", "我们做一个最快版本的放松。只需要90秒。躺好，开始。")
                outro = script_tiny.get("outro_script", "好。你做到了。现在，让放松的感觉继续蔓延。不需要做任何事，只需要闭眼。")
                mid = "很好。再来一轮，感受对比。"
            elif pmr_version == "pmr_short":
                script_short = PMR_SCRIPTS.get("pmr_short", {})
                regions = script_short.get("regions", [])
                intro = script_short.get("intro_script", "我们做一个3分钟的快速放松。只有5个部位。躺好，我们开始。")
                outro = script_short.get("outro_script", "很好。现在，整个人比练习前更沉更暖了。记住这个感觉。现在，让呼吸完全自然。不需要做任何事，晚安。")
                mid = script_short.get("mid_script", "很好。无论有多少放松，它都是真实的。再来一轮，感受对比。")
            else:
                # full_body（默认）
                script_full = PMR_SCRIPTS.get("full_body", {})
                regions = script_full.get("sequence", [])
                intro = script_full.get("intro_script", "我们来做一个身体扫描放松...")
                outro = "很好，全身都放松了。现在，让你的呼吸变得自然..."
                mid = "很好，继续感受这个放松的感觉..."

            if state.relaxation_cycles_completed == 0:
                content = intro
            elif state.relaxation_cycles_completed < len(regions):
                region_data = regions[state.relaxation_cycles_completed]
                content = f"现在，{region_data['tense_instruction']}"
                # 加入放松引导
                content += f"\n\n{region_data['relax_instruction']}"
            elif state.relaxation_cycles_completed == len(regions):
                content = outro
            else:
                content = "现在，让呼吸完全自然，不需要控制。你的身体已经完全沉入休息了。"

            state.relaxation_cycles_completed += 1
            return {
                "response_type": "pmr",
                "content": content,
                "pmr_version": pmr_version,
                "pmr_region": regions[state.relaxation_cycles_completed - 1].get("region", "") if state.relaxation_cycles_completed <= len(regions) else "全身",
                "tts_params": self.TTS_PARAMS_BY_ANXIETY[state.anxiety_level],
                "state_update": _serialize_state(state),
                "next_phase": SessionPhase.RELAXATION_INDUCTION.value,
                "should_close": False
            }

        else:
            content = "现在，我们一起做几个深呼吸。吸气...慢慢呼气...很好，再来一次..."
            return self._build_response("text", content, state)

    def _select_closure_variant_id(self, state: SessionState, worry_category: str = "general") -> str:
        """
        选择 15 种关闭变体之一（5模板 × 3情绪强度）
        
        选择逻辑：
        1. 反刍计数 >= 2 → rumination_break
        2. 担忧已表达并记录 → post_worry
        3. 焦虑水平 SEVERE → anxious_closure
        4. 焦虑水平 NORMAL/MILD → peaceful_closure
        5. 默认 → standard
        
        强度映射：
        - AnxietyLevel.NORMAL/MILD → light
        - AnxietyLevel.MODERATE → moderate
        - AnxietyLevel.SEVERE → severe
        """
        intensity_map = {
            AnxietyLevel.NORMAL: "light",
            AnxietyLevel.MILD: "light",
            AnxietyLevel.MODERATE: "moderate",
            AnxietyLevel.SEVERE: "severe",
        }
        intensity = intensity_map.get(state.anxiety_level, "moderate")
        
        # 模板选择
        if state.consecutive_rumination >= 2:
            ritual = "rumination_break"
        elif state.worry_expressed and state.worry_write_confirmed:
            ritual = "post_worry_closure"
        elif state.anxiety_level == AnxietyLevel.SEVERE:
            ritual = "anxious_closure"
        elif state.anxiety_level in (AnxietyLevel.NORMAL, AnxietyLevel.MILD):
            ritual = "peaceful_closure"
        else:
            ritual = "standard"
        
        variant_id = f"{ritual}_{intensity}"
        
        # 验证该变体是否存在（fallback 逻辑）
        existing_ids = [v["id"] for v in CLOSURE_VARIANTS_15]
        if variant_id not in existing_ids:
            # intensity 太低/高，找同 ritual 的 moderate fallback
            fallback_id = f"{ritual}_moderate"
            if fallback_id in existing_ids:
                variant_id = fallback_id
            else:
                variant_id = "standard_moderate"  # 全局 fallback
        
        return variant_id

    def _build_closure_from_variant(self, state: SessionState, variant_id: str) -> str:
        """从15种变体中构建关闭语，支持变量填充"""
        variant = next((v for v in CLOSURE_VARIANTS_15 if v["id"] == variant_id), None)
        if not variant:
            return self._closure_response_fallback(state)
        
        template = variant["template"]
        
        # 变量填充
        replacements = {
            "worry_topic": state.worry_topic or "一些事",
            "rumination_topic": state.worry_topic or "",
            "location": "床上",
            "next_action_time": "明天 17:00",
            "user_name": state.user_id,
        }
        
        for key, val in replacements.items():
            placeholder = "{" + key + "}"
            if placeholder in template:
                template = template.replace(placeholder, val)
        
        return template

    def _closure_response(self, state: SessionState, user_message: str, worry_category: str = "general") -> Dict[str, Any]:
        """
        关闭仪式：优先使用 15 种变体中的一种
        """
        # 1. 选择变体 ID
        variant_id = self._select_closure_variant_id(state, worry_category)
        
        # 2. 构建内容
        content = self._build_closure_from_variant(state, variant_id)
        
        # 3. 查找该变体的情绪强度，决定 TTS 参数
        variant = next((v for v in CLOSURE_VARIANTS_15 if v["id"] == variant_id), {})
        intensity = variant.get("intensity", "moderate")
        
        # SEVERE 强度：TTS 更慢，更多停顿
        if intensity == "severe":
            tts_params = {**self.TTS_PARAMS_BY_ANXIETY[AnxietyLevel.SEVERE], "pause_ms": 3000}
        elif intensity == "moderate":
            tts_params = {**self.TTS_PARAMS_BY_ANXIETY[AnxietyLevel.MODERATE], "pause_ms": 2000}
        else:
            tts_params = {**self.TTS_PARAMS_BY_ANXIETY[AnxietyLevel.NORMAL], "pause_ms": 1500}
        
        return {
            "response_type": "closure",
            "content": content,
            "closure_variant_id": variant_id,
            "closure_intensity": intensity,
            "tts_params": tts_params,
            "state_update": _serialize_state(state),
            "next_phase": SessionPhase.CLOSURE.value,
            "should_close": True
        }

    def _closure_response_fallback(self, state: SessionState) -> str:
        """静态 fallback（当变体选择失败时）"""
        template = CLOSURE_RITUALS.get("closure_rituals", {}).get("standard", {}).get("template", "")
        worry_display = state.worry_topic or "一些事"
        return template.format(worry_topic=worry_display, user_name=state.user_id, session_summary="")

    def _safety_response(self, state: SessionState) -> Dict[str, Any]:
        """安全协议响应"""
        content = (
            "我很在乎你的安全。你现在的感受听起来非常沉重。\n\n"
            "如果你有立即的危险想法，请拨打：010-82951332（全国心理援助热线）\n\n"
            "如果你愿意，可以告诉我你现在的情况。我在这里陪着你。"
        )
        
        return {
            "response_type": "safety",
            "content": content,
            "tts_params": {"rate": 0.85, "pitch": "-2st", "volume": 1.0, "pause_ms": 2000},
            "state_update": _serialize_state(state),
            "next_phase": SessionPhase.SAFETY_PROTOCOL.value,
            "should_close": False,
            "safety_trigger": True
        }

    def _assessment_response(self, state: SessionState) -> Dict[str, Any]:
        """评估阶段的响应——由 LLM 动态生成"""
        return self._build_response("text", "[assessment]", state)

    def _continue_phase_response(self, state: SessionState, user_message: str) -> Dict[str, Any]:
        """继续当前阶段的响应——由 LLM 动态生成"""
        return self._build_response("text", "[continue]", state)

    def _build_response(self, response_type: str, content: str, state: SessionState) -> Dict[str, Any]:
        """构建通用响应结构（语音参数按 response_type 覆盖焦虑等级）"""
        base_params = self.TTS_PARAMS_BY_ANXIETY.get(state.anxiety_level, self.TTS_PARAMS_BY_ANXIETY[AnxietyLevel.NORMAL]).copy()
        type_params = self.TTS_PARAMS_BY_RESPONSE_TYPE.get(response_type, {})
        style_params = self.TTS_ADJUSTMENTS_BY_USER_STYLE.get(state.user_style, {})
        tts_params = {**base_params, **type_params, **style_params}

        return {
            "response_type": response_type,
            "content": content,
            "tts_params": tts_params,
            "state_update": _serialize_state(state),
            "next_phase": state.phase.value,
            "should_close": False
        }

    PHASE_INSTRUCTIONS = {
        "assessment": "当前阶段：评估。任务：1）根据用户具体描述确认感受，把情绪客体化，不评判；2）给选择权；3）不出现'我'，禁止'没关系'/'不用硬撑'。禁止重复用户的词开头。整体不超过40字。",
        "worry_capture": "当前阶段：担忧捕获。任务：1）像朋友一样继续聊，了解用户的具体感受；2）不要直接说'记下来了'或'已记录'，而是自然地回应用户的情绪；3）给用户提供选择权。可以用'我'。不超过40字。",
        "cognitive_restructuring": "当前阶段：认知重构。任务：用1-2句沉稳的问句松动灾难化思维，不急于纠正。不出现'我'，不评判。禁止重复用户的词开头。整体不超过40字。",
        "relaxation_induction": "当前阶段：放松引导。任务：简短引导把注意力放到呼吸或身体上，身体导向。不出现'我'。不超过40字。",
        "closure": "当前阶段：结束仪式。任务：简短确认身体放松了，然后自然说晚安。不出现'我'。不超过40字。",
        "safety_protocol": "当前阶段：安全协议。任务：平静地给出全国心理援助热线 010-82951332，24小时。不超过40字。",
    }

    # ── 用户风格（Persona）动态指令 ───────────────────────────
    # ── 用户风格（Persona）动态指令 ───────────────────────────
    # ── 用户风格（Persona）动态指令 ───────────────────────────
    PERSONA_INSTRUCTIONS_BY_STYLE = {
        UserStyle.HIGHLY_ANXIOUS: "\n【用户风格：高度焦虑】回复极短（≤15字），每句后停顿，优先呼吸引导，用安全感确认代替分析。禁止追问'为什么'。",
        UserStyle.VENTING: "\n【用户风格：倾诉型】倾听为主，不打断，反馈简短（如'嗯'、'我在听'），适时用问句引导说出具体感受。",
        UserStyle.ANALYTICAL: '\n【用户风格：分析型】用结构化表达，分步骤引导，多用苏格拉底式问句，不直接给答案。',
        UserStyle.AVOIDANT: '\n【用户风格：回避型】不直接问情绪和感受，从身体感觉或环境聊起，迂回切入，降低压力。',
        UserStyle.NORMAL: '',
    }

    def get_cbt_system_prompt(self, user_id: str, session_id: str, phase: str = None, profile: Dict = None) -> str:
        """获取用于 LLM 的系统提示词（含用户上下文、阶段指令、关系深度）"""
        state = self.get_or_create_session(user_id, session_id)

        context_addition = ""
        if state.last_topic:
            context_addition += f"\n[用户背景] 近日常见担忧领域：{state.last_topic}。"
        if state.triggers:
            top_triggers = sorted(state.triggers.items(), key=lambda x: -x[1])[:3]
            triggers_str = "、".join([f"{k}({v}次)" for k, v in top_triggers])
            context_addition += f"担忧频率：{triggers_str}。"
        
        # ── 信念链暴露给 RAG / LLM ───────────────────────────
        # 将用户在担忧捕获阶段表达的逻辑链暴露给后续阶段，增强连续性
        if state.logical_chain and len(state.logical_chain) >= 2:
            chain_summary = " → ".join(state.logical_chain[-3:])  # 最近3条
            context_addition += f"\n[信念链] 用户担忧逻辑：{chain_summary}。回应时可适度引用用户自己的逻辑。"

        phase_instruction = ""
        if phase:
            phase_instruction = f"\n[阶段指令] {self.PHASE_INSTRUCTIONS.get(phase, '')}"

        persona_instruction = self.PERSONA_INSTRUCTIONS_BY_STYLE.get(state.user_style, "")
        
        # ── 关系深度动态语气调整 ───────────────────────────
        relationship_instruction = ""
        if profile:
            depth = profile.get("relationship_depth", 0)
            if depth == 1:
                relationship_instruction = "\n【关系阶段：初识】保持专业克制，不假设用户历史，语气沉稳但有距离感。"
            elif 2 <= depth <= 3:
                relationship_instruction = "\n【关系阶段：熟悉】可以适度自然，像一位了解对方的朋友，但仍保持专业边界。"
            elif 4 <= depth <= 9:
                relationship_instruction = "\n【关系阶段：信任】语气可以更放松，适度提及之前的进展或共同经历过的技术，增强连续性。"
            elif depth >= 10:
                relationship_instruction = "\n【关系阶段：深度】像老朋友一样陪伴，自然提及用户的历史偏好和有效技术，但不过度侵入。"
        
        return self.CBT_SYSTEM_PROMPT_V2 + context_addition + phase_instruction + persona_instruction + relationship_instruction
    def reset_session(self, user_id: str, session_id: str) -> None:
        """重置会话状态"""
        key = f"{user_id}:{session_id}"
        if key in self._sessions:
            del self._sessions[key]


def _serialize_state(state: SessionState) -> Dict[str, Any]:
    """将 SessionState 序列化为可 JSON 序列化的字典"""
    return {
        "user_id": state.user_id,
        "session_id": state.session_id,
        "phase": state.phase.value,
        "anxiety_level": state.anxiety_level.value,
        "worry_topic": state.worry_topic,
        "worry_expressed": state.worry_expressed,
        "worry_write_confirmed": state.worry_write_confirmed,
        "detected_distortion_id": state.detected_distortion_id,
        "relaxation_technique": state.relaxation_technique,
        "relaxation_cycles_completed": state.relaxation_cycles_completed,
        "turns_in_phase": state.turns_in_phase,
        "total_turns": state.total_turns,
        "consecutive_rumination": state.consecutive_rumination,
        "emotional_momentum": state.emotional_momentum.value if isinstance(state.emotional_momentum, EmotionalMomentum) else state.emotional_momentum,
        "user_style": state.user_style.value if isinstance(state.user_style, UserStyle) else state.user_style,
        "detected_scenario": state.detected_scenario,
        "last_topic": state.last_topic,
    }


# ============ L3: 理解性共情 - 信念链推理 ============

class BeliefChainInferrer:
    """
    理解性共情：推理用户话语背后的"为什么"
    
    不只是识别"什么情绪"，而是推断"为什么会有这个情绪"
    例如："汇报搞砸我就完了" → 推理出信念链：
      汇报差 → 领导否定 → 年终奖少/被裁 → 生活崩盘
    """
    
    # 信念映射模板（场景 → 深层信念）
    BELIEF_TEMPLATES = {
        "work": {
            "汇报/演讲": {
                "if_patterns": ["汇报", "演讲", "presentation"],
                "inferred_beliefs": [
                    "表现差 = 我能力不行",
                    "被否定 = 我不够好",
                    "领导失望 = 我会失去机会",
                    "搞砸 = 后果无法挽回"
                ],
                "core_fear": "被评价为无能",
                "socratic_probes": [
                    "你说的'完了'具体是指什么？",
                    "如果这次真的搞砸了，你最担心会发生什么？",
                    "以前有没有遇到过类似的情况，后来怎么样了？"
                ]
            },
            "面试": {
                "if_patterns": ["面试", "找工作"],
                "inferred_beliefs": [
                    "面试失败 = 我不够优秀",
                    "被拒绝 = 我再也好不了了",
                    "表现不好 = 机会就没了"
                ],
                "core_fear": "自我价值被否定",
                "socratic_probes": [
                    "如果这次面试没过，你心里先想到的是什么？",
                    "一次面试的结果，能定义你整个人吗？"
                ]
            },
            "KPI/考核": {
                "if_patterns": ["KPI", "考核", "绩效", "评分"],
                "inferred_beliefs": [
                    "KPI不达标 = 我不够努力/不够好",
                    "评分低 = 我被定性了",
                    "完不成 = 会被淘汰"
                ],
                "core_fear": "被归类为'不够好'",
                "socratic_probes": [
                    "KPI没完成，真的代表你不够好吗？",
                    "你有没有过虽然KPI没完成，但还是被认可的时期？"
                ]
            }
        },
        "relationship": {
            "吵架/冲突": {
                "if_patterns": ["吵架", "争吵", "冲突", "闹矛盾"],
                "inferred_beliefs": [
                    "吵架 = 这段关系要完了",
                    "对方生气 = 他不要我了",
                    "我说了不该说的话 = 我搞砸了",
                    "冷暴力 = 我被惩罚/被抛弃"
                ],
                "core_fear": "关系破裂 / 被抛弃",
                "socratic_probes": [
                    "以前吵过架吗，后来怎么样了？",
                    "吵架一定意味着关系会断吗？"
                ]
            },
            "分手/失恋": {
                "if_patterns": ["分手", "失恋", "离婚", "离开"],
                "inferred_beliefs": [
                    "分手 = 我不够好才被甩",
                    "被分手 = 我没有价值了",
                    "再也找不到 = 我会孤独终老"
                ],
                "core_fear": "自我价值崩塌",
                "socratic_probes": [
                    "一段关系的结束，真的能定义你的全部价值吗？",
                    "身边有没有分手后反而过得更好的人？"
                ]
            }
        },
        "health": {
            "身体症状": {
                "if_patterns": ["头疼", "胸闷", "心脏", "指标异常", "体检"],
                "inferred_beliefs": [
                    "身体有症状 = 我得了大病",
                    "检查结果不好 = 我的人生完了",
                    "身体出问题 = 我无法控制"
                ],
                "core_fear": "疾病 / 失去控制",
                "socratic_probes": [
                    "身体偶尔有点不舒服，一定意味着大问题吗？",
                    "你有没有过体检有点小问题，后来没什么事的情况？"
                ]
            }
        }
    }
    
    @classmethod
    def infer_belief_chain(cls, user_message: str, scenario: str, history: List[Dict]) -> Dict[str, Any]:
        """
        从用户消息推断深层信念链
        Returns: {
            "has_inference": bool,
            "scenario_key": str,  # e.g. "汇报/演讲"
            "core_fear": str,
            "inferred_beliefs": List[str],
            "socratic_probes": List[str],
            "current_belief": str,  # 用户当前表达的信念
        }
        """
        text_lower = user_message.lower()
        
        if scenario not in cls.BELIEF_TEMPLATES:
            return {"has_inference": False}
        
        scenario_templates = cls.BELIEF_TEMPLATES.get(scenario, {})
        
        for topic_key, template in scenario_templates.items():
            for pattern in template.get("if_patterns", []):
                if pattern in text_lower:
                    return {
                        "has_inference": True,
                        "scenario_key": topic_key,
                        "core_fear": template.get("core_fear", ""),
                        "inferred_beliefs": template.get("inferred_beliefs", []),
                        "socratic_probes": template.get("socratic_probes", []),
                        "current_belief": cls._extract_current_belief(user_message),
                    }
        
        return {"has_inference": False}
    
    @classmethod
    def _extract_current_belief(cls, text: str) -> str:
        """从用户输入中提取当前表达的信念句式"""
        # 提取 "X就是Y" / "X等于Y" / "X就完了" 等句式
        patterns = [
            r'(.+?)就是(.+?)了',
            r'(.+?)等于(.+?)',
            r'如果(.+?)就(.+?)',
            r'(.+?)就完了',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        return text[:50]  # fallback


# ============ L3: 心理教育嵌入 ============

class PsychoeducationManager:
    """
    心理教育时机管理
    
    在对话自然停顿点，插入不超过1句话的科普内容
    时机：phase 转换时 / 担忧处理完成后 / 放松诱导前
    """
    
    # 心理教育内容库（按触发话题）
    CONTENT = {
        "sleep_hygiene_alcohol": {
            "triggers": ["酒", "喝酒", "红酒", "白酒", "啤酒"],
            "condition": "用户提到睡前饮酒",
            "content": "酒精其实会破获睡眠结构，REM（快速眼动期）会变少。",
            "insertion_point": "worry_capture_done",
            "max_length": 30
        },
        "sleep_hygiene_caffeine": {
            "triggers": ["咖啡", "茶", "奶茶", "可乐"],
            "condition": "用户提到下午/晚上喝咖啡",
            "content": "咖啡因半衰期约5-6小时，下午3点后喝会影响入睡。",
            "insertion_point": "worry_capture_done",
            "max_length": 30
        },
        "sleep_hygiene_nap": {
            "triggers": ["午睡", "小睡", "下午睡", "白天睡"],
            "condition": "用户提到白天小睡",
            "content": "下午3点后小睡会削弱睡眠压力，让晚上更难睡。",
            "insertion_point": "worry_capture_done",
            "max_length": 30
        },
        "sleep_hygiene_weekend_sleep": {
            "triggers": ["周末补觉", "周末多睡", "补觉"],
            "condition": "用户提到周末补觉",
            "content": "周末补觉会打乱生物钟，建议每天同一时间起床。",
            "insertion_point": "worry_capture_done",
            "max_length": 30
        },
        "stimulus_control_20min": {
            "triggers": ["睡不着", "一直醒", "睡不去"],
            "condition": "躺床超过20分钟未入睡",
            "content": "睡不着时，起身去别的房间做无聊的事，等困了再回来。",
            "insertion_point": "relaxation_induction_start",
            "max_length": 30
        },
        "sleep_effort": {
            "triggers": ["努力睡", "强迫自己睡", "一定要睡着"],
            "condition": "用户表现出睡眠努力",
            "content": "越'努力'入睡，反而越睡不着。睡眠不是需要赢得的奖杯。",
            "insertion_point": "worry_capture_done",
            "max_length": 30
        },
        "catastrophic_thinking": {
            "triggers": ["完了", "彻底完蛋", "一切完蛋"],
            "condition": "检测到灾难化思维",
            "content": "失眠时大脑会放大负面事件的概率，这叫'灾难化思维'。",
            "insertion_point": "cognitive_restructure",
            "max_length": 30
        },
    }
    
    @classmethod
    def should_insert(cls, user_message: str, last_phase: SessionPhase, 
                     current_phase: SessionPhase, detected_distortion: Optional[str]) -> Tuple[bool, Optional[str]]:
        """
        判断是否应该插入心理教育内容
        
        插入时机：
        1. worry_capture 完成 → 进入下一个 phase 时
        2. 检测到特定认知扭曲时
        3. 放松诱导开始前
        
        Returns: (should_insert, content_key)
        """
        text_lower = user_message.lower()
        
        # 时机1：担忧捕获完成，转换到放松
        if last_phase == SessionPhase.WORRY_CAPTURE and current_phase == SessionPhase.RELAXATION_INDUCTION:
            for key, item in cls.CONTENT.items():
                if any(trigger in text_lower for trigger in item["triggers"]):
                    if item["insertion_point"] == "worry_capture_done":
                        return True, key
        
        # 时机2：进入认知重构时
        if current_phase == SessionPhase.COGNITIVE_RESTRUCTURING and detected_distortion:
            if detected_distortion in ["catastrophizing", "all_or_nothing"]:
                for key, item in cls.CONTENT.items():
                    if item["insertion_point"] == "cognitive_restructure":
                        return True, key
        
        # 时机3：放松诱导开始前
        if last_phase in [SessionPhase.ASSESSMENT, SessionPhase.WORRY_CAPTURE] and current_phase == SessionPhase.RELAXATION_INDUCTION:
            for key, item in cls.CONTENT.items():
                if any(trigger in text_lower for trigger in item["triggers"]):
                    if item["insertion_point"] == "relaxation_induction_start":
                        return True, key
        
        return False, None
    
    @classmethod
    def get_content(cls, content_key: str) -> Optional[str]:
        """获取心理教育内容"""
        item = cls.CONTENT.get(content_key)
        if not item:
            return None
        return item.get("content", "")[:item.get("max_length", 30)]


# ============ L4: 用户心理档案管理器 ============

class UserProfileManager:
    """
    用户心理档案：跨会话积累，Redis 持久化
    
    档案结构：
    user_profile:{user_id} = {
        worry_type_distribution: Dict[str, float],  # 担忧类型比例
        dominant_distortion: str,                    # 最常见认知扭曲
        avg_anxiety_recovery_turns: float,            # 平均焦虑消退轮数
        most_effective_technique: str,              # 最有效放松技术
        technique_effectiveness_history: Dict[str, List[float]],  # 技术有效性历史
        risk_signals: List[Dict],                    # 高风险信号历史
        total_sessions: int,
        avg_session_turns: float,
        last_session_date: str,
        consecutive_negative_sessions: int,           # 连续无效会话数
        sleep_quality_trend: List[float],            # 最近睡眠质量评分序列
    }
    """
    
    PROFILE_KEY = "user_profile:{user_id}"
    
    def __init__(self, redis_client=None):
        self._redis = redis_client
    
    def set_redis(self, redis_client):
        self._redis = redis_client
    
    async def load_profile(self, user_id: str) -> Dict[str, Any]:
        """从 Redis 加载用户档案"""
        if not self._redis:
            return self._default_profile(user_id)
        try:
            import json as _json
            key = self.PROFILE_KEY.format(user_id=user_id)
            data = await asyncio.to_thread(self._redis.get, key)
            if data:
                profile = _json.loads(data)
                return profile
            return self._default_profile(user_id)
        except Exception as e:
            return self._default_profile(user_id)
    
    async def save_profile(self, user_id: str, profile: Dict[str, Any]) -> None:
        """保存用户档案到 Redis"""
        if not self._redis:
            return
        try:
            import json as _json
            key = self.PROFILE_KEY.format(user_id=user_id)
            await asyncio.to_thread(self._redis.set, key, _json.dumps(profile, ensure_ascii=False), ex=86400 * 90)  # 90天过期
        except Exception:
            pass
    
    def _default_profile(self, user_id: str) -> Dict[str, Any]:
        return {
            "user_id": user_id,
            "worry_type_distribution": {},  # {work: 0.7, relationship: 0.2, ...}
            "dominant_distortion": "",
            "avg_anxiety_recovery_turns": 0.0,
            "most_effective_technique": "478",
            "technique_effectiveness_history": {},  # {pmr_short: [5.0, 4.0, ...], ...}
            "risk_signals": [],
            "total_sessions": 0,
            "avg_session_turns": 0.0,
            "last_session_date": "",
            "consecutive_negative_sessions": 0,
            "sleep_quality_trend": [],
            "preferred_voice": "female_warm",  # 音色偏好: female_warm | male_calm | female_young
            "relationship_depth": 0,  # 关系深度：累计会话次数
            "session_turns_history": [],  # 最近会话轮数历史（用于依赖度趋势分析）
        }
    

    async def set_voice_preference(self, user_id: str, voice: str) -> bool:
        """设置用户音色偏好，返回是否成功"""
        valid_voices = {"female_warm", "male_calm", "female_young"}
        if voice not in valid_voices:
            return False
        profile = await self.load_profile(user_id)
        profile["preferred_voice"] = voice
        await self.save_profile(user_id, profile)
        return True
    async def update_after_session(self, user_id: str, session_summary: Dict[str, Any]) -> None:
        """
        会话结束后更新用户档案
        
        session_summary 包含：
          - worry_type: str (本次主要担忧类型)
          - detected_distortion: str (本次认知扭曲)
          - technique_used: str (使用的放松技术)
          - anxiety_recovery_turns: int (焦虑消退用了几轮)
          - effectiveness_score: float (技术有效性 1-5)
          - emotional_momentum: str (IMPROVING/STABLE/DETERIORATING)
          - slept_well: Optional[bool] (晨间打卡，异步)
        """
        profile = await self.load_profile(user_id)
        
        # 更新担忧类型分布
        worry_type = session_summary.get("worry_type", "unknown")
        dist = profile.get("worry_type_distribution", {})
        total = sum(dist.values()) + 1
        dist[worry_type] = dist.get(worry_type, 0) + 1
        for k in dist:
            dist[k] = dist[k] / total
        profile["worry_type_distribution"] = dist
        
        # 更新最常见认知扭曲
        distortion = session_summary.get("detected_distortion", "")
        if distortion:
            profile["dominant_distortion"] = distortion
        
        # 更新平均焦虑消退轮数
        recovery_turns = session_summary.get("anxiety_recovery_turns", 0)
        total_sessions = profile.get("total_sessions", 0)
        current_avg = profile.get("avg_anxiety_recovery_turns", 0.0)
        profile["avg_anxiety_recovery_turns"] = (
            (current_avg * total_sessions + recovery_turns) / (total_sessions + 1)
        )
        
        # 更新技术有效性
        technique = session_summary.get("technique_used", "")
        score = session_summary.get("effectiveness_score", 3.0)
        if technique and score:
            history = profile.get("technique_effectiveness_history", {})
            if technique not in history:
                history[technique] = []
            history[technique] = (history[technique] + [score])[-10:]  # 保留最近10次
            profile["technique_effectiveness_history"] = history
            # 计算最有效技术
            avg_scores = {k: sum(v) / len(v) for k, v in history.items() if v}
            if avg_scores:
                profile["most_effective_technique"] = max(avg_scores, key=avg_scores.get)
        
        # 更新连续无效会话计数
        momentum = session_summary.get("emotional_momentum", "STABLE")
        if momentum == "DETERIORATING":
            profile["consecutive_negative_sessions"] = profile.get("consecutive_negative_sessions", 0) + 1
        else:
            profile["consecutive_negative_sessions"] = 0
        
        # 更新会话统计
        total_s = profile.get("total_sessions", 0) + 1
        profile["total_sessions"] = total_s
        turns = session_summary.get("total_turns", 0)
        current_avg_turns = profile.get("avg_session_turns", 0.0)
        profile["avg_session_turns"] = (
            (current_avg_turns * (total_s - 1) + turns) / total_s
        )
        profile["last_session_date"] = session_summary.get("date", "")
        
        # 更新关系深度（累计会话次数）
        profile["relationship_depth"] = total_s
        
        # 记录会话轮数历史（保留最近10次，用于依赖度趋势分析）
        turns_history = profile.get("session_turns_history", [])
        turns_history.append(turns)
        profile["session_turns_history"] = turns_history[-10:]
        
        await self.save_profile(user_id, profile)
    
    async def get_profile(self, user_id: str) -> Dict[str, Any]:
        """获取用户档案"""
        return await self.load_profile(user_id)
    
    async def get_recommended_technique(self, user_id: str) -> str:
        """获取该用户最有效的放松技术"""
        profile = await self.load_profile(user_id)
        return profile.get("most_effective_technique", "478")


# ============ L4: 风险预测 ============

class RiskPredictor:
    """
    风险预测：识别需要人工介入的信号
    
    监控维度：
    1. 连续会话同类担忧上升
    2. 情绪曲线持续恶化
    3. 安全协议触发频率上升
    4. 用户主动表达需要专业帮助
    """
    
    # 风险阈值
    CONSECUTIVE_NEGATIVE_SESSIONS_THRESHOLD = 3  # 连续3次无效会话
    RISING_WORRY_SAME_TYPE_THRESHOLD = 3          # 同一担忧类型出现3次
    SAFETY_TRIGGER_THRESHOLD = 2                  # 2次安全协议触发
    
    @classmethod
    async def assess_risk(cls, user_id: str, profile_manager: UserProfileManager) -> Dict[str, Any]:
        """
        评估用户当前风险等级
        
        Returns: {
            "risk_level": "low" | "medium" | "high",
            "risk_signals": List[str],  # 触发风险的具体信号
            "recommended_action": str,   # 建议动作
            "professional_referral": bool,  # 是否推荐专业资源
        }
        """
        profile = await profile_manager.load_profile(user_id)
        risk_signals = []
        
        # 信号1：连续无效会话
        consecutive_neg = profile.get("consecutive_negative_sessions", 0)
        if consecutive_neg >= cls.CONSECUTIVE_NEGATIVE_SESSIONS_THRESHOLD:
            risk_signals.append(f"连续{consecutive_neg}次会话情绪未改善")
        
        # 信号2：同一担忧类型频繁出现
        worry_dist = profile.get("worry_type_distribution", {})
        for worry_type, ratio in worry_dist.items():
            if worry_type not in ["unknown", "general"] and ratio > 0.5:
                # 同类担忧占比超过50%，且历史记录够多
                if profile.get("total_sessions", 0) >= 3:
                    risk_signals.append(f"{worry_type}类担忧持续占比过高（{ratio:.0%}）")
        
        # 信号3：最常见扭曲是高危类型
        dominant_distortion = profile.get("dominant_distortion", "")
        high_risk_distortions = ["personalization", "catastrophizing"]
        if dominant_distortion in high_risk_distortions:
            if profile.get("total_sessions", 0) >= 2:
                risk_signals.append(f"频繁出现高风险认知扭曲：{dominant_distortion}")
        
        # 信号4：风险信号历史
        risk_history = profile.get("risk_signals", [])
        recent_risks = [r for r in risk_history if r.get("date", "") > ""][-3:]
        if len(recent_risks) >= 2:
            risk_signals.append(f"近期已有{len(recent_risks)}次风险预警")
        
        # 风险等级判断
        risk_level = "low"
        professional_referral = False
        
        if len(risk_signals) >= 3 or consecutive_neg >= 4:
            risk_level = "high"
            professional_referral = True
        elif len(risk_signals) >= 1:
            risk_level = "medium"
        
        recommended_action = {
            "low": "继续当前对话策略",
            "medium": "在关闭仪式中温和建议专业资源",
            "high": "主动推荐专业心理援助渠道"
        }.get(risk_level, "继续当前对话策略")
        
        return {
            "risk_level": risk_level,
            "risk_signals": risk_signals,
            "recommended_action": recommended_action,
            "professional_referral": professional_referral,
        }
    
    @classmethod
    async def should_refer_professional(cls, user_id: str, profile_manager: UserProfileManager) -> Tuple[bool, Optional[str]]:
        """
        判断是否应该推荐专业资源
        
        Returns: (should_refer, referral_message)
        """
        assessment = await cls.assess_risk(user_id, profile_manager)
        
        if assessment["professional_referral"]:
            referral_messages = [
                "我注意到你最近几周经常因为{topic}睡不着，要不要考虑和专业心理老师聊一次？",
                "如果觉得一直走不出来，找专业心理咨询师聊一次会很有帮助。",
                "如果这个担忧已经持续很久，让你很困扰，找专业老师聊聊会是个好选择。",
            ]
            import random
            msg = random.choice(referral_messages)
            return True, msg
        
        return False, None
    
    # ── 结构化转介流程（替代简单消息拼接）─────────────────────
    REFERRAL_RESOURCES = [
        {"name": "全国心理援助热线", "contact": "010-82951332", "hours": "24小时", "type": "crisis"},
        {"name": "北京回龙观医院危机干预", "contact": "010-82951332", "hours": "24小时", "type": "crisis"},
        {"name": "简单心理", "contact": "https://www.jiandanxinli.com", "hours": "预约制", "type": "platform"},
        {"name": "壹心理", "contact": "https://www.xinli001.com", "hours": "预约制", "type": "platform"},
    ]
    
    @classmethod
    async def trigger_referral(cls, user_id: str, profile_manager: UserProfileManager) -> Dict[str, Any]:
        """
        触发结构化转介流程
        
        区分"温和建议"和"主动转介"，包含资源列表和运营通知标记。
        
        Returns: {
            "triggered": bool,           # 是否触发转介
            "referral_type": str,        # "none" | "gentle_suggestion" | "active_referral"
            "referral_message": str,     # 给用户的话术
            "referral_resources": List[Dict],  # 推荐资源列表
            "should_notify_admin": bool, # 是否通知运营人工介入
            "reason": str,               # 转介原因说明
        }
        """
        assessment = await cls.assess_risk(user_id, profile_manager)
        risk_level = assessment.get("risk_level", "low")
        risk_signals = assessment.get("risk_signals", [])
        
        result = {
            "triggered": False,
            "referral_type": "none",
            "referral_message": "",
            "referral_resources": [],
            "should_notify_admin": False,
            "reason": "",
        }
        
        if risk_level == "low":
            return result
        
        if risk_level == "high":
            # 主动转介：提供危机资源 + 通知运营
            result["triggered"] = True
            result["referral_type"] = "active_referral"
            result["referral_message"] = (
                "我注意到你最近情绪状态让人有些担心。"
                "如果你愿意，可以拨打全国心理援助热线 010-82951332（24小时），"
                "或者找专业心理咨询师聊聊。你不需要一个人扛着。"
            )
            result["referral_resources"] = [r for r in cls.REFERRAL_RESOURCES if r["type"] == "crisis"]
            result["should_notify_admin"] = True
            result["reason"] = "；".join(risk_signals) if risk_signals else "高风险信号触发"
            
        elif risk_level == "medium":
            # 温和建议：只提供平台资源，不通知运营
            result["triggered"] = True
            result["referral_type"] = "gentle_suggestion"
            result["referral_message"] = (
                "如果这个困扰持续影响你的睡眠，可以考虑和专业心理咨询师聊聊，"
                "他们会有更系统的方法帮你。"
            )
            result["referral_resources"] = [r for r in cls.REFERRAL_RESOURCES if r["type"] == "platform"]
            result["should_notify_admin"] = False
            result["reason"] = "；".join(risk_signals) if risk_signals else "中等风险信号"
        
        # 记录风险信号到档案
        await cls.record_risk_signal(
            user_id, profile_manager,
            signal_type=result["referral_type"],
            details=result["reason"]
        )
        
        return result
    
    @classmethod
    async def record_risk_signal(cls, user_id: str, profile_manager: UserProfileManager,
                                  signal_type: str, details: str = "") -> None:
        """记录一次风险信号"""
        profile = await profile_manager.load_profile(user_id)
        risk_signals = profile.get("risk_signals", [])
        risk_signals.append({
            "date": time.strftime("%Y-%m-%d"),
            "type": signal_type,
            "details": details,
        })
        # 只保留最近10条
        risk_signals = risk_signals[-10:]
        profile["risk_signals"] = risk_signals
        await profile_manager.save_profile(user_id, profile)


# ============ 全局实例 ============
cbt_manager = CBTManager()
user_profile_manager = UserProfileManager()
