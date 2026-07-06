-- 025: world_characters (D3 5 实体补全: 修炼/地理/法宝/人物/势力)
-- 静态人物档案 (定义/出身/性格/阵营), 区别于 character_trackers (动态 5 维度)
-- 4.0 现状: character_trackers 已存在 (5 维度动态), 此表加静态定义

CREATE TABLE IF NOT EXISTS world_characters (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT DEFAULT '',          -- 主角 / 配角 / 敌人 / 路人
    faction_id TEXT DEFAULT '',    -- 所属势力
    birth TEXT DEFAULT '',         -- 出身
    personality TEXT DEFAULT '',   -- 性格
    description TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_char_project ON world_characters(project_id);
CREATE INDEX IF NOT EXISTS idx_char_faction ON world_characters(faction_id);
