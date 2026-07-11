# zvec (alibaba) v0.5.1 — 完整技术分析

MiMoCode · 2026-07-10T10:30:00+08:00

## 一、zvec 是什么

zvec 是阿里巴巴开源的**嵌入式向量数据库**，v0.5.0+ 已不是纯向量引擎，而是：

```text
zvec = 向量检索 + 全文检索(FTS) + 混合检索 + 持久化
```

关键特性：
- **进程内运行**：不需要独立服务，`pip install zvec` 即用
- **FTS（全文检索）**：v0.5.0 新增，支持中文（内置 jieba 词典）
- **混合检索**：单次 MultiQuery 融合 FTS + Vector + 标量过滤 + ReRank
- **HNSW 索引**：毫秒级向量检索
- **WAL 持久化**：崩溃恢复，数据不丢
- **零外部依赖**：只需 numpy（已有）

---

## 二、与当前系统的对比

| 维度 | 当前系统 (BM25+Vector) | zvec v0.5.1 |
|------|----------------------|-------------|
| **架构** | 自研 BM25 + numpy Vector + 手动融合 | 统一引擎，原生混合检索 |
| **BM25** | jieba 分词 + 自定义词典 + 倒排索引 | FTS（内置 jieba，支持中文） |
| **向量** | sentence-transformers / TF-IDF fallback | HNSW 索引，支持 FP16/FP32/INT8 |
| **混合融合** | 手动 weighted_sum (50/50) | RRF / Weighted ReRank（更优） |
| **持久化** | pickle + numpy 文件 | WAL 日志，崩溃恢复 |
| **部署** | 零依赖（纯 Python） | `pip install zvec`（12.8MB wheel） |
| **Agent 分区** | 按 agent/category/genre 过滤 | filter 表达式（`category == 'tech'`） |
| **中文支持** | jieba + 自定义词典 | 内置 jieba 词典 |
| **并发** | 单进程 | 多进程读，单进程写 |
| **性能** | < 100ms (100 docs) | < 10ms (HNSW) |
| **可扩展性** | 内存限制 | 支持 DiskANN 磁盘索引 |

---

## 三、API 对比

### 当前系统的检索方式

```python
# finder.py
finder = HybridFinder(bm25=bm25_idx, vector=vec_idx)
hits = finder.search("修仙境界", top_k=5, genre="仙侠", agent="writer")
# 内部: BM25 top_k×3 + Vector top_k×3 → weighted_sum 融合 → top_k
```

### zvec 的检索方式

```python
import zvec

# 1. 定义 schema（一次）
schema = zvec.CollectionSchema(
    name="knowledge",
    vectors=zvec.VectorSchema("embedding", zvec.DataType.VECTOR_FP32, 384),
    fields=[
        zvec.FieldSchema("content", zvec.DataType.STRING),
        zvec.FieldSchema("category", zvec.DataType.STRING),
        zvec.FieldSchema("genre", zvec.DataType.STRING),
        zvec.FieldSchema("agent", zvec.DataType.STRING),
    ],
)

# 2. 创建 collection（一次）
collection = zvec.create_and_open(path="./knowledge_index", schema=schema)

# 3. 创建索引
collection.create_index("embedding", HnswIndexParam())
collection.create_index("content", FtsIndexParam())  # FTS 索引

# 4. 插入文档
collection.insert([
    zvec.Doc(
        id="doc_1",
        vectors={"embedding": [0.1, 0.2, ...]},
        content="修仙境界分为炼气、筑基、金丹...",
        category="桥段",
        genre="仙侠",
        agent="writer",
    ),
])

# 5. 混合检索（FTS + Vector + 标量过滤 + ReRank）
results = collection.query(
    queries=[
        zvec.Query(field_name="embedding", vector=query_vector),
        zvec.Query(field_name="content", fts=zvec.Fts(match_string="修仙境界")),
    ],
    topk=5,
    filter="genre == '仙侠' AND agent == 'writer'",
    reranker=zvec.RrfReRanker(),
    output_fields=["content", "category", "genre"],
)
```

---

## 四、迁移可行性评估

### 4.1 技术可行性：✅ 高

| 检查项 | 结果 |
|--------|------|
| Windows 支持 | ✅ `zvec-0.5.1-cp312-cp312-win_amd64.whl` |
| Python 版本 | ✅ 3.10-3.14（当前 3.12） |
| 依赖 | ✅ 仅 numpy（已安装） |
| 安装大小 | ✅ 12.8MB wheel |
| 中文 FTS | ✅ 内置 jieba 词典 |
| 混合检索 | ✅ FTS + Vector + ReRank |

