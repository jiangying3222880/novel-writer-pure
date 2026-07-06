-- 009: subtext_full
-- G3 subtext card 13 字段完整版
-- 4.0 现状 scene_subtext_cards 已有 5 字段，加 8 字段 + source + template_id

ALTER TABLE scene_subtext_cards ADD COLUMN real_intent_others TEXT DEFAULT '';
ALTER TABLE scene_subtext_cards ADD COLUMN emotional TEXT DEFAULT '';
ALTER TABLE scene_subtext_cards ADD COLUMN pacing TEXT DEFAULT '';
ALTER TABLE scene_subtext_cards ADD COLUMN viewpoint TEXT DEFAULT '';
ALTER TABLE scene_subtext_cards ADD COLUMN anti_rules TEXT DEFAULT '';
ALTER TABLE scene_subtext_cards ADD COLUMN callback_to TEXT DEFAULT '';
ALTER TABLE scene_subtext_cards ADD COLUMN scene_map TEXT DEFAULT '';
ALTER TABLE scene_subtext_cards ADD COLUMN ending_scene_state TEXT DEFAULT '';
ALTER TABLE scene_subtext_cards ADD COLUMN source TEXT DEFAULT 'manual';
ALTER TABLE scene_subtext_cards ADD COLUMN template_id TEXT;
ALTER TABLE scene_subtext_cards ADD COLUMN updated_at TEXT DEFAULT (datetime('now'));
