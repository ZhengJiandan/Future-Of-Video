USE `delta_force_video`;

ALTER TABLE `pipeline_character_profiles`
  ADD COLUMN IF NOT EXISTS `category` VARCHAR(100) NULL AFTER `name`;

ALTER TABLE `pipeline_scene_profiles`
  ADD COLUMN IF NOT EXISTS `category` VARCHAR(100) NULL AFTER `name`;

SET @has_character_category_index = (
  SELECT COUNT(1)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'pipeline_character_profiles'
    AND index_name = 'ix_pipeline_character_profiles_category'
);

SET @create_character_category_index_sql = IF(
  @has_character_category_index = 0,
  'CREATE INDEX `ix_pipeline_character_profiles_category` ON `pipeline_character_profiles` (`category`)',
  'SELECT 1'
);

PREPARE create_character_category_index_stmt FROM @create_character_category_index_sql;
EXECUTE create_character_category_index_stmt;
DEALLOCATE PREPARE create_character_category_index_stmt;

SET @has_scene_category_index = (
  SELECT COUNT(1)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'pipeline_scene_profiles'
    AND index_name = 'ix_pipeline_scene_profiles_category'
);

SET @create_scene_category_index_sql = IF(
  @has_scene_category_index = 0,
  'CREATE INDEX `ix_pipeline_scene_profiles_category` ON `pipeline_scene_profiles` (`category`)',
  'SELECT 1'
);

PREPARE create_scene_category_index_stmt FROM @create_scene_category_index_sql;
EXECUTE create_scene_category_index_stmt;
DEALLOCATE PREPARE create_scene_category_index_stmt;
