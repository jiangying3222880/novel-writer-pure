-- Migration 007: entity_appearances (实体引用索引)
-- Phase 3 M0: 实体重塑 / 扫前后 / 反向查询

CREATE TABLE IF NOT EXISTS entity_appearances (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,              -- 'character' | 'location' | 'item' | 'faction'
    entity_name TEXT NOT NULL,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    draft_id TEXT REFERENCES chapter_drafts(id) ON DELETE CASCADE,
    paragraph_index INTEGER,                -- 段落序号 (用于段落级定位)
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_entity_appearances_entity ON entity_appearances(project_id, entity_name);
CREATE INDEX IF NOT EXISTS idx_entity_appearances_chapter ON entity_appearances(chapter_id);
