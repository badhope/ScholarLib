-- ============================================================================
-- 等级轴：user_levels + point_events（v1.14）
-- 日期：2026-11-07
-- 幂等 DDL，生产库由数据侧手工执行。
-- 与权限轴（users.role）正交：等级只在身份内比较，不换权限。
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_levels (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id     integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    identity    varchar(16) NOT NULL,
    level       integer NOT NULL DEFAULT 1,
    points      integer NOT NULL DEFAULT 0,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_user_level_identity UNIQUE (tenant_id, user_id, identity)
);

CREATE INDEX IF NOT EXISTS ix_user_levels_user ON user_levels(user_id);

CREATE TABLE IF NOT EXISTS point_events (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id   uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id     integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    identity    varchar(16) NOT NULL,
    delta       integer NOT NULL DEFAULT 0,
    reason      varchar(64) NOT NULL,
    ref_type    varchar(32) NOT NULL DEFAULT '',
    ref_id      varchar(64) NOT NULL DEFAULT '',
    note        varchar(255),
    created_at  timestamptz NOT NULL DEFAULT now(),
    -- 同一业务动作（同一 ref）幂等：重复触发不重复加分。
    CONSTRAINT uq_point_event_identity UNIQUE (tenant_id, user_id, identity, reason, ref_type, ref_id)
);

CREATE INDEX IF NOT EXISTS ix_point_events_tenant_user_created
    ON point_events(tenant_id, user_id, created_at DESC);
