-- 048: 卷纲表 (book_outline_service.py 使用)
-- 支持分卷编排，定义每卷的核心内容和目标

CREATE TABLE IF NOT EXISTS book_outlines (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    core_theme TEXT DEFAULT '',           -- 卷核心主题
    emotion_arc TEXT DEFAULT '',          -- 卷情绪曲线描述
    key_events TEXT DEFAULT '[]',        -- 关键事件列表（JSON）
    character_arcs TEXT DEFAULT '[]',    -- 角色弧线（JSON）
    hook_plants TEXT DEFAULT '[]',       -- 计划埋设的伏笔（JSON）
    hook_payoffs TEXT DEFAULT '[]',      -- 计划回收的伏笔（JSON）
    target_word_count INTEGER DEFAULT 0, -- 目标字数
    target_unit_count INTEGER DEFAULT 0, -- 目标单元数
    status TEXT DEFAULT 'planning',      -- planning/in_progress/completed
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (book_id) REFERENCES books(id),
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE INDEX IF NOT EXISTS idx_book_outlines_book ON book_outlines(book_id);
CREATE INDEX IF NOT EXISTS idx_book_outlines_project ON book_outlines(project_id);
CREATE INDEX IF NOT EXISTS idx_book_outlines_status ON book_outlines(status);
