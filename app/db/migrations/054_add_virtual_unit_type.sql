-- Migration 054: Add 'virtual' to story_units.unit_type CHECK constraint
-- SQLite requires table rebuild to modify CHECK constraints.
-- Idempotent: safe to re-run (checks if already applied).

-- Guard: skip if new table already exists (partial previous run)
CREATE TABLE IF NOT EXISTS story_units_new (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT DEFAULT '',
    unit_no INTEGER DEFAULT 0,
    title TEXT NOT NULL,
    unit_type TEXT DEFAULT 'other' CHECK(unit_type IN ('battle','romance','reveal','transition','climax','setup','payoff','filler','other','virtual')),
    story_order INTEGER DEFAULT 0,
    present_order INTEGER DEFAULT 0,
    status TEXT DEFAULT 'draft' CHECK(status IN ('draft','outlining','writing','completed','split')),
    synopsis TEXT DEFAULT '',
    draft TEXT DEFAULT '',
    word_count INTEGER DEFAULT 0,
    emotion_basis TEXT DEFAULT '',
    transition_type TEXT DEFAULT '',
    transition_text TEXT DEFAULT '',
    pov_character TEXT DEFAULT '',
    timeline_label TEXT DEFAULT '',
    entry_characters TEXT DEFAULT '',
    entry_world TEXT DEFAULT '',
    entry_commitments TEXT DEFAULT '',
    exit_characters TEXT DEFAULT '',
    exit_world TEXT DEFAULT '',
    exit_commitments TEXT DEFAULT '',
    unit_memories TEXT DEFAULT '',
    target_chars INTEGER DEFAULT 0,
    target_chapter_count INTEGER DEFAULT 0,
    current_step INTEGER DEFAULT 0,
    total_steps INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);

-- Only migrate if old table exists and new table is empty
INSERT OR IGNORE INTO story_units_new
    (id, project_id, book_id, unit_no, title, unit_type,
     story_order, present_order, status, synopsis, draft, word_count,
     emotion_basis, transition_type, transition_text,
     pov_character, timeline_label,
     entry_characters, entry_world, entry_commitments,
     exit_characters, exit_world, exit_commitments,
     unit_memories, target_chars, target_chapter_count,
     current_step, total_steps, created_at, updated_at)
SELECT
    id, project_id, book_id, unit_no, title, unit_type,
    story_order, present_order, status, synopsis, draft, word_count,
    emotion_basis, transition_type, transition_text,
    pov_character, timeline_label,
    entry_characters, entry_world, entry_commitments,
    exit_characters, exit_world, exit_commitments,
    unit_memories, target_chars, target_chapter_count,
    current_step, total_steps, created_at, updated_at
FROM story_units
WHERE id NOT IN (SELECT id FROM story_units_new);

-- Drop old table if it still exists
DROP TABLE IF EXISTS story_units;

-- Rename new table
ALTER TABLE story_units_new RENAME TO story_units;

-- Recreate indexes
CREATE INDEX IF NOT EXISTS idx_story_units_project ON story_units(project_id);
CREATE INDEX IF NOT EXISTS idx_story_units_book ON story_units(book_id);
CREATE INDEX IF NOT EXISTS idx_story_units_story_order ON story_units(project_id, book_id, story_order);
CREATE INDEX IF NOT EXISTS idx_story_units_present_order ON story_units(project_id, present_order);
