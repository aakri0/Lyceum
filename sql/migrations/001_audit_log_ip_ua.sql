-- Adds IP and user-agent columns to audit_logs.
-- Idempotent — safe to run on a fresh schema or an existing DB.

SET @col_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'audit_logs'
    AND COLUMN_NAME = 'ip_address'
);
SET @ddl := IF(@col_exists = 0,
  'ALTER TABLE audit_logs ADD COLUMN ip_address VARCHAR(45) DEFAULT NULL',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'audit_logs'
    AND COLUMN_NAME = 'user_agent'
);
SET @ddl := IF(@col_exists = 0,
  'ALTER TABLE audit_logs ADD COLUMN user_agent VARCHAR(255) DEFAULT NULL',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'audit_logs'
    AND INDEX_NAME = 'idx_audit_created_at'
);
SET @ddl := IF(@idx_exists = 0,
  'CREATE INDEX idx_audit_created_at ON audit_logs (created_at)',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
