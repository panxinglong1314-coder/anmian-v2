"""
RAG 引擎 — L2 检索增强生成（混合检索版）
MiniLM 语义 + BM25 词法 + 规则路由
知眠: 向量化语料库接入会话流程
"""
import json
from typing import Dict, Any, List, Optional

# 导入混合检索索引（单例）
from hybrid_rag_index import hybrid_rag

# session_logger 保持不变
from session_logger import session_logger

# ============ 兼容性别名（兼容旧接口）============
rag_index = hybrid_rag  # 旧代码 from vector_store import rag_index 还能用


# ============ 初始化 ============
def build_rag_index(force: bool = False):
    """构建或加载RAG索引（启动时调用一次）"""
    hybrid_rag.build_index(force=force)


def init_rag():
    """启动时初始化RAG索引"""
    try:
        if hybrid_rag.load():
            hybrid_rag._load_model()
            hybrid_rag._build_bm25()
            print(f"[RAG] ✅ 混合索引加载成功（chunks={len(hybrid_rag.chunks)}, vectors={hybrid_rag.vectors.shape}）")
        else:
            build_rag_index()
    except Exception as e:
        print(f"[RAG] ⚠️ RAG索引加载失败: {e}")


# ============ RAG 检索核心 ============
def enhance_cbt_response(
    user_message: str,
    session_context: Dict[str, Any],
    cbt_state: Dict[str, Any]
) -> str:
    """用RAG检索增强CBT系统指令

    Args:
        user_message: 用户最新消息
        session_context: Redis中的用户记忆
        cbt_state: cbt_manager当前的会话状态

    Returns:
        增强后的系统指令片段（JSON字符串）
    """
    results = hybrid_rag.retrieve_for_session(
        query=user_message,
        ctx={
            "anxiety_level": cbt_state.get("anxiety_level", 5),
            "phase": cbt_state.get("phase", "assessment"),
            "insomnia_subtype": session_context.get("insomnia_subtype", "mixed"),
        }
    )
    return json.dumps(results, ensure_ascii=False, indent=2)


def get_relevant_closure_template(
    scenario_id: str,
    anxiety_level: int,
    phase: str
) -> Optional[Dict[str, Any]]:
    """根据场景+焦虑等级获取最匹配的关闭仪式模板"""
    raw_al = anxiety_level
    if hasattr(raw_al, "value"):
        al_map = {"severe": 8, "moderate": 5, "mild": 2, "normal": 0}
        raw_al = al_map.get(raw_al.value, 5)
    try:
        anxiety = int(raw_al)
    except (TypeError, ValueError):
        anxiety = 5

    intensity = "severe" if anxiety >= 7 else ("moderate" if anxiety >= 4 else "light")
    combined_query = f"{scenario_id} {phase} {intensity} 关闭仪式"

    results = hybrid_rag.retrieve(query=combined_query, top_k=10)
    results = [r for r in results if r.get("chunk", {}).get("source") == "closure_rituals"]

    best = None
    for r in results:
        if r.get("chunk", {}).get("intensity") in (intensity, "all", None):
            best = r
            break
    if not best and results:
        best = results[0]
    return best


def get_technique_guidance(
    technique: str,
    user_message: str,
    anxiety_level: int
) -> Optional[str]:
    """获取特定CBT技术的引导文本"""
    type_to_source = {
        "pmr": "pmr_scripts",
        "body_scan": "pmr_scripts",
        "breathing": "breathing_scripts",
        "478": "breathing_scripts",
        "cognitive_restructuring": "cognitive_distortions",
        "worry_externalization": "worry_scenarios",
        "paradoxical_intention": "breathing_scripts",
        "loving_kindness": "pmr_scripts",
        "open_awareness": "pmr_scripts",
    }
    source = type_to_source.get(technique.lower())
    if not source:
        return None

    results = hybrid_rag.retrieve(query=user_message, top_k=5)
    for r in results:
        if r.get("chunk", {}).get("source") == source:
            return r.get("text", "")
    return None


# ============ 会话日志增强 ==========
def log_cbt_turn_with_rag(
    user_message: str,
    assistant_response: str,
    technique_used: str,
    cbt_state: Dict[str, Any],
    session_context: Dict[str, Any],
    scenario_id: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
):
    """记录一轮CBT对话，自动推断场景并记录"""
    if not scenario_id:
        results = hybrid_rag.retrieve(query=user_message, top_k=3)
        for r in results:
            sid = r.get("chunk", {}).get("scenario_id")
            if sid:
                scenario_id = sid
                break

    session_logger.add_turn(
        role="user",
        content=user_message,
        anxiety_level=cbt_state.get("anxiety_level"),
        scenario_id=scenario_id,
        technique_used=None,
        user_id=user_id,
        session_id=session_id,
    )
    session_logger.add_turn(
        role="assistant",
        content=assistant_response,
        anxiety_level=cbt_state.get("anxiety_level"),
        scenario_id=scenario_id,
        technique_used=technique_used,
        user_id=user_id,
        session_id=session_id,
    )


