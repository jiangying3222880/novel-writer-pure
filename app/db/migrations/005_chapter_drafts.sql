-- Migration 005: chapter_drafts (多版本快照)
-- Phase 3 M0: 支持段落重写 / 整章重生成 / 回到前一版

CREATE TABLE IF NOT EXISTS chapter_drafts (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL,           -- 1, 2, 3, ...
    content TEXT NOT NULL,
    source TEXT NOT NULL                   -- 'agent' | 'user' | 'paragraph_rewrite' | 'merge'
        CHECK(source IN ('agent', 'user', 'paragraph_rewrite', 'merge')),
    parent_draft_id TEXT REFERENCES chapter_drafts(id) ON DELETE SET NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(chapter_id, version_no)
);

CREATE INDEX IF NOT EXISTS idx_chapter_drafts_chapter ON chapter_drafts(chapter_id);
