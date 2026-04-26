-- C7: Profile photo path on users.
--
-- Stored as a relative filename inside UPLOAD_DIR/avatars (image data is
-- on disk, not in the DB).

SET @col_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'profile_photo'
);
SET @ddl := IF(@col_exists = 0,
  'ALTER TABLE users ADD COLUMN profile_photo VARCHAR(255) NULL',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
