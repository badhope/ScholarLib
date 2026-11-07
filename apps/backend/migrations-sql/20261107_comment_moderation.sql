-- ============================================================================
-- 评论审核状态机
-- 日期：2026-11-07
--
-- 说明：
--   * 幂等 DDL（ADD COLUMN IF NOT EXISTS / DROP CONSTRAINT IF EXISTS），
--     可重复执行；生产库由数据侧手工执行，本文件仅留痕。
--   * 历史评论保持 published（DEFAULT 'published'），不回填 pending，
--     避免上线即积压一屏待审。
--   * 新评论由应用层写入 status='pending'；前台默认仍展示（事后审核，
--     被拒绝的评论前台过滤掉），editor 及以上可在后台改判。
-- ============================================================================

ALTER TABLE comments ADD COLUMN IF NOT EXISTS status            varchar(16)  NOT NULL DEFAULT 'published';
ALTER TABLE comments ADD COLUMN IF NOT EXISTS moderated_by      integer     NULL REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE comments ADD COLUMN IF NOT EXISTS moderated_at      timestamptz NULL;
ALTER TABLE comments ADD COLUMN IF NOT EXISTS moderation_note   text        NULL;

-- 取值约束：pending（待审）/ published（已通过）/ rejected（已拒绝）。
ALTER TABLE comments DROP CONSTRAINT IF EXISTS chk_comments_status;
ALTER TABLE comments ADD CONSTRAINT chk_comments_status
    CHECK (status IN ('pending', 'published', 'rejected'));

-- 后台待审列表主查询：WHERE tenant_id=? AND status=? ORDER BY created_at DESC。
CREATE INDEX IF NOT EXISTS ix_comments_tenant_status_created
    ON comments (tenant_id, status, created_at DESC);
