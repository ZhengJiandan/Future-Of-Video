-- Upgrade script for environments that already have a legacy `users` table.
-- This script aligns the table with the current auth model used by the project.

USE `future_of_video`;

ALTER TABLE `users`
  ADD COLUMN IF NOT EXISTS `name` VARCHAR(100) NULL AFTER `email`,
  ADD COLUMN IF NOT EXISTS `password_hash` VARCHAR(255) NULL AFTER `name`,
  ADD COLUMN IF NOT EXISTS `is_active` TINYINT(1) NOT NULL DEFAULT 1 AFTER `password_hash`,
  ADD COLUMN IF NOT EXISTS `created_at` DATETIME NULL AFTER `is_active`,
  ADD COLUMN IF NOT EXISTS `updated_at` DATETIME NULL AFTER `created_at`;

UPDATE `users`
SET
  `name` = COALESCE(NULLIF(`name`, ''), `email`),
  `created_at` = COALESCE(`created_at`, NOW()),
  `updated_at` = COALESCE(`updated_at`, NOW()),
  `is_active` = COALESCE(`is_active`, 1)
WHERE
  `name` IS NULL
  OR `name` = ''
  OR `created_at` IS NULL
  OR `updated_at` IS NULL
  OR `is_active` IS NULL;

SET @has_uq_users_email = (
  SELECT COUNT(1)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'users'
    AND index_name = 'uq_users_email'
);

SET @create_uq_users_email_sql = IF(
  @has_uq_users_email = 0,
  'CREATE UNIQUE INDEX `uq_users_email` ON `users` (`email`)',
  'SELECT 1'
);

PREPARE create_uq_users_email_stmt FROM @create_uq_users_email_sql;
EXECUTE create_uq_users_email_stmt;
DEALLOCATE PREPARE create_uq_users_email_stmt;
