-- 055: Pressure 4 维扩展
-- 在 narrative_pressures 表增加 3 个维度列

ALTER TABLE narrative_pressures ADD COLUMN reader_pressure INTEGER DEFAULT 0;
ALTER TABLE narrative_pressures ADD COLUMN character_pressure INTEGER DEFAULT 0;
ALTER TABLE narrative_pressures ADD COLUMN timeline_pressure INTEGER DEFAULT 0;
