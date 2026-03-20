ALTER TABLE `pipeline_character_profiles`
  ADD COLUMN `voice_profile` JSON NULL AFTER `emotion_baseline`;
