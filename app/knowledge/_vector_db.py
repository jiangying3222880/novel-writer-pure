"""
F2 拍板: 向量 DB (本地嵌入 + 0 tokens 费用)
- 嵌入器懒加载: 优先 sentence-transformers, fallback TF-IDF + SVD (避免模型下载失败)
- 余弦相似度 top_k 检索
- numpy 持久化 (向量 + meta) 到 app/knowledge/index/
- 配套 A1.4 混合检索的第二零件 (与 F1 BM25 融合)

设计取舍:
- 生产: sentence-transformers + paraphrase-multilingual-MiniLM-L12-v2 (CPU 友好 ~470MB)
- Smoke / 离线: TF-IDF + TruncatedSVD(dim=128) 兜底
- 模型状态: 第一次 embed() 才加载 (启动快)
"""
from __future__ import annotations

import logging
import pickle
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from app.knowledge import (
    BUILTIN_DIR,
    INDEX_DIR,
    PRESET_CATEGORIES,
    RETRIEVAL_CATEGORIES,
    INDEX_RETRIEVAL_CATEGORIES,
    SOURCE_BUILTIN,
    KnowledgeDoc,
    read_doc,
    scan_category,
)
from app.knowledge._bm25 import tokenize as _bm25_tokenize

_logger = logging.getLogger("NovelWriter.vector")

# ────────────────────── 配置 ──────────────────────

# 默认模型 (生产用)
DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
# Fallback 维度 (TF-IDF 走 SVD)
FALLBACK_DIM = 128

# 持久化路径
VECTORS_FILE = INDEX_DIR / "vectors.npy"
META_FILE = INDEX_DIR / "vectors_meta.pkl"


# ────────────────────── 数据类 ──────────────────────

@dataclass
class VectorHit:
    """一次向量检索命中。"""
    doc_id: str
    score: float                # 余弦相似度 (-1, 1), 越大越相关
    snippet: str = ""


# ────────────────────── 嵌入器 ──────────────────────

