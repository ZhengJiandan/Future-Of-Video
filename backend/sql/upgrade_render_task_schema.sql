CREATE TABLE IF NOT EXISTS `pipeline_render_tasks` (
  `id` VARCHAR(50) NOT NULL,
  `user_id` VARCHAR(50) NOT NULL,
  `project_id` VARCHAR(50) NULL,
  `project_title` VARCHAR(255) NOT NULL,
  `segments` JSON NOT NULL,
  `keyframes` JSON NOT NULL,
  `character_profiles` JSON NOT NULL,
  `scene_profiles` JSON NOT NULL,
  `render_config` JSON NOT NULL,
  `status` VARCHAR(50) NOT NULL DEFAULT 'queued',
  `progress` DOUBLE NOT NULL DEFAULT 0,
  `current_step` VARCHAR(255) NOT NULL DEFAULT '等待开始',
  `renderer` VARCHAR(100) NOT NULL DEFAULT 'pending',
  `clips` JSON NOT NULL,
  `final_output` JSON NOT NULL,
  `fallback_used` TINYINT(1) NOT NULL DEFAULT 0,
  `warnings` JSON NOT NULL,
  `error` TEXT NULL,
  `created_at` DATETIME NULL,
  `updated_at` DATETIME NULL,
  PRIMARY KEY (`id`),
  KEY `ix_pipeline_render_tasks_user_id` (`user_id`),
  KEY `ix_pipeline_render_tasks_project_id` (`project_id`),
  KEY `ix_pipeline_render_tasks_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE `pipeline_render_tasks`
  ADD COLUMN IF NOT EXISTS `project_id` VARCHAR(50) NULL AFTER `user_id`;

SET @has_render_task_project_index = (
  SELECT COUNT(1)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'pipeline_render_tasks'
    AND index_name = 'ix_pipeline_render_tasks_project_id'
);

SET @create_render_task_project_index_sql = IF(
  @has_render_task_project_index = 0,
  'CREATE INDEX `ix_pipeline_render_tasks_project_id` ON `pipeline_render_tasks` (`project_id`)',
  'SELECT 1'
);

PREPARE create_render_task_project_index_stmt FROM @create_render_task_project_index_sql;
EXECUTE create_render_task_project_index_stmt;
DEALLOCATE PREPARE create_render_task_project_index_stmt;
