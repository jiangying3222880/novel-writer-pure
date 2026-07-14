"""
ZvecIndex — zvec 检索适配器

替代 _bm25.py + _vector_db.py 的自研检索，使用 zvec 的原生 FTS + Vector + 混合检索。

接口与 VectorIndex 兼容：search() / add() / remove()
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_logger = logging.getLogger("NovelWriter.zvec_index")


@dataclass
class ZvecHit:
    """zvec 检索命中."""
    doc_id: str
    score: float
    snippet: str = ""
    name: str = ""
    category: str = ""
    genre: str = ""
    source: str = ""
    agent: str = ""
    doc_type: str = ""


class ZvecIndex:
    """zvec 检索索引.

    使用 zvec 的 FTS + HNSW Vector + RRF 混合检索。
    替代原有的 BM25 + numpy Vector 手动融合。
    """

    def __init__(self, path: str = "./knowledge_index"):
        import zvec

        self._path = path
        self._collection = None
        self._doc_meta: dict[str, dict] = {}
        self._doc_texts: list[str] = []
        self._doc_ids: list[str] = []

        # 延迟初始化 (首次使用时)
        self._initialized = False

    def _ensure_init(self):
        """懒加载: 首次使用时初始化 zvec collection + 从知识库填充."""
        if self._initialized:
            return
        self._initialized = True

        import zvec

        Path(self._path).mkdir(parents=True, exist_ok=True)
        collection_path = os.path.join(self._path, "zvec_knowledge")

        try:
            # 尝试打开已有 collection
            self._collection = zvec.open(collection_path)
            _logger.info("zvec: 打开已有 collection: %s", collection_path)
        except Exception:
            # 创建新 collection
            schema = zvec.CollectionSchema(
                name="knowledge",
                vectors=zvec.VectorSchema("embedding", zvec.DataType.VECTOR_FP32, 384),
                fields=[
                    zvec.FieldSchema("doc_id", zvec.DataType.STRING),
                    zvec.FieldSchema("content", zvec.DataType.STRING),
                    zvec.FieldSchema("name", zvec.DataType.STRING),
                    zvec.FieldSchema("category", zvec.DataType.STRING),
                    zvec.FieldSchema("genre", zvec.DataType.STRING),
                    zvec.FieldSchema("source", zvec.DataType.STRING),
                    zvec.FieldSchema("agent", zvec.DataType.STRING),
                    zvec.FieldSchema("doc_type", zvec.DataType.STRING),
                ],
            )
            self._collection = zvec.create_and_open(path=collection_path, schema=schema)

            # 创建索引
            try:
                self._collection.create_index("embedding", zvec.HnswIndexParam())
            except Exception as e:
                _logger.warning("HNSW 索引创建失败: %s", e)

            try:
                self._collection.create_index("content", zvec.FtsIndexParam())
            except Exception as e:
                _logger.warning("FTS 索引创建失败: %s", e)

            _logger.info("zvec: 创建新 collection: %s", collection_path)

        # 从知识库填充 (如果 collection 为空)
        try:
            stats = self._collection.stats
            if stats.doc_count == 0:
                self._populate_from_knowledge()
        except Exception:
            self._populate_from_knowledge()

    def _populate_from_knowledge(self):
        """从知识库文档填充 zvec collection (builtin + local)."""
        try:
            from app.knowledge import scan_category, PRESET_CATEGORIES, SOURCE_BUILTIN, SOURCE_LOCAL

            count = 0
            for cat in PRESET_CATEGORIES:
                for source in (SOURCE_BUILTIN, SOURCE_LOCAL):
                    docs = scan_category(cat, source, for_retrieval=True)
                    for doc in docs:
                        # 去掉 frontmatter
                        content = doc.content
                        if content.startswith("---"):
                            end = content.find("\n---\n", 3)
                            if end != -1:
                                content = content[end + 5:]
                        content = content.strip()[:2000]

                        if not content:
                            continue

                        # 清洗 doc_id: zvec 不接受中文和特殊字符, 用 MD5
                        import hashlib
                        raw_id = f"{doc.source}_{doc.category}_{doc.name}"
                        doc_id = "d_" + hashlib.md5(raw_id.encode()).hexdigest()[:16]

                        self.add(doc_id, content, {
                            "name": doc.name,
                            "category": doc.category,
                            "genre": doc.genre or "",
                            "source": doc.source,
                            "agent": doc.agent or "",
                            "doc_type": doc.doc_type or "",
                        })
                        count += 1

            _logger.info("zvec: 从知识库填充 %d 篇文档", count)
        except Exception as e:
            _logger.warning("zvec 填充知识库失败: %s", e)

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
    ) -> list[ZvecHit]:
        """zvec 混合检索 (FTS + Vector + RRF ReRank)."""
        self._ensure_init()

        import zvec

        # 构建 filter 表达式 (zvec 用 = 不是 ==)
        filters = []
        if genre:
            filters.append(f"genre = '{genre}'")
        if category:
            filters.append(f"category = '{category}'")
        if source:
            filters.append(f"source = '{source}'")
        if agent:
            filters.append(f"agent = '{agent}'")
        if doc_type:
            filters.append(f"doc_type = '{doc_type}'")
        filter_expr = " AND ".join(filters) if filters else None

        # 构建混合查询: FTS + Vector
        queries = []

        # FTS 查询 (关键词匹配)
        try:
            queries.append(
                zvec.Query(
                    field_name="content",
                    fts=zvec.Fts(match_string=query),
                )
            )
        except Exception as e:
            _logger.warning("zvec FTS query 失败: %s", e)

        # 如果有 embedding 索引, 也做向量查询
        try:
            # 尝试用 TF-IDF 生成查询向量 (简单实现)
            query_vector = self._text_to_vector(query)
            if query_vector is not None:
                queries.append(
                    zvec.Query(
                        field_name="embedding",
                        vector=query_vector,
                    )
                )
        except Exception as e:
            _logger.warning("zvec Vector query 失败: %s", e)

        if not queries:
            return []

        # 执行混合查询
        results = self._collection.query(
            queries=queries,
            topk=top_k,
            filter=filter_expr,
            reranker=zvec.RrfReRanker(),
            output_fields=["doc_id", "content", "name", "category", "genre", "source", "agent", "doc_type"],
        )

        # 转换结果 (zvec Doc 对象, 用 .field() 或 .fields 访问)
        hits = []
        for doc in results:
            doc_id = doc.id
            try:
                content = doc.field("content") if doc.has_field("content") else ""
                name = doc.field("name") if doc.has_field("name") else ""
                category = doc.field("category") if doc.has_field("category") else ""
                genre = doc.field("genre") if doc.has_field("genre") else ""
                source = doc.field("source") if doc.has_field("source") else ""
                agent = doc.field("agent") if doc.has_field("agent") else ""
                doc_type = doc.field("doc_type") if doc.has_field("doc_type") else ""
            except Exception:
                content = name = category = genre = source = agent = doc_type = ""

            hits.append(ZvecHit(
                doc_id=doc_id,
                score=float(doc.score) if doc.score else 1.0,
                snippet=content[:200],
                name=name,
                category=category,
                genre=genre,
                source=source,
                agent=agent,
                doc_type=doc_type,
            ))

        return hits

    def add(self, doc_id: str, text: str, meta: Optional[dict] = None) -> None:
        """添加/更新文档."""
        self._ensure_init()

        import zvec

        # 生成简单向量 (TF-IDF 风格)
        vector = self._text_to_vector(text)

        fields = {
            "doc_id": doc_id,
            "content": text[:2000],
            "name": meta.get("name", "") if meta else "",
            "category": meta.get("category", "") if meta else "",
            "genre": meta.get("genre", "") if meta else "",
            "source": meta.get("source", "") if meta else "",
            "agent": meta.get("agent", "") if meta else "",
            "doc_type": meta.get("doc_type", "") if meta else "",
        }

        doc = zvec.Doc(
            id=doc_id,
            vectors={"embedding": vector} if vector is not None else None,
            fields=fields,
        )

        try:
            self._collection.upsert([doc])
        except Exception as e:
            _logger.warning("zvec upsert 失败: %s", e)

        # 缓存 meta
        self._doc_meta[doc_id] = meta or {}
        self._doc_ids.append(doc_id)
        self._doc_texts.append(text[:2000])

    def remove(self, doc_id: str) -> bool:
        """删除文档."""
        self._ensure_init()
        try:
            self._collection.delete([doc_id])
            self._doc_meta.pop(doc_id, None)
            return True
        except Exception as e:
            _logger.warning("zvec delete 失败: %s", e)
            return False

    def _text_to_vector(self, text: str):
        """确定性 TF-IDF 风格向量生成 (384 维)."""
        try:
            import numpy as np
            import zlib
            vec = np.zeros(384, dtype=np.float32)
            for i, char in enumerate(text[:500]):
                idx = zlib.crc32(char.encode("utf-8")) % 384
                vec[idx] += 1.0
            # L2 normalize
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            return vec.tolist()
        except Exception:
            return None

    @property
    def N(self) -> int:
        """文档数量."""
        return len(self._doc_ids)
