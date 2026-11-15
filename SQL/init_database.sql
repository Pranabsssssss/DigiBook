-- DigiBook Database Initialization
-- Run as root or MySQL administrative user:
-- sudo mysql < SQL/init_database.sql

CREATE DATABASE IF NOT EXISTS digibook
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'digibook'@'localhost'
    IDENTIFIED BY 'digibook_secure_pass_2026';

GRANT ALL PRIVILEGES ON digibook.* TO 'digibook'@'localhost';
FLUSH PRIVILEGES;
