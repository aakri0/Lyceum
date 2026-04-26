-- B8: Account lockout after N failed logins.
--
-- One row per failed attempt. The login route counts rows in the recent
-- LOCKOUT_WINDOW_SECONDS bucket per email; once they cross the threshold
-- a lockout row exists in account_locks. Successful login wipes the
-- attempt history.

SET @t1_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'login_attempts'
);
SET @ddl := IF(@t1_exists = 0, '
  CREATE TABLE login_attempts (
    attempt_id  INT NOT NULL AUTO_INCREMENT,
    email       VARCHAR(100) NOT NULL,
    ip_address  VARCHAR(45) NULL,
    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (attempt_id),
    KEY idx_attempt_email (email, occurred_at)
  ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @t2_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'account_locks'
);
SET @ddl := IF(@t2_exists = 0, '
  CREATE TABLE account_locks (
    email        VARCHAR(100) NOT NULL,
    locked_until DATETIME NOT NULL,
    reason       VARCHAR(64) NOT NULL DEFAULT ''too_many_failed_logins'',
    PRIMARY KEY (email)
  ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
