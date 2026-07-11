"""
H2 Knowledge 服务 (原插件, 已固化)
- 封装 app.knowledge (C1/D1/D2/F1/F2) 的能力
- 暴露 4 个用户常用维度: 文风 / 桥段 / 人设 / 场景
  (框架模板 是 engine 内部用, 不计入 H2 维度)
- 操作: search / import_file / list_by_dimension / stats

DB: 无 (明文 MD 文件系统)
依赖: app.knowledge (importer/finder/bm25/vector_db)
"""
from __future__ import annotations

import logging
import re as _re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.knowledge import (
    BUILTIN_DIR, LOCAL_DIR, INDEX_DIR,
    PRESET_CATEGORIES, RETRIEVAL_CATEGORIES,
    SOURCE_BUILTIN, SOURCE_LOCAL,
    KnowledgeDoc, bootstrap, count_all,
    scan_category, read_doc, extract_for_prompt,
)

_logger = logging.getLogger("NovelWriter.plugin.knowledge")


# ────────────────────── 4 维度定义 ──────────────────────

# 4 维度: 用户写章节时会用到的 4 类知识
DIMENSION_STYLE = "style"        # 文风语料
DIMENSION_PLOT = "plot"          # 桥段
DIMENSION_CHARACTER = "character"  # 人物人设
DIMENSION_SCENE = "scene"        # 场景描写

DIMENSIONS = (
    DIMENSION_STYLE,
    DIMENSION_PLOT,
    DIMENSION_CHARACTER,
    DIMENSION_SCENE,
)

# 维度 → 知识库 category
DIMENSION_TO_CATEGORY = {
    DIMENSION_STYLE: "文风语料",
    DIMENSION_PLOT: "桥段",
    DIMENSION_CHARACTER: "人物人设",
    DIMENSION_SCENE: "场景描写",
}

CATEGORY_TO_DIMENSION = {v: k for k, v in DIMENSION_TO_CATEGORY.items()}

DIMENSION_LABELS = {
    DIMENSION_STYLE: "文风语料",
    DIMENSION_PLOT: "桥段",
    DIMENSION_CHARACTER: "人物人设",
    DIMENSION_SCENE: "场景描写",
}

DIMENSION_DESCRIPTIONS = {
    DIMENSION_STYLE: "作者风格 / 文笔范例 (供 AI 学习语气)",
    DIMENSION_PLOT: "常见套路 / 经典桥段 (供 AI 借鉴情节)",
    DIMENSION_CHARACTER: "主角/反派/配角人设模板",
    DIMENSION_SCENE: "场景 / 环境 / 氛围描写模板",
}

# 可检索维度 (A1.7 拍板: 只取 文风+桥段 进 RAG)
RETRIEVAL_DIMENSIONS = frozenset({DIMENSION_STYLE, DIMENSION_PLOT})


# ────────────────────── 检索结果数据类 ──────────────────────

@dataclass
class KnowledgeHit:
    """单条检索命中。"""
    dimension: str
    dimension_label: str
    name: str
    category: str
    source: str           # builtin / local
    genre: str
    score: float = 0.0
    snippet: str = ""
    path: str = ""

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "dimension_label": self.dimension_label,
            "name": self.name,
            "category": self.category,
            "source": self.source,
            "genre": self.genre,
            "score": self.score,
            "snippet": self.snippet[:200],
            "path": self.path,
        }


# ────────────────────── 插件实现 ──────────────────────

