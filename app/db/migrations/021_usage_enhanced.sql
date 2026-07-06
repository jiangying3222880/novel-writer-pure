-- 021: usage_enhanced
-- A2 拍板: 用量统计
-- 4.0 现状 usage_records 已存在 (schema.sql): id/project_id/chapter_id/provider/model/step/tokens_in/tokens_out/cost/duration_ms/created_at
-- 4.0 用 step (不是 task_type) → 这里加索引

CREATE INDEX IF NOT EXISTS idx_usage_project_date ON usage_records(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_usage_step ON usage_records(step);
CREATE INDEX IF NOT EXISTS idx_usage_provider ON usage_records(provider);

-- 月度汇总 (A2 用量统计)
CREATE TABLE IF NOT EXISTS usage_summary (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    month TEXT NOT NULL,                -- 'YYYY-MM'
    total_input_tokens INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    total_cost REAL DEFAULT 0.0,
    step_breakdown TEXT DEFAULT '{}',   -- {"write": 0.4, "subtext": 0.05, ...}
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(project_id, month)
);
CREATE INDEX IF NOT EXISTS idx_usum_project ON usage_summary(project_id);
