-- 047: 反向编译结果表 (reverse_compile.py 使用)
-- 将文本反向解析为结构化数据

CREATE TABLE IF NOT EXISTS reverse_compile_results (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    source_chapter_id TEXT NOT NULL,
    ai_version_hash TEXT NOT NULL,
    author_version_hash TEXT NOT NULL,
    parsed_outline TEXT DEFAULT '{}',  -- JSON: title, synopsis, chapters, worldbuilding
    extracted_patterns TEXT DEFAULT '[]',  -- JSON: 提取的写作模式
    weight_updates TEXT DEFAULT '[]',  -- JSON: 知识权重更新建议
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE INDEX IF NOT EXISTS idx_reverse_compile_project ON reverse_compile_results(project_id);
CREATE INDEX IF NOT EXISTS idx_reverse_compile_chapter ON reverse_compile_results(source_chapter_id);
