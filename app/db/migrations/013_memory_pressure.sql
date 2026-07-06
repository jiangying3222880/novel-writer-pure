-- 013: memory_pressure
-- E2 拍板: L1-L4 + 压力计

-- L1 故事弧记忆 (always available)
-- L2 承诺 (commitment) / 世界规则 (immutable)
-- L3 细节检索 (RAG)
-- L4 优雅遗忘

CREATE TABLE IF NOT EXISTS agent_memories (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    chapter_id TEXT,
    level TEXT NOT NULL,                -- L1 / L2 / L3 / L4
    category TEXT NOT NULL,             -- arc_main / arc_sub / arc_char / commitment_active / commitment_promise / world_rule_power / world_rule_view / rag_chunk / faded_detail
    content TEXT DEFAULT '',
    token_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mem_project ON agent_memories(project_id);
CREATE INDEX IF NOT EXISTS idx_mem_level ON agent_memories(project_id, level);
CREATE INDEX IF NOT EXISTS idx_mem_category ON agent_memories(project_id, category);

-- 压力计
CREATE TABLE IF NOT EXISTS narrative_pressures (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    pressure INTEGER DEFAULT 0,
    active_hooks INTEGER DEFAULT 0,
    open_promises INTEGER DEFAULT 0,
    unresolved_subplots INTEGER DEFAULT 0,
    zone TEXT DEFAULT 'green',          -- green / yellow / orange / red
    deadline_chapter INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_press_project ON narrative_pressures(project_id);
CREATE INDEX IF NOT EXISTS idx_press_chapter ON narrative_pressures(chapter_id);
