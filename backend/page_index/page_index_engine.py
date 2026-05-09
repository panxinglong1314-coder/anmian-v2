"""
PageIndex Engine — LLM 推理导航引擎
知眠: 用 LLM reasoning 遍历 page_index_tree，在语料库中找最相关的 CBT 片段。
Leaf fallback: hybrid_rag_index 的 LSA 检索。
"""

import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from .page_index_tree import PageNode, NodeKind, CorpusTreeBuilder, load_tree

# ── LLM 调用（MiniMax Text-01）───────────────────────────────────────────────

def _call_minimax(prompt: str, system: str = "", timeout: int = 30) -> str:
    """调用 MiniMax /v1/text/chat/completions（RPA 000 签名模式）"""
    import os, httpx

    api_key = os.getenv("MINIMAX_API_KEY", "")
    if not api_key:
        return '{"error":"MINIMAX_API_KEY not set"}'

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "MiniMax-M2.7",
        "messages": (
            [{"role": "system", "content": system}] if system else []
        ) + [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 12000,
        "stream": False,
    }
    try:
        with httpx.Client(timeout=max(timeout, 300)) as client:
            resp = client.post(
                "https://api.minimaxi.com/v1/chat/completions",
                headers=headers,
                json=payload,
            )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Tree Summarizer — 对非叶子节点补充 LLM summary ─────────────────────────

_SUMMARIZE_PROMPT = """你是一个专业的 CBT-I 睡眠治疗师助手。
请为下面这个{kind}节点生成一个简洁的中文摘要（50字以内），
供后续检索引擎判断该节点是否与用户查询相关。

节点标题: {title}
节点内容: {content}

直接返回摘要文字，不需要 JSON。"""


def summarize_node(node: PageNode, model: str = "MiniMax-M2.7") -> str:
    """为单个 PageNode 生成 summary（如果还没有）"""
    if node.summary and len(node.summary) > 10:
        return node.summary

    content = node.text[:500] if node.text else ""
    if not content:
        # 聚合所有子节点的 summary 作为参考
        child_summaries = [c.summary for c in node.nodes if c.summary][:5]
        content = " | ".join(child_summaries) or "(无内容)"

    prompt = _SUMMARIZE_PROMPT.format(
        kind=node.kind.value,
        title=node.title,
        content=content[:400],
    )
    try:
        resp = _call_minimax(prompt, timeout=15)
        if resp and not resp.startswith("{"):
            return resp.strip()[:200]
    except Exception:
        pass
    return node.summary or node.title


def summarize_tree_batch(
    root: PageNode,
    model: str = "MiniMax-M2.7",
    max_workers: int = 4,
) -> PageNode:
    """
    批量为树中所有非叶子节点补充 LLM summary。
    从叶子到根反向聚合：先总结子节点，再总结父节点。
    """
    def _summarize_sub(node: PageNode) -> Tuple[str, str]:
        """返回 (node_id, new_summary)"""
        if node.is_leaf():
            return node.node_id, node.summary

        child_summaries = "\n".join(
            f"- {c.node_id} {c.title}: {c.summary}"
            for c in node.nodes if c.summary
        )
        prompt = (
            f"你是一个 CBT-I 睡眠治疗师。请根据子节点摘要，"
            f"为父节点「{node.title}」生成一句中文总结（60字以内）。\n\n"
            f"子节点:\n{child_summaries or '(无子节点摘要)'}\n\n"
            f"直接返回总结文字，不超过60字："
        )
        try:
            resp = _call_minimax(prompt, timeout=20)
            new_summary = resp.strip()[:200] if resp and not resp.startswith("{") else node.summary
        except Exception:
            new_summary = node.summary or node.title
        return node.node_id, new_summary

    # 自底向上：先收集所有非叶子节点
    non_leaves = [n for n in root.walk() if not n.is_leaf()]

    # 并行总结
    node_map = {n.node_id: n for n in root.walk()}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(non_leaves))) as pool:
        futures = {pool.submit(_summarize_sub, n): n for n in non_leaves}
        for fut in as_completed(futures):
            nid, summary = fut.result()
            if nid in node_map and summary:
                node_map[nid].summary = summary

    return root


# ── Tree Navigator — LLM 推理遍历 ───────────────────────────────────────────

_TREE_NAVIGATE_PROMPT = """你是一个专业的 CBT-I 睡前焦虑陪伴 AI 的检索规划器。

你有一棵树结构表示的 CBT-I 语料库（类似"目录"），用户会问一个问题。
你的任务是：**只通过阅读树节点的标题和摘要（不需要看正文）**，
找出最可能相关的 3~5 个叶节点，输出它们的 node_id 列表。

## 树结构（缩进代表层级）
{tree_repr}

## 用户问题
{query}

## 会话上下文
- 焦虑等级: {anxiety_level} (1=平静, 5=轻度, 8=重度)
- CBT 阶段: {phase}
- 失眠类型: {insomnia_subtype}

## 输出要求（严格遵守）
直接只返回一个 JSON 对象。不要思考内容、不要解释、不要思考过程：
{{"reasoning": "简要说明", "selected_node_ids": ["0001.001.003", ...]}}

要求：
- 选 3~5 个节点
- 优先选叶子节点（kind=leaf）
- 兼顾当前焦虑等级和 CBT 阶段
- 只输出 node_id，不要其他内容
"""


