import os
"""
LSA 语义 RAG 索引 — TF-IDF + TruncatedSVD 降维
在 1.9GB 内存服务器上实现轻量级语义检索
"""
import json
import glob
import hashlib
import time
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
import numpy as np
import jieba
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD

# ============ 路径配置 ============
CORPUS_DIR = Path(os.environ.get("ANMIAN_CORPUS_DIR", Path(__file__).parent.parent / "corpus"))
INDEX_DIR = Path(os.environ.get("ANMIAN_INDEX_DIR", Path(__file__).parent / "vector_index"))

# LSA 降维维度（3081 条语料，128 维足够捕捉主要语义）
LSA_COMPONENTS = 128

# ============ 语料提取（通用递归） ============
def _walk(obj, prefix=""):
    """递归遍历 JSON，提取所有长度>=10的字符串"""
    results = []
    if isinstance(obj, str):
        if len(obj) >= 10:
            text = obj[:500]
            source = prefix.split("_")[0] if prefix else "unknown"
            results.append({
                "type": source,
                "text": text,
                "source": source,
            })
    elif isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}_{k}" if prefix else k
            results.extend(_walk(v, p))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_walk(item, prefix))
    return results


def _extract_generic_corpus():
    """遍历 corpus/*.json，提取通用语料（排除已由 vector_store 处理的文件）"""
    known_files = {
        "closure_rituals.json", "worry_scenarios.json", "pmr_scripts.json",
        "breathing_scripts.json", "cognitive_distortions.json"
    }
    chunks = []
    for fpath in glob.glob(str(CORPUS_DIR / "*.json")):
        fname = Path(fpath).name
        if fname in known_files:
            continue
        stem = Path(fpath).stem
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in _walk(data, stem):
            h = hashlib.md5(item["text"].encode()).hexdigest()
            item["hash"] = h
            chunks.append(item)
    # 去重
    seen = set()
    unique = []
    for c in chunks:
        if c["hash"] not in seen and len(c["text"]) >= 10:
            seen.add(c["hash"])
            del c["hash"]
            unique.append(c)
    return unique


# ============ 中文分词 ============
def _tokenize_cjk(text: str) -> List[str]:
    """混合中英文分词"""
    tokens = []
    for token in jieba.cut(text.strip()):
        t = token.strip().lower()
        if t and len(t) >= 1:
            tokens.append(t)
    import re
    for word in re.findall(r"[a-zA-Z]+", text):
        w = word.lower()
        if len(w) >= 2:
            tokens.append(w)
    return tokens


