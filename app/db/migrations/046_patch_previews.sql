-- 046: 增量补丁预览表 (patch_preview.py 使用)
-- 展示AI生成的增量变更，支持人工预览

CREATE TABLE IF NOT EXISTS patch_previews (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    description TEXT NOT NULL,
    estimated_api_cost REAL DEFAULT 0.0,
    estimated_time_seconds REAL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending/applied/rejected
    created_at TEXT NOT NULL,
    applied_at TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (unit_id) REFERENCES story_units(id)
);

CREATE TABLE IF NOT EXISTS patch_changes (
    id TEXT PRIMARY KEY,
    patch_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    paragraph_index INTEGER NOT NULL,
    change_type TEXT NOT NULL,  -- add/delete/modify
    old_content TEXT DEFAULT '',
    new_content TEXT DEFAULT '',
    similarity REAL DEFAULT 0.0,
    FOREIGN KEY (patch_id) REFERENCES patch_previews(id),
    FOREIGN KEY (unit_id) REFERENCES story_units(id)
);

CREATE INDEX IF NOT EXISTS idx_patch_previews_project ON patch_previews(project_id);
CREATE INDEX IF NOT EXISTS idx_patch_previews_unit ON patch_previews(unit_id);
CREATE INDEX IF NOT EXISTS idx_patch_previews_status ON patch_previews(status);
CREATE INDEX IF NOT EXISTS idx_patch_changes_patch ON patch_changes(patch_id);
