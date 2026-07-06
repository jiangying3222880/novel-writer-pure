-- v3.5.1 Event 表 + enum 表 (work-3)
--
-- 设计: 每个 Unit 完成时, 自动计算 entry/exit 状态的 diff, 写入 story_events.
-- 段级时间锚点 (step_no + as_of_step) 支持回滚时事件不污染.
--
-- enum 表防拼写错误 + 支持扩展 (workbuddy v4 微调 2).

CREATE TABLE IF NOT EXISTS event_type_enum (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name_zh TEXT NOT NULL
);

INSERT OR IGNORE INTO event_type_enum (code, name_zh) VALUES
    ('character_state',       '角色状态'),
    ('character_relationship', '角色关系'),
    ('character_knowledge',   '角色认知'),
    ('character_location',    '角色位置'),
    ('character_inventory',   '角色物品'),
    ('world_state',           '世界状态'),
    ('world_location',        '地点'),
    ('world_time',            '时间推进'),
    ('hook_plant',            '伏笔埋设'),
    ('hook_payoff',           '伏笔回收'),
    ('promise_made',          '承诺作出'),
    ('promise_broken',        '承诺打破'),
    ('revelation',            '真相揭示');

CREATE TABLE IF NOT EXISTS story_events (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    step_no INTEGER DEFAULT 0,
    event_type TEXT NOT NULL REFERENCES event_type_enum(code),
    entity_type TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    field_name TEXT NOT NULL,
    old_value TEXT DEFAULT '',
    new_value TEXT DEFAULT '',
    description TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_events_project ON story_events(project_id);
CREATE INDEX IF NOT EXISTS idx_events_unit    ON story_events(unit_id, step_no);
CREATE INDEX IF NOT EXISTS idx_events_type   ON story_events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_entity ON story_events(entity_type, entity_name);