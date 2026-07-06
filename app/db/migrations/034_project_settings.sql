-- 034_project_settings.sql
-- 项目级 key-value 配置表，统一存储 hooks/voice_profiles/foreshadowing/notes 等 JSON 数据
-- 替代分散在项目目录下的 JSON sidecar 文件

CREATE TABLE IF NOT EXISTS project_settings (
    project_id TEXT NOT NULL,
    key TEXT NOT NULL,
    data TEXT,                    -- JSON 内容 (可为 NULL)
    updated_at REAL DEFAULT (strftime('%s', 'now')),
    PRIMARY KEY (project_id, key),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_project_settings_project ON project_settings(project_id);
CREATE INDEX IF NOT EXISTS idx_project_settings_key ON project_settings(key);