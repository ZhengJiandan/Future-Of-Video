ALTER TABLE `pipeline_character_profiles`
  ADD COLUMN `face_closeup_image_url` VARCHAR(500) NULL AFTER `three_view_prompt`,
  ADD COLUMN `face_closeup_image_path` VARCHAR(500) NULL AFTER `face_closeup_image_url`;
