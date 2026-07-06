-- 026: chapters 加 subtext 标记 (G3 决策: 用了 Subtext 的章节在列表后用符号标注)
ALTER TABLE chapters ADD COLUMN has_subtext INTEGER DEFAULT 0;   -- 0/1
ALTER TABLE chapters ADD COLUMN subtext_mode TEXT DEFAULT '';   -- 生成时所用模式
