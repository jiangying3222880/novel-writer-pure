-- 050: Book表扩展 (分卷编排需要)
-- 增加卷状态、字数统计、单元数统计

ALTER TABLE books ADD COLUMN outline_id TEXT DEFAULT '';
ALTER TABLE books ADD COLUMN status TEXT DEFAULT 'planning';
ALTER TABLE books ADD COLUMN word_count INTEGER DEFAULT 0;
ALTER TABLE books ADD COLUMN unit_count INTEGER DEFAULT 0;
