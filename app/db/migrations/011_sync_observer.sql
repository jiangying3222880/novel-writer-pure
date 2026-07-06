-- 011: sync_observer
-- D4 + G10: 世界观与章节同步 + 角色追踪 (5 维度)
-- 4.0 现状: world_state_snapshots 已存在 (schema.sql)
-- 9.0 加: character_trackers 5 维度

CREATE TABLE IF NOT EXISTS character_trackers (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    character_name TEXT NOT NULL,
    location TEXT DEFAULT '',
    state TEXT DEFAULT '',
    power_level TEXT DEFAULT '',
    equipment TEXT DEFAULT '',
    relationship TEXT DEFAULT '',
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tracker_project ON character_trackers(project_id);
CREATE INDEX IF NOT EXISTS idx_tracker_chapter ON character_trackers(chapter_id);
CREATE INDEX IF NOT EXISTS idx_tracker_char ON character_trackers(project_id, character_name);

-- G10: 4.0 现状 world_state_snapshots 已存在 (按 entity 拆分的快照)
-- 9.0 不再加快照表，复用现有结构
-- 9.0 加索引 (如果没)
CREATE INDEX IF NOT EXISTS idx_snap_project_chapter ON world_state_snapshots(project_id, chapter_no);
