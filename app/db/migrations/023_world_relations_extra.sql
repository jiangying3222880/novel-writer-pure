-- 023: world_relations
-- H3 拍板: 实体图+时间线+世界观编辑器 合并为 1 个插件 (4 维度)
-- 4 维度: 人物关系/物品关系/地理关系/时间关系
-- DB 端已在 010 中处理 (world_relations 表)
-- 此迁移加 2 字段支持"时间维度"

ALTER TABLE world_relations ADD COLUMN valid_from_chapter INTEGER;
ALTER TABLE world_relations ADD COLUMN valid_to_chapter INTEGER;
CREATE INDEX IF NOT EXISTS idx_rel_time ON world_relations(project_id, valid_from_chapter, valid_to_chapter);
