"""
情感分析模块（规则 + LLM 辅助）
阶段1：规则匹配 + Minimax LLM 辅助分析
阶段2：BERT 微调（待训练）
"""
import json
import os
from typing import Optional, Dict, List, Any
from dataclasses import dataclass

@dataclass
class EmotionResult:
    primary: str          # 主情绪: anxiety/sadness/anger/frustration/neutral
    intensity: int        # 强度 1-5
    level: str            # mild/moderate/severe
    confidence: float     # 置信度 0-1
    risk_flag: str        # CONTINUE / CONTINUE_WITH_CARE / IMMEDIATE_SAFETY
    worry_domains: List[str]  # 担忧领域
    cognitive_distortions: List[str]  # 认知扭曲信号
    suicide_risk: float   # 自杀风险 0-1

class EmotionAnalyzer:
    """情感分析器（规则基线 + LLM 增强）"""
    
    def __init__(self, corpus_path: str = None):
        self.corpus = self._load_corpus(corpus_path)
        self.emotion_keywords = self.corpus.get("emotion_categories", {})
        self.worry_domains = self.corpus.get("worry_domains", {})
        self.cognitive_signals = self.corpus.get("cognitive_distortion_signals", {})
        
    def _load_corpus(self, path: str = None) -> dict:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        # 默认空结构
        return {"emotion_categories": {}, "worry_domains": {}, "cognitive_distortion_signals": {}}
    
    # 分级危机关键词库
    CRISIS_KEYWORDS = {
        "suicide": {
            "high": ["想死", "不想活了", "活着没意思", "死了算了", "自杀", "结束生命", "了结自己", "没有活下去的理由"],
            "medium": ["活不下去", "撑不下去了", "死了更好", "不想存在", "消失", "离开这个世界"],
            "low": ["没意思", "没劲", "好累", "想休息", "不想面对"],
        },
        "self_harm": {
            "high": ["自残", "割腕", "跳楼", "上吊", "服毒", "烧自己"],
            "medium": ["伤害自己", "打自己", "掐自己", "撞墙", "划伤"],
            "low": ["想疼一下", "想流血", "想感受疼痛"],
        },
        "violence": {
            "high": ["杀人", "想杀人", "同归于尽", "报复", "毁灭"],
            "medium": ["想打人", "想砸东西", "控制不住暴力", "想报复"],
            "low": ["好烦", "想发泄", "想吵架"],
        },
        "acute_psychosis": {
            "high": ["幻听", "幻视", "被监视", "被控制", "脑子不是自己的", "有人在脑子里说话"],
            "medium": ["感觉不真实", "解离", "和现实脱节", "恍恍惚惚"],
            "low": ["奇怪的感觉", "不对劲", "说不出的怪"],
        },
        "child_abuse": {
            "high": ["虐待孩子", "打孩子", "性侵", "猥亵", "儿童色情"],
            "medium": ["家庭暴力", "家暴", "打老婆", "打老公", "虐老"],
            "low": ["孩子害怕", "不敢回家", "家里很可怕"],
        },
    }

    def _detect_crisis(self, text: str) -> Dict[str, Any]:
        """分级危机检测：返回危机类型、等级、分数"""
        max_level = "none"  # none / low / medium / high
        max_score = 0
        detected_types = []
        for crisis_type, levels in self.CRISIS_KEYWORDS.items():
            for level, kws in levels.items():
                score = sum(1 for kw in kws if kw in text)
                if score > 0:
                    detected_types.append(crisis_type)
                    level_score = {"low": 1, "medium": 2, "high": 3}.get(level, 0) * score
                    if level_score > max_score:
                        max_score = level_score
                        max_level = level
        return {
            "level": max_level,
            "score": min(max_score * 0.15, 1.0),
            "types": list(set(detected_types)),
        }

    def analyze(self, text: str) -> EmotionResult:
        """分析文本情绪"""
        text_lower = text.lower()
        
        # 1. 分级危机检测（最高优先级）
        crisis = self._detect_crisis(text)
        suicide_risk = crisis["score"]
        
        # 2. 情绪分类和强度
        primary = "neutral"
        intensity = 1
        level = "mild"
        risk_flag = "CONTINUE"
        max_score = 0
        
        for emotion, config in self.emotion_keywords.items():
            if emotion == "anxiety":
                for lvl, cfg in config.items():
                    if not isinstance(cfg, dict):
                        continue
                    kws = cfg.get("keywords", [])
                    score = sum(2 if kw in text else 0 for kw in kws)
                    if score > max_score:
                        max_score = score
                        primary = "anxiety"
                        level = lvl.replace("level_", "")
                        risk_flag = cfg.get("recommended_action", "CONTINUE")
                        intensity = {"mild": 2, "moderate": 3, "severe": 5}.get(level, 2)
            else:
                # sadness, anger, frustration
                for lvl in ["mild", "moderate", "severe"]:
                    kws = config.get(lvl, [])
                    score = sum(2 if kw in text else 0 for kw in kws)
                    if score > max_score:
                        max_score = score
                        primary = emotion
                        level = lvl
                        intensity = {"mild": 2, "moderate": 3, "severe": 5}.get(lvl, 2)
                        actions = config.get("recommended_action_by_level", {})
                        risk_flag = actions.get(lvl, "CONTINUE")
        
        # 3. 担忧领域检测
        worry_domains = []
        for domain, kws in self.worry_domains.items():
            if any(kw in text for kw in kws):
                worry_domains.append(domain)
        
        # 4. 认知扭曲检测
        cognitive_distortions = []
        for distortion, kws in self.cognitive_signals.items():
            if any(kw in text for kw in kws):
                cognitive_distortions.append(distortion)
        
        # 5. 危机风险覆盖（分级）
        if crisis["level"] == "high":
            risk_flag = "IMMEDIATE_SAFETY"
            if primary == "neutral":
                primary = "sadness"
                level = "severe"
                intensity = 5
        elif crisis["level"] == "medium":
            if risk_flag not in ["IMMEDIATE_SAFETY"]:
                risk_flag = "CONTINUE_WITH_CARE"
            if level in ["mild", "moderate"]:
                level = "moderate"
                intensity = max(intensity, 3)
        elif crisis["level"] == "low":
            if level == "mild":
                level = "moderate"
                intensity = max(intensity, 2)
        
        confidence = min(max_score / 6, 1.0) if max_score > 0 else 0.3
        
        return EmotionResult(
            primary=primary,
            intensity=intensity,
            level=level,
            confidence=confidence,
            risk_flag=risk_flag,
            worry_domains=worry_domains,
            cognitive_distortions=cognitive_distortions,
            suicide_risk=suicide_risk
        )
    
    def to_dict(self, result: EmotionResult) -> dict:
        return {
            "primary": result.primary,
            "intensity": result.intensity,
            "level": result.level,
            "confidence": round(result.confidence, 2),
            "risk_flag": result.risk_flag,
            "worry_domains": result.worry_domains,
            "cognitive_distortions": result.cognitive_distortions,
            "suicide_risk": round(result.suicide_risk, 2)
        }


# 全局实例（单例）
_emotion_analyzer: Optional[EmotionAnalyzer] = None

def get_emotion_analyzer(corpus_path: str = None) -> EmotionAnalyzer:
    global _emotion_analyzer
    if _emotion_analyzer is None:
        # 尝试找到语料文件
        if corpus_path is None:
            candidates = [
                "/home/ubuntu/anmian/corpus/emotion_keywords.json",
                "./corpus/emotion_keywords.json",
                "../corpus/emotion_keywords.json",
            ]
            for c in candidates:
                if os.path.exists(c):
                    corpus_path = c
                    break
        _emotion_analyzer = EmotionAnalyzer(corpus_path)
    return _emotion_analyzer
