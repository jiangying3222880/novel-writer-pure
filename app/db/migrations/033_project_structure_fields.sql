-- 033_project_structure_fields.sql
-- 把 structure.json 的字段迁到 projects 表，取消 JSON 文件双写

ALTER TABLE projects ADD COLUMN sub_genres TEXT DEFAULT '[]';
ALTER TABLE projects ADD COLUMN volumes INTEGER DEFAULT 1;
ALTER TABLE projects ADD COLUMN chapters_per_volume INTEGER DEFAULT 100;
ALTER TABLE projects ADD COLUMN words_per_chapter INTEGER DEFAULT 2000;
ALTER TABLE projects ADD COLUMN total_chapters INTEGER DEFAULT 0;
ALTER TABLE projects ADD COLUMN total_words INTEGER DEFAULT 0;
