-- ============================================================================
-- 审稿/主编工作台分离 + 站内通知邮件摘要
-- 日期：2026-11-07
--
-- 说明：
--   * 幂等 DDL（IF NOT EXISTS），可重复执行。
--   * 生产库由数据侧手工执行；本文件仅留痕，不再生成 alembic revision。
--   * 不触碰 quality.scores / 文章 markdown / 既有 review_assignments 数据。
--
-- 新增表：
--   * email_digest_records —— 每次"本该发邮件"的事件落一行，诚实记录
--     sent / skipped_disabled / skipped_no_smtp / failed。未配置 SMTP 时
--     不再假装已发，而是留痕供运维核对。
-- ============================================================================

CREATE TABLE IF NOT EXISTS email_digest_records (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_type      VARCHAR(32)  NOT NULL,   -- assigned / reminder / decision / claim_decision
    recipient_email VARCHAR(255) NOT NULL,
    subject         VARCHAR(255) NOT NULL,
    body            TEXT,
    status          VARCHAR(32)  NOT NULL,   -- sent / skipped_disabled / skipped_no_smtp / failed
    related_type    VARCHAR(50),
    related_id      VARCHAR(100),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_email_digest_records_user_created
    ON email_digest_records (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_email_digest_records_event_type
    ON email_digest_records (event_type);
CREATE INDEX IF NOT EXISTS ix_email_digest_records_status
    ON email_digest_records (status);

-- RLS：与其它租户表同口径（policy 由统一 RLS 策略生成器接管；
-- 若老库未自动建 policy，按需补 ENABLE ROW LEVEL SECURITY）。
-- 不写死 policy，避免与现有 RLS 迁移冲突。
