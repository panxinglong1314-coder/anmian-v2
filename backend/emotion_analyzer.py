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
    continuous_anxiety_score: float = 5.0  # 连续焦虑分数 0-10，LLM辅助时可更高精度
    suicide_risk: float = 0.0  # 自杀风险 0-1

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
    
    def analyze(self, text: str) -> EmotionResult:
        """分析文本情绪"""
        text_lower = text.lower()
        
        # 1. 自杀/自伤风险检测（最高优先级）
        suicide_keywords = ["想死", "不想活了", "活着没意思", "死了算了", "自杀", "自残", "活不下去"]
        suicide_score = sum(1 for kw in suicide_keywords if kw in text)
        suicide_risk = min(suicide_score * 0.3, 1.0)
        
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
        
        # 5. 自杀风险覆盖
        if suicide_risk > 0.5:
            risk_flag = "IMMEDIATE_SAFETY"
            if primary == "neutral":
                primary = "sadness"
                level = "severe"
                intensity = 5
        
        confidence = min(max_score / 6, 1.0) if max_score > 0 else 0.3
        # 连续焦虑分数
        continuous_score = self.get_continuous_anxiety_score(text)
        
        return EmotionResult(
            primary=primary,
            intensity=intensity,
            level=level,
            confidence=confidence,
            risk_flag=risk_flag,
            worry_domains=worry_domains,
            cognitive_distortions=cognitive_distortions,
            suicide_risk=suicide_risk,
            continuous_anxiety_score=continuous_score
        )
    
    def get_continuous_anxiety_score(self, text: str) -> float:
        """
        返回连续焦虑评分 0-10。
        基于关键词加权 + LLM辅助（如有）综合计算。
        比 analyze().intensity (1-5离散) 更精细。
        """
        text_lower = text.lower()
        base_score = 5.0  # 默认中性

        # 强焦虑词（权重高）
        high_anxiety = [
            ("非常害怕", 2.0), ("特别担心", 1.8), ("睡不着", 1.5),
            ("一直想", 1.5), ("脑子停不下来", 1.5), ("焦虑到", 2.0),
            ("很紧张", 1.2), ("心慌", 1.5), ("害怕睡着", 1.8),
            ("反复担心", 1.3), ("灾难化", 2.0), ("控制不住", 1.5),
        ]
        # 情绪缓和词（减分）
        calming = [
            ("放松", -0.8), ("好多了", -1.5), ("不担心了", -1.5),
            ("感觉好些", -1.2), ("平静", -1.0), ("安心", -1.2),
            ("不那么焦虑", -1.3), ("现在好点了", -1.2),
        ]
        # 自杀/自伤风险词（直接拉满）
        crisis = [
            "想死", "不想活了", "活着没意思", "死了算了", "自杀", "自残"
        ]

        score = base_score
        for kw, weight in high_anxiety:
            if kw in text_lower:
                score += weight
        for kw, weight in calming:
            if kw in text_lower:
                score += weight
        for kw in crisis:
            if kw in text_lower:
                score = 10.0
                break
        return max(0.0, min(10.0, round(score, 1)))

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
