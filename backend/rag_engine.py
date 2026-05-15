"""
RAG 引擎 — L2 检索增强生成（PageIndex + LSA Fallback 版）
知眠: 用 LLM reasoning 导航 + LSA 兜底
"""
import json
from typing import Dict, Any, List, Optional
from functools import lru_cache

try:
    from page_index.page_index_engine import get_engine as _get_page_index_engine
    _PAGE_INDEX_AVAILABLE = True
except ImportError:
    _PAGE_INDEX_AVAILABLE = False

# LSA fallback (hybrid_rag)
try:
    from hybrid_rag_index import hybrid_rag
    _LSA_AVAILABLE = True
except ImportError:
    _LSA_AVAILABLE = False

# session_logger 延迟导入
_session_logger = None


def _get_session_logger():
    global _session_logger
    if _session_logger is None:
        try:
            from session_logger import session_logger as _sl
            _session_logger = _sl
        except ImportError:
            _session_logger = None
    return _session_logger


# 兼容旧接口
rag_index = hybrid_rag if _LSA_AVAILABLE else None

# RAG 缓存（5分钟 TTL）
_RAG_CACHE: Dict[str, tuple] = {}
_CACHE_TTL = 300

# ── PageIndex Engine 单例 ────────────────────────────────────────────────────

_page_engine = None


def _get_engine():
    global _page_engine
    if _page_engine is None and _PAGE_INDEX_AVAILABLE:
        from pathlib import Path
        corpus_dir = Path("/home/ubuntu/anmian/corpus")
        tree_cache = Path("/home/ubuntu/anmian/backend/vector_index/page_tree.json")
        _page_engine = _get_page_index_engine(corpus_dir=corpus_dir, tree_cache_path=tree_cache)
    return _page_engine


# ── 初始化 ─────────────────────────────────────────────────────────────────

def build_rag_index(force: bool = False):
    """构建 RAG 索引（启动时调用一次）"""
    engine = _get_engine()
    if engine:
        engine.load_or_build_tree(force_rebuild=force)


def init_rag():
    """启动时初始化 RAG 索引"""
    engine = _get_engine()
    if engine:
        try:
            engine.load_or_build_tree()
            print(f"[RAG] ✅ PageIndex 引擎已就绪")
        except Exception as e:
            print(f"[RAG] ⚠️ PageIndex 加载失败: {e}")
            if _LSA_AVAILABLE:
                hybrid_rag.load()
                print(f"[RAG] ⚠️  回退到 LSA 检索")
    else:
        if _LSA_AVAILABLE:
            if hybrid_rag.load():
                print(f"[RAG] ⚠️ PageIndex 不可用，LSA 加载成功")
            else:
                hybrid_rag.build_index()


# ── PageIndex 导航检索 ────────────────────────────────────────────────────

