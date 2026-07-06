-- Migration 006: chapter_change_log (修改流水)
-- Phase 3 M0: 审计/撤销/回溯

CREATE TABLE IF NOT EXISTS chapter_change_log (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    change_type TEXT NOT NULL              -- 'regen' | 'paragraph_rewrite' | 'manual_edit' | 'entity_reshape'
        CHECK(change_type IN ('regen', 'paragraph_rewrite', 'manual_edit', 'entity_reshape')),
    scope TEXT NOT NULL                     -- 'chapter' | 'paragraph'
        CHECK(scope IN ('chapter', 'paragraph')),
    target_draft_id TEXT REFERENCES chapter_drafts(id) ON DELETE SET NULL,
    note TEXT,                              -- 用户反馈 / critic 评语
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_change_log_chapter ON chapter_change_log(chapter_id, created_at DESC);
