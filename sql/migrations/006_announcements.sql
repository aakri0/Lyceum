-- B3: Announcements / circulars.
--
-- Targeting is layered: NULL = all, set = scoped to that group.
--   target_dept_id NULL → all departments
--   target_year    NULL → all years (1..4)
--   target_role    NULL → all roles (otherwise 'student'/'faculty')
--   target_course_id NULL → not course-scoped
-- A row is "for me" if every set field matches my profile.

SET @t_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'announcements'
);
SET @ddl := IF(@t_exists = 0, '
  CREATE TABLE announcements (
    announcement_id INT NOT NULL AUTO_INCREMENT,
    posted_by       INT NOT NULL,
    title           VARCHAR(150) NOT NULL,
    body            TEXT NOT NULL,
    target_dept_id  INT NULL,
    target_year     INT NULL,
    target_role     ENUM(''student'',''faculty'') NULL,
    target_course_id INT NULL,
    pinned          TINYINT(1) NOT NULL DEFAULT 0,
    expires_at      DATETIME NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (announcement_id),
    KEY idx_ann_created (created_at),
    KEY idx_ann_dept (target_dept_id),
    KEY idx_ann_course (target_course_id),
    CONSTRAINT fk_ann_poster FOREIGN KEY (posted_by) REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_ann_dept FOREIGN KEY (target_dept_id) REFERENCES departments(dept_id) ON DELETE CASCADE,
    CONSTRAINT fk_ann_course FOREIGN KEY (target_course_id) REFERENCES courses(course_id) ON DELETE CASCADE
  ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