def _tree_to_repr(root: PageNode, max_depth: int = 3, indent: int = 0) -> str:
    """将树渲染为缩进文本（供 LLM 阅读）"""
    pad = "  " * indent
    kind_tag = "" if root.kind == NodeKind.ROOT else f"[{root.kind.value}]"
    summary_line = f" — {root.summary[:40]}" if root.summary else ""
    lines = [f"{pad}{root.node_id} {root.title}{kind_tag}{summary_line}"]
    if indent < max_depth:
        for child in root.nodes[:10]:  # 每层最多10个child
            lines.append(_tree_to_repr(child, max_depth, indent + 1))
    return "\n".join(lines)


class PageIndexEngine:
    """
    LLM 推理导航引擎。
    流程：
        1. 加载/构建 PageNode 树
        2. 可选：对非叶子节点批量补充 LLM summary
        3. 接收用户查询 + CBT 上下文
        4. LLM 阅读树结构，选出相关 node_id
        5. 提取对应叶子节点文本
        6. LSA fallback：若叶子文本不足，用 hybrid_rag 补充
    """

    def __init__(
        self,
        corpus_dir: Optional[Path] = None,
        tree_cache_path: Optional[Path] = None,
        llm_model: str = "MiniMax-M2.7",
    ):
        self.corpus_dir = corpus_dir or Path("/home/ubuntu/anmian/corpus")
        self.tree_cache_path = tree_cache_path or Path("/home/ubuntu/anmian/backend/vector_index/page_tree.json")
        self.llm_model = llm_model
        self.root: Optional[PageNode] = None

    # ── 初始化 ──────────────────────────────────────────────────────────

    def load_or_build_tree(self, force_rebuild: bool = False) -> PageNode:
        """加载缓存树，或从语料库重建"""
        if not force_rebuild and self.tree_cache_path.exists():
            print(f"[PageIndex] 加载缓存树: {self.tree_cache_path}")
            self.root = load_tree(self.tree_cache_path)
            return self.root

        print(f"[PageIndex] 从语料库构建树: {self.corpus_dir}")
        builder = CorpusTreeBuilder(corpus_dir=self.corpus_dir)
        self.root = builder.build()

        # 批量补充 LLM summary（可选，耗时）
        # summarize_tree_batch(self.root, model=self.llm_model)

        # 保存缓存
        self.tree_cache_path.parent.mkdir(parents=True, exist_ok=True)
        from .page_index_tree import save_tree
        save_tree(self.root, self.tree_cache_path)
        return self.root

    # ── 核心检索 ────────────────────────────────────────────────────────

    def navigate(
        self,
        query: str,
        ctx: Optional[Dict[str, Any]] = None,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """
        主检索入口：LLM 推理导航 + LSA fallback。

        Args:
            query: 用户问题或消息
            ctx: CBT 会话上下文
                - anxiety_level: int 1-10
                - phase: str (assessment/worry_capture/cognitive/relaxation/closure/normal_chat/safety)
                - insomnia_subtype: str
            top_k: 返回的叶子节点数量

        Returns:
            {
                "selected_nodes": [PageNode, ...],      # LLM 选中的节点
                "fallback_results": [...],             # LSA fallback 结果
                "tree_reasoning": str,                  # LLM 的推理过程
                "source": "tree" | "tree+fallback",
            }
        """
        ctx = ctx or {}
        anxiety_level = ctx.get("anxiety_level", 5)
        phase = ctx.get("phase", "normal_chat")
        insomnia_subtype = ctx.get("insomnia_subtype", "mixed")

        if self.root is None:
            self.load_or_build_tree()

        # Step 1: 将树渲染为文本，给 LLM 看
        tree_repr = _tree_to_repr(self.root, max_depth=3)
        # 截断到 8000 字，避免 prompt 爆炸
        if len(tree_repr) > 3000:
            tree_repr = tree_repr[:3000] + "\n... (truncated)"

        # Step 2: LLM 推理选节点
        prompt = _TREE_NAVIGATE_PROMPT.format(
            tree_repr=tree_repr,
            query=query,
            anxiety_level=anxiety_level,
            phase=phase,
            insomnia_subtype=insomnia_subtype,
        )

        reasoning = ""
        selected_ids: List[str] = []

        try:
            resp = _call_minimax(prompt, timeout=240)
            resp = resp.strip()
            # 去掉 markdown 代码块
            if resp.startswith("```"):
                for line in resp.splitlines():
                    if line.startswith("```"):
                        resp = resp[resp.find("```")+3:]
                        resp = resp.lstrip()
                        break
                resp = resp.split("```")[0]
            # 从后向前找 "reasoning" → 对应的 { → 括号匹配提取完整 JSON
            reasoning_pos = resp.rfind('"reasoning"')
            if reasoning_pos < 0:
                raise ValueError("No 'reasoning' key in response")
            search_start = reasoning_pos
            prefix = resp[:search_start]
            last_open = prefix.rfind('{')
            if last_open < 0:
                raise ValueError("No opening brace found")
            json_candidate = resp[last_open:]
            depth = 0
            end_pos = 0
            for i, ch in enumerate(json_candidate):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        end_pos = i + 1
                        break
            if end_pos == 0:
                raise ValueError("Incomplete JSON - no closing brace")
            json_str = json_candidate[:end_pos]
            print(f"[PageIndex] JSON ({len(json_str)} chars): {json_str[:150]}...")
            parsed = json.loads(json_str)
            reasoning = parsed.get("reasoning", "")
            selected_ids = parsed.get("selected_node_ids", [])
        except json.JSONDecodeError as e:
            print(f"[PageIndex] LLM JSON 解析失败: {e}, raw={resp[:200]}")
        except Exception as e:
            print(f"[PageIndex] LLM 调用失败: {e}")

        # Step 3: 根据 node_id 提取叶子节点
        selected_nodes: List[PageNode] = []
        for nid in selected_ids:
            node = self.root.find_node(nid)
            if node and node.is_leaf():
                selected_nodes.append(node)

        # Step 4: 如果树导航结果少于 top_k，用 LSA 补充
        fallback_results: List[Dict[str, Any]] = []
        source = "tree"
        if len(selected_nodes) < top_k:
            source = "tree+fallback"
            try:
                from hybrid_rag_index import hybrid_rag
                lsa_results = hybrid_rag.retrieve(query=query, top_k=top_k - len(selected_nodes))
                fallback_results = lsa_results
            except ImportError:
                print("[PageIndex] hybrid_rag 不可用，纯树检索")

        return {
            "selected_nodes": selected_nodes,
            "fallback_results": fallback_results,
            "tree_reasoning": reasoning,
            "source": source,
            "ctx": ctx,
        }

    # ── 结果格式化 ─────────────────────────────────────────────────────

    def format_result(
        self,
        nav_result: Dict[str, Any],
        include_text: bool = True,
        max_text_len: int = 600,
    ) -> str:
        """将导航结果格式化为可注入 system prompt 的文本"""
        parts = []
        parts.append("【PageIndex 检索结果】")
        parts.append(f"来源: {nav_result['source']}")

        ctx = nav_result.get("ctx", {})
        parts.append(f"焦虑等级: {ctx.get('anxiety_level', '?')} | 阶段: {ctx.get('phase', '?')}")

        if nav_result["selected_nodes"]:
            parts.append("\n── 树导航相关节点 ──")
            for node in nav_result["selected_nodes"]:
                summary = node.summary or "(无摘要)"
                parts.append(f"  [{node.node_id}] {node.title}")
                parts.append(f"    摘要: {summary[:100]}")
                if include_text and node.text:
                    text = node.text[:max_text_len]
                    parts.append(f"    正文: {text}")

        if nav_result["fallback_results"]:
            parts.append("\n── LSA Fallback 补充结果 ──")
            for r in nav_result["fallback_results"][:3]:
                chunk = r.get("chunk", {})
                score = r.get("score", 0)
                text = r.get("text", "")[:200]
                parts.append(f"  [score={score}] {chunk.get('source','?')}: {text}")

        return "\n".join(parts)


# ── 单例 ────────────────────────────────────────────────────────────────────────

_engine: Optional[PageIndexEngine] = None


def get_engine(
    corpus_dir: Optional[Path] = None,
    tree_cache_path: Optional[Path] = None,
) -> PageIndexEngine:
    global _engine
    if _engine is None:
        _engine = PageIndexEngine(corpus_dir=corpus_dir, tree_cache_path=tree_cache_path)
    return _engine


# ── CLI 调试入口 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    engine = get_engine()
    engine.load_or_build_tree()

    query = sys.argv[1] if len(sys.argv) > 1 else "我睡不着，总是担心明天的工作"
    ctx = {
        "anxiety_level": 6,
        "phase": "worry_capture",
        "insomnia_subtype": "sleep_onset",
    }

    print(f"[Query] {query}")
    print(f"[Ctx] {ctx}")
    print()
    result = engine.navigate(query, ctx=ctx, top_k=5)
    print(engine.format_result(result))
