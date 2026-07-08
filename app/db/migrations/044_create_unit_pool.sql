-- 044: 单元池 (unit_pool) — 独立于 project 的故事单元素材库
-- 用户后续在池里放很多 1000 字内的「故事单元」, 规划主线/灵感后,
-- 用这些单元拼装小说 (clone_to_project → 进入 story_units 参与 manuscript_assembly)。
-- 与 story_units 解耦: 池是素材库, 克隆进项目后才成为可成稿单元。
CREATE TABLE IF NOT EXISTS unit_pool (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  genre TEXT DEFAULT '通用',
  scene_type TEXT DEFAULT '',
  emotion TEXT DEFAULT '',
  tags TEXT DEFAULT '[]',
  word_count INTEGER DEFAULT 0,
  source TEXT DEFAULT 'manual',
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_unit_pool_gs ON unit_pool(genre, scene_type);
CREATE INDEX IF NOT EXISTS idx_unit_pool_emotion ON unit_pool(emotion);
CREATE INDEX IF NOT EXISTS idx_unit_pool_source ON unit_pool(source);
