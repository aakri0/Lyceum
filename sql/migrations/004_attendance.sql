-- B1: Attendance tracking.
--
-- One row per (section, student, date). status is text not bool so we can
-- support 'P', 'A', 'L' (late), 'X' (excused) without further migrations.
-- Faculty marks each session for each section they teach.

SET @t_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'attendance'
);
SET @ddl := IF(@t_exists = 0, '
  CREATE TABLE attendance (
    attendance_id INT NOT NULL AUTO_INCREMENT,
    section_id    INT NOT NULL,
    student_id    INT NOT NULL,
    session_date  DATE NOT NULL,
    status        ENUM(''P'',''A'',''L'',''X'') NOT NULL DEFAULT ''P'',
    marked_by     INT NULL,
    marked_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (attendance_id),
    UNIQUE KEY uk_attendance_session_student (section_id, student_id, session_date),
    KEY idx_attendance_student (student_id),
    KEY idx_attendance_date (session_date),
    CONSTRAINT fk_attendance_section FOREIGN KEY (section_id) REFERENCES course_sections(section_id) ON DELETE CASCADE,
    CONSTRAINT fk_attendance_student FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE,
    CONSTRAINT fk_attendance_marked_by FOREIGN KEY (marked_by) REFERENCES users(user_id) ON DELETE SET NULL
  ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
