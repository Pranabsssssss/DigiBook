-- Optional Seed Data for Development / Testing
USE digibook;

-- Insert a test student without PIN (first-time login simulation)
-- RFID Key: 1234567890
INSERT INTO students (student_id, student_name, rfid_key, class, email, pin_hash, pin_set)
VALUES (
    'STU2026001',
    'Alex Rivera',
    '1234567890',
    'Grade 10-A',
    'alex.rivera@example.com',
    NULL,
    FALSE
)
ON DUPLICATE KEY UPDATE student_name = VALUES(student_name);

-- Insert a test student with pre-set PIN: 1234
-- bcrypt hash for '1234'
INSERT INTO students (student_id, student_name, rfid_key, class, email, pin_hash, pin_set)
VALUES (
    'STU2026002',
    'Sam Taylor',
    '0987654321',
    'Grade 10-B',
    'sam.taylor@example.com',
    '$2b$12$e6mZ8bL0y0m9gW0j6oE9fe333f2s5u/6k9f9n4v.x7p2d8r4a1m3q',
    TRUE
)
ON DUPLICATE KEY UPDATE student_name = VALUES(student_name);
