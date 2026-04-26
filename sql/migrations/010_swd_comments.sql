-- A7: SWD request comments + status-change timeline.
--
-- Comments are posted by either party (student, faculty, admin) and are
-- visible to all participants of the request. Status changes are also
-- written here as system rows (commenter_user_id NULL) so the timeline
-- on the request detail page is one ordered query.

SET @t_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'swd_comments'
);
SET @ddl := IF(@t_exists = 0, '
  CREATE TABLE swd_comments (
    comment_id   INT NOT NULL AUTO_INCREMENT,
    req_id       INT NOT NULL,
    user_id      INT NULL,
    body         TEXT NULL,
    event_kind   VARCHAR(32) NOT NULL DEFAULT ''comment'',
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (comment_id),
    KEY idx_swd_comment_req (req_id, created_at),
    CONSTRAINT fk_swd_comment_req FOREIGN KEY (req_id) REFERENCES swd_requests(req_id) ON DELETE CASCADE,
    CONSTRAINT fk_swd_comment_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL
  ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
