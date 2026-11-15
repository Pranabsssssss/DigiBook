-- DigiBook Database Schema
-- Compatible with MySQL 8.0+ and MariaDB 10.5+

USE digibook;

-- ============================================
-- TABLE: students
-- Central student registration table
-- ============================================
CREATE TABLE IF NOT EXISTS students (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    student_id      VARCHAR(50)     NOT NULL UNIQUE,
    student_name    VARCHAR(150)    NOT NULL,
    rfid_key        VARCHAR(50)     NOT NULL UNIQUE,
    class           VARCHAR(50)     NOT NULL,
    email           VARCHAR(255)    NOT NULL UNIQUE,
    pin_hash        VARCHAR(255)    DEFAULT NULL,       -- bcrypt hash; NULL until first login
    pin_set         BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_login_at   DATETIME        DEFAULT NULL,

    INDEX idx_rfid_key (rfid_key),
    INDEX idx_email (email),
    INDEX idx_student_id (student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================
-- TABLE: whiteboards
-- Each whiteboard belongs to one student
-- ============================================
CREATE TABLE IF NOT EXISTS whiteboards (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    student_id      INT UNSIGNED    NOT NULL,
    title           VARCHAR(255)    NOT NULL DEFAULT 'Untitled',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_deleted      BOOLEAN         NOT NULL DEFAULT FALSE,
    thumbnail_b64   MEDIUMTEXT      DEFAULT NULL,       -- Base64-encoded small PNG thumbnail

    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    INDEX idx_student_whiteboards (student_id, is_deleted, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================
-- TABLE: whiteboard_strokes
-- Individual drawing strokes for a whiteboard
-- Stores structured JSON stroke data
-- ============================================
CREATE TABLE IF NOT EXISTS whiteboard_strokes (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    whiteboard_id   INT UNSIGNED    NOT NULL,
    stroke_index    INT UNSIGNED    NOT NULL,           -- Order within the whiteboard
    stroke_data     JSON            NOT NULL,           -- Structured stroke data
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (whiteboard_id) REFERENCES whiteboards(id) ON DELETE CASCADE,
    INDEX idx_wb_strokes (whiteboard_id, stroke_index)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================
-- TABLE: sessions
-- Active login sessions (local + web)
-- ============================================
CREATE TABLE IF NOT EXISTS sessions (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    student_id      INT UNSIGNED    NOT NULL,
    session_token   VARCHAR(128)    NOT NULL UNIQUE,
    session_type    ENUM('local', 'web') NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at      DATETIME        NOT NULL,
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,

    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    INDEX idx_session_token (session_token),
    INDEX idx_session_expiry (expires_at, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================
-- TABLE: audit_log
-- Security audit trail & rate limiting
-- ============================================
CREATE TABLE IF NOT EXISTS audit_log (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    student_id      INT UNSIGNED    DEFAULT NULL,
    event_type      VARCHAR(50)     NOT NULL,           -- 'LOGIN', 'LOGIN_FAIL', 'LOGOUT', 'PIN_SET', 'WHITEBOARD_SAVE', etc.
    event_detail    TEXT            DEFAULT NULL,
    ip_address      VARCHAR(45)     DEFAULT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE SET NULL,
    INDEX idx_audit_student (student_id, created_at),
    INDEX idx_audit_time (created_at),
    INDEX idx_audit_event (event_type, ip_address, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
