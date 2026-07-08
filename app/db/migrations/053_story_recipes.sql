-- 053: Story Recipe表 (story_recipe.py 使用)
-- 一键创建不同创作模式的方案

CREATE TABLE IF NOT EXISTS story_recipes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    description TEXT DEFAULT '',
    genre TEXT DEFAULT '',                    -- 适用题材
    config TEXT DEFAULT '{}',                 -- 配置JSON（知识包、Unit Pool、Capability等）
    is_builtin INTEGER DEFAULT 0,            -- 是否内置
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 内置Recipe示例
INSERT OR IGNORE INTO story_recipes (id, name, display_name, description, genre, config, is_builtin, created_at, updated_at)
VALUES
    ('recipe-xianxia', 'xianxia', '仙侠修炼', '修仙题材创作方案', '修仙',
     '{"knowledge_packs": ["修仙"], "unit_pool": "xianxia", "capabilities": ["narrative", "worldbuilding"], "guide": "仙侠Guide"}',
     1, datetime('now'), datetime('now')),
    ('recipe-urban', 'urban', '都市爽文', '都市题材创作方案', '都市',
     '{"knowledge_packs": ["都市"], "unit_pool": "urban", "capabilities": ["narrative", "dialogue"], "guide": "都市Guide"}',
     1, datetime('now'), datetime('now')),
    ('recipe-mystery', 'mystery', '悬疑推理', '悬疑题材创作方案', '悬疑',
     '{"knowledge_packs": ["悬疑"], "unit_pool": "mystery", "capabilities": ["narrative", "plot", "logic"], "guide": "悬疑Guide"}',
     1, datetime('now'), datetime('now')),
    ('recipe-romance', 'romance', '言情', '言情题材创作方案', '言情',
     '{"knowledge_packs": ["言情"], "unit_pool": "romance", "capabilities": ["narrative", "emotion", "dialogue"], "guide": "言情Guide"}',
     1, datetime('now'), datetime('now'));

CREATE INDEX IF NOT EXISTS idx_story_recipes_genre ON story_recipes(genre);
CREATE INDEX IF NOT EXISTS idx_story_recipes_name ON story_recipes(name);
