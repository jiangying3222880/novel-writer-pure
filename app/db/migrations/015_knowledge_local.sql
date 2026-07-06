-- 015: knowledge_local
-- H2 拍板: 用户上传的本地知识库 (txt / md)

CREATE TABLE IF NOT EXISTS knowledge_local (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    content TEXT DEFAULT '',
    file_type TEXT DEFAULT 'txt',       -- txt / md
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_kl_project ON knowledge_local(project_id);
