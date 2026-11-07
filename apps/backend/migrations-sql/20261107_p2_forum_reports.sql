-- ============================================================================
-- 论坛闭环：举报表 forum_reports
-- 日期：2026-11-07
--
-- 说明：
--   * 幂等 DDL（IF NOT EXISTS），可重复执行。
--   * 生产库由数据侧手工执行；本文件仅留痕，不再生成 alembic revision。
--   * 同一用户对同一对象（topic 或 reply）的重复举报由应用层校验返回 409，
--     数据库层不建 partial unique 约束（两种对象可空列组合会让 PG 的
--     NULL 语义变复杂），应用层先查 open 记录兜底。
-- ============================================================================

CREATE TABLE IF NOT EXISTS forum_reports (
    id           SERIAL PRIMARY KEY,
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    reporter_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic_id     INTEGER REFERENCES forum_topics(id) ON DELETE CASCADE,
    reply_id     INTEGER REFERENCES forum_replies(id) ON DELETE CASCADE,
    reason       VARCHAR(200) NOT NULL DEFAULT '',
    status       VARCHAR(16)  NOT NULL DEFAULT 'open',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    resolved_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_forum_reports_tenant_status
    ON forum_reports (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_forum_reports_reporter
    ON forum_reports (reporter_id);
CREATE INDEX IF NOT EXISTS ix_forum_reports_topic
    ON forum_reports (topic_id);
CREATE INDEX IF NOT EXISTS ix_forum_reports_reply
    ON forum_reports (reply_id);

-- 应用层校验：一条举报必须指向 topic 或 reply（至少其一）。
ALTER TABLE forum_reports DROP CONSTRAINT IF EXISTS chk_forum_reports_target;
ALTER TABLE forum_reports ADD CONSTRAINT chk_forum_reports_target
    CHECK (topic_id IS NOT NULL OR reply_id IS NOT NULL);
