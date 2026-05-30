"""
关系深化:用户档案 prompt 块构造(中英)。

从 main.py 抽出来,避免测试时拉起整个 FastAPI app 的副作用(static mount 等)。
"""
from datetime import datetime
from typing import Optional


# Worry domain → 中文标签
DOMAIN_LABELS_ZH = {
    "work": "工作压力",
    "relationship": "人际关系",
    "health": "健康担忧",
    "finance": "财务压力",
    "study": "学业压力",
    "family": "家庭关系",
    "general": "其他",
}

# Worry domain → 英文标签(v2.4 EN 关系深化)
DOMAIN_LABELS_EN = {
    "work": "work stress",
    "relationship": "relationships",
    "health": "health worry",
    "finance": "money pressure",
    "study": "school stress",
    "family": "family",
    "general": "other",
}


def label_domain(domain: str, locale: str = "zh") -> str:
    if locale == "en":
        return DOMAIN_LABELS_EN.get(domain, domain)
    return DOMAIN_LABELS_ZH.get(domain, domain)


def _build_user_profile_block_zh(memory: dict) -> str:
    triggers = memory.get("triggers", {}) or {}
    session_count = int(memory.get("session_count", 0))
    last_summary = memory.get("last_session_summary", "")
    last_time = memory.get("last_session_time", "")
    insomnia_subtype = memory.get("insomnia_subtype", "")

    if session_count < 1 and not triggers and not last_summary:
        return ""

    lines = ["", "[用户档案 — 仅供你了解，不要直接重复出来]"]

    if session_count >= 5:
        depth = f"老熟人，已陪伴 {session_count} 个夜晚"
    elif session_count >= 2:
        depth = f"第 {session_count + 1} 次见面"
    elif session_count == 1:
        depth = "第二次见面"
    else:
        depth = "首次见面"
    lines.append(f"- 关系深度：{depth}")

    if triggers:
        top3 = sorted(triggers.items(), key=lambda kv: -kv[1])[:3]
        concerns_str = "、".join(f"{label_domain(k, 'zh')}({v} 次)" for k, v in top3)
        lines.append(f"- 主要担忧领域：{concerns_str}")

    if insomnia_subtype:
        subtype_label = {
            "sleep_onset": "入睡困难型",
            "sleep_maintenance": "维持困难型",
            "early_morning": "早醒型",
            "mixed": "混合型",
        }.get(insomnia_subtype, insomnia_subtype)
        lines.append(f"- 失眠亚型：{subtype_label}")

    if last_summary:
        rel = "前不久"
        if last_time:
            try:
                dt = datetime.fromisoformat(last_time)
                days_ago = (datetime.now() - dt).days
                if days_ago == 0:
                    rel = "今天早些时候"
                elif days_ago == 1:
                    rel = "昨晚"
                elif days_ago < 7:
                    rel = f"{days_ago} 天前"
                elif days_ago < 30:
                    rel = f"{days_ago // 7} 周前"
                else:
                    rel = "之前"
            except Exception:
                pass
        lines.append(f"- 上次会话（{rel}）：{last_summary}")

    lines.append("")
    lines.append("[使用提示]")
    if last_summary and session_count >= 1:
        lines.append("- 你是一位认识用户的睡前陪伴师，请像老朋友重逢一样自然带出对上次的轻盈回访。")
        lines.append("- 推荐的开场（在用户首句较短或泛泛时）：「今晚怎么样，上次说的那件事 / 上次提到的 XX，有没有再让你难受？」")
        lines.append("- 不要机械复述「上次」二字，关键词换成抽象的呼应（例如说「汇报的事」而不是「被裁的担心」，让用户感到被记得，但不被审视）。")
    elif triggers:
        top_label = label_domain(sorted(triggers.items(), key=lambda kv: -kv[1])[0][0], "zh")
        lines.append(f"- 用户最常因「{top_label}」失眠；当前消息若涉及类似话题，自然呼应。")
    lines.append("- 严禁直接念出这份档案的字段、数字或原文。当作内部记忆使用。")

    return "\n".join(lines)


def _build_user_profile_block_en(memory: dict) -> str:
    triggers = memory.get("triggers", {}) or {}
    session_count = int(memory.get("session_count", 0))
    last_summary = memory.get("last_session_summary", "")
    last_time = memory.get("last_session_time", "")
    insomnia_subtype = memory.get("insomnia_subtype", "")

    if session_count < 1 and not triggers and not last_summary:
        return ""

    lines = ["", "[User profile — internal context only, never recite verbatim]"]

    if session_count >= 5:
        depth = f"a familiar regular — {session_count} bedtime visits together"
    elif session_count >= 2:
        depth = f"visit #{session_count + 1}"
    elif session_count == 1:
        depth = "second time meeting"
    else:
        depth = "first time"
    lines.append(f"- Relationship: {depth}")

    if triggers:
        top3 = sorted(triggers.items(), key=lambda kv: -kv[1])[:3]
        concerns_str = ", ".join(
            f"{label_domain(k, 'en')} (x{v})" for k, v in top3
        )
        lines.append(f"- Recurring worry domains: {concerns_str}")

    if insomnia_subtype:
        subtype_label = {
            "sleep_onset": "sleep-onset difficulty",
            "sleep_maintenance": "sleep-maintenance difficulty",
            "early_morning": "early-morning awakening",
            "mixed": "mixed type",
        }.get(insomnia_subtype, insomnia_subtype)
        lines.append(f"- Insomnia subtype: {subtype_label}")

    if last_summary:
        rel = "recently"
        if last_time:
            try:
                dt = datetime.fromisoformat(last_time)
                days_ago = (datetime.now() - dt).days
                if days_ago == 0:
                    rel = "earlier today"
                elif days_ago == 1:
                    rel = "last night"
                elif days_ago < 7:
                    rel = f"{days_ago} days ago"
                elif days_ago < 30:
                    weeks = days_ago // 7
                    rel = f"{weeks} week{'s' if weeks > 1 else ''} ago"
                else:
                    rel = "a while back"
            except Exception:
                pass
        lines.append(f"- Last session ({rel}): {last_summary}")

    lines.append("")
    lines.append("[How to use]")
    if last_summary and session_count >= 1:
        lines.append("- You're a bedtime companion they already know. Open like an old friend who remembers — gentle, not investigative.")
        lines.append("- Suggested opening (when their first message is brief or vague): 'How's tonight? Still on your mind, that thing you mentioned?' — keep it light.")
        lines.append("- Don't mechanically say 'last time' — paraphrase abstractly (say 'the presentation thing' instead of 'getting laid off'). Make them feel remembered, not surveilled.")
    elif triggers:
        top_label = label_domain(sorted(triggers.items(), key=lambda kv: -kv[1])[0][0], "en")
        lines.append(f"- This user most often loses sleep over {top_label}; if tonight's message touches anything similar, echo it gently.")
    lines.append("- NEVER quote this card's fields, numbers, or original text. Use it as internal memory only.")

    return "\n".join(lines)


def build_user_profile_block(memory: dict, locale: str = "zh") -> str:
    """
    构建结构化用户档案 prompt 块（供 system prompt 注入）。
    设计原则：让 LLM 看到的是「人」（"老朋友 4 次会话，主要担工作"），
    而不是裸短语（"我担心被裁(1次)"）。
    v2.4: locale='en' 时输出英文版本,英文用户也能感受到被记得。
    """
    if not memory:
        return ""
    if locale == "en":
        return _build_user_profile_block_en(memory)
    return _build_user_profile_block_zh(memory)
