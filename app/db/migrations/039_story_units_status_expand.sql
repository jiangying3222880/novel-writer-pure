-- Migration 039: Expand story_units status enum and add more fields
-- Need to recreate table because SQLite can't alter CHECK constraints

CREATE TABLE IF NOT EXISTS story_units_new (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT DEFAULT '',
    unit_no INTEGER DEFAULT 0,
    title TEXT DEFAULT '',
    unit_type TEXT DEFAULT 'other' CHECK(unit_type IN ('battle','romance','reveal','transition','climax','setup','payoff','filler','other')),
    story_order INTEGER DEFAULT 0,
    present_order INTEGER DEFAULT 0,
    status TEXT DEFAULT 'draft' CHECK(status IN ('draft','outlining','writing','completed','split')),
    synopsis TEXT DEFAULT '',
    draft TEXT DEFAULT '',
    word_count INTEGER DEFAULT 0,
    emotion_basis TEXT DEFAULT '',
    transition_type TEXT DEFAULT 'direct' CHECK(transition_type IN ('direct','time_jump','pov_switch','flashback','parallel','chekhov','contrast','suspense_front')),
    transition_text TEXT DEFAULT '',
    pov_character TEXT DEFAULT '',
    timeline_label TEXT DEFAULT '现在',
    entry_characters TEXT DEFAULT '',
    entry_world TEXT DEFAULT '',
    entry_commitments TEXT DEFAULT '',
    exit_characters TEXT DEFAULT '',
    exit_world TEXT DEFAULT '',
    exit_commitments TEXT DEFAULT '',
    unit_memories TEXT DEFAULT '',
    target_chars INTEGER DEFAULT 5000,
    target_chapter_count INTEGER DEFAULT 0,
    current_step INTEGER DEFAULT 0,
    total_steps INTEGER DEFAULT 0,
    created_at TEXT DEFAULT '',
    updated_at TEXT DEFAULT '',
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- Copy data with proper column mapping and NULL handling
INSERT INTO story_units_new (
    id, project_id, title, unit_type, story_order, status,
    synopsis, draft, word_count, emotion_basis,
    entry_characters, entry_world, entry_commitments,
    exit_characters, exit_world, exit_commitments,
    unit_memories, target_chapter_count, created_at, updated_at
)
SELECT
    id, project_id,
    COALESCE(title, ''),
    COALESCE(unit_type, 'other'),
    COALESCE(story_order, 0),
    COALESCE(status, 'draft'),
    COALESCE(synopsis, ''),
    COALESCE(draft, ''),
    COALESCE(word_count, 0),
    COALESCE(emotion_basis, ''),
    COALESCE(entry_characters, ''),
    COALESCE(entry_world, ''),
    COALESCE(entry_commitments, ''),
    COALESCE(exit_characters, ''),
    COALESCE(exit_world, ''),
    COALESCE(exit_commitments, ''),
    COALESCE(unit_memories, ''),
    COALESCE(target_chapter_count, 0),
    COALESCE(created_at, ''),
    COALESCE(updated_at, '')
FROM story_units;

DROP TABLE IF EXISTS story_units;
ALTER TABLE story_units_new RENAME TO story_units;

CREATE INDEX IF NOT EXISTS idx_story_units_project ON story_units(project_id);
CREATE INDEX IF NOT EXISTS idx_story_units_story_order ON story_units(project_id, story_order);
CREATE INDEX IF NOT EXISTS idx_story_units_present_order ON story_units(project_id, present_order);
CREATE INDEX IF NOT EXISTS idx_story_units_status ON story_units(status);

-- Also make sure unit_briefs has project_id (some DBs may already have it from 037)
-- Use a safe approach: check if column exists, add if not
-- (SQLite doesn't support IF NOT EXISTS for ADD COLUMN, so we try/catch via the migrator)
