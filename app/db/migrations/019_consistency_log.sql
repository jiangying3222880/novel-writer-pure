-- 019: consistency_log
-- G5 拍板: 一致性检测 4 维 (人物/地理/时间/物品)
-- 矛盾点日志

CREATE TABLE IF NOT EXISTS consistency_logs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    dimension TEXT NOT NULL,             -- character / location / time / item
    severity TEXT DEFAULT 'warning',     -- info / warning / error
    description TEXT NOT NULL,
    chapter_a INTEGER,
    chapter_b INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_conlog_project ON consistency_logs(project_id);
CREATE INDEX IF NOT EXISTS idx_conlog_chapter ON consistency_logs(chapter_id);
CREATE INDEX IF NOT EXISTS idx_conlog_dim ON consistency_logs(project_id, dimension);
