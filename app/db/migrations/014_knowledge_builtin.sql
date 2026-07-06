-- 014: knowledge_builtin
-- H2 拍板: 内置知识库 (题材/文风/桥段) + 可增/减/改

CREATE TABLE IF NOT EXISTS knowledge_builtin (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,             -- 文风语料 / 桥段 / 人物人设 / 场景描写 / 框架模板
    genre TEXT NOT NULL,                -- 仙侠 / 古言 / 都市 / 悬疑 / ...
    name TEXT NOT NULL,
    content TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_kb_category ON knowledge_builtin(category);
CREATE INDEX IF NOT EXISTS idx_kb_genre ON knowledge_builtin(genre);
CREATE INDEX IF NOT EXISTS idx_kb_genre_cat ON knowledge_builtin(genre, category);

-- 项目级题材选择 (1 主 + X 辅)
CREATE TABLE IF NOT EXISTS project_genres (
    project_id TEXT NOT NULL,
    genre TEXT NOT NULL,
    is_primary INTEGER DEFAULT 0,       -- 1 = 主题材, 0 = 辅题材
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (project_id, genre)
);
CREATE INDEX IF NOT EXISTS idx_pg_project ON project_genres(project_id);

-- subtext 卡模板 (6 个预置)
CREATE TABLE IF NOT EXISTS subtext_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,                 -- 对峙 / 离别 / 暧昧 / 反转 / 重逢 / 隐瞒
    description TEXT DEFAULT '',
    template_json TEXT DEFAULT '{}',
    built_in INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

-- subtext 项目级模式开关
CREATE TABLE IF NOT EXISTS subtext_project_modes (
    project_id TEXT PRIMARY KEY,
    mode TEXT DEFAULT 'ai_auto',       -- ai_auto / manual / closed
    template_id TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
