-- ============================================================================
-- P1：认领绑定 + 作者归属
-- 日期：2026-11-07
--
-- 说明：
--   * 幂等 DDL（IF NOT EXISTS），可重复执行。
--   * 生产库由数据侧手工执行；本文件仅留痕，不再生成 alembic revision。
--   * author_claims 扩展：作者位、证据类型/值；
--     authors_meta（resources.authors_meta JSONB）承载结构化作者位与认领状态。
-- ============================================================================

-- --- author_claims 扩展 ------------------------------------------------------
ALTER TABLE author_claims ADD COLUMN IF NOT EXISTS author_position    integer;
ALTER TABLE author_claims ADD COLUMN IF NOT EXISTS evidence_type     varchar(16);
ALTER TABLE author_claims ADD COLUMN IF NOT EXISTS evidence_value    varchar(255);

-- decided_by / decided_at / decision_note 已在 P0 前存在，无需新增。

-- --- resources.authors_meta 承载结构（无需新列） ----------------------------
-- resources.authors_meta 为 JSONB，每条目结构：
--   {"name","order","roles":["first"|"corresponding"],"claimed":bool,
--    "user_id":int|null,"affiliation","email"}
-- 未认领位（claimed=false）公开面 email 强制 null（见 ResourceResponse validator）。

-- --- 回填（可选） -----------------------------------------------------------
-- 历史资源 owner_id 已绑定者，把第 1 位作者标记为已认领（email 取账号邮箱）。
-- 由数据侧在需要时执行，此处不自动回填。
