-- 036_story_units_enhanced.sql
-- 故事单元模式 Phase 1-1：扩展 story_units 表字段
-- 增加 book_id/双时间线/衔接类型/写作进度等字段

-- ============================================================
-- 1. story_units 表扩字段
-- ============================================================

-- 分卷关联
ALTER TABLE story_units ADD COLUMN book_id TEXT NOT NULL DEFAULT '';
ALTER TABLE story_units ADD COLUMN unit_no INTEGER NOT NULL DEFAULT 0;

-- 双时间线
ALTER TABLE story_units ADD COLUMN present_order INTEGER NOT NULL DEFAULT 0;

-- 衔接类型
ALTER TABLE story_units ADD COLUMN transition_type TEXT NOT NULL DEFAULT 'direct';
ALTER TABLE story_units ADD COLUMN transition_text TEXT DEFAULT '';

-- 视角与时间线标签
ALTER TABLE story_units ADD COLUMN pov_character TEXT DEFAULT '';
ALTER TABLE story_units ADD COLUMN timeline_label TEXT NOT NULL DEFAULT '现在';

-- 写作进度
ALTER TABLE story_units ADD COLUMN target_chars INTEGER NOT NULL DEFAULT 5000;
ALTER TABLE story_units ADD COLUMN current_step INTEGER NOT NULL DEFAULT 0;
ALTER TABLE story_units ADD COLUMN total_steps INTEGER NOT NULL DEFAULT 0;

-- ============================================================
-- 2. 新增索引
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_story_units_book ON story_units(project_id, book_id);
CREATE INDEX IF NOT EXISTS idx_story_units_present_order ON story_units(project_id, present_order);

-- ============================================================
-- 3. 更新 status 约束（增加 outlining 状态）
-- ============================================================

-- SQLite 不能直接修改 CHECK 约束，需要重建表
-- 这里用触发器方式在应用层保证，数据库层放宽
-- 先不做表重建，避免破坏已有数据