class Embedder:
    """
    嵌入器。
    - 模式 1 (st): sentence-transformers 真模型 (384 维, 跨语言)
    - 模式 2 (tfidf): TF-IDF + SVD 兜底 (128 维, 轻量, 不需下载模型)
    """

    def __init__(self, model_name: str = DEFAULT_MODEL, dim: int = FALLBACK_DIM):
        self.model_name = model_name
        self.dim = dim
        self._mode: Optional[str] = None
        self._model = None
        self._tfidf = None
        self._svd = None
        self._fitted = False
        # 缓存已拟合 corpus (用于增量 fit)
        self._corpus_texts: list[str] = []

    @property
    def mode(self) -> str:
        if self._mode is None:
            self._ensure()
        return self._mode or "unknown"

    @property
    def dim_out(self) -> int:
        """实际输出维度 (st 384 / tfidf self.dim)."""
        if self.mode == "st":
            return 384
        return self.dim

    def _ensure(self) -> None:
        if self._mode is not None:
            return
        # 默认走 TF-IDF 兜底 (避免无网环境卡 5min)
        # 显式设置 NOVEL_WRITER_NO_HF=0 才尝试 sentence-transformers
        import os
        if os.environ.get("NOVEL_WRITER_NO_HF", "1").strip() not in ("0", "false", "no", ""):
            _logger.info("默认 TF-IDF 模式 (设 NOVEL_WRITER_NO_HF=0 启用 st 模式)")
            self._mode = "tfidf"
            self._init_tfidf()
            return
        try:
            from sentence_transformers import SentenceTransformer
            try:
                self._model = SentenceTransformer(self.model_name, device="cpu")
                self._mode = "st"
                _logger.info("Vector Embedder: 使用 sentence-transformers (%s, dim=384)",
                             self.model_name)
                return
            except Exception as e:
                _logger.warning("加载 sentence-transformers 模型失败 (%s): %s → fallback TF-IDF",
                                self.model_name, e)
        except ImportError:
            _logger.warning("sentence-transformers 未安装 → fallback TF-IDF")
        self._mode = "tfidf"
        self._init_tfidf()

    def _init_tfidf(self) -> None:
        """初始化 TF-IDF (用 dense 截断/补零, 避免 SVD 维度不足)。"""
        from sklearn.feature_extraction.text import TfidfVectorizer

        def _ch_tokenizer(s: str):
            return _bm25_tokenize(s)

        self._tfidf = TfidfVectorizer(
            tokenizer=_ch_tokenizer,
            token_pattern=None,
            max_features=5000,
        )
        _logger.info("Vector Embedder: 使用 TF-IDF (dim=%d, dense 截断/补零)", self.dim)

    def embed(self, texts: list[str]) -> np.ndarray:
        """
        嵌入文本列表。
        返回 (N, D) 的 numpy 数组 (L2 normalized)。
        """
        if not texts:
            return np.zeros((0, self.dim_out), dtype=np.float32)
        self._ensure()
        if self._mode == "st":
            vecs = self._model.encode(
                texts,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return vecs.astype(np.float32)
        # tfidf 模式: 拟合 corpus, 转 dense, 截断/补零到 dim
        all_texts = self._corpus_texts + list(texts)
        try:
            tfidf_mat = self._tfidf.fit_transform(all_texts)
        except ValueError as e:
            _logger.warning("TF-IDF 拟合失败: %s → 返回零向量", e)
            return np.zeros((len(texts), self.dim), dtype=np.float32)
        if tfidf_mat.shape[1] == 0:
            return np.zeros((len(texts), self.dim), dtype=np.float32)
        # 转 dense
        try:
            dense = tfidf_mat.toarray().astype(np.float32)
        except Exception as e:
            _logger.warning("TF-IDF toarray 失败: %s", e)
            return np.zeros((len(texts), self.dim), dtype=np.float32)
        # 截断/补零到 dim
        D = self.dim
        if dense.shape[1] >= D:
            out = dense[:, :D]
        else:
            pad = np.zeros((dense.shape[0], D - dense.shape[1]), dtype=np.float32)
            out = np.hstack([dense, pad])
        # L2 normalize
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        out = out / norms
        # 取新加的部分
        return out[-len(texts):]

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


# ────────────────────── 向量索引 ──────────────────────

class VectorIndex:
    """向量索引 (内存态 + numpy)。"""

    def __init__(self, embedder: Optional[Embedder] = None):
        self.embedder = embedder or Embedder()
        self.doc_ids: list[str] = []
        self.doc_texts: list[str] = []          # 配套 doc 的原文 (用于 search 时一起 fit)
        self.vectors: Optional[np.ndarray] = None   # (N, D)
        self.doc_meta: dict[str, dict] = {}
        self._dirty = False                     # add/remove 后置 True, 搜索前 refit

    def _refit(self) -> None:
        """重新 fit 所有 doc 的向量 (保证搜索时空间一致)。"""
        if not self.doc_texts:
            self.vectors = None
            return
        # 拼接所有 doc 一起 embed
        all_vecs = self.embedder.embed(self.doc_texts)
        self.vectors = all_vecs
        self._dirty = False

    def add(self, doc_id: str, text: str, meta: Optional[dict] = None) -> None:
        """添加一篇文档 (懒 fit, 下次 search 才 refit)。"""
        if doc_id in self.doc_ids:
            self.remove(doc_id)
        self.doc_ids.append(doc_id)
        self.doc_texts.append(text)
        if meta:
            self.doc_meta[doc_id] = meta
        self._dirty = True

    def remove(self, doc_id: str) -> bool:
        if doc_id not in self.doc_ids:
            return False
        idx = self.doc_ids.index(doc_id)
        self.doc_ids.pop(idx)
        self.doc_texts.pop(idx)
        if self.vectors is not None:
            self.vectors = np.delete(self.vectors, idx, axis=0)
        self.doc_meta.pop(doc_id, None)
        self._dirty = True
        return True

    @property
    def N(self) -> int:
        return len(self.doc_ids)

    def search(
        self,
        query: str,
        top_k: int = 5,
        genre: Optional[str] = None,
        category: Optional[str] = None,
        source: Optional[str] = None,
        agent: Optional[str] = None,
        doc_type: Optional[str] = None,
    ) -> list[VectorHit]:
        if self._dirty or self.vectors is None:
            self._refit()
        if self.vectors is None or self.N == 0:
            return []
        # 重要: query 必须和 doc 在同一向量空间
        # → 把 query 也 join 进 corpus 一起 fit, 然后取最后一行的向量
        corpus = self.doc_texts + [query]
        all_vecs = self.embedder.embed(corpus)
        q_vec = all_vecs[-1].reshape(1, -1)
        doc_vecs = all_vecs[:-1]
        # 余弦相似度 (向量已 L2 normalize)
        sims = (doc_vecs @ q_vec.T).flatten()
        # 取 top_k
        if genre or category or source or agent or doc_type:
            kept: list[tuple[str, float]] = []
            from app.knowledge import agent_in_partition
            for i, doc_id in enumerate(self.doc_ids):
                meta = self.doc_meta.get(doc_id, {})
                if genre and meta.get("genre") != genre:
                    continue
                if category and meta.get("category") != category:
                    continue
                if source and meta.get("source") != source:
                    continue
                if agent and not agent_in_partition(meta.get("agent", ""), agent):
                    continue
                if doc_type and meta.get("doc_type") != doc_type:
                    continue
                kept.append((doc_id, float(sims[i])))
        else:
            kept = [(self.doc_ids[i], float(sims[i])) for i in range(self.N)]
        kept.sort(key=lambda x: x[1], reverse=True)
        out: list[VectorHit] = []
        for doc_id, sc in kept[:top_k]:
            meta = self.doc_meta.get(doc_id, {})
            out.append(VectorHit(doc_id=doc_id, score=sc, snippet=meta.get("snippet", "")[:80]))
        return out


# ────────────────────── 构造 / 持久化 ──────────────────────

def _doc_to_id(doc: KnowledgeDoc) -> str:
    return f"{doc.source}/{doc.category}/{doc.name}"


def _doc_to_embed_text(doc: KnowledgeDoc, max_chars: int = 2000) -> str:
    """取文档前 max_chars 字用于嵌入 (嵌入模型有 token 上限)。"""
    text = doc.content
    if text.startswith("---"):
        end = text.find("\n---\n", 3)
        if end != -1:
            text = text[end + 5:]
    text = text.strip()
    return text[:max_chars]


def _doc_to_snippet(doc: KnowledgeDoc, max_chars: int = 80) -> str:
    text = doc.content
    if text.startswith("---"):
        end = text.find("\n---\n", 3)
        if end != -1:
            text = text[end + 5:]
    return text.strip().replace("\n", " ")[:max_chars]


def build_from_knowledge(
    *,
    source: str = "all",
    for_retrieval: bool = True,
    embedder: Optional[Embedder] = None,
) -> tuple[VectorIndex, str]:
    """
    从 app/knowledge/ 扫描 + 嵌入。
    返回 (index, mode)。
    """
    if embedder is None:
        embedder = Embedder()
    idx = VectorIndex(embedder=embedder)
    sources = (SOURCE_BUILTIN, "local") if source == "all" else (source,)
    for src in sources:
        for cat in PRESET_CATEGORIES:
            if for_retrieval and cat not in INDEX_RETRIEVAL_CATEGORIES:
                continue
            docs = scan_category(cat, src)
            for d in docs:
                idx.add(
                    doc_id=_doc_to_id(d),
                    text=_doc_to_embed_text(d),
                    meta={
                        "name": d.name,
                        "category": d.category,
                        "source": d.source,
                        "genre": d.genre,
                        "tags": d.tags,
                        "agent": d.agent,
                        "doc_type": d.doc_type,
                        "snippet": _doc_to_snippet(d),
                    },
                )
    _logger.info("Vector 索引构建: N=%d, mode=%s, dim=%d",
                 idx.N, idx.embedder.mode, idx.embedder.dim_out)
    return idx, idx.embedder.mode


def save(idx: VectorIndex) -> tuple[Path, Path]:
    """保存向量 + meta。"""
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    if idx.vectors is not None:
        np.save(VECTORS_FILE, idx.vectors)
    with open(META_FILE, "wb") as f:
        pickle.dump({
            "doc_ids": idx.doc_ids,
            "doc_meta": idx.doc_meta,
            "mode": idx.embedder.mode,
            "model_name": idx.embedder.model_name,
            "dim_out": idx.embedder.dim_out,
        }, f, protocol=pickle.HIGHEST_PROTOCOL)
    _logger.info("Vector 索引已保存: N=%d, mode=%s", idx.N, idx.embedder.mode)
    return VECTORS_FILE, META_FILE


def load(embedder: Optional[Embedder] = None) -> Optional[VectorIndex]:
    """加载。"""
    if not VECTORS_FILE.exists() or not META_FILE.exists():
        return None
    try:
        with open(META_FILE, "rb") as f:
            meta = pickle.load(f)
        if embedder is None:
            embedder = Embedder(model_name=meta.get("model_name", DEFAULT_MODEL))
        idx = VectorIndex(embedder=embedder)
        idx.doc_ids = meta.get("doc_ids", [])
        idx.doc_meta = meta.get("doc_meta", {})
        idx.vectors = np.load(VECTORS_FILE)
        _logger.info("Vector 索引已加载: N=%d, mode=%s, dim=%d",
                     idx.N, meta.get("mode"), idx.vectors.shape[1] if idx.vectors is not None else 0)
        return idx
    except Exception as e:
        _logger.warning("加载 Vector 索引失败: %s (需重建)", e)
        return None


# ────────────────────── 主入口 ──────────────────────

def search(
    query: str,
    *,
    top_k: int = 5,
    genre: Optional[str] = None,
    category: Optional[str] = None,
    source: Optional[str] = None,
    agent: Optional[str] = None,
    doc_type: Optional[str] = None,
    idx: Optional[VectorIndex] = None,
) -> list[VectorHit]:
    """一站式检索。"""
    if idx is None:
        idx = load()
        if idx is None:
            idx, _ = build_from_knowledge()
    return idx.search(query, top_k=top_k, genre=genre, category=category,
                      source=source, agent=agent, doc_type=doc_type)


def rebuild(embedder: Optional[Embedder] = None) -> tuple[VectorIndex, str]:
    idx, mode = build_from_knowledge(embedder=embedder)
    save(idx)
    return idx, mode


# ────────────────────── CLI ──────────────────────

if __name__ == "__main__":
    print("=== 重建 Vector 索引 ===")
    t0 = time.time()
    idx, mode = rebuild()
    print(f"耗时: {time.time()-t0:.2f}s  N={idx.N}  mode={mode}  dim={idx.embedder.dim_out}")
    test_queries = ["修真的仙侠故事", "古言宫廷里王爷和侯爷", "密室里的真相", "霸总与灰姑娘"]
    for q in test_queries:
        print(f"\nQuery: {q!r}")
        hits = search(q, top_k=3, idx=idx)
        for h in hits:
            print(f"  - {h.doc_id}  score={h.score:.3f}")
