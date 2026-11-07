-- ============================================================================
-- P0 重构：文件解析 / 中图分类号 / 内容赛道派生 / 认领归属
-- 日期：2026-11-07
--
-- 说明：
--   * 本文件为**幂等 DDL**（IF NOT EXISTS），可重复执行。
--   * 生产库已由数据侧**手工执行**本脚本；此处提交仅为留痕，避免 Alembic
--     版本号冲突——不要再为这些列生成 alembic revision。
--   * 历史 track 列（serious|absurd）语义不动，content_track 是新列，
--     二者互不替代。
--
-- 影响表：resources、submissions
-- ============================================================================

-- --- resources -------------------------------------------------------------
ALTER TABLE resources ADD COLUMN IF NOT EXISTS clc_code      varchar(20);
ALTER TABLE resources ADD COLUMN IF NOT EXISTS clc_label     varchar(80);
ALTER TABLE resources ADD COLUMN IF NOT EXISTS content_track varchar(8);
ALTER TABLE resources ADD COLUMN IF NOT EXISTS owner_id      integer
    REFERENCES users (id) ON DELETE SET NULL;

-- 目录按中图分类号前缀筛选（?clc=TP）。
CREATE INDEX IF NOT EXISTS ix_resources_clc_code ON resources (clc_code);

-- --- submissions -----------------------------------------------------------
ALTER TABLE submissions ADD COLUMN IF NOT EXISTS clc_code      varchar(20);
ALTER TABLE submissions ADD COLUMN IF NOT EXISTS clc_label     varchar(80);
ALTER TABLE submissions ADD COLUMN IF NOT EXISTS content_track varchar(8);

-- --- 回填（可选，幂等） -----------------------------------------------------
-- 历史资源按 content_category 回填 content_track（academic→paper，其余→essay）。
UPDATE resources
   SET content_track = 'paper'
 WHERE content_track IS NULL AND content_category = 'academic';
UPDATE resources
   SET content_track = 'essay'
 WHERE content_track IS NULL AND content_category IN ('fun', 'rant');
-- content_category 为空的历史记录保守算 paper（本刊默认学术刊）。
UPDATE resources
   SET content_track = 'paper'
 WHERE content_track IS NULL;

-- 历史已发布稿：owner_id 为空者保持 NULL（早期批量导入稿，允许走认领审批）。
-- 新发布由后端物化流程写入 owner_id = submissions.submitted_by。
