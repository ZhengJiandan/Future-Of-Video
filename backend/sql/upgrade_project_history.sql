-- Upgrade script for existing environments that already created `pipeline_projects`
-- in single-project mode.
--
-- Execute manually if your DB already contains the old schema:
-- 1. remove unique-per-user constraint
-- 2. keep normal index on user_id for project list/history

USE `future_of_video`;

ALTER TABLE `pipeline_projects`
  DROP INDEX `uq_pipeline_projects_user_id`;

ALTER TABLE `pipeline_projects`
  ADD KEY `ix_pipeline_projects_user_id` (`user_id`);
