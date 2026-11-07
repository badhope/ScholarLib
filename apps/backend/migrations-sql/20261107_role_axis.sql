-- ============================================================================
-- 权限轴：users.role 五层收敛（v1.14）
-- 日期：2026-11-07
-- 幂等 DDL/DML，生产库由数据侧手工执行。
--
-- 五层：user < reviewer < editor < editor_in_chief（访客不入库）。
-- 大身份包含小身份全部权限；主编不叠加小身份。
-- 本脚本只做"收敛"：把 is_admin 与历史 user_roles 折叠进 users.role，
-- 不删除旧列/旧表（回滚兜底 + 其他子智能体仍在引用 user_roles）。
-- ============================================================================

-- 1) 备份：执行前先整表复制一份，便于回滚或审计。
CREATE TABLE IF NOT EXISTS users_backup_20261107 AS SELECT * FROM users;

-- 2) 加列（幂等）。
ALTER TABLE users ADD COLUMN IF NOT EXISTS "role" varchar(32) NOT NULL DEFAULT 'user';

-- 3) 收敛 is_admin=true → editor_in_chief（拿不准的 admin 一律按主编收敛，
--    与任务口径一致；编辑部实际职责后续可在 users.role 上单独降级）。
UPDATE users
   SET role = 'editor_in_chief'
 WHERE is_admin = true
   AND (role IS NULL OR role = '' OR role = 'user');

-- 4) 收敛历史 user_roles：
--    reviewer / senior_reviewer            → reviewer
--    section_editor / board_editor / editor → editor
--    chief_editor / deputy_editor         → editor_in_chief
--    同一用户命中多档时取最高档。
WITH mapped AS (
  SELECT u.id AS user_id,
         CASE
           WHEN r.name IN ('chief_editor', 'deputy_editor')            THEN 'editor_in_chief'
           WHEN r.name IN ('section_editor', 'board_editor', 'editor') THEN 'editor'
           WHEN r.name IN ('reviewer', 'senior_reviewer')              THEN 'reviewer'
           ELSE NULL
         END AS perm_role
    FROM users u
    JOIN user_roles ur ON ur.user_id = u.id
    JOIN roles r       ON r.id = ur.role_id
   WHERE r.name IN ('reviewer','senior_reviewer','section_editor',
                    'board_editor','editor','chief_editor','deputy_editor')
),
best AS (
  SELECT user_id,
         CASE MAX(CASE perm_role
                    WHEN 'editor_in_chief' THEN 4
                    WHEN 'editor'          THEN 3
                    WHEN 'reviewer'        THEN 2
                    ELSE 1 END)
           WHEN 4 THEN 'editor_in_chief'
           WHEN 3 THEN 'editor'
           WHEN 2 THEN 'reviewer'
           WHEN 1 THEN 'user'
         END AS perm_role
    FROM mapped
   WHERE perm_role IS NOT NULL
   GROUP BY user_id
)
UPDATE users u
   SET role = b.perm_role
  FROM best b
 WHERE u.id = b.user_id
   AND (u.role IS NULL OR u.role = '' OR u.role = 'user')
   AND u.is_admin = false;

-- 5) 约束：只允许五层取值（给应用层一道兜底）。
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_users_role_axis'
  ) THEN
    ALTER TABLE users
      ADD CONSTRAINT ck_users_role_axis
      CHECK (role IN ('user','reviewer','editor','editor_in_chief'));
  END IF;
END $$;
