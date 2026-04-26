-- B2: In-app notifications.
--
-- One row per notification per recipient. Sender code (in app.py helper)
-- inserts on key events (grade post, request status change, new
-- announcement, faculty request assignment). The bell icon polls
-- COUNT WHERE read_at IS NULL.

SET @t_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'notifications'
);
SET @ddl := IF(@t_exists = 0, '
  CREATE TABLE notifications (
    notification_id INT NOT NULL AUTO_INCREMENT,
    user_id         INT NOT NULL,
    kind            VARCHAR(32) NOT NULL,
    message         VARCHAR(500) NOT NULL,
    link            VARCHAR(255) NULL,
    read_at         TIMESTAMP NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (notification_id),
    KEY idx_notif_user_unread (user_id, read_at),
    KEY idx_notif_created (created_at),
    CONSTRAINT fk_notif_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
  ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
