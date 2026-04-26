-- B4: Course materials.
--
-- One row per uploaded file, scoped to a course (visible to all enrolled
-- students regardless of section). The existing ``documents`` table is
-- per-student and not the right shape, so we add a dedicated table.

SET @t_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'course_materials'
);
SET @ddl := IF(@t_exists = 0, '
  CREATE TABLE course_materials (
    material_id   INT NOT NULL AUTO_INCREMENT,
    course_id     INT NOT NULL,
    uploaded_by   INT NOT NULL,
    title         VARCHAR(200) NOT NULL,
    file_name     VARCHAR(255) NOT NULL,
    file_path     VARCHAR(500) NOT NULL,
    mime_type     VARCHAR(100) NOT NULL,
    size_bytes    INT NOT NULL,
    uploaded_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (material_id),
    KEY idx_material_course (course_id),
    CONSTRAINT fk_material_course FOREIGN KEY (course_id) REFERENCES courses(course_id) ON DELETE CASCADE,
    CONSTRAINT fk_material_uploader FOREIGN KEY (uploaded_by) REFERENCES users(user_id) ON DELETE CASCADE
  ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
