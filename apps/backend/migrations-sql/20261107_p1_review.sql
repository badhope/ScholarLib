-- ============================================================================
-- P1：双人审稿闸门
-- 日期：2026-11-07
-- 幂等 DDL，生产库由数据侧手工执行。
-- ============================================================================

ALTER TABLE review_assignments ADD COLUMN IF NOT EXISTS "round" integer NOT NULL DEFAULT 1;
ALTER TABLE review_assignments ADD COLUMN IF NOT EXISTS slot     integer NOT NULL DEFAULT 1;
ALTER TABLE review_assignments ADD COLUMN IF NOT EXISTS is_adjudicator boolean NOT NULL DEFAULT false;

-- 历史行：round=1, slot 按 assigned 顺序填充（这里只做兜底默认值，
-- 具体 slot 由编辑后续批量指派时覆盖）。
-- 不需要额外索引：现有 (submission_id, reviewer_id) 唯一约束已覆盖查询。
