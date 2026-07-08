-- 045: 冲突日志表 (conflict_log.py 使用)
-- 记录因果冲突，支持人工干预

CREATE TABLE IF NOT EXISTS conflict_logs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    conflict_type TEXT NOT NULL,  -- causal/hook/timeline/character/world
    description TEXT NOT NULL,
    source_a TEXT NOT NULL,
    source_b TEXT NOT NULL,
    resolution TEXT NOT NULL DEFAULT 'pending',  -- pending/override_a/override_b/merge/manual
    resolution_note TEXT DEFAULT '',
    confidence REAL DEFAULT 0.5,
    affected_paragraphs TEXT DEFAULT '[]',  -- JSON array
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (unit_id) REFERENCES story_units(id)
);

CREATE INDEX IF NOT EXISTS idx_conflict_logs_project ON conflict_logs(project_id);
CREATE INDEX IF NOT EXISTS idx_conflict_logs_unit ON conflict_logs(unit_id);
CREATE INDEX IF NOT EXISTS idx_conflict_logs_resolution ON conflict_logs(resolution);
