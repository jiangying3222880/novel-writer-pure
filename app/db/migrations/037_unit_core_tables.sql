-- 037_unit_core_tables.sql
-- 故事单元模式 Phase 1-2：新增核心表
-- unit_briefs / unit_writing_snapshots / unit_paragraphs /
-- unit_causal_edges / unit_causal_groups / split_configs

-- ============================================================
-- 1. unit_briefs（单元大纲表）
-- ============================================================

CREATE TABLE IF NOT EXISTS unit_briefs (
    id TEXT PRIMARY KEY,
    unit_id TEXT NOT NULL UNIQUE,
    project_id TEXT NOT NULL,
    brief TEXT DEFAULT '',
    core_events TEXT DEFAULT '[]',
    emotion_arc TEXT DEFAULT '',
    cause_summary TEXT DEFAULT '',
    effect_summary TEXT DEFAULT '',
    hooks_planned_plant TEXT DEFAULT '[]',
    hooks_planned_pay TEXT DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_unit_briefs_project ON unit_briefs(project_id);
CREATE INDEX IF NOT EXISTS idx_unit_briefs_unit ON unit_briefs(unit_id);

-- ============================================================
-- 2. unit_writing_snapshots（写作断点快照表）
-- ============================================================

CREATE TABLE IF NOT EXISTS unit_writing_snapshots (
    id TEXT PRIMARY KEY,
    unit_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    step_no INTEGER NOT NULL,
    draft_text TEXT NOT NULL,
    unit_summary TEXT NOT NULL DEFAULT '',
    word_count INTEGER NOT NULL DEFAULT 0,
    character_state TEXT DEFAULT '{}',
    world_state TEXT DEFAULT '{}',
    active_hooks TEXT DEFAULT '[]',
    step_prompt TEXT DEFAULT '',
    model_used TEXT DEFAULT '',
    tokens_used INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_unit_snapshots_unit ON unit_writing_snapshots(unit_id, step_no);
CREATE INDEX IF NOT EXISTS idx_unit_snapshots_project ON unit_writing_snapshots(project_id);

-- ============================================================
-- 3. unit_paragraphs（单元段落表，段落 ID 锚点）
-- ============================================================

CREATE TABLE IF NOT EXISTS unit_paragraphs (
    id TEXT PRIMARY KEY,
    unit_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    text TEXT NOT NULL,
    char_start INTEGER DEFAULT -1,
    char_end INTEGER DEFAULT -1,
    paragraph_type TEXT NOT NULL DEFAULT 'normal',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_unit_paragraphs_unit ON unit_paragraphs(unit_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_unit_paragraphs_project ON unit_paragraphs(project_id);

-- ============================================================
-- 4. unit_causal_edges（因果边表）
-- ============================================================

CREATE TABLE IF NOT EXISTS unit_causal_edges (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    from_unit_id TEXT NOT NULL,
    to_unit_id TEXT NOT NULL,
    edge_type TEXT NOT NULL DEFAULT 'direct',
    description TEXT DEFAULT '',
    strength REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_causal_edges_project ON unit_causal_edges(project_id);
CREATE INDEX IF NOT EXISTS idx_causal_edges_from ON unit_causal_edges(from_unit_id);
CREATE INDEX IF NOT EXISTS idx_causal_edges_to ON unit_causal_edges(to_unit_id);

-- ============================================================
-- 5. unit_causal_groups（剧情线表）
-- ============================================================

CREATE TABLE IF NOT EXISTS unit_causal_groups (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '#4A90D9',
    description TEXT DEFAULT '',
    unit_ids TEXT NOT NULL DEFAULT '[]',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_causal_groups_project ON unit_causal_groups(project_id, sort_order);

-- ============================================================
-- 6. split_configs（分章规则配置表）
-- ============================================================

CREATE TABLE IF NOT EXISTS split_configs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '默认',
    target_chars INTEGER NOT NULL DEFAULT 3000,
    min_chars INTEGER NOT NULL DEFAULT 2000,
    max_chars INTEGER NOT NULL DEFAULT 5000,
    split_strategy TEXT NOT NULL DEFAULT 'auto',
    use_ai_analysis INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_split_configs_project ON split_configs(project_id);
