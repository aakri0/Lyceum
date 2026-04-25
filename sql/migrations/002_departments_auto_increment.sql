-- Make ``departments.dept_id`` AUTO_INCREMENT.
--
-- The original schema dump (from `mysqldump`) defined dept_id as a plain
-- ``INT NOT NULL`` because the original DB pre-dated auto-increment on
-- this table. The /admin_add_department route, however, omits dept_id
-- on INSERT and expects MySQL to assign one — without this migration
-- every department creation fails with "Field 'dept_id' doesn't have a
-- default value".
--
-- Idempotent: only modifies if AUTO_INCREMENT isn't already set.

SET @needs_alter := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'departments'
    AND COLUMN_NAME = 'dept_id'
    AND EXTRA NOT LIKE '%auto_increment%'
);
-- FOREIGN_KEY_CHECKS=0 lets us alter a column that's referenced by FKs
-- in students/faculty/courses without dropping and recreating them.
SET @prev_fk := @@FOREIGN_KEY_CHECKS;
SET FOREIGN_KEY_CHECKS = 0;
SET @ddl := IF(@needs_alter = 1,
  'ALTER TABLE departments MODIFY dept_id INT NOT NULL AUTO_INCREMENT',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET FOREIGN_KEY_CHECKS = @prev_fk;
