"""
PageIndex Tree — 知眠 CBT-I 语料库树结构定义
模拟 PageIndex 论文的 hierarchical tree index，专为睡眠焦虑对话场景定制。
Leaf nodes carry the actual CBT script content; non-leaf nodes carry LLM-generated summaries.
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class NodeKind(Enum):
    ROOT      = "root"
    CORPUS    = "corpus"
    SECTION   = "section"
    SUBSECT   = "subsect"
    LEAF      = "leaf"
    FALLBACK  = "fallback"


@dataclass
class PageNode:
    title:       str = ""
    node_id:     str = ""
    kind:        NodeKind = NodeKind.LEAF
    summary:     str = ""
    text:        str = ""
    start_index: int = 0
    end_index:   int = 0
    page_num:    int = 0
    source_file: str = ""
    chunk_index: int = 0
    metadata:    Dict[str, Any] = field(default_factory=dict)
    nodes:       List["PageNode"] = field(default_factory=list)

    def add_child(self, child: "PageNode") -> None:
        self.nodes.append(child)

    def is_leaf(self) -> bool:
        return self.kind in (NodeKind.LEAF, NodeKind.FALLBACK)

    def to_dict(self) -> dict:
        d = {
            "title": self.title,
            "node_id": self.node_id,
            "kind": self.kind.value,
            "summary": self.summary,
            "start_index": self.start_index,
            "end_index": self.end_index,
        }
        if self.text:          d["text"]         = self.text
        if self.page_num:     d["page_num"]      = self.page_num
        if self.source_file:  d["source_file"]   = self.source_file
        if self.chunk_index:  d["chunk_index"]   = self.chunk_index
        if self.metadata:     d["metadata"]      = self.metadata
        if self.nodes:        d["nodes"]         = [n.to_dict() for n in self.nodes]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "PageNode":
        kind_str = d.get("kind", "leaf")
        kind = NodeKind(kind_str) if kind_str in [e.value for e in NodeKind] else NodeKind.LEAF
        return cls(
            title       = d.get("title", ""),
            node_id     = d.get("node_id", ""),
            kind       = kind,
            summary    = d.get("summary", ""),
            text       = d.get("text", ""),
            start_index = d.get("start_index", 0),
            end_index  = d.get("end_index", 0),
            page_num   = d.get("page_num", 0),
            source_file = d.get("source_file", ""),
            chunk_index = d.get("chunk_index", 0),
            metadata   = d.get("metadata", {}),
            nodes      = [cls.from_dict(n) for n in d.get("nodes", [])],
        )

    def walk(self):
        yield self
        for child in self.nodes:
            yield from child.walk()

    def find_node(self, node_id: str) -> Optional["PageNode"]:
        if self.node_id == node_id:
            return self
        for child in self.nodes:
            found = child.find_node(node_id)
            if found:
                return found
        return None

    def find_leaves(self, predicate=None) -> List["PageNode"]:
        results = []
        for node in self.walk():
            if node.is_leaf():
                if predicate is None or predicate(node):
                    results.append(node)
        return results

    def describe_tree(self, indent: int = 0) -> str:
        pad = "  " * indent
        line = f"{pad}[{self.node_id}] {self.title}"
        if self.summary:
            line += f" -- {self.summary[:60]}"
        lines = [line]
        for child in self.nodes:
            lines.append(child.describe_tree(indent + 1))
        return "\n".join(lines)


# ── Helpers (module-level, not class methods) ────────────────────────────────

_PMR_TYPE_SEQ = {"full_body": 1, "express": 2, "pmr_short": 3, "pmr_tiny": 4}
_BREATH_TYPE_SEQ = {"478": 1, "diaphragmatic": 2, "box_breathing": 3}


def _pmr_idx(st: str) -> int:
    return _PMR_TYPE_SEQ.get(st, 0)


def _breath_idx(st: str) -> int:
    return _BREATH_TYPE_SEQ.get(st, 0)


# ── CorpusTreeBuilder ────────────────────────────────────────────────────────

class CorpusTreeBuilder:
    """
    将知眠 corpus/*.json 语料目录转换为 PageNode 树。
    结构:
        ROOT
        ├── closure_rituals/        关闭仪式
        ├── worry_scenarios/       担忧场景路由
        ├── pmr_scripts/           渐进式肌肉放松
        ├── breathing_scripts/     呼吸引导
        ├── cognitive_distortions/ 认知扭曲
        ├── sleep_hygiene/        睡眠卫生
        ├── dCBT-I_protocol/      CBT-I 协议
        └── safe_scripts/          安心脚本
    """

    CORPUS_DIR = Path("/home/ubuntu/anmian/corpus")

    def __init__(self, corpus_dir: Optional[Path] = None):
        self.corpus_dir = corpus_dir or self.CORPUS_DIR

    def build(self) -> PageNode:
        root = PageNode(
            title   = "知眠 CBT-I 语料库",
            node_id = "0000",
            kind    = NodeKind.ROOT,
            summary = "睡前大脑关机助手全部 CBT-I 干预语料。",
        )
        root.add_child(self._build_closure_rituals())
        root.add_child(self._build_worry_scenarios())
        root.add_child(self._build_pmr_scripts())
        root.add_child(self._build_breathing_scripts())
        root.add_child(self._build_cognitive_distortions())
        root.add_child(self._build_sleep_hygiene())
        root.add_child(self._build_cbti_protocol())
        root.add_child(self._build_safe_scripts())
        return root

    def _mkid(self, seq: int, parent_seq: int = 0) -> str:
        if parent_seq:
            return f"{parent_seq:04d}.{seq:03d}"
        return f"{seq:04d}"

    # ── closure_rituals ──────────────────────────────────────────────────

    def _build_closure_rituals(self) -> PageNode:
        node = PageNode(
            title   = "关闭仪式语料",
            node_id = self._mkid(1),
            kind    = NodeKind.CORPUS,
            summary = "睡前关闭仪式话术模板，按焦虑强度分级。",
        )
        path = self.corpus_dir / "closure_rituals.json"
        if not path.exists():
            node.add_child(PageNode(title="（文件不存在）", node_id=node.node_id + ".001", kind=NodeKind.LEAF))
            return node

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        # 标准模板
        std = PageNode(
            title="标准关闭模板", node_id=node.node_id + ".001",
            kind=NodeKind.SECTION, summary="5个标准关闭仪式模板。",
        )
        for i, (k, v) in enumerate(data.get("closure_rituals", {}).items()):
            if isinstance(v, dict) and "template" in v:
                std.add_child(PageNode(
                    title     = f"关闭仪式: {k}",
                    node_id   = std.node_id + f".{i+1:02d}",
                    kind      = NodeKind.LEAF,
                    summary   = v.get("template", "")[:100],
                    text      = v["template"],
                    source_file="closure_rituals.json",
                    chunk_index=i,
                    metadata  = {"ritual": k, "intensity": v.get("intensity", "moderate"), "type": "standard_template"},
                ))
        node.add_child(std)

        # 15变体
        var = PageNode(
            title="15变体关闭模板", node_id=node.node_id + ".002",
            kind=NodeKind.SECTION, summary="15个场景化变体。",
        )
        for i, variant in enumerate(data.get("closure_variants_15", {}).get("variants", [])):
            var.add_child(PageNode(
                title     = f"变体: {variant.get('ritual','')} [{variant.get('intensity','')}]",
                node_id   = var.node_id + f".{i+1:03d}",
                kind      = NodeKind.LEAF,
                summary   = variant.get("template", "")[:120],
                text      = variant.get("template", ""),
                source_file="closure_rituals.json",
                chunk_index=i,
                metadata  = {"ritual": variant.get("ritual", ""), "intensity": variant.get("intensity", ""), "type": "variant"},
            ))
        node.add_child(var)

        # Few-shot
        fs = PageNode(
            title="Few-shot 示例", node_id=node.node_id + ".003",
            kind=NodeKind.SECTION, summary="对话示例。",
        )
        for i, ex in enumerate(data.get("fewshot_examples", {}).get("examples", [])):
            inp = ex.get("input", {})
            if isinstance(inp, dict):
                user_msg = inp.get("worry_expressed", "") or inp.get("worry_topic", "")
            else:
                user_msg = str(inp)
            fs.add_child(PageNode(
                title     = f"示例: {ex.get('scenario','')} [{ex.get('intensity','')}]",
                node_id   = fs.node_id + f".{i+1:03d}",
                kind      = NodeKind.LEAF,
                summary   = f"用户: {user_msg[:80]}...",
                text      = f"用户: {user_msg}\n助手: {ex.get('output_script', '')}",
                source_file="closure_rituals.json",
                chunk_index=i,
                metadata  = {"scenario": ex.get("scenario", ""), "intensity": ex.get("intensity", ""), "type": "fewshot"},
            ))
        node.add_child(fs)

        # Sleep induction phrases
        sip = PageNode(
            title="睡眠诱导语", node_id=node.node_id + ".004",
            kind=NodeKind.SECTION, summary="诱导睡眠感的简短 phrases。",
        )
        for i, phrase in enumerate(data.get("sleep_induction_phrases", [])):
            sip.add_child(PageNode(
                title=f"诱导语 {i+1}", node_id=sip.node_id + f".{i+1:03d}",
                kind=NodeKind.LEAF, summary=phrase[:80], text=phrase,
                source_file="closure_rituals.json", chunk_index=i,
                metadata={"type": "induction_phrase"},
            ))
        node.add_child(sip)
        return node

    # ── worry_scenarios ─────────────────────────────────────────────────

    def _build_worry_scenarios(self) -> PageNode:
        node = PageNode(
            title   = "担忧场景语料",
            node_id = self._mkid(2),
            kind    = NodeKind.CORPUS,
            summary = "担忧场景路由表，映射到对应 CBT 技术。",
        )
        path = self.corpus_dir / "worry_scenarios.json"
        if not path.exists():
            node.add_child(PageNode(title="（文件不存在）", node_id=node.node_id + ".001", kind=NodeKind.LEAF))
            return node

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        scenarios = data.get("worry_scenarios", {}).get("scenarios", [])
        by_cat: Dict[str, List] = {}
        for sc in scenarios:
            by_cat.setdefault(sc.get("category", "other"), []).append(sc)

        for cat_i, (cat, sc_list) in enumerate(sorted(by_cat.items())):
            cat_node = PageNode(
                title=f"类别: {cat}", node_id=node.node_id + f".{cat_i+1:02d}",
                kind=NodeKind.SECTION, summary=f"包含 {len(sc_list)} 个场景。",
            )
            for sc_i, sc in enumerate(sc_list):
                keywords = ", ".join(sc.get("emotion_keywords", [])[:8])
                cat_node.add_child(PageNode(
                    title     = sc.get("description", "") or f"场景 {sc.get('id','')}",
                    node_id   = cat_node.node_id + f".{sc_i+1:03d}",
                    kind      = NodeKind.LEAF,
                    summary   = f"[{cat}] {keywords}",
                    text      = f"描述: {sc.get('description','')}\n关键词: {keywords}",
                    source_file="worry_scenarios.json",
                    chunk_index=sc_i,
                    metadata  = {
                        "scenario_id": sc.get("id", ""),
                        "category": cat,
                        "type": "scenario_router",
                        "recommended_techniques": sc.get("recommended_techniques", {}),
                        "example_prompts": sc.get("example_prompts", [])[:3],
                        "clue_phrases": sc.get("clue_phrases", [])[:8],
                    },
                ))
            node.add_child(cat_node)
        return node

    # ── pmr_scripts ────────────────────────────────────────────────────

    def _build_pmr_scripts(self) -> PageNode:
        node = PageNode(
            title="PMR 渐进式肌肉放松",
            node_id=self._mkid(3),
            kind=NodeKind.CORPUS,
            summary="PMR 脚本，引导用户逐部位放松。",
        )
        path = self.corpus_dir / "pmr_scripts.json"
        if not path.exists():
            node.add_child(PageNode(title="（文件不存在）", node_id=node.node_id + ".001", kind=NodeKind.LEAF))
            return node

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        script_types = list(data.get("pmr_scripts", {}).keys())
        for stype_i, stype in enumerate(script_types):
            seq = _pmr_idx(stype) or (stype_i + 1)
            scripts = data["pmr_scripts"][stype]
            type_node = PageNode(
                title=f"PMR 类型: {stype}",
                node_id=node.node_id + f".{seq:02d}",
                kind=NodeKind.SECTION,
                summary=f"PMR {stype} 脚本",
            )
            if isinstance(scripts, list):
                for i, script in enumerate(scripts):
                    if isinstance(script, dict) and "text" in script:
                        type_node.add_child(PageNode(
                            title=f"{stype} 脚本 #{i+1}",
                            node_id=type_node.node_id + f".{i+1:03d}",
                            kind=NodeKind.LEAF,
                            summary=script["text"][:100],
                            text=script["text"],
                            source_file="pmr_scripts.json",
                            chunk_index=i,
                            metadata={"script_type": stype, "type": "relaxation_script"},
                        ))
            node.add_child(type_node)
        return node

    # ── breathing_scripts ───────────────────────────────────────────────

    def _build_breathing_scripts(self) -> PageNode:
        node = PageNode(
            title="呼吸引导脚本",
            node_id=self._mkid(4),
            kind=NodeKind.CORPUS,
            summary="呼吸引导技术：4-7-8、呼吸、膈肌呼吸等。",
        )
        path = self.corpus_dir / "breathing_scripts.json"
        if not path.exists():
            node.add_child(PageNode(title="（文件不存在）", node_id=node.node_id + ".001", kind=NodeKind.LEAF))
            return node

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        script_types = list(data.get("breathing_scripts", {}).keys())
        for stype_i, stype in enumerate(script_types):
            seq = _breath_idx(stype) or (stype_i + 1)
            scripts = data["breathing_scripts"][stype]
            type_node = PageNode(
                title=f"呼吸类型: {stype}",
                node_id=node.node_id + f".{seq:02d}",
                kind=NodeKind.SECTION,
                summary=f"{stype} 呼吸引导脚本",
            )
            if isinstance(scripts, list):
                for i, script in enumerate(scripts):
                    if isinstance(script, dict) and "instruction" in script:
                        type_node.add_child(PageNode(
                            title=f"{stype} #{i+1}",
                            node_id=type_node.node_id + f".{i+1:03d}",
                            kind=NodeKind.LEAF,
                            summary=script["instruction"][:100],
                            text=script["instruction"],
                            source_file="breathing_scripts.json",
                            chunk_index=i,
                            metadata={"breathing_type": stype, "type": "breathing_script"},
                        ))
            node.add_child(type_node)
        return node

    # ── cognitive_distortions ───────────────────────────────────────────

    def _build_cognitive_distortions(self) -> PageNode:
        node = PageNode(
            title="认知扭曲识别",
            node_id=self._mkid(5),
            kind=NodeKind.CORPUS,
            summary="识别常见认知扭曲并引导重构。",
        )
        path = self.corpus_dir / "cognitive_distortions.json"
        if not path.exists():
            node.add_child(PageNode(title="（文件不存在）", node_id=node.node_id + ".001", kind=NodeKind.LEAF))
            return node

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        for i, dist in enumerate(data.get("cognitive_distortions", [])):
            node.add_child(PageNode(
                title=f"认知扭曲: {dist.get('type','')}",
                node_id=node.node_id + f".{i+1:03d}",
                kind=NodeKind.LEAF,
                summary=f"{dist.get('definition','')[:80]}",
                text=f"定义: {dist.get('definition','')}\n示例: {'; '.join(dist.get('examples',[])[:3])}",
                source_file="cognitive_distortions.json",
                chunk_index=i,
                metadata={"distortion_type": dist.get("type", ""), "type": "cognitive_distortion"},
            ))
        return node

    # ── sleep_hygiene ───────────────────────────────────────────────────

    def _build_sleep_hygiene(self) -> PageNode:
        node = PageNode(
            title="睡眠卫生教育",
            node_id=self._mkid(6),
            kind=NodeKind.CORPUS,
            summary="睡眠卫生通用知识。",
        )
        path = self.corpus_dir / "sleep_hygiene.json"
        if not path.exists():
            node.add_child(PageNode(title="（文件不存在）", node_id=node.node_id + ".001", kind=NodeKind.LEAF))
            return node

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        items = data if isinstance(data, list) else data.get("sleep_hygiene", data.get("items", []))
        for i, item in enumerate(items):
            node.add_child(PageNode(
                title=f"睡眠卫生 #{i+1}",
                node_id=node.node_id + f".{i+1:03d}",
                kind=NodeKind.LEAF,
                summary=str(item)[:100] if isinstance(item, str) else item.get("title", ""),
                text=str(item) if isinstance(item, str) else item.get("content", ""),
                source_file="sleep_hygiene.json",
                chunk_index=i,
                metadata={"type": "sleep_hygiene"},
            ))
        return node

    # ── cbti_protocol ──────────────────────────────────────────────────

    def _build_cbti_protocol(self) -> PageNode:
        node = PageNode(
            title="CBT-I 协议",
            node_id=self._mkid(7),
            kind=NodeKind.CORPUS,
            summary="认知行为疗法-失眠核心原理和分步操作。",
        )
        path = self.corpus_dir / "dCBT-I_protocol.json"
        if not path.exists():
            node.add_child(PageNode(title="（文件不存在）", node_id=node.node_id + ".001", kind=NodeKind.LEAF))
            return node

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        def _walk(obj, prefix="", seq=0):
            results = []
            if isinstance(obj, dict):
                for k, v in obj.items():
                    seq += 1
                    if isinstance(v, str) and len(v) >= 20:
                        results.append(PageNode(
                            title=k,
                            node_id=f"{node.node_id}.{seq:03d}",
                            kind=NodeKind.LEAF,
                            summary=v[:100],
                            text=v,
                            source_file="dCBT-I_protocol.json",
                            metadata={"type": "cbti_protocol"},
                        ))
                    elif isinstance(v, (dict, list)):
                        results.extend(_walk(v, k, seq))
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    results.extend(_walk(v, prefix, i))
            return results

        children = _walk(data)
        for child in children[:50]:
            node.add_child(child)
        return node

    # ── safe_scripts ────────────────────────────────────────────────────

    def _build_safe_scripts(self) -> PageNode:
        node = PageNode(
            title="安心脚本 & 情绪关键词",
            node_id=self._mkid(8),
            kind=NodeKind.CORPUS,
            summary="安心话术和情绪关键词库。",
        )
        for f_i, fname in enumerate(["safe_scripts.json", "emotion_keywords.json"]):
            path = self.corpus_dir / fname
            if not path.exists():
                continue
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            f_node = PageNode(
                title=fname, node_id=node.node_id + f".{f_i+1:02d}",
                kind=NodeKind.SECTION,
            )
            if isinstance(data, list):
                for i, item in enumerate(data):
                    if isinstance(item, str):
                        f_node.add_child(PageNode(
                            title=f"{fname} #{i+1}",
                            node_id=f_node.node_id + f".{i+1:03d}",
                            kind=NodeKind.LEAF,
                            summary=item[:80],
                            text=item,
                            source_file=fname,
                            metadata={"type": "safe_script"},
                        ))
            node.add_child(f_node)
        return node


# ── Tree I/O ───────────────────────────────────────────────────────────────

def save_tree(root: PageNode, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(root.to_dict(), f, ensure_ascii=False, indent=2)
    print(f"[PageIndex] 树已保存: {path}")


def load_tree(path: Path) -> PageNode:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return PageNode.from_dict(d)


if __name__ == "__main__":
    try:
        builder = CorpusTreeBuilder(Path("/home/ubuntu/anmian/corpus"))
        root = builder.build()
        print(root.describe_tree())
    except FileNotFoundError:
        print("[PageIndex] 服务器 corpus 路径不可用，跳过本地测试")
