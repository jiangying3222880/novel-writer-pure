-- 027: chapter_critiques
-- G1 v3 写作引擎 Step 6 评估存档 (6 维评分)

CREATE TABLE IF NOT EXISTS chapter_critiques (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL,
    draft_id TEXT NOT NULL,
    score INTEGER DEFAULT 0,
    axes_json TEXT DEFAULT '{}',  -- {plot/character/writing/rhythm/style/foreshadow}
    summary TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_critiques_chapter ON chapter_critiques(chapter_id);
CREATE INDEX IF NOT EXISTS idx_critiques_draft ON chapter_critiques(draft_id);
