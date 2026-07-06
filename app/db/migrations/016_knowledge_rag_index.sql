-- 016: knowledge_rag_index
-- F1 + F2 拍板: BM25 + 向量 混合检索索引

CREATE TABLE IF NOT EXISTS knowledge_index (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,          -- builtin / local / chapter / entity
    source_id TEXT NOT NULL,
    chunk_index INTEGER DEFAULT 0,
    content TEXT DEFAULT '',
    bm25_tokens TEXT DEFAULT '',        -- 分词后（中文用 jieba）
    vector_blob BLOB,                   -- 向量嵌入 (numpy.tobytes)
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_kidx_source ON knowledge_index(source_type, source_id);
