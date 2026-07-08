-- 051: 单元池增强 (unit_pool_composer.py 使用)
-- 增加节奏类型、依赖字段、适用题材扩展

-- 扩展unit_pool表
ALTER TABLE unit_pool ADD COLUMN rhythm_type TEXT DEFAULT 'other';
ALTER TABLE unit_pool ADD COLUMN dependency_hooks TEXT DEFAULT '[]';
ALTER TABLE unit_pool ADD COLUMN provide_hooks TEXT DEFAULT '[]';
ALTER TABLE unit_pool ADD COLUMN prerequisites TEXT DEFAULT '[]';
ALTER TABLE unit_pool ADD COLUMN effects TEXT DEFAULT '[]';

-- 创建节奏类型索引
CREATE INDEX IF NOT EXISTS idx_unit_pool_rhythm ON unit_pool(rhythm_type);
