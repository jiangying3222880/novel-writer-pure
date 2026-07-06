-- 017: style_fingerprint
-- G6 拍板: 风格指纹 5 维度 (修真度/阴谋度/色调/句长/词汇)
-- 1-10 滑块

CREATE TABLE IF NOT EXISTS style_fingerprints (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    cultivation_level INTEGER DEFAULT 5,   -- 1-10
    intrigue_level INTEGER DEFAULT 5,
    tone INTEGER DEFAULT 5,                 -- 1=明 10=暗
    sentence_length INTEGER DEFAULT 5,
    vocabulary INTEGER DEFAULT 5,
    source TEXT DEFAULT 'manual',           -- manual / ai_learned
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_style_project ON style_fingerprints(project_id);
