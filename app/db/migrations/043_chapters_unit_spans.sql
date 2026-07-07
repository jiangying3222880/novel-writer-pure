-- 043: chapters 增加段落级单元溯源 (unit_spans)
-- 支持「多单元拼接 → 断章」新流程: 章节由多个单元拼接而成,
-- 需精确到段落知道每段来自哪个单元 (unit_no 唯一编号)。
-- unit_spans 为 JSON 数组:
--   [{"unit_id": "...", "unit_no": 3, "char_start": 0, "char_end": 512}, ...]
-- source_unit_id (单值, 迁移038) 保留作章节级冗余标识, 不再作为唯一溯源。
ALTER TABLE chapters ADD COLUMN unit_spans TEXT DEFAULT '';
