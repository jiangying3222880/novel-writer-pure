-- 032: 双层风格指纹 (L1 作者指纹 + L2 作品指纹)
-- 取代旧的 017_style_fingerprint 单表 5 维 (题材属性)
-- 
-- L1 作者指纹 (6 维, 跨书迁移):
--   句子节奏 / 对话密度 / 描写风格 / 情绪表达 / 段落密度 / 语言层级
--   → 描述的是"这作者怎么写", 不是"这小说写什么"
--   → 新书自动继承
--
-- L2 作品指纹 (4 维, 随书而定):
--   题材基调 / 氛围取向 / 叙事复杂度 / 节奏偏好
--   → 描述的是"这本小说的调性", 新书重新初始化

-- ═══════════════════ L1 作者指纹 ═══════════════════
CREATE TABLE IF NOT EXISTS author_fingerprints (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    sentence_rhythm INTEGER DEFAULT 5,       -- 1=短促 10=流水
    dialogue_density INTEGER DEFAULT 5,      -- 1=叙述为主 10=对话为主
    description_style INTEGER DEFAULT 5,     -- 1=动作驱动 10=氛围描写
    emotion_expression INTEGER DEFAULT 5,    -- 1=直说情绪 10=身体暗示
    paragraph_density INTEGER DEFAULT 5,     -- 1=密集长段落 10=舒朗短段落
    language_level INTEGER DEFAULT 5,        -- 1=口语/网络语 10=文学/书面语
    source TEXT DEFAULT 'manual',            -- manual / ai_learned / hybrid
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_author_fp_user ON author_fingerprints(user_id);

-- ═══════════════════ L2 作品指纹 ═══════════════════
CREATE TABLE IF NOT EXISTS book_fingerprints (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    genre_tone INTEGER DEFAULT 5,            -- 1=轻快明亮 10=厚重暗沉 (从设定+题材提取)
    atmosphere_tendency INTEGER DEFAULT 5,   -- 1=温情日常 10=紧张压迫 (从潜文本聚合)
    narrative_complexity INTEGER DEFAULT 5,  -- 1=单线简单 10=多线交织 (角色数+伏笔+阵营)
    pacing_preference INTEGER DEFAULT 5,     -- 1=快节奏 10=慢热铺垫 (从大纲碰撞密度推算)
    source TEXT DEFAULT 'manual',            -- manual / ai_learned / hybrid
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_book_fp_project ON book_fingerprints(project_id);
