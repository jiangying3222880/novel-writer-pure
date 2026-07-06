-- Novel Writer Pure v4 - Database Schema
-- 8 tables for novel writing workflow

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    book_title TEXT,
    genre TEXT,
    platform TEXT,
    word_target INTEGER DEFAULT 200000,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS books (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    volume_no INTEGER NOT NULL,
    title TEXT,
    synopsis TEXT,
    target_chapters INTEGER DEFAULT 100,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS chapters (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chapter_no INTEGER NOT NULL,
    status TEXT DEFAULT 'draft' CHECK(status IN ('draft', 'generated', 'critiqued', 'persisted', 'reviewed')),
    title TEXT,
    scene_context TEXT,
    draft TEXT,
    final TEXT,
    critique TEXT,
    checkpoint TEXT,
    word_count INTEGER DEFAULT 0,
    review_flag TEXT DEFAULT 'pending' CHECK(review_flag IN ('pending', 'accepted', 'problem')),
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS chapter_briefs (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    brief TEXT,
    core_events TEXT,
    emotion_arc TEXT,
    volume_no INTEGER,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS agent_memory (
    id TEXT PRIMARY KEY,
    chapter_id TEXT REFERENCES chapters(id) ON DELETE CASCADE,
    tier TEXT NOT NULL CHECK(tier IN ('L1', 'L2', 'L3', 'L4')),
    entity_type TEXT,
    entity_name TEXT,
    content TEXT NOT NULL,
    token_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS world_state_snapshots (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chapter_no INTEGER NOT NULL,
    entity_name TEXT NOT NULL,
    entity_kind TEXT,
    state_value TEXT,
    changes_delta TEXT,
    source TEXT DEFAULT 'observer' CHECK(source IN ('observer', 'manual', 'imported')),
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(project_id, chapter_no, entity_name)
);

CREATE TABLE IF NOT EXISTS scene_subtext_cards (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    surface_event TEXT,
    true_intent TEXT,
    lie TEXT,
    truth TEXT,
    physical_anchor TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS usage_records (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    chapter_id TEXT REFERENCES chapters(id) ON DELETE SET NULL,
    provider TEXT,
    model TEXT,
    step TEXT,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost REAL DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
