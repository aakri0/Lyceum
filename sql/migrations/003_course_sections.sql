-- B11: Course-faculty allotment via sections (Option 2).
--
-- Each course can have N sections per semester. Each section has exactly
-- one primary faculty. Students enroll into a section, not a course
-- directly — so grades, attendance, and faculty access all flow through
-- the section.
--
-- Migration is idempotent and back-fills existing data:
--   1. Creates the course_sections table.
--   2. Creates one default 'A' section per existing (course, semester)
--      combo, picking the lowest-faculty_id in that dept as a placeholder.
--   3. Adds enrollments.section_id and back-fills it from the new sections.
--   4. Leaves enrollments.section_id NULLable for now — admin can re-allot
--      students to sections via the new UI; we'll tighten to NOT NULL in
--      a later migration once allotment is complete.

-- 1) course_sections table
SET @t_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'course_sections'
);
SET @ddl := IF(@t_exists = 0, '
  CREATE TABLE course_sections (
    section_id    INT NOT NULL AUTO_INCREMENT,
    course_id     INT NOT NULL,
    faculty_id    INT NULL,
    section_label VARCHAR(10) NOT NULL DEFAULT ''A'',
    semester      INT NOT NULL,
    capacity      INT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (section_id),
    UNIQUE KEY uk_course_label_sem (course_id, section_label, semester),
    KEY idx_section_faculty (faculty_id),
    KEY idx_section_course (course_id),
    CONSTRAINT fk_section_course FOREIGN KEY (course_id) REFERENCES courses(course_id) ON DELETE CASCADE,
    CONSTRAINT fk_section_faculty FOREIGN KEY (faculty_id) REFERENCES faculty(faculty_id) ON DELETE SET NULL,
    CONSTRAINT chk_section_sem CHECK (semester BETWEEN 1 AND 8)
  ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 2) Back-fill: one default 'A' section per (course, semester) seen in enrollments
INSERT IGNORE INTO course_sections (course_id, semester, section_label, faculty_id)
SELECT DISTINCT
  e.course_id,
  e.semester,
  'A' AS section_label,
  (SELECT MIN(f.faculty_id)
     FROM faculty f
     JOIN courses c2 ON c2.dept_id = f.dept_id
    WHERE c2.course_id = e.course_id) AS faculty_id
FROM enrollments e;

-- 3) enrollments.section_id column
SET @col_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'enrollments' AND COLUMN_NAME = 'section_id'
);
SET @ddl := IF(@col_exists = 0,
  'ALTER TABLE enrollments ADD COLUMN section_id INT NULL AFTER course_id',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 4) Add the FK (idempotent — skip if already present)
SET @fk_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'enrollments'
    AND CONSTRAINT_NAME = 'fk_enrollment_section'
);
SET @ddl := IF(@fk_exists = 0,
  'ALTER TABLE enrollments
     ADD CONSTRAINT fk_enrollment_section
     FOREIGN KEY (section_id) REFERENCES course_sections(section_id) ON DELETE SET NULL',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 5) Back-fill enrollments.section_id from the matching default section
UPDATE enrollments e
JOIN course_sections cs
  ON cs.course_id = e.course_id
 AND cs.semester  = e.semester
 AND cs.section_label = 'A'
SET e.section_id = cs.section_id
WHERE e.section_id IS NULL;
