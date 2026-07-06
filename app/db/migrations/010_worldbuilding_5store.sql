-- 010: worldbuilding_5store
-- D3 拍板：5 张表 (修炼/地理/法宝/人物/势力) + 5 文件 store 双向同步
-- 静态存 MD，动态存 DB
-- 这里只建 DB 端 5 表，5 文件 store 在 Python 端

CREATE TABLE IF NOT EXISTS world_power_systems (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    level INTEGER DEFAULT 0,
    description TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_power_project ON world_power_systems(project_id);

CREATE TABLE IF NOT EXISTS world_locations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    region TEXT DEFAULT '',
    description TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_loc_project ON world_locations(project_id);

CREATE TABLE IF NOT EXISTS world_items (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    owner TEXT DEFAULT '',
    tier TEXT DEFAULT '',
    description TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_item_project ON world_items(project_id);

CREATE TABLE IF NOT EXISTS world_factions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_faction_project ON world_factions(project_id);

CREATE TABLE IF NOT EXISTS world_relations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    src_id TEXT NOT NULL,
    src_type TEXT NOT NULL,
    dst_id TEXT NOT NULL,
    dst_type TEXT NOT NULL,
    relation TEXT NOT NULL,
    metadata TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_rel_project ON world_relations(project_id);
CREATE INDEX IF NOT EXISTS idx_rel_src ON world_relations(src_id, src_type);
CREATE INDEX IF NOT EXISTS idx_rel_dst ON world_relations(dst_id, dst_type);
