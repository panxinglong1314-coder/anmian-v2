"""
RAG 向量存储引擎
知眠 L2: 语料库向量化 + FAISS 检索
"""

import json
import hashlib
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import numpy as np

CORPUS_DIR = Path(__file__).parent.parent / "corpus"
INDEX_DIR = Path(__file__).parent / "vector_index"
INDEX_DIR.mkdir(exist_ok=True)

# ============ 向量化（用 TF-IDF，无API依赖）============

def _tokenize(text: str) -> List[str]:
    """中文分词：混合中英文处理
    - 英文/数字按空格分词
    - 中文用字符二元组（2-gram）捕捉语义，比整句单个token效果好得多
    """
    import re
    text = re.sub(r'[^\w\s]', ' ', text)
    parts = text.lower().split()
    tokens = []
    for part in parts:
        if re.match(r'^[a-z0-9]+$', part):
            if len(part) >= 2:
                tokens.append(part)
        else:
            # 中文及混合文本：字符 bigram
            chars = [c for c in part if c.strip()]
            for i in range(len(chars) - 1):
                tokens.append(chars[i] + chars[i + 1])
    return tokens


def _build_vocab(corpus: List[str], min_freq: int = 2) -> Dict[str, int]:
    """从语料库构建词汇表"""
    freq = {}
    for text in corpus:
        for token in _tokenize(text):
            freq[token] = freq.get(token, 0) + 1
    vocab = {w: i for i, (w, f) in enumerate(sorted(freq.items(), key=lambda x: -x[1])) if f >= min_freq}
    return vocab


def _text_to_tfidf(text: str, vocab: Dict[str, int], idf: Dict[str, float]) -> np.ndarray:
    """文本转TF-IDF向量"""
    tokens = _tokenize(text)
    vec = np.zeros(len(vocab))
    tf = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    for token, count in tf.items():
        if token in vocab:
            vec[vocab[token]] = count * idf.get(token, 1.0)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec.astype(np.float32)


def _compute_idf(corpus: List[str], vocab: Dict[str, int]) -> Dict[str, float]:
    """计算IDF（逆文档频率）"""
    N = len(corpus)
    df = {w: 0 for w in vocab}
    for text in corpus:
        seen = set(_tokenize(text))
        for w in seen:
            if w in df:
                df[w] += 1
    idf = {w: np.log(N / (d + 1)) + 1 for w, d in df.items()}
    return idf