def _page_index_retrieve(
    query: str,
    ctx: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """用 PageIndex LLM 推理导航检索"""
    engine = _get_engine()
    if not engine:
        return {"selected_nodes": [], "fallback_results": [], "source": "unavailable"}

    return engine.navigate(
        query=query,
        ctx=ctx or {},
        top_k=5,
    )


def _format_page_index_result(result: Dict[str, Any]) -> str:
    """将 PageIndex 结果格式化为文本（供注入 system prompt）"""
    parts = []
    parts.append("【PageIndex 检索结果】")
    parts.append(f"来源: {result['source']}")

    ctx = result.get("ctx", {})
    parts.append(f"焦虑: {ctx.get('anxiety_level','?')} | 阶段: {ctx.get('phase','?')}")

    if result["selected_nodes"]:
        parts.append("\n── 相关 CBT 节点 ──")
        for node in result["selected_nodes"]:
            parts.append(f"[{node.node_id}] {node.title}")
            if node.summary:
                parts.append(f"  摘要: {node.summary[:120]}")
            if node.text:
                text = node.text[:500]
                parts.append(f"  正文: {text}")

    if result.get("fallback_results"):
        parts.append("\n── LSA Fallback ──")
        for r in result["fallback_results"][:3]:
            chunk = r.get("chunk", {})
            parts.append(f"  [{chunk.get('source','?')}] {r.get('text','')[:200]}")

    return "\n".join(parts)


# ── 主检索入口 ────────────────────────────────────────────────────────────

def enhance_cbt_response(
    user_message: str,
    session_context: Dict[str, Any],
    cbt_state: Dict[str, Any]
) -> str:
    """用 PageIndex + LSA 检索增强 CBT 系统指令"""
    ctx = {
        "anxiety_level": cbt_state.get("anxiety_level", 5),
        "phase": cbt_state.get("phase", "assessment"),
        "insomnia_subtype": session_context.get("insomnia_subtype", "mixed"),
    }

    cache_key = f"{user_message[:40]}:{ctx['phase']}:{ctx['anxiety_level']}"
    now = __import__('time').time()
    if cache_key in _RAG_CACHE:
        cached_ts, cached_result = _RAG_CACHE[cache_key]
        if now - cached_ts < _CACHE_TTL:
            return cached_result

    result = _page_index_retrieve(user_message, ctx=ctx)
    formatted = _format_page_index_result(result)

    if len(result.get("selected_nodes", [])) < 5 and _LSA_AVAILABLE:
        lsa_results = hybrid_rag.retrieve(query=user_message, top_k=5 - len(result.get("selected_nodes", [])))
        if lsa_results:
            formatted += "\n\n── LSA Fallback 补充 ──"
            for r in lsa_results:
                formatted += f"\n[{r.get('chunk',{}).get('source','?')}] {r.get('text','')[:200]}"

    _RAG_CACHE[cache_key] = (now, formatted)
    return formatted


def get_relevant_closure_template(
    scenario_id: str,
    anxiety_level: int,
    phase: str
) -> Optional[Dict[str, Any]]:
    """根据场景+焦虑等级获取最匹配的关闭仪式模板"""
    intensity = "severe" if anxiety_level >= 7 else ("moderate" if anxiety_level >= 4 else "light")
    combined_query = f"{scenario_id} {phase} {intensity} 关闭仪式"

    result = _page_index_retrieve(combined_query, ctx={"anxiety_level": anxiety_level, "phase": phase, "insomnia_subtype": "mixed"})

    for node in result.get("selected_nodes", []):
        meta = node.metadata or {}
        if meta.get("type") in ("standard_template", "variant") and meta.get("intensity") in (intensity, "all", None):
            return {"node": node, "text": node.text}

    if _LSA_AVAILABLE:
        lsa_results = hybrid_rag.retrieve(query=combined_query, top_k=10)
        for r in lsa_results:
            if r.get("chunk", {}).get("source") == "closure_rituals":
                return r
    return None


def get_technique_guidance(
    technique: str,
    user_message: str,
    anxiety_level: int
) -> Optional[str]:
    """获取特定 CBT 技术的引导文本"""
    type_to_source = {
        "pmr": "pmr_scripts", "body_scan": "pmr_scripts",
        "breathing": "breathing_scripts", "478": "breathing_scripts",
        "cognitive_restructuring": "cognitive_distortions",
        "worry_externalization": "worry_scenarios",
        "paradoxical_intention": "breathing_scripts",
        "loving_kindness": "pmr_scripts", "open_awareness": "pmr_scripts",
    }
    source = type_to_source.get(technique.lower())
    if not source:
        return None

    result = _page_index_retrieve(user_message, ctx={"anxiety_level": anxiety_level, "phase": "relaxation", "insomnia_subtype": "mixed"})

    for node in result.get("selected_nodes", []):
        if node.source_file and source in node.source_file:
            return node.text[:600]

    return None


# ── 会话日志增强 ─────────────────────────────────────────────────────────

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
    sl = _get_session_logger()
    if not sl:
        return

    if not scenario_id:
        result = _page_index_retrieve(user_message, ctx={"anxiety_level": cbt_state.get("anxiety_level", 5), "phase": "worry_capture", "insomnia_subtype": "mixed"})
        for node in result.get("selected_nodes", []):
            sid = (node.metadata or {}).get("scenario_id")
            if sid:
                scenario_id = sid
                break

    sl.add_turn(role="user", content=user_message,
                anxiety_level=cbt_state.get("anxiety_level"),
                scenario_id=scenario_id, technique_used=None,
                user_id=user_id, session_id=session_id)
    sl.add_turn(role="assistant", content=assistant_response,
                anxiety_level=cbt_state.get("anxiety_level"),
                scenario_id=scenario_id, technique_used=technique_used,
                user_id=user_id, session_id=session_id)


def finalize_session(outcome: str = "completed", sleep_quality: Optional[int] = None, rating: Optional[int] = None):
    sl = _get_session_logger()
    if sl:
        sl.end_session(outcome=outcome, sleep_quality=sleep_quality, rating=rating)


# ── RAG 个性化系统提示 ─────────────────────────────────────────────────────

def _anxiety_desc(level) -> str:
    """兼容 int (0-10) / str ("normal"/"mild"/etc) / AnxietyLevel enum value"""
    if isinstance(level, str):
        _smap = {"normal": 0, "mild": 2, "moderate": 5, "severe": 8,
                 "AnxietyLevel.NORMAL": 0, "AnxietyLevel.MILD": 2,
                 "AnxietyLevel.MODERATE": 5, "AnxietyLevel.SEVERE": 8}
        if level in _smap:
            level = _smap[level]
        else:
            try: level = int(level)
            except (TypeError, ValueError): level = 0
    if level >= 8: return "重度焦虑，需要大量安全感和沉稳陪伴"
    elif level >= 5: return "中度焦虑，需要被确认和温柔转移"
    elif level >= 2: return "轻度焦虑，只需要简洁引导和信任"
    return "很平静，只需要简单陪伴"


def _phase_desc(phase: str) -> str:
    return {
        "assessment": "评估阶段——先了解用户今晚状态",
        "worry_capture": "担忧捕获阶段——帮用户说出/写下担忧，然后立即转移",
        "cognitive": "认知重构阶段——用温柔问句松动灾难化思维",
        "relaxation": "放松诱导阶段——引导注意力到呼吸或身体",
        "closure": "关闭仪式阶段——温柔收尾，确认安全感，说晚安",
        "normal_chat": "自然闲聊",
        "safety": "安全协议——冷静，提供热线资源",
    }.get(phase, "自然流动")


def _insomnia_desc(subtype: str) -> str:
    return {
        "sleep_onset": "入睡困难型——越努力越清醒，适合矛盾意向法",
        "sleep_maintenance": "睡眠维持型——半夜易醒，适合正念身体扫描",
        "mixed": "混合型",
        "social_rumination": "社交反刍型——反复复盘人际关系，适合慈心冥想",
    }.get(subtype, "一般失眠")


def build_rag_system_prompt(
    user_id: str,
    session_context: Dict[str, Any],
    current_phase: str,
    user_message: str,
    anxiety_level: int = 5,
    user_style: str = "NORMAL"
) -> str:
    """构建 PageIndex 增强的 RAG 标签提示"""
    cache_key = f"{user_message[:40]}:{current_phase}:{anxiety_level}:{user_style}"
    now = __import__('time').time()
    if cache_key in _RAG_CACHE:
        cached_ts, cached_result = _RAG_CACHE[cache_key]
        if now - cached_ts < _CACHE_TTL:
            return cached_result

    result = _page_index_retrieve(
        user_message,
        ctx={
            "anxiety_level": anxiety_level,
            "phase": current_phase,
            "insomnia_subtype": session_context.get("insomnia_subtype", "mixed")
        }
    )

    lines = []
    lines.append("[RAG 参考——以下标签和话术示例供你学习风格，严禁直接复述给用户]")

    style_map = {
        "HIGHLY_ANXIOUS": "高度焦虑——极短回复，安全感确认，优先呼吸引导",
        "VENTING": "倾诉型——倾听为主，不打断，适时引导说出感受",
        "ANALYTICAL": "分析型——结构化表达，苏格拉底式问句",
        "AVOIDANT": "回避型——不直接问情绪，从身体/环境聊起",
        "NORMAL": "正常风格——自然对话即可",
    }
    lines.append(f"用户风格: {style_map.get(user_style, user_style)}")

    state_parts = [f"焦虑等级: {_anxiety_desc(anxiety_level)}"]
    if session_context.get("last_topic"):
        state_parts.append(f"历史话题: {session_context['last_topic']}")
    subtype = session_context.get("insomnia_subtype", "mixed")
    if subtype != "mixed":
        state_parts.append(f"失眠类型: {_insomnia_desc(subtype)}")
    lines.append(" | ".join(state_parts))

    selected = result.get("selected_nodes", [])
    if selected:
        lines.append(f"\n推荐 CBT 节点 ({len(selected)} 个):")
        for node in selected[:5]:
            tech = (node.metadata or {}).get("recommended_techniques", {})
            primary = tech.get("primary", "") if isinstance(tech, dict) else ""
            lines.append(f"  [{node.node_id}] {node.title} (摘要: {node.summary[:80] if node.summary else '无'})")

    phase_strategy = {
        "assessment": "先简短确认状态，再问今晚感觉。",
        "worry_capture": "确认感受，帮说出担忧，立即转移。",
        "cognitive": "用问句轻轻松动，不评判。",
        "relaxation": "把注意力拉到呼吸或身体，不解释原因。",
        "closure": "温柔收尾，确认放下，说晚安。",
        "normal_chat": "像朋友一样简短回应。",
        "safety": "冷静、不评判，提供热线资源。",
    }
    lines.append(f"\n当前阶段: {current_phase} | 策略: {phase_strategy.get(current_phase, '自然回应')}")

    result_text = "\n".join(lines)
    _RAG_CACHE[cache_key] = (now, result_text)
    return result_text