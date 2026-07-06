-- 031: 世界图谱增强 - 关系类型和强度
-- 支持: 关系类型分类 (情感/利益/敌对/师徒/血缘等) + 强度值 (1-10)
-- 用于: 可视化图谱时按类型着色、按强度调整线宽

ALTER TABLE world_relations ADD COLUMN relation_type TEXT DEFAULT 'general';
ALTER TABLE world_relations ADD COLUMN intensity INTEGER DEFAULT 5;

CREATE INDEX IF NOT EXISTS idx_rel_type ON world_relations(project_id, relation_type);