class VectorStore:
    """FAISS替代：内存向量索引（简单版，支持余弦相似度）"""

    def __init__(self):
        self.vectors: List[np.ndarray] = []
        self.metadata: List[Dict[str, Any]] = []

    def add(self, vector: np.ndarray, metadata: Dict[str, Any]):
        self.vectors.append(vector)
        self.metadata.append(metadata)

    def search(self, query_vec: np.ndarray, top_k: int = 5) -> List[Tuple[Dict[str, Any], float]]:
        """余弦相似度检索"""
        if not self.vectors or len(query_vec) == 0:
            return []
        q_len = len(query_vec)
        scores = []
        for v in self.vectors:
            if len(v) != q_len:
                scores.append(0.0)
            else:
                sim = float(np.dot(query_vec, v))
                scores.append(sim)
        top_indices = np.argsort(scores)[::-1][:top_k]
        return [(self.metadata[i], scores[i]) for i in top_indices if scores[i] > 0]

    def save(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        np.save(path / "vectors.npy", np.array(self.vectors))
        with open(path / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)

    def save_vocab(self, path: Path, vocab: dict, idf: dict):
        path.mkdir(parents=True, exist_ok=True)
        with open(path / "vocab.json", "w", encoding="utf-8") as f:
            json.dump({"vocab": vocab, "idf": {k: float(v) for k, v in idf.items()}}, f, ensure_ascii=False, indent=2)

    def load_vocab(self, path: Path):
        with open(path / "vocab.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return data["vocab"], data["idf"]

    def load(self, path: Path):
        self.vectors = list(np.load(path / "vectors.npy"))
        with open(path / "metadata.json", "r", encoding="utf-8") as f:
            self.metadata = json.load(f)


class RAGIndex:
    """RAG索引管理器"""

    def __init__(self):
        self.vocab: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}
        self.store = VectorStore()
        self._index_path = INDEX_DIR / "corpus_index"

    # ---------- 加载语料库文本 ----------

    def _load_corpus_texts(self) -> List[Tuple[str, Dict[str, Any]]]:
        """从语料库加载所有可检索文本"""
        texts = []

        # 1. closure_rituals.json — 关闭仪式（高价值）
        cr_path = CORPUS_DIR / "closure_rituals.json"
        if cr_path.exists():
            with open(cr_path, encoding="utf-8") as f:
                data = json.load(f)
            # 标准模板
            for key, val in data.get("closure_rituals", {}).items():
                if isinstance(val, dict) and "template" in val:
                    texts.append((val["template"], {
                        "source": "closure_rituals",
                        "ritual": key,
                        "type": "standard_template",
                        "intensity": "all"
                    }))
            # 15变体
            for variant in data.get("closure_variants_15", {}).get("variants", []):
                texts.append((variant.get("template", ""), {
                    "source": "closure_rituals",
                    "ritual": variant.get("ritual", ""),
                    "type": "variant",
                    "intensity": variant.get("intensity", "moderate"),
                    "id": variant.get("id", "")
                }))
            # few-shot示例（正确字段：input 是 dict，output_script 是 string）
            for ex in data.get("fewshot_examples", {}).get("examples", []):
                inp = ex.get("input", {})
                if isinstance(inp, dict):
                    user_msg = inp.get("worry_expressed", "") or inp.get("worry_topic", "")
                else:
                    user_msg = str(inp)
                assistant_msg = ex.get("output_script", "")
                texts.append((f"用户: {user_msg}\n助手: {assistant_msg}", {
                    "source": "closure_rituals",
                    "type": "fewshot",
                    "scenario": ex.get("scenario", ""),
                    "intensity": ex.get("intensity", "moderate"),
                }))

        # 2. worry_scenarios.json — 担忧场景路由
        ws_path = CORPUS_DIR / "worry_scenarios.json"
        if ws_path.exists():
            with open(ws_path, encoding="utf-8") as f:
                data = json.load(f)
            for scene in data.get("worry_scenarios", {}).get("scenarios", []):
                # 收集关键词作为检索文本
                keywords = ", ".join(scene.get("emotion_keywords", [])[:10])
                examples = "\n".join(scene.get("example_prompts", [])[:3])
                clue_phrases = ", ".join(scene.get("clue_phrases", [])[:10])
                texts.append((f"{scene.get('description', '')}\n关键词: {keywords}\n示例: {examples}\n触发词: {clue_phrases}", {
                    "source": "worry_scenarios",
                    "scenario_id": scene.get("id", ""),
                    "category": scene.get("category", ""),
                    "type": "scenario_router",
                    "description": scene.get("description", ""),
                    "recommended_techniques": scene.get("recommended_techniques", {}),
                    "example_prompts": scene.get("example_prompts", [])[:3],
                }))

        # 3. pmr_scripts.json — PMR身体扫描
        pmr_path = CORPUS_DIR / "pmr_scripts.json"
        if pmr_path.exists():
            with open(pmr_path, encoding="utf-8") as f:
                data = json.load(f)
            for key, scripts in data.get("pmr_scripts", {}).items():
                for script in (scripts if isinstance(scripts, list) else [scripts]):
                    if isinstance(script, dict) and "text" in script:
                        texts.append((script["text"], {
                            "source": "pmr_scripts",
                            "script_type": key,
                            "type": "relaxation_script"
                        }))

        # 4. breathing_scripts.json — 呼吸引导
        br_path = CORPUS_DIR / "breathing_scripts.json"
        if br_path.exists():
            with open(br_path, encoding="utf-8") as f:
                data = json.load(f)
            for key, scripts in data.get("breathing_scripts", {}).items():
                for script in (scripts if isinstance(scripts, list) else [scripts]):
                    if isinstance(script, dict) and "instruction" in script:
                        texts.append((script["instruction"], {
                            "source": "breathing_scripts",
                            "breathing_type": key,
                            "type": "breathing_script"
                        }))

        # 5. cognitive_distortions.json — 认知扭曲
        cd_path = CORPUS_DIR / "cognitive_distortions.json"
        if cd_path.exists():
            with open(cd_path, encoding="utf-8") as f:
                data = json.load(f)
            for dist in data.get("cognitive_distortions", []):
                texts.append((f"{dist.get('definition', '')}\n示例: {', '.join(dist.get('examples', [])[:3])}", {
                    "source": "cognitive_distortions",
                    "distortion_type": dist.get("type", ""),
                    "type": "cognitive_distortion"
                }))

        return texts

    # ---------- 构建索引 ----------

    def build_index(self, force: bool = False):
        """构建RAG索引"""
        if self._index_path.exists() and not force:
            print("[RAG] 索引已存在，跳过构建（force=True可强制重建）")
            return

        print("[RAG] 开始构建索引...")
        corpus_texts = self._load_corpus_texts()
        print(f"[RAG] 加载了 {len(corpus_texts)} 条语料")

        all_texts = [t[0] for t in corpus_texts]
        self.vocab = _build_vocab(all_texts)
        self.idf = _compute_idf(all_texts, self.vocab)
        print(f"[RAG] 词汇表大小: {len(self.vocab)}")

        self.store = VectorStore()
        for text, meta in corpus_texts:
            vec = _text_to_tfidf(text, self.vocab, self.idf)
            self.store.add(vec, {**meta, "text": text[:200]})  # 保留前200字

        self.store.save(self._index_path)
        self.store.save_vocab(self._index_path, self.vocab, self.idf)
        print(f"[RAG] 索引构建完成，共 {len(self.store.vectors)} 条向量")

    def load_index(self):
        """加载已有索引"""
        if not self._index_path.exists():
            raise FileNotFoundError("索引不存在，请先调用 build_index()")
        self.store.load(self._index_path)
        # 加载保存的vocab/idf，避免从截断text重建导致维度不匹配
        vocab_path = self._index_path / "vocab.json"
        if vocab_path.exists():
            self.vocab, self.idf = self.store.load_vocab(self._index_path)
        else:
            # 回退：从metadata重建（旧索引兼容）
            all_texts = [meta.get("text", "") for meta in self.store.metadata]
            self.vocab = _build_vocab(all_texts)
            self.idf = _compute_idf(all_texts, self.vocab)
        print(f"[RAG] 索引加载完成，共 {len(self.store.vectors)} 条向量，词汇表 {len(self.vocab)}")

    # ---------- 检索 ----------

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """检索最相关的语料片段"""
        if not self.vocab:
            self.load_index()

        query_vec = _text_to_tfidf(query, self.vocab, self.idf)
        results = self.store.search(query_vec, top_k=top_k * 2)  # 多检索一些用于过滤

        # 应用过滤器
        filtered = []
        for meta, score in results:
            if filters:
                match = all(meta.get(k) == v for k, v in filters.items())
                if not match:
                    continue
            filtered.append({**meta, "score": round(score, 4)})
            if len(filtered) >= top_k:
                break

        return filtered

    def retrieve_for_session(
        self,
        user_message: str,
        session_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """根据会话上下文检索多种类型的相关语料

        Returns:
            {
                "closure_templates": [...],  # 关闭仪式模板
                "worry_scenarios": [...],   # 担忧场景路由
                "pmr_scripts": [...],        # PMR脚本
                "breathing_scripts": [...],  # 呼吸引导
                "cognitive_distortions": [...],  # 认知扭曲
            }
        """
        ctx = session_context or {}

        # 1. 担忧场景检索（总是检索，帮助路由）
        worry_results = self.retrieve(
            user_message,
            top_k=3,
            filters={"type": "scenario_router"}
        )

        # 2. 关闭仪式检索（根据情绪强度）
        _alvl_raw = ctx.get("anxiety_level", 5)
        # 兼容 AnxietyLevel 枚举类型
        if hasattr(_alvl_raw, "value"):  # enum
            _alvl_raw = {"severe": 8, "moderate": 5, "mild": 2, "normal": 0}.get(_alvl_raw.value, 5)
        try:
            anxiety_level = int(_alvl_raw)
        except (TypeError, ValueError):
            anxiety_level = 5
        if anxiety_level >= 7:
            intensity_filter = "severe"
        elif anxiety_level >= 4:
            intensity_filter = "moderate"
        else:
            intensity_filter = "light"

        closure_results = self.retrieve(
            user_message,
            top_k=5,
            filters={"source": "closure_rituals"}
        )

        # 3. 放松脚本检索
        relaxation_results = self.retrieve(
            user_message,
            top_k=3,
            filters={"type": "relaxation_script"}
        )

        breathing_results = self.retrieve(
            user_message,
            top_k=3,
            filters={"type": "breathing_script"}
        )

        # 4. 认知扭曲检索
        distortion_results = self.retrieve(
            user_message,
            top_k=2,
            filters={"type": "cognitive_distortion"}
        )

        return {
            "worry_scenarios": worry_results,
            "closure_templates": closure_results,
            "pmr_scripts": relaxation_results,
            "breathing_scripts": breathing_results,
            "cognitive_distortions": distortion_results,
        }


# 单例
rag_index = RAGIndex()
