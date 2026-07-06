-- 030: project.author
-- 用户反馈缺「作者信息」字段; 在 projects 表加 author TEXT (nullable, 老项目填空)
-- sqlite ALTER TABLE ADD COLUMN 不会影响已有数据, 也不会破坏索引

ALTER TABLE projects ADD COLUMN author TEXT;