### 4.2 功能匹配度：✅ 高

| 当前需求 | zvec 支持 | 说明 |
|----------|----------|------|
| BM25 关键词检索 | ✅ FTS | 内置 jieba，支持中文 |
| 向量语义检索 | ✅ HNSW | 比 numpy 暴力扫描快 10x+ |
| 混合融合 | ✅ RRF/Weighted | 比手动 weighted_sum 更优 |
| Agent/Category 过滤 | ✅ filter 表达式 | `genre == '仙侠' AND agent == 'writer'` |
| 增量更新 | ✅ insert/upsert/delete | 支持单条和批量 |
| 持久化 | ✅ WAL | 崩溃恢复 |
| 知识库管理 | ✅ Collection API | DDL + DML + DQL 统一 |

### 4.3 迁移风险：⚠️ 中等

| 风险 | 影响 | 缓解 |
|------|------|------|
| 索引迁移 | 需要重新构建索引 | 一次性操作，数据在 SQLite 不丢 |
| API 变化 | finder.py 接口需改 | 保持 `HybridFinder` 类名不变，内部实现替换 |
| jieba 词典差异 | zvec 内置词典可能缺自定义词 | 可配置 `jieba_dict_dir` |
| 性能回归 | 100 docs 下差异不大 | 无风险 |

---

## 五、迁移方案

### Phase 1: 安装 + 验证（1 天）

```bash
pip install zvec
```

验证 zvec 在当前环境可用，FTS + Vector + 混合检索正常。

### Phase 2: 适配器层（2 天）

在 `finder.py` 和 `_vector_db.py` 之间加一个 zvec 适配器：

```python
# app/knowledge/_zvec_index.py (新建)

class ZvecIndex:
    """zvec 适配器，实现与 VectorIndex 相同的接口."""

    def __init__(self, path: str = "./knowledge_index"):
        import zvec
        self.collection = self._open_or_create(path)

    def search(self, query, top_k=5, **filters) -> list:
        # FTS + Vector 混合检索
        ...

    def add(self, doc_id, text, meta=None):
        # 插入/更新文档
        ...

    def remove(self, doc_id):
        # 删除文档
        ...
```

### Phase 3: Finder 切换（1 天）

```python
# finder.py 改动
class HybridFinder:
    def __init__(self, bm25=None, vector=None, zvec=None):
        self.bm25 = bm25       # 保留作为 fallback
        self.vector = vector   # 保留作为 fallback
        self.zvec = zvec       # 新增: zvec 优先

    def search(self, query, top_k=5, **kwargs):
        if self.zvec:
            return self._search_zvec(query, top_k, **kwargs)
        # fallback 到原有 BM25+Vector
        return self._search_legacy(query, top_k, **kwargs)
```

### Phase 4: 索引迁移（1 天）

从现有知识文档重建 zvec 索引。

**总计：~5 天**

---

## 六、成本估算

```text
安装: pip install zvec (12.8MB, 0 费用)
开发: 5 天 (适配器 + Finder切换 + 索引迁移)
运行: 0 费用 (进程内，无服务器)
性能: 100 docs < 10ms, 10000 docs < 50ms
```

---

## 七、结论

### 推荐替换，但分阶段

```text
v4.3 (当前):
  ✅ 保持现有 BM25+Vector
  ✅ 知识库规模小 (100 docs)，够用

v4.4 (建议):
  Phase 1: pip install zvec + 验证
  Phase 2: ZvecIndex 适配器
  Phase 3: Finder 切换 (zvec 优先, legacy fallback)
  Phase 4: 索引迁移

v5.0 (如果知识库扩展到 1000+):
  完全移除 legacy BM25+Vector
  zvec 作为唯一检索引擎
  支持 8000 本小说的段落级索引
```

### 核心理由

1. **zvec v0.5.0+ 已支持 FTS** — 之前的"不支持 BM25"分析已过时
2. **混合检索原生支持** — 比手动 weighted_sum 更优
3. **进程内运行** — 与当前"零依赖"理念一致
4. **大厂质量** — 阿里巴巴开源，活跃维护，社区支持
5. **为未来扩展做准备** — 单元池/证据库增长后，当前系统会成为瓶颈
