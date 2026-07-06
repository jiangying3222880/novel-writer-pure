-- Migration 008: chapters.current_draft_id
-- Phase 3 M0: 章节表加指针列，指向 chapter_drafts 当前活跃版本

-- SQLite 不支持 IF NOT EXISTS for ADD COLUMN，包裹在 try/catch
-- Python 端会先检查列是否存在

ALTER TABLE chapters ADD COLUMN current_draft_id TEXT REFERENCES chapter_drafts(id) ON DELETE SET NULL;