class KnowledgePlugin:
    """
    H2 知识库服务。

    功能:
      - search(query, dimension, top_k)  按维度检索
      - search_multi(query, dims, top_k)  跨多维度
      - import_file(path, dimension)      导入到指定维度
      - list_by_dimension(dimension)      列某维度所有文档
      - stats()                           各维度统计
      - refresh()                         重新扫描 (导入后调)
    """

    def __init__(self):
        self._finder = None  # HybridFinder (懒加载)

    # ─────────────── 检索 ───────────────

    def _get_finder(self):
        """懒加载 HybridFinder。"""
        if self._finder is None:
            try:
                from app.knowledge.finder import build_finder
                self._finder = build_finder()
            except Exception as e:
                _logger.warning("HybridFinder 初始化失败, 降级: %s", e)
                self._finder = None
        return self._finder

    def search(
        self,
        query: str,
        dimension: str,
        *,
        top_k: int = 5,
        source: str = SOURCE_BUILTIN,
    ) -> list[KnowledgeHit]:
        """
        按维度检索。
        - dimension: 4 维度之一 (DIMENSION_STYLE 等)
        - 非检索维度 (人设/场景) 走 fallback: 简单关键词匹配
        """
        if dimension not in DIMENSIONS:
            raise ValueError(f"未知维度: {dimension} (合法: {DIMENSIONS})")
        category = DIMENSION_TO_CATEGORY[dimension]

        # 优先用 HybridFinder
        finder = self._get_finder()
        if finder and hasattr(finder, "search"):
            try:
                hits = finder.search(query, top_k=top_k, source=source,
                                     category=category)
                out: list[KnowledgeHit] = []
                for h in hits:
                    out.append(KnowledgeHit(
                        dimension=dimension,
                        dimension_label=DIMENSION_LABELS[dimension],
                        name=getattr(h, "name", ""),
                        category=category,
                        source=getattr(h, "source", source),
                        genre=getattr(h, "genre", "通用"),
                        score=getattr(h, "score", 0.0),
                        snippet=getattr(h, "snippet", ""),
                        path=getattr(h, "path", ""),
                    ))
                # 命中数 >= 1 → 直接返回, 否则降级 (避免空索引时无声失败)
                if out:
                    return out
            except Exception as e:
                _logger.warning("HybridFinder.search 失败, 降级: %s", e)

        # Fallback: 简单关键词 (索引未加载/无命中时兜底)
        return self._fallback_search(query, category, source, top_k)

    def _fallback_search(
        self, query: str, category: str, source: str, top_k: int,
    ) -> list[KnowledgeHit]:
        """降级: 基于内容关键词匹配的简单检索。"""
        keywords = [k for k in _re.split(r"[\s,，]+", query) if k]
        if not keywords:
            return []
        docs = scan_category(category, source, for_retrieval=True)
        if not docs and source == SOURCE_BUILTIN:
            # 检索范围 (文风/桥段) 才有, 人设/场景不在 RETRIEVAL, 直接扫
            docs = scan_category(category, source, for_retrieval=False)
        scored: list[tuple[int, KnowledgeDoc]] = []
        for d in docs:
            text = d.content
            score = sum(text.count(k) for k in keywords)
            if score > 0:
                scored.append((score, d))
        scored.sort(key=lambda x: x[0], reverse=True)
        out: list[KnowledgeHit] = []
        for score, d in scored[:top_k]:
            dim = CATEGORY_TO_DIMENSION.get(d.category, "")
            out.append(KnowledgeHit(
                dimension=dim,
                dimension_label=DIMENSION_LABELS.get(dim, d.category),
                name=d.name,
                category=d.category,
                source=d.source,
                genre=d.genre,
                score=float(score),
                snippet=d.content[:200],
                path=str(d.path),
            ))
        return out

    def search_multi(
        self,
        query: str,
        dimensions: Optional[list[str]] = None,
        *,
        top_k_per_dim: int = 3,
    ) -> dict[str, list[KnowledgeHit]]:
        """跨多维度检索 → {dimension: [hits]}。"""
        if dimensions is None:
            dimensions = list(RETRIEVAL_DIMENSIONS)  # 默认只检索 文风+桥段
        return {
            d: self.search(query, d, top_k=top_k_per_dim)
            for d in dimensions
        }

    def extract_for_prompt(
        self,
        query: str,
        *,
        dimensions: Optional[list[str]] = None,
        max_total_chars: int = 300,
    ) -> str:
        """
        把多维度的检索结果拼成 prompt 文本 (限长)。
        默认只取可检索维度 (文风+桥段)。
        """
        if dimensions is None:
            dimensions = list(RETRIEVAL_DIMENSIONS)
        parts: list[str] = []
        for d in dimensions:
            hits = self.search(query, d, top_k=2)
            for h in hits:
                if h.snippet:
                    parts.append(f"【{h.dimension_label}/{h.name}】\n{h.snippet[:150]}")
        text = "\n\n".join(parts)
        if len(text) > max_total_chars:
            text = text[:max_total_chars] + "…"
        return text

    def extract_for_agent(
        self,
        agent: str,
        query: str,
        **kwargs,
    ) -> str:
        """
        分层知识库 M1: 给某 Agent 拼装专属知识块。
        agent ∈ {orchestration, writing, general}。直接注入 system 段。
        """
        from app.knowledge.finder import extract_for_agent as _ea
        return _ea(agent, query, **kwargs)

    def rebuild_index(self):
        """
        重建知识索引 (新增/修改文档或 frontmatter 后调用)。
        返回新的 HybridFinder。
        """
        from app.knowledge.finder import rebuild_index
        return rebuild_index()

    # ─────────────── 列表 / 统计 ───────────────

    def list_by_dimension(
        self,
        dimension: str,
        source: str = SOURCE_BUILTIN,
    ) -> list[KnowledgeDoc]:
        """列出某维度下所有文档。"""
        if dimension not in DIMENSIONS:
            raise ValueError(f"未知维度: {dimension}")
        category = DIMENSION_TO_CATEGORY[dimension]
        return scan_category(category, source, for_retrieval=False)

    def stats(self) -> dict:
        """统计各维度 (按 source 拆分)。"""
        out: dict = {
            "total": 0,
            "by_dimension": {},
            "by_source": {SOURCE_BUILTIN: 0, SOURCE_LOCAL: 0},
        }
        for dim in DIMENSIONS:
            cat = DIMENSION_TO_CATEGORY[dim]
            bu = len(scan_category(cat, SOURCE_BUILTIN, for_retrieval=False))
            lo = len(scan_category(cat, SOURCE_LOCAL, for_retrieval=False))
            out["by_dimension"][dim] = {
                "label": DIMENSION_LABELS[dim],
                "builtin": bu,
                "local": lo,
                "total": bu + lo,
                "retrieval_enabled": dim in RETRIEVAL_DIMENSIONS,
            }
            out["total"] += bu + lo
            out["by_source"][SOURCE_BUILTIN] += bu
            out["by_source"][SOURCE_LOCAL] += lo
        return out

    # ─────────────── 导入 ───────────────

    def import_file(
        self,
        path: str | Path,
        *,
        dimension: Optional[str] = None,
        category: Optional[str] = None,
        genre: Optional[str] = None,
        use_ai: bool = True,
        overwrite: bool = False,
    ) -> dict:
        """
        导入一个文件 (.txt / .md) 到指定维度 (或 category)。
        - dimension: 4 维度之一 (DIMENSION_STYLE 等), 与 category 二选一
        - 若两者都未指定, 自动用 AI 推断
        """
        if dimension is not None and category is None:
            if dimension not in DIMENSIONS:
                raise ValueError(f"未知维度: {dimension}")
            category = DIMENSION_TO_CATEGORY[dimension]
        try:
            from app.knowledge.importer import import_file
            result = import_file(
                path, category=category, genre=genre, use_ai=use_ai, overwrite=overwrite,
            )
            # import_file 返回 ImportResult, 转 dict
            return {
                "ok": True,
                "path": str(getattr(result, "path", "")),
                "category": getattr(result, "category", ""),
                "genre": getattr(result, "genre", "通用"),
                "skipped": getattr(result, "skipped", False),
                "reason": getattr(result, "reason", ""),
            }
        except Exception as e:
            _logger.exception("导入失败: %s", e)
            return {"ok": False, "error": str(e)}

    # ─────────────── 元信息 (UI 用) ───────────────

    def get_dimensions(self) -> list[dict]:
        """返回 4 维度元信息 (UI 渲染用)。"""
        return [
            {
                "id": d,
                "label": DIMENSION_LABELS[d],
                "description": DIMENSION_DESCRIPTIONS[d],
                "category": DIMENSION_TO_CATEGORY[d],
                "retrieval_enabled": d in RETRIEVAL_DIMENSIONS,
            }
            for d in DIMENSIONS
        ]


# 导出
__all__ = [
    "DIMENSION_STYLE", "DIMENSION_PLOT", "DIMENSION_CHARACTER", "DIMENSION_SCENE",
    "DIMENSIONS", "DIMENSION_TO_CATEGORY", "CATEGORY_TO_DIMENSION",
    "DIMENSION_LABELS", "DIMENSION_DESCRIPTIONS", "RETRIEVAL_DIMENSIONS",
    "KnowledgeHit",
    "KnowledgePlugin",
]
