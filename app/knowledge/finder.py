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
    KNOWLEDGE_ROOT,
    PRESET_CATEGORIES,
    RETRIEVAL_CATEGORIES,
    INDEX_RETRIEVAL_CATEGORIES,
    SOURCE_BUILTIN,
    SOURCE_LOCAL,
    AGENT_GENERAL,
    DOC_MANUAL,
    KB_BUDGET_MANUAL,
    KB_BUDGET_RETRIEVE,
    KB_BUDGET_SHARED,
    KB_BUDGET_TOTAL_PER_AGENT,
    agent_in_partition,
    KnowledgeDoc,
    extract_for_prompt,
    read_doc,
    scan_category,
)
from app.knowledge._bm25 import BM25Index, BM25Hit, build_from_knowledge as bm25_build
from app.knowledge._vector_db import VectorIndex, VectorHit, build_from_knowledge as vector_build

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
    - zvec 模式: FTS + Vector + RRF (默认)
    - Legacy 模式: BM25 + numpy Vector 手动融合 (fallback)
    """

    def __init__(
        self,
        *,
        bm25: Optional[BM25Index] = None,
        vector: Optional[VectorIndex] = None,
        zvec=None,  # ZvecIndex 实例
        w_bm25: float = 0.5,
        w_vector: float = 0.5,
    ):
        self.bm25 = bm25
        self.vector = vector
        self.zvec = zvec  # zvec 优先
        self.w_bm25 = w_bm25
        self.w_vector = w_vector
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
        agent: Optional[str] = None,
        doc_type: Optional[str] = None,
        for_retrieval: bool = True,
    ) -> list[HybridHit]:
        """
        混合检索。
        - zvec 模式: FTS + Vector + RRF (优先)
        - Legacy 模式: BM25 + numpy Vector 手动融合 (fallback)
        """
        if not query.strip():
            return []

        # ---- zvec 路径 ----
        if self.zvec is not None:
            try:
                hits = self.zvec.search(
                    query, top_k=top_k,
                    genre=genre, category=category,
                    source=source, agent=agent, doc_type=doc_type,
                )
                return [
                    HybridHit(
                        doc_id=h.doc_id, score=h.score,
                        bm25_score=0, vector_score=h.score,
                        snippet=h.snippet, name=h.name,
                        category=h.category, genre=h.genre,
                        source=h.source,
                    )
                    for h in hits
                ]
            except Exception as e:
                _logger.warning("zvec search 失败, 降级到 legacy: %s", e)

        # ---- Legacy 路径 (BM25 + Vector) ----
        self._merge_meta()
        # 1) BM25
        bm25_hits: dict[str, float] = {}
        if self.bm25 is not None:
            from app.knowledge._bm25 import tokenize as _bm25_tok
            q_toks = _bm25_tok(query)
            hits = self.bm25.top_k(
                q_toks, k=top_k * 3,    # 多取一些, 融合后截断
                genre=genre, category=category, source=source,
                agent=agent, doc_type=doc_type,
            )
            for h in hits:
                bm25_hits[h.doc_id] = h.score
        # 2) Vector
        vector_hits: dict[str, float] = {}
        if self.vector is not None:
            hits = self.vector.search(
                query, top_k=top_k * 3,
                genre=genre, category=category, source=source,
                agent=agent, doc_type=doc_type,
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
            meta = self._meta.get(did, {})
            # 旧 category 门控 (仅未指定 agent 时生效, 保持旧 RAG 行为)
            if for_retrieval and agent is None:
                if meta.get("category") not in RETRIEVAL_CATEGORIES:
                    continue
            # Agent 分区过滤 (绕过 category 门控)
            if agent is not None:
                if not agent_in_partition(meta.get("agent", ""), agent):
                    continue
            # doc_type 过滤
            if doc_type is not None and meta.get("doc_type") != doc_type:
                continue
            bm25_s = bm25_hits.get(did, 0.0)
            vec_s = vector_hits.get(did, 0.0)
            bm25_n = norm_bm25(bm25_s) if bm25_s > 0 else 0.0
            vec_n = norm_vector(vec_s) if vec_s > 0 else 0.0
            fused = self.w_bm25 * bm25_n + self.w_vector * vec_n
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

    # ────────────────────── 文档内容读取 / 拼装辅助 ──────────────────────

    def _read_doc_content(self, doc_id: str) -> str:
        """按 doc_id (source/category/name) 读正文, 去 frontmatter。"""
        p = KNOWLEDGE_ROOT / f"{doc_id}.md"
        if not p.exists():
            return ""
        try:
            doc = read_doc(p)
        except Exception:
            return ""
        return _strip_frontmatter(doc.content)

    def _hits_to_text(self, hits: list[HybridHit], max_chars: int, label_prefix: str = "") -> str:
        """
        把命中拼成限长文本 (复用旧 extract_for_prompt 逻辑, 但用真实正文而非 snippet)。
        """
        from collections import defaultdict
        by_cat: dict[str, list[HybridHit]] = defaultdict(list)
        for h in hits:
            if len(by_cat[h.category]) < 2:
                by_cat[h.category].append(h)
        chunks: list[str] = []
        used = 0
        for cat, cat_hits in by_cat.items():
            for h in cat_hits:
                if used >= max_chars:
                    break
                text = self._read_doc_content(h.doc_id) or h.snippet
                if used + len(text) > max_chars:
                    text = text[:max_chars - used]
                if text:
                    label = f"{label_prefix}{cat}/{h.name}" if label_prefix else f"{cat}/{h.name}"
                    chunks.append(f"【{label}】\n{text}")
                    used += len(text)
            if used >= max_chars:
                break
        return "\n\n".join(chunks)

    def extract_for_prompt(
        self,
        query: str,
        top_k: int = 3,
        max_total_chars: int = 200,
    ) -> str:
        """
        A1.8 拍板: 检索后拼成 ~200 字, 给 AI 参考 (旧 RAG 行为, 仅文风+桥段)。
        """
        hits = self.search(query, top_k=top_k * 2, for_retrieval=True)
        if not hits:
            return ""
        return self._hits_to_text(hits, max_total_chars)

    def _collect_manuals(self, agent: str, max_chars: int) -> list[str]:
        """
        收集某 Agent 分区的指导手册 (doc_type=manual, agent 命中该分区)。
        指导手册固定注入 system 段, 不占检索预算。
        """
        chunks: list[str] = []
        used = 0
        for source in (SOURCE_BUILTIN, SOURCE_LOCAL):
            for cat in PRESET_CATEGORIES:
                for d in scan_category(cat, source):
                    if d.doc_type != DOC_MANUAL:
                        continue
                    if not agent_in_partition(d.agent, agent):
                        continue
                    text = _strip_frontmatter(d.content)
                    if used + len(text) > max_chars:
                        text = text[:max_chars - used]
                    if text:
                        chunks.append(f"【{cat}/{d.name}】\n{text}")
                        used += len(text)
                    if used >= max_chars:
                        return chunks
        return chunks

    def extract_for_agent(
        self,
        agent: str,
        query: str,
        *,
        include_manual: bool = True,
        include_shared: bool = True,
        manual_max_chars: int = KB_BUDGET_MANUAL,
        retrieve_max_chars: int = KB_BUDGET_RETRIEVE,
        shared_max_chars: int = KB_BUDGET_SHARED,
        top_k: int = 3,
    ) -> str:
        """
        给某 Agent 拼装专属知识块 (分层知识库 M1 核心入口)。

        结构:
        ① 【指导手册】固定注入该 Agent 的 doc_type=manual 块 (永驻, 不占检索预算)
        ② 【专属知识-<agent>】检索该分区相关文档 (按 query 相关度)
        ③ 【共享库】合并 agent=general 的相关文档 (include_shared 时)

        带分节标记, 直接可注入 system 段; user 段保持纯净 (0 污染)。
        """
        sections: list[str] = []
        total = 0
        # ① 指导手册
        if include_manual:
            manuals = self._collect_manuals(agent, manual_max_chars)
            if manuals:
                block = "\n\n".join(manuals)
                sections.append("【指导手册】\n" + block)
                total += len(block)
        # ② 专属分区检索
        if query.strip():
            hits = self.search(query, top_k=top_k, for_retrieval=False, agent=agent)
            # 指导手册已固定注入, 检索段去重避免重复占用预算
            if include_manual:
                hits = [h for h in hits
                        if self._meta.get(h.doc_id, {}).get("doc_type") != DOC_MANUAL]
            if hits:
                txt = self._hits_to_text(hits, retrieve_max_chars, label_prefix=f"专属-{agent}-")
                if txt:
                    sections.append("【专属知识-" + agent + "】\n" + txt)
                    total += len(txt)
        # ③ 共享库
        if include_shared and agent != AGENT_GENERAL and query.strip():
            shared = self.search(query, top_k=top_k, for_retrieval=False, agent=AGENT_GENERAL)
            if include_manual:
                shared = [h for h in shared
                          if self._meta.get(h.doc_id, {}).get("doc_type") != DOC_MANUAL]
            if shared:
                txt = self._hits_to_text(shared, shared_max_chars, label_prefix="共享库-")
                if txt:
                    sections.append("【共享库】\n" + txt)
                    total += len(txt)
        full = "\n\n".join(sections)
        # 总预算封顶
        if total > KB_BUDGET_TOTAL_PER_AGENT:
            full = full[:KB_BUDGET_TOTAL_PER_AGENT]
        return full

    def extract_by_capability(
        self,
        capabilities: list[str],
        query: str,
        *,
        max_total_chars: int = 1500,
        top_k: int = 3,
    ) -> str:
        """
        按Capability检索知识块。

        Args:
            capabilities: Capability名称列表（如 ["narrative", "dialogue"]）
            query: 检索查询
            max_total_chars: 总字符预算
            top_k: 每个Capability检索数量

        Returns:
            str: 拼装后的知识块
        """
        from app.knowledge.capability import search_by_capability

        sections: list[str] = []
        total = 0

        # 按Capability检索
        docs = search_by_capability(capabilities, limit=top_k * len(capabilities))

        for doc in docs:
            content = doc.get("content", "")
            if not content:
                continue

            cap_name = doc.get("capability", "unknown")
            block = f"【{cap_name}】\n{content[:500]}"
            sections.append(block)
            total += len(block)

            if total >= max_total_chars:
                break

        full = "\n\n".join(sections)
        return full[:max_total_chars] if len(full) > max_total_chars else full


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
    use_zvec: bool = True,
) -> HybridFinder:
    """
    从知识库构建混合检索器。

    use_zvec=True (默认): 使用 zvec 原生 FTS+Vector+RRF 混合检索
    use_zvec=False: 使用原有 BM25 + numpy Vector 手动融合 (fallback)
    """
    if use_zvec:
        try:
            from app.knowledge._zvec_index import ZvecIndex
            zvec_idx = ZvecIndex()
            _logger.info("Finder: 使用 zvec 混合检索")
            return HybridFinder(zvec=zvec_idx)
        except Exception as e:
            _logger.warning("zvec 初始化失败, 降级到 legacy: %s", e)

    # Fallback: 原有 BM25 + Vector
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


def extract_for_agent(agent: str, query: str, **kwargs) -> str:
    """一站式: 给某 Agent 拼装专属知识块。"""
    return get_finder().extract_for_agent(agent, query, **kwargs)


def extract_by_capability(capabilities: list[str], query: str, **kwargs) -> str:
    """一站式: 按Capability检索知识块。"""
    return get_finder().extract_by_capability(capabilities, query, **kwargs)


def rebuild_index() -> HybridFinder:
    """
    重建 BM25 + 向量索引 (改/加 frontmatter 或新增文档后调用)。
    重置全局 finder 单例并返回新实例。
    """
    from app.knowledge._bm25 import rebuild as bm25_rebuild
    from app.knowledge._vector_db import rebuild as vector_rebuild
    bm25_rebuild()
    vector_rebuild()
    global _finder
    _finder = None
    return get_finder()


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
