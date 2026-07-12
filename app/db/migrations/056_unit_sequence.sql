-- 056: 单元复合结构 (sequence_id + seq_order)
-- 方案D: 支持复合单元(容器) + 原子单元(写作单位)
-- 不改变已有平坦单元的行为 (sequence_id='' = 顶层)

ALTER TABLE story_units ADD COLUMN sequence_id TEXT DEFAULT '';
ALTER TABLE story_units ADD COLUMN seq_order INTEGER DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_story_units_sequence ON story_units(sequence_id);