def finalize_session(
    outcome: str = "completed",
    sleep_quality: Optional[int] = None,
    rating: Optional[int] = None
):
    session_logger.end_session(outcome=outcome, sleep_quality=sleep_quality, rating=rating)


# ============ RAG 个性化系统提示（给千问的角色提示） ==========
def _anxiety_desc(level: int) -> str:
    if level >= 8:
        return "重度焦虑，情绪很满，需要大量的安全感和沉稳的陪伴"
    elif level >= 5:
        return "中度焦虑，有一些残余的担忧，需要被确认和温柔转移"
    elif level >= 2:
        return "轻度焦虑，已经比较平静，只需要简洁的引导和信任"
    return "很平静，只需要简单的陪伴和收尾"


def _phase_desc(phase: str) -> str:
    mapping = {
        "assessment": "评估阶段——先了解用户今晚的状态，不要太快给建议",
        "worry_capture": "担忧捕获阶段——帮用户把具体担忧说出来/写下来，然后立即转移",
        "cognitive": "认知重构阶段——用温柔的问句松动用户的灾难化思维，不直接指出扭曲",
        "relaxation": "放松诱导阶段——引导用户把注意力转移到呼吸或身体上",
        "closure": "关闭仪式阶段——给今晚一个温柔的收尾，确认安全感，说晚安",
        "normal_chat": "自然闲聊——像朋友一样陪伴",
        "safety": "安全协议——冷静、不评判，提供热线资源",
    }
    return mapping.get(phase, "根据对话自然流动")


def _insomnia_desc(subtype: str) -> str:
    mapping = {
        "sleep_onset": "入睡困难型——越努力入睡越清醒，适合矛盾意向法",
        "sleep_maintenance": "睡眠维持型——容易半夜醒来，适合正念身体扫描",
        "mixed": "混合型——兼顾入睡和维持问题",
        "social_rumination": "社交反刍型——反复复盘人际关系，适合慈心冥想",
    }
    return mapping.get(subtype, "一般失眠")


def _technique_desc(tech: str) -> str:
    mapping = {
        "paradoxical_intention": "矛盾意向法——告诉用户'不要努力入睡，只是躺着休息'",
        "cognitive_restructuring": "认知重构——用问句轻轻松动，不说'你错了'",
        "body_scan": "正念身体扫描——从脚到头，只是觉察",
        "loving_kindness": "慈心冥想——把对抗变成善意",
        "open_awareness": "开放觉察——向一切体验敞开",
        "478": "4-7-8呼吸——吸气4秒，屏息7秒，呼气8秒",
        "pmr_short": "PMR短版放松——3分钟，5个部位",
        "pmr_tiny": "PMR微版放松——90秒，2个部位，急性焦虑用",
    }
    return mapping.get(tech, tech)


def build_rag_system_prompt(
    user_id: str,
    session_context: Dict[str, Any],
    current_phase: str,
    user_message: str,
    anxiety_level: int = 5
) -> str:
    """
    构建极简 RAG 标签提示。
    只输出核心策略标签，严禁包含任何示例话术、脚本原文或诗意描述。
    """
    rag_results = hybrid_rag.retrieve_for_session(
        query=user_message,
        ctx={
            "anxiety_level": anxiety_level,
            "phase": current_phase,
            "insomnia_subtype": session_context.get("insomnia_subtype", "mixed")
        }
    )

    scenario_id = None
    scenario_results = rag_results.get("worry_scenarios", [])
    if scenario_results:
        scenario_id = scenario_results[0].get("scenario_id")

    lines = []
    lines.append("[RAG 内部标签——仅作策略参考，严禁复述给用户]")

    state_tags = [f"焦虑等级: {_anxiety_desc(anxiety_level)}"]
    if session_context.get("last_topic"):
        state_tags.append(f"历史话题: {session_context['last_topic']}")
    subtype = session_context.get("insomnia_subtype", "mixed")
    if subtype != "mixed":
        state_tags.append(f"失眠类型: {_insomnia_desc(subtype)}")
    lines.append(" | ".join(state_tags))

    if scenario_results:
        techs = scenario_results[0].get("chunk", {}).get("recommended_techniques", {})
        primary = techs.get("primary", "relaxation") if isinstance(techs, dict) else "relaxation"
        lines.append(f"推荐技术: {_technique_desc(primary)}")

    phase_strategy = {
        "assessment": "先简短确认用户状态，再问今晚感觉。",
        "worry_capture": "确认感受，帮用户说出担忧，立即转移。",
        "cognitive": "用问句轻轻松动灾难化思维，不评判。",
        "relaxation": "直接把注意力拉到呼吸或身体，不解释原因。",
        "closure": "温柔收尾，确认放下，说晚安。",
        "normal_chat": "像朋友一样简短回应。",
        "safety": "冷静、不评判，提供热线资源。",
    }
    lines.append(f"当前阶段: {current_phase} | 策略: {phase_strategy.get(current_phase, '自然回应')}")

    return "\n".join(lines)