-- 029: chapter_outlines
-- H1 ai_outline_gen 插件用
-- 一章 3 版本大纲 (A/B/C), 用户选定版本后由 chapter_brief 流程消化

CREATE TABLE IF NOT EXISTS chapter_outlines (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    version TEXT NOT NULL CHECK(version IN ('A', 'B', 'C')),
    outline TEXT NOT NULL,
    core_events TEXT,
    emotion_arc TEXT,
    word_target INTEGER,
    selected INTEGER NOT NULL DEFAULT 0,    -- 0/1, 用户选定的版本
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(chapter_id, version)
);

CREATE INDEX IF NOT EXISTS idx_chapter_outlines_chapter ON chapter_outlines(chapter_id);
CREATE INDEX IF NOT EXISTS idx_chapter_outlines_selected ON chapter_outlines(chapter_id, selected);
