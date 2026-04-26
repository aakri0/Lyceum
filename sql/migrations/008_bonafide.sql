-- B7: Bonafide certificate issue records.
--
-- Generated automatically when an admin approves a SWD request whose
-- category is 'Bonafide'. The serial number (BONA-YYYY-NNNN) is unique
-- and printed on the certificate. We also extend swd_requests.category
-- to include 'Bonafide' as a valid value.

ALTER TABLE swd_requests
  MODIFY category ENUM('Leave','Hostel','Medical','Financial Aid','Bonafide') NOT NULL;

SET @t_exists := (
  SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'bonafide_certificates'
);
SET @ddl := IF(@t_exists = 0, '
  CREATE TABLE bonafide_certificates (
    bonafide_id   INT NOT NULL AUTO_INCREMENT,
    req_id        INT NOT NULL,
    student_id    INT NOT NULL,
    serial_no     VARCHAR(40) NOT NULL,
    issued_by     INT NOT NULL,
    issued_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (bonafide_id),
    UNIQUE KEY uk_bonafide_serial (serial_no),
    KEY idx_bonafide_req (req_id),
    KEY idx_bonafide_student (student_id),
    CONSTRAINT fk_bonafide_req FOREIGN KEY (req_id) REFERENCES swd_requests(req_id) ON DELETE CASCADE,
    CONSTRAINT fk_bonafide_student FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE,
    CONSTRAINT fk_bonafide_issuer FOREIGN KEY (issued_by) REFERENCES users(user_id) ON DELETE SET DEFAULT
  ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
