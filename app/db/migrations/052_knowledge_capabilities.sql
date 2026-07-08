-- 052: 知识Capability索引表 (capability.py 使用)
-- 支持按能力维度检索知识

CREATE TABLE IF NOT EXISTS knowledge_capabilities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT DEFAULT '',
    applicable_agents TEXT DEFAULT '[]',  -- 适用的Agent列表（JSON）
    created_at TEXT NOT NULL
);

-- 预置Capability
INSERT OR IGNORE INTO knowledge_capabilities (id, name, display_name, description, applicable_agents, created_at)
VALUES
    ('cap-narrative', 'narrative', '叙事', '叙事技巧和结构', '["writer", "planner", "critic"]', datetime('now')),
    ('cap-dialogue', 'dialogue', '对话', '对话写作技巧', '["writer"]', datetime('now')),
    ('cap-character', 'character', '人物', '人物塑造技巧', '["writer", "planner"]', datetime('now')),
    ('cap-plot', 'plot', '情节', '情节设计技巧', '["planner", "critic"]', datetime('now')),
    ('cap-emotion', 'emotion', '情绪', '情绪表达技巧', '["writer"]', datetime('now')),
    ('cap-worldbuilding', 'worldbuilding', '世界观', '世界观构建技巧', '["planner"]', datetime('now')),
    ('cap-logic', 'logic', '逻辑', '逻辑一致性检查', '["critic"]', datetime('now')),
    ('cap-language', 'language', '语言', '语言风格技巧', '["writer", "editor"]', datetime('now')),
    ('cap-history', 'history', '历史', '历史知识', '[]', datetime('now')),
    ('cap-legal', 'legal', '法律', '法律知识', '[]', datetime('now')),
    ('cap-medical', 'medical', '医疗', '医疗知识', '[]', datetime('now'));

-- 知识文档Capability关联表
CREATE TABLE IF NOT EXISTS knowledge_doc_capabilities (
    doc_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    PRIMARY KEY (doc_id, capability_id),
    FOREIGN KEY (capability_id) REFERENCES knowledge_capabilities(id)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_doc_caps_doc ON knowledge_doc_capabilities(doc_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_doc_caps_cap ON knowledge_doc_capabilities(capability_id);
