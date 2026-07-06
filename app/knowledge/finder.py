"""
D2 拍板: 知识检索 (BM25 + 向量 + 融合 + 排序)
- 融合策略: 加权求和 (BM25 + 向量 归一化分数)
- 配套 A1.4 拍板的混合检索
- 配套 A1.7 拍板: 只取 文风+桥段
- 配套 A1.8 拍板: 每类抽 1-2 段, 总 ~200 字

融合算法:
1. BM25 分数 → min-max 归一化到 [0, 1]
2. Vector 余弦 → 已在 [-1, 1] → 映射到 [0, 1] (score+1)/2
3. weighted_sum = w_bm25 * bm25_norm + w_vector * vector_norm
4. 按 weighted_sum 降序, 取 top_k
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app.knowledge import (
    INDEX_DIR,
    PRESET_CATEGORIES,
    RETRIEVAL_CATEGORIES,
    SOURCE_BUILTIN,
    KnowledgeDoc,
    extract_for_prompt,
    read_doc,
    scan_category,
)
from app.knowledge.bm25 import BM25Index, BM25Hit, build_from_knowledge as bm25_build
from app.knowledge.vector_db import VectorIndex, VectorHit, build_from_knowledge as vector_build

_logger = logging.getLogger("NovelWriter.finder")


# ────────────────────── 数据类 ──────────────────────

@dataclass
class HybridHit:
    """混合检索命中。"""
    doc_id: str
    score: float             # 融合分数
    bm25_score: float        # BM25 原始 (0 if not hit)
    vector_score: float      # 余弦原始 (0 if not hit)
    snippet: str = ""
    name: str = ""
    category: str = ""
    genre: str = ""
    source: str = ""


# ────────────────────── 混合检索器 ──────────────────────

class HybridFinder:
    """
    混合检索器。
    - 维护 BM25 + Vector 两个索引
    - search() 融合两个分数
    """

    def __init__(
        self,
        *,
        bm25: Optional[BM25Index] = None,
        vector: Optional[VectorIndex] = None,
        w_bm25: float = 0.5,
        w_vector: float = 0.5,
    ):
        self.bm25 = bm25
        self.vector = vector
        self.w_bm25 = w_bm25
        self.w_vector = w_vector
        # 缓存 doc_meta 合并 (两种索引都有, 优先 vector 因为有 doc_texts)
        self._meta: dict[str, dict] = {}

    def _merge_meta(self) -> None:
        """合并两个索引的 meta。"""
        if self.bm25:
            for did, m in self.bm25.doc_meta.items():
                self._meta.setdefault(did, m)
        if self.vector:
            for did, m in self.vector.doc_meta.items():
                self._meta.setdefault(did, m)

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        genre: Optional[str] = None,
        category: Optional[str] = None,
        source: Optional[str] = None,
        for_retrieval: bool = True,
    ) -> list[HybridHit]:
        """
        混合检索。
        for_retrieval=True → 跳过非检索类 (A1.7 拍板)
        """
        if not query.strip():
            return []
        self._merge_meta()
        # 1) BM25
        bm25_hits: dict[str, float] = {}
        if self.bm25 is not None:
            from app.knowledge.bm25 import tokenize as _bm25_tok
            q_toks = _bm25_tok(query)
            hits = self.bm25.top_k(
                q_toks, k=top_k * 3,    # 多取一些, 融合后截断
                genre=genre, category=category, source=source,
            )
            for h in hits:
                bm25_hits[h.doc_id] = h.score
        # 2) Vector
        vector_hits: dict[str, float] = {}
        if self.vector is not None:
            hits = self.vector.search(
                query, top_k=top_k * 3,
                genre=genre, category=category, source=source,
            )
            for h in hits:
                vector_hits[h.doc_id] = h.score
        # 3) 融合
        all_ids = set(bm25_hits.keys()) | set(vector_hits.keys())
        if not all_ids:
            return []
        # 归一化
        bm25_vals = list(bm25_hits.values())
        vector_vals = list(vector_hits.values())
        bm25_min, bm25_max = (min(bm25_vals), max(bm25_vals)) if bm25_vals else (0.0, 1.0)
        v_min, v_max = (min(vector_vals), max(vector_vals)) if vector_vals else (-1.0, 1.0)

        def norm_bm25(s: float) -> float:
            if bm25_max == bm25_min:
                return 0.5 if bm25_hits else 0.0
            return (s - bm25_min) / (bm25_max - bm25_min)

        def norm_vector(s: float) -> float:
            # 余弦在 [-1, 1], 映射到 [0, 1]
            return max(0.0, min(1.0, (s + 1) / 2))

        out: list[HybridHit] = []
        for did in all_ids:
            # 后置过滤: for_retrieval
            if for_retrieval:
                meta = self._meta.get(did, {})
                if meta.get("category") not in RETRIEVAL_CATEGORIES:
                    continue
            bm25_s = bm25_hits.get(did, 0.0)
            vec_s = vector_hits.get(did, 0.0)
            bm25_n = norm_bm25(bm25_s) if bm25_s > 0 else 0.0
            vec_n = norm_vector(vec_s) if vec_s > 0 else 0.0
            fused = self.w_bm25 * bm25_n + self.w_vector * vec_n
            meta = self._meta.get(did, {})
            out.append(HybridHit(
                doc_id=did,
                score=fused,
                bm25_score=bm25_s,
                vector_score=vec_s,
                snippet=meta.get("snippet", "")[:80],
                name=meta.get("name", did.split("/")[-1] if "/" in did else did),
                category=meta.get("category", ""),
                genre=meta.get("genre", ""),
                source=meta.get("source", ""),
            ))
        out.sort(key=lambda x: x.score, reverse=True)
        return out[:top_k]

    def extract_for_prompt(
        self,
        query: str,
        top_k: int = 3,
        max_total_chars: int = 200,
    ) -> str:
        """
        A1.8 拍板: 检索后拼成 ~200 字, 给 AI 参考。
        保持文风 + 桥段 各 1-2 段。
        """
        hits = self.search(query, top_k=top_k * 2, for_retrieval=True)
        if not hits:
            return ""
        # 按 category 分组, 每类最多 2 篇
        from collections import defaultdict
        by_cat: dict[str, list[HybridHit]] = defaultdict(list)
        for h in hits:
            if len(by_cat[h.category]) < 2:
                by_cat[h.category].append(h)
        # 拼装
        chunks: list[str] = []
        used = 0
        for cat, cat_hits in by_cat.items():
            for h in cat_hits:
                if used >= max_total_chars:
                    break
                # 重新读 doc 取正文
                try:
                    doc = read_doc(f"app/knowledge/{h.doc_id}.md")
                except Exception:
                    # 路径猜不到 → 用 snippet
                    text = h.snippet
                else:
                    text = _strip_frontmatter(doc.content)
                if used + len(text) > max_total_chars:
                    text = text[:max_total_chars - used]
                if text:
                    chunks.append(f"【{h.category}/{h.name}】\n{text}")
                    used += len(text)
            if used >= max_total_chars:
                break
        return "\n\n".join(chunks)


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---\n", 3)
        if end != -1:
            text = text[end + 5:]
    return text.strip()


# ────────────────────── 工厂 / 主入口 ──────────────────────

def build_finder(
    *,
    for_retrieval: bool = True,
    w_bm25: float = 0.5,
    w_vector: float = 0.5,
) -> HybridFinder:
    """
    从知识库构建混合检索器。
    - 同时建 BM25 + Vector 索引
    """
    bm25_idx = bm25_build(for_retrieval=for_retrieval)
    vec_idx, mode = vector_build(for_retrieval=for_retrieval)
    return HybridFinder(bm25=bm25_idx, vector=vec_idx, w_bm25=w_bm25, w_vector=w_vector)


# 全局单例 (懒加载)
_finder: Optional[HybridFinder] = None


def get_finder() -> HybridFinder:
    global _finder
    if _finder is None:
        _finder = build_finder()
    return _finder


def search(query: str, top_k: int = 5, **kwargs) -> list[HybridHit]:
    """一站式入口。"""
    return get_finder().search(query, top_k=top_k, **kwargs)


def extract_for_prompt(query: str, top_k: int = 3, max_total_chars: int = 200) -> str:
    """一站式拼装。"""
    return get_finder().extract_for_prompt(query, top_k=top_k, max_total_chars=max_total_chars)


# ────────────────────── CLI ──────────────────────

if __name__ == "__main__":
    print("=== 混合检索 ===")
    f = build_finder()
    print(f"BM25 N={f.bm25.N}  Vector N={f.vector.N}")
    test_qs = [
        "仙侠修真故事",
        "古言宫廷",
        "都市职场的霸总",
        "密室悬疑",
    ]
    for q in test_qs:
        print(f"\nQuery: {q!r}")
        hits = f.search(q, top_k=3)
        for h in hits:
            print(f"  - {h.doc_id:60s}  fused={h.score:.3f}  bm25={h.bm25_score:.2f}  vec={h.vector_score:.2f}")
        print(f"  → 拼装 ({len(f.extract_for_prompt(q))} 字):")
        print(f"  {f.extract_for_prompt(q)[:200]}...")
