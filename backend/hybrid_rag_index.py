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

# LSA 检索最低相似度阈值：低于此值视为噪声，不返回
LSA_MIN_SCORE = 0.12

# 英文 corpus 较小（~125KB），降维到 64 足够
LSA_COMPONENTS_EN = 64

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


def _extract_generic_corpus(locale: str = "zh"):
    """遍历 corpus/*.json，提取通用语料（排除已由 vector_store 处理的文件）。
    locale='en' 时只读 *.en.json 并跳过 raw 大数据集(中文)。"""
    known_files_zh = {
        "closure_rituals.json", "worry_scenarios.json", "pmr_scripts.json",
        "breathing_scripts.json", "cognitive_distortions.json"
    }
    known_files_en = {
        "closure_rituals.en.json", "worry_scenarios.en.json", "pmr_scripts.en.json",
        "breathing_scripts.en.json", "cognitive_distortions.en.json"
    }
    chunks = []
    for fpath in glob.glob(str(CORPUS_DIR / "*.json")):
        fname = Path(fpath).name
        is_en_file = fname.endswith(".en.json")
        if locale == "en":
            # 英文索引只吃英文文件，且跳过已由结构化抽取处理的
            if not is_en_file:
                continue
            if fname in known_files_en:
                continue
        else:
            # 中文索引跳过英文文件 + 已处理文件
            if is_en_file:
                continue
            if fname in known_files_zh:
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
    """LSA 语义检索索引：TF-IDF + TruncatedSVD (按 locale 支持中/英两套独立索引)"""

    def __init__(self, locale: str = "zh"):
        self.locale = locale if locale in ("zh", "en") else "zh"
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.svd: Optional[TruncatedSVD] = None
        self.lsa_vectors: Optional[np.ndarray] = None
        self.chunks_data: List[Dict[str, Any]] = []
        # 中文沿用旧路径 lsa_index 保持兼容,英文独立到 lsa_index_en
        self._index_path = INDEX_DIR / "lsa_index" if self.locale == "zh" else INDEX_DIR / f"lsa_index_{self.locale}"

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
        if self.locale == "en":
            known = self._load_corpus_texts_en()
        else:
            from vector_store import RAGIndex as _BaseRAGIndex
            base = _BaseRAGIndex()
            known = base._load_corpus_texts()
        generic = _extract_generic_corpus(locale=self.locale)
        return known + [(c["text"], c) for c in generic]

    def _load_corpus_texts_en(self) -> List[Tuple[str, Dict[str, Any]]]:
        """英文结构化语料抽取(并行于 vector_store._load_corpus_texts 的中文版本)。
        覆盖 closure_rituals/worry_scenarios/pmr_scripts/breathing_scripts/cognitive_distortions 的英文文件。"""
        texts: List[Tuple[str, Dict[str, Any]]] = []

        # 1. closure_rituals.en.json
        cr_path = CORPUS_DIR / "closure_rituals.en.json"
        if cr_path.exists():
            with open(cr_path, encoding="utf-8") as f:
                data = json.load(f)
            for key, val in data.get("closure_rituals", {}).items():
                if isinstance(val, dict) and "template" in val:
                    texts.append((val["template"], {
                        "source": "closure_rituals", "ritual": key,
                        "type": "standard_template", "intensity": "all",
                    }))
            for variant in data.get("closure_variants_15", {}).get("variants", []):
                texts.append((variant.get("template", ""), {
                    "source": "closure_rituals", "ritual": variant.get("ritual", ""),
                    "type": "variant", "intensity": variant.get("intensity", "moderate"),
                    "id": variant.get("id", ""),
                }))
            for ex in data.get("fewshot_examples", {}).get("examples", []):
                inp = ex.get("input", {}) or {}
                user_msg = inp.get("worry_expressed", "") or inp.get("worry_topic", "")
                assistant_msg = ex.get("output_script", "")
                texts.append((f"User: {user_msg}\nAssistant: {assistant_msg}", {
                    "source": "closure_rituals", "type": "fewshot",
                    "scenario": ex.get("scenario", ""), "intensity": ex.get("intensity", "moderate"),
                }))

        # 2. worry_scenarios.en.json
        ws_path = CORPUS_DIR / "worry_scenarios.en.json"
        if ws_path.exists():
            with open(ws_path, encoding="utf-8") as f:
                data = json.load(f)
            for scene in data.get("worry_scenarios", {}).get("scenarios", []):
                keywords = ", ".join(scene.get("emotion_keywords", [])[:10])
                examples = "\n".join(scene.get("example_prompts", [])[:3])
                clue_phrases = ", ".join(scene.get("clue_phrases", [])[:10])
                texts.append((f"{scene.get('description', '')}\nkeywords: {keywords}\nexamples: {examples}\ntriggers: {clue_phrases}", {
                    "source": "worry_scenarios", "scenario_id": scene.get("id", ""),
                    "category": scene.get("category", ""), "type": "scenario_router",
                    "description": scene.get("description", ""),
                    "recommended_techniques": scene.get("recommended_techniques", {}),
                    "example_prompts": scene.get("example_prompts", [])[:3],
                }))

        # 3. pmr_scripts.en.json — 把每个 region 的 tense+relax 拼成可检索文本
        pmr_path = CORPUS_DIR / "pmr_scripts.en.json"
        if pmr_path.exists():
            with open(pmr_path, encoding="utf-8") as f:
                data = json.load(f)
            for key, script in data.get("pmr_scripts", {}).items():
                if not isinstance(script, dict):
                    continue
                intro = script.get("intro_script", "")
                if intro:
                    texts.append((intro, {"source": "pmr_scripts", "script_type": key, "type": "pmr_intro"}))
                # sequence (full_body) 或 regions (short/tiny)
                regions = script.get("sequence") or script.get("regions") or []
                for region in regions:
                    if not isinstance(region, dict):
                        continue
                    combined = " ".join(filter(None, [
                        region.get("tense_instruction", ""),
                        region.get("relax_instruction", ""),
                    ]))
                    if combined:
                        texts.append((combined, {
                            "source": "pmr_scripts", "script_type": key,
                            "region": region.get("region", ""), "type": "relaxation_script",
                        }))

        # 4. breathing_scripts.en.json
        br_path = CORPUS_DIR / "breathing_scripts.en.json"
        if br_path.exists():
            with open(br_path, encoding="utf-8") as f:
                data = json.load(f)
            for key, script in data.get("breathing_scripts", {}).items():
                if not isinstance(script, dict):
                    continue
                intro = script.get("intro_script", "")
                if intro:
                    texts.append((intro, {"source": "breathing_scripts", "breathing_type": key, "type": "breathing_intro"}))
                for inst in script.get("instructions", []):
                    text = " ".join(filter(None, [inst.get("physical_guide", ""), inst.get("mental_focus", "")]))
                    if text:
                        texts.append((text, {
                            "source": "breathing_scripts", "breathing_type": key,
                            "phase": inst.get("phase", ""), "type": "breathing_script",
                        }))
            # mindfulness + paradoxical_intention + sleep_effort_reduction 也吃进来
            for section_key in ("mindfulness_scripts", "paradoxical_intention", "sleep_effort_reduction"):
                section = data.get(section_key, {})
                if isinstance(section, dict):
                    for item in _walk(section, section_key):
                        texts.append((item["text"], {"source": section_key, "type": "mindfulness"}))

        # 5. cognitive_distortions.en.json
        cd_path = CORPUS_DIR / "cognitive_distortions.en.json"
        if cd_path.exists():
            with open(cd_path, encoding="utf-8") as f:
                data = json.load(f)
            for dist in data.get("cognitive_distortions", []):
                combined = f"{dist.get('definition', '')}\nExamples: {', '.join(dist.get('examples', [])[:3])}"
                if dist.get('reframing'):
                    combined += f"\nReframe: {dist['reframing']}"
                texts.append((combined, {
                    "source": "cognitive_distortions",
                    "distortion_type": dist.get("id", ""),
                    "type": "cognitive_distortion",
                }))
                # Socratic questions 单独入库,便于直接召回
                for q in dist.get("socratic_questions", [])[:5]:
                    texts.append((q, {
                        "source": "cognitive_distortions",
                        "distortion_type": dist.get("id", ""),
                        "type": "socratic_question",
                    }))
        return texts

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

        print(f"[RAG/{self.locale}] 开始构建 LSA 语义索引，共 {len(texts)} 条语料...")

        # 1. TF-IDF — 中英用不同分词器
        t0 = time.time()
        if self.locale == "en":
            # sklearn 内置英文 analyzer:小写化、按空白/标点切词、去英文停用词
            self.vectorizer = TfidfVectorizer(
                analyzer="word",
                lowercase=True,
                stop_words="english",
                token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z\-']+\b",
                min_df=1,
                max_df=0.95,
                sublinear_tf=True,
                ngram_range=(1, 2),
            )
        else:
            self.vectorizer = TfidfVectorizer(
                tokenizer=_tokenize_cjk,
                token_pattern=None,
                min_df=1,
                max_df=0.95,
                sublinear_tf=True,
            )
        tfidf_matrix = self.vectorizer.fit_transform(texts)
        print(f"[RAG/{self.locale}] TF-IDF 完成 ({time.time()-t0:.1f}s), shape={tfidf_matrix.shape}")

        # 2. LSA 降维 — 英文 corpus 较小,components 64
        t0 = time.time()
        target_components = LSA_COMPONENTS_EN if self.locale == "en" else LSA_COMPONENTS
        n_components = min(target_components, tfidf_matrix.shape[1] - 1, len(texts) - 1)
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
            if scores[idx] < LSA_MIN_SCORE:
                break
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


# 单例（中文为兼容旧接口的 hybrid_rag,新增英文 hybrid_rag_en + locale 路由）
hybrid_rag = HybridRAGIndex(locale="zh")
hybrid_rag_en = HybridRAGIndex(locale="en")
HYBRID_RAG_BY_LOCALE = {"zh": hybrid_rag, "en": hybrid_rag_en}


def get_hybrid_rag(locale: str = "zh") -> HybridRAGIndex:
    """按 locale 返回对应索引单例。未知 locale 回退 zh。"""
    code = (locale or "zh").lower().split("-")[0]
    return HYBRID_RAG_BY_LOCALE.get(code, hybrid_rag)
