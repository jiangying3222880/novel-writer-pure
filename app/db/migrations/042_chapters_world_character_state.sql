-- 042: chapters 增加 world_state / character_state 列
-- 设计文档§7: 拆章后单元世界状态/角色状态需插值分配到各章节。
-- 原 distribute_pressure_curve / interpolate_character_state 写入这两个列,
-- 但 chapters 表此前无此列 (死代码未捕获). 此处补齐。
ALTER TABLE chapters ADD COLUMN world_state TEXT DEFAULT '{}';
ALTER TABLE chapters ADD COLUMN character_state TEXT DEFAULT '{}';
