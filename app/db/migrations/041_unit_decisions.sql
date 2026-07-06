-- v3.6 Decision 层
-- 记录 AI/作者对 Guide 的采纳/忽略/修改决策
-- 用途: Explainable AI 回溯, "不是 Guide 错, 是 AI 没采纳"

CREATE TABLE IF NOT EXISTS unit_decisions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    step_no INTEGER DEFAULT 0,
    guide_id TEXT NOT NULL,
    guide_source TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('adopted', 'ignored', 'modified')),
    reason TEXT DEFAULT '',
    decided_by TEXT NOT NULL CHECK (decided_by IN ('ai', 'author')) DEFAULT 'ai',
    decided_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    context TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_decisions_unit ON unit_decisions(unit_id, step_no);
CREATE INDEX IF NOT EXISTS idx_decisions_guide ON unit_decisions(guide_id);
CREATE INDEX IF NOT EXISTS idx_decisions_project ON unit_decisions(project_id);