# ============ LSA 语义 RAG 索引 ============
class HybridRAGIndex:
    """LSA 语义检索索引：TF-IDF + TruncatedSVD"""

    def __init__(self):
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.svd: Optional[TruncatedSVD] = None
        self.lsa_vectors: Optional[np.ndarray] = None
        self.chunks_data: List[Dict[str, Any]] = []
        self._index_path = INDEX_DIR / "lsa_index"

    # ---------- 属性兼容 ----------
    @property
    def chunks(self) -> List[str]:
        return [c["text"] for c in self.chunks_data]

    @property
    def vectors(self) -> np.ndarray:
        return self.lsa_vectors if self.lsa_vectors is not None else np.array([])

    # ---------- 占位兼容方法 ----------
    def _load_model(self):
        """LSA 无需外部模型加载"""
        pass

    def _build_bm25(self):
        """LSA 无需 BM25"""
        pass

    # ---------- 语料加载 ----------
    def _load_corpus_texts(self) -> List[Tuple[str, Dict[str, Any]]]:
        """加载所有语料（已知格式 + 通用格式）"""
        from vector_store import RAGIndex as _BaseRAGIndex
        base = _BaseRAGIndex()
        known = base._load_corpus_texts()
        generic = _extract_generic_corpus()
        return known + [(c["text"], c) for c in generic]

    # ---------- 索引构建 ----------
    def build_index(self, force: bool = False):
        if self._index_path.exists() and not force:
            print("[RAG] LSA 索引已存在，跳过构建（force=True 可强制重建）")
            return

        corpus = self._load_corpus_texts()
        self.chunks_data = []
        for text, meta in corpus:
            meta["text"] = text
            self.chunks_data.append(meta)
        texts = [text for text, _ in corpus]

        print(f"[RAG] 开始构建 LSA 语义索引，共 {len(texts)} 条语料...")

        # 1. TF-IDF
        t0 = time.time()
        self.vectorizer = TfidfVectorizer(
            tokenizer=_tokenize_cjk,
            token_pattern=None,
            min_df=1,
            max_df=0.95,
            sublinear_tf=True,
        )
        tfidf_matrix = self.vectorizer.fit_transform(texts)
        print(f"[RAG] TF-IDF 完成 ({time.time()-t0:.1f}s), shape={tfidf_matrix.shape}")

        # 2. LSA 降维
        t0 = time.time()
        n_components = min(LSA_COMPONENTS, tfidf_matrix.shape[1] - 1, len(texts) - 1)
        self.svd = TruncatedSVD(n_components=n_components, random_state=42)
        self.lsa_vectors = self.svd.fit_transform(tfidf_matrix).astype(np.float32)
        print(f"[RAG] LSA 降维完成 ({time.time()-t0:.1f}s), components={n_components}, shape={self.lsa_vectors.shape}")
        print(f"[RAG] 累计解释方差比: {self.svd.explained_variance_ratio_.sum():.2%}")

        # 保存
        self._save()
        print(f"[RAG] LSA 语义索引构建完成，chunks={len(texts)}, dim={n_components}")

    def _save(self):
        self._index_path.mkdir(parents=True, exist_ok=True)
        np.save(self._index_path / "lsa_vectors.npy", self.lsa_vectors)
        with open(self._index_path / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(self.chunks_data, f, ensure_ascii=False, indent=2)
        joblib.dump(self.vectorizer, self._index_path / "vectorizer.pkl")
        joblib.dump(self.svd, self._index_path / "svd.pkl")

    # ---------- 索引加载 ----------
    def load(self) -> bool:
        return self.load_index()

    def load_index(self) -> bool:
        if not self._index_path.exists():
            return False

        self.lsa_vectors = np.load(self._index_path / "lsa_vectors.npy")
        with open(self._index_path / "metadata.json", "r", encoding="utf-8") as f:
            self.chunks_data = json.load(f)
        self.vectorizer = joblib.load(self._index_path / "vectorizer.pkl")
        self.svd = joblib.load(self._index_path / "svd.pkl")

        print(f"[RAG] LSA 语义索引加载成功，chunks={len(self.chunks_data)}, dim={self.lsa_vectors.shape[1]}")
        return True

    # ---------- 检索核心 ----------
    def _cosim(self, q_vec: np.ndarray, doc_vecs: np.ndarray) -> np.ndarray:
        """批量余弦相似度"""
        q_norm = q_vec / (np.linalg.norm(q_vec) + 1e-10)
        d_norms = np.linalg.norm(doc_vecs, axis=1, keepdims=True) + 1e-10
        d_norm = doc_vecs / d_norms
        return np.dot(d_norm, q_norm).flatten()

    def retrieve(self, query: str, top_k: int = 5, filters: Optional[Dict[str, Any]] = None):
        if self.lsa_vectors is None or self.vectorizer is None or self.svd is None:
            return []

        # 查询 -> TF-IDF -> LSA 投影
        q_tfidf = self.vectorizer.transform([query])
        q_lsa = self.svd.transform(q_tfidf).astype(np.float32)[0]
        scores = self._cosim(q_lsa, self.lsa_vectors)

        # 取 top_k * 2 用于过滤
        top_indices = np.argsort(scores)[::-1][:top_k * 2]

        results = []
        for idx in top_indices:
            chunk = self.chunks_data[idx]
            if filters:
                match = all(chunk.get(k) == v for k, v in filters.items())
                if not match:
                    continue
            results.append({
                "chunk": chunk,
                "score": float(round(scores[idx], 4)),
                "text": chunk.get("text", ""),
            })
            if len(results) >= top_k:
                break
        return results

    def _retrieve_with_fallback(self, query: str, top_k: int, filters: Optional[Dict[str, Any]] = None):
        """带 fallback 的检索（供线程池并行调用）"""
        results = self.retrieve(query, top_k=top_k, filters=filters)
        if not results:
            results = self.retrieve(query, top_k=top_k)
        return results

    def retrieve_for_session(self, query: str, ctx: Optional[Dict[str, Any]] = None):
        """根据会话上下文检索多种类型的相关语料（并行化，减少串行延迟）"""
        ctx = ctx or {}

        from concurrent.futures import ThreadPoolExecutor
        tasks = [
            ("worry_scenarios", {"top_k": 3, "filters": {"type": "scenario_router"}}),
            ("closure_templates", {"top_k": 5, "filters": {"source": "closure_rituals"}}),
            ("pmr_scripts", {"top_k": 3, "filters": {"type": "relaxation_script"}}),
            ("breathing_scripts", {"top_k": 3, "filters": {"type": "breathing_script"}}),
            ("cognitive_distortions", {"top_k": 2, "filters": {"type": "cognitive_distortion"}}),
        ]

        results_map = {}
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {
                name: pool.submit(self._retrieve_with_fallback, query, cfg["top_k"], cfg["filters"])
                for name, cfg in tasks
            }
            for name, fut in futures.items():
                try:
                    results_map[name] = fut.result(timeout=3.0)
                except Exception as e:
                    print(f"[RAG] {name} retrieve error: {e}")
                    results_map[name] = []

        return results_map


# 单例（兼容旧接口）
hybrid_rag = HybridRAGIndex()
