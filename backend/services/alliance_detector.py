"""
治疗联盟信号检测（Bordin task-agreement 的工程化）。

用于 cbt_manager 状态机:在进入"工作阶段"(WORRY_CAPTURE / RELAXATION_INDUCTION)
之前,判断用户是否已明确表达了愿意,避免技术先于关系。

不替代 LLM 的语义判断,只做关键词层的快速门禁,失败侧偏向"不推进"。
"""
from __future__ import annotations
from typing import Dict, Any


# 明确同意/愿意的短语
CONSENT_PHRASES = (
    "想试", "试试", "试一下", "试一试",
    "我想", "我愿意", "可以", "好的", "好",
    "教我", "帮我", "陪我", "带我",
    "想做", "想聊", "想说", "想知道", "想了解",
    "走一遍", "走一步", "开始吧", "来吧",
    "我需要", "需要你",
)

# 明确拒绝/不愿意
DECLINE_PHRASES = (
    "不想说", "不想聊", "不想做", "不想试",
    "不要", "不用", "不需要",
    "不知道说什么", "没什么好说", "算了",
    "现在不", "等会再", "等一下",
    "别问", "别说", "别管",
)

# 仅是社交填充/未提供实质内容
FILLER_ONLY = (
    "嗯", "嗯嗯", "啊", "哦", "唉", "唔",
    "好", "行", "对",
    "在", "在的", "在呢",
    "你好", "hi", "hello",
)


def _norm(msg: str) -> str:
    return (msg or "").strip().lower()


def user_signals_decline(msg: str) -> bool:
    """用户明确表示不想 / 拒绝。命中即应阻止推进。"""
    t = _norm(msg)
    return any(p in t for p in DECLINE_PHRASES)


def user_signals_consent(msg: str) -> bool:
    """用户明确表示愿意/想做。命中可作为强推进信号。"""
    t = _norm(msg)
    if user_signals_decline(t):
        return False
    return any(p in t for p in CONSENT_PHRASES)


def user_is_filler_only(msg: str) -> bool:
    """用户的消息只是社交填充,没有实质内容。"""
    t = _norm(msg).rstrip("。.!?！？～~ ")
    if not t:
        return True
    # 全是填充词、且总长极短
    if len(t) <= 3 and any(t == f or t.startswith(f) for f in FILLER_ONLY):
        return True
    return False


def user_substantive_content(msg: str, min_chars: int = 5) -> bool:
    """用户给出了实质内容(超过最短长度且不是纯填充)。"""
    if not msg:
        return False
    if user_is_filler_only(msg):
        return False
    return len(msg.strip()) >= min_chars


def alliance_state(msg: str) -> Dict[str, Any]:
    """打包返回一个状态字典,供状态机一次调用拿到所有信号。"""
    return {
        "consent": user_signals_consent(msg),
        "decline": user_signals_decline(msg),
        "filler_only": user_is_filler_only(msg),
        "substantive": user_substantive_content(msg),
    }
