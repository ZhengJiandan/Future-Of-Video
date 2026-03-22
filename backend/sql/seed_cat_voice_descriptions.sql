-- Extra SQL for adding voice descriptions to the cat seed characters.
-- Usage:
--   1. Make sure you are already using the correct database.
--   2. Run: source backend/sql/seed_cat_voice_descriptions.sql

SET @has_voice_description := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'pipeline_character_profiles'
    AND COLUMN_NAME = 'voice_description'
);

SET @voice_description_ddl := IF(
  @has_voice_description = 0,
  'ALTER TABLE `pipeline_character_profiles` ADD COLUMN `voice_description` TEXT NULL AFTER `emotion_baseline`',
  'SELECT 1'
);

PREPARE stmt_voice_description FROM @voice_description_ddl;
EXECUTE stmt_voice_description;
DEALLOCATE PREPARE stmt_voice_description;

UPDATE `pipeline_character_profiles`
SET
  `voice_description` = CASE `id`
    WHEN 'cat_char_xuan_hujiao' THEN '偏低沉的中性声线，干净克制，语速偏慢，咬字短促有压迫感，像随时在下达精准指令，不带明显情绪起伏。'
    WHEN 'cat_char_mianhua' THEN '温柔清透的女性化声线，音区中高但不尖，气息稳定，语速舒缓，有明显安抚感，危机时会更坚定但依旧柔和。'
    WHEN 'cat_char_lihuaqi' THEN '年轻灵巧的中性声线，语速快，带一点街头调侃感和机灵劲，尾音偶尔上扬，紧张时会立刻收紧变得更短更利落。'
    WHEN 'cat_char_lanwei' THEN '偏冷静的中性技术型声线，清晰、理性、颗粒感轻，语速中等偏快，像在持续做信息播报和风险提示，几乎没有多余语气词。'
    WHEN 'cat_char_juwan' THEN '略低的成熟男性化声线，慵懒松弛、带一点沙哑和笑意，讲话像在开玩笑但始终留着锋芒，危险时会突然压低变冷。'
    ELSE `voice_description`
  END,
  `updated_at` = NOW()
WHERE `id` IN (
  'cat_char_xuan_hujiao',
  'cat_char_mianhua',
  'cat_char_lihuaqi',
  'cat_char_lanwei',
  'cat_char_juwan'
);
