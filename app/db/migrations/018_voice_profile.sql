-- 018: voice_profile
-- G9 拍板: 声音档案 5 维度 (性格/句长/语气词/口头禅/隐喻偏好)
-- 每个角色 1 张

CREATE TABLE IF NOT EXISTS voice_profiles (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    character_name TEXT NOT NULL,
    personality INTEGER DEFAULT 5,         -- 1-10
    sentence_length INTEGER DEFAULT 5,     -- 1-10
    tone_words TEXT DEFAULT '',
    catchphrases TEXT DEFAULT '',
    metaphor_pref INTEGER DEFAULT 5,        -- 1-10
    source TEXT DEFAULT 'manual',           -- manual / ai_inferred
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_voice_project ON voice_profiles(project_id);
CREATE INDEX IF NOT EXISTS idx_voice_char ON voice_profiles(project_id, character_name);
