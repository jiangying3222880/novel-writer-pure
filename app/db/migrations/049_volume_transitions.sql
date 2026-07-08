-- 049: 卷间过渡表 (book_outline_service.py 使用)
-- 记录前后卷的关联关系

CREATE TABLE IF NOT EXISTS volume_transitions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    from_book_id TEXT NOT NULL,              -- 前一卷
    to_book_id TEXT NOT NULL,                -- 后一卷
    transition_type TEXT DEFAULT 'direct',   -- direct/cliffhanger/time_jump/parallel
    summary TEXT DEFAULT '',                 -- 过渡摘要
    required_memories TEXT DEFAULT '[]',     -- 需要继承的记忆（JSON）
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (from_book_id) REFERENCES books(id),
    FOREIGN KEY (to_book_id) REFERENCES books(id)
);

CREATE INDEX IF NOT EXISTS idx_volume_transitions_project ON volume_transitions(project_id);
CREATE INDEX IF NOT EXISTS idx_volume_transitions_from ON volume_transitions(from_book_id);
CREATE INDEX IF NOT EXISTS idx_volume_transitions_to ON volume_transitions(to_book_id);
