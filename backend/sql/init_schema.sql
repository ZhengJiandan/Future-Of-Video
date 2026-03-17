-- MySQL schema for the current active main pipeline only.
-- Scope:
-- 1. users
-- 2. pipeline_projects
-- 3. pipeline_character_profiles
-- 4. pipeline_scene_profiles

CREATE DATABASE IF NOT EXISTS `delta_force_video`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `delta_force_video`;

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS `users` (
  `id` VARCHAR(50) NOT NULL,
  `email` VARCHAR(255) NOT NULL,
  `name` VARCHAR(100) NOT NULL,
  `password_hash` VARCHAR(255) NOT NULL,
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at` DATETIME NULL,
  `updated_at` DATETIME NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_users_email` (`email`),
  KEY `ix_users_email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `pipeline_projects` (
  `id` VARCHAR(50) NOT NULL,
  `user_id` VARCHAR(50) NOT NULL,
  `project_title` VARCHAR(255) NOT NULL,
  `current_step` INT NOT NULL DEFAULT 0,
  `state` JSON NOT NULL,
  `status` VARCHAR(50) NOT NULL DEFAULT 'draft',
  `last_render_task_id` VARCHAR(100) NULL,
  `summary` TEXT NULL,
  `created_at` DATETIME NULL,
  `updated_at` DATETIME NULL,
  PRIMARY KEY (`id`),
  KEY `ix_pipeline_projects_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `pipeline_character_profiles` (
  `id` VARCHAR(50) NOT NULL,
  `name` VARCHAR(100) NOT NULL,
  `category` VARCHAR(100) NULL,
  `role` VARCHAR(100) NULL,
  `archetype` VARCHAR(100) NULL,
  `age_range` VARCHAR(50) NULL,
  `gender_presentation` VARCHAR(50) NULL,
  `description` TEXT NULL,
  `appearance` TEXT NULL,
  `personality` TEXT NULL,
  `core_appearance` TEXT NULL,
  `hair` TEXT NULL,
  `face_features` TEXT NULL,
  `body_shape` TEXT NULL,
  `outfit` TEXT NULL,
  `gear` TEXT NULL,
  `color_palette` TEXT NULL,
  `visual_do_not_change` TEXT NULL,
  `speaking_style` TEXT NULL,
  `common_actions` TEXT NULL,
  `emotion_baseline` TEXT NULL,
  `forbidden_behaviors` TEXT NULL,
  `prompt_hint` TEXT NULL,
  `llm_summary` TEXT NULL,
  `image_prompt_base` TEXT NULL,
  `video_prompt_base` TEXT NULL,
  `negative_prompt` TEXT NULL,
  `tags` JSON NULL,
  `must_keep` JSON NULL,
  `forbidden_traits` JSON NULL,
  `aliases` JSON NULL,
  `profile_version` INT NOT NULL DEFAULT 1,
  `source` VARCHAR(50) NOT NULL,
  `reference_image_url` VARCHAR(500) NULL,
  `reference_image_path` VARCHAR(500) NULL,
  `reference_image_original_name` VARCHAR(255) NULL,
  `three_view_image_url` VARCHAR(500) NULL,
  `three_view_image_path` VARCHAR(500) NULL,
  `three_view_prompt` TEXT NULL,
  `created_at` DATETIME NULL,
  `updated_at` DATETIME NULL,
  PRIMARY KEY (`id`),
  KEY `ix_pipeline_character_profiles_name` (`name`),
  KEY `ix_pipeline_character_profiles_category` (`category`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `pipeline_scene_profiles` (
  `id` VARCHAR(50) NOT NULL,
  `name` VARCHAR(100) NOT NULL,
  `category` VARCHAR(100) NULL,
  `scene_type` VARCHAR(100) NULL,
  `description` TEXT NULL,
  `story_function` VARCHAR(100) NULL,
  `location` VARCHAR(255) NULL,
  `scene_rules` TEXT NULL,
  `time_setting` VARCHAR(100) NULL,
  `weather` VARCHAR(100) NULL,
  `lighting` VARCHAR(100) NULL,
  `atmosphere` TEXT NULL,
  `architecture_style` TEXT NULL,
  `color_palette` TEXT NULL,
  `prompt_hint` TEXT NULL,
  `llm_summary` TEXT NULL,
  `image_prompt_base` TEXT NULL,
  `video_prompt_base` TEXT NULL,
  `negative_prompt` TEXT NULL,
  `tags` JSON NULL,
  `allowed_characters` JSON NULL,
  `props_must_have` JSON NULL,
  `props_forbidden` JSON NULL,
  `must_have_elements` JSON NULL,
  `forbidden_elements` JSON NULL,
  `camera_preferences` JSON NULL,
  `profile_version` INT NOT NULL DEFAULT 1,
  `source` VARCHAR(50) NOT NULL,
  `reference_image_url` VARCHAR(500) NULL,
  `reference_image_path` VARCHAR(500) NULL,
  `reference_image_original_name` VARCHAR(255) NULL,
  `created_at` DATETIME NULL,
  `updated_at` DATETIME NULL,
  PRIMARY KEY (`id`),
  KEY `ix_pipeline_scene_profiles_name` (`name`),
  KEY `ix_pipeline_scene_profiles_category` (`category`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
