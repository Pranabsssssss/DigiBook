# DigiBook Database Setup & Administration

This directory contains the database resources, schemas, and initialization scripts for DigiBook.

## 1. Setup on Raspberry Pi (MariaDB)

### Step 1: Install MariaDB Server
```bash
sudo apt update
sudo apt install -y mariadb-server
sudo systemctl enable mariadb
sudo systemctl start mariadb
```

### Step 2: Secure Installation (Optional for Dev, Recommended for Prod)
```bash
sudo mysql_secure_installation
```

### Step 3: Initialize Database & User
```bash
cd /path/to/DigiBook
sudo mysql < SQL/init_database.sql
```

### Step 4: Apply Schema
```bash
sudo mysql digibook < SQL/schema.sql
```

### Step 5: (Optional) Seed Test Data
```bash
sudo mysql digibook < SQL/seed.sql
```

---

## 2. Setup on Windows / PC Development (MySQL or MariaDB)

If you have MySQL or MariaDB installed locally:
```powershell
mysql -u root -p < SQL\init_database.sql
mysql -u root -p digibook < SQL\schema.sql
```

Make sure your `.env` file credentials match:
```env
DB_HOST=localhost
DB_PORT=3306
DB_USER=digibook
DB_PASSWORD=digibook_secure_pass_2026
DB_NAME=digibook
```

---

## 3. Database Architecture & Tables

| Table | Description |
|---|---|
| `students` | Registered student profiles (RFID key, Student ID, Class, Email, bcrypt 4-digit PIN hash) |
| `whiteboards` | Whiteboard metadata (title, student ownership, timestamps, base64 thumbnail) |
| `whiteboard_strokes` | Structured JSON strokes recorded at normalized `[0.0, 1.0]` coordinates |
| `sessions` | Active login sessions for local Raspberry Pi and remote web interfaces |
| `audit_log` | Security audit trail, failed login tracking, and rate limiting logs |

---

## 4. Raspberry Pi 3B+ Resource Optimization

To ensure optimal performance on the Raspberry Pi 3B+ (1GB RAM), add the following lines to `/etc/mysql/mariadb.conf.d/50-server.cnf` under `[mysqld]`:

```ini
[mysqld]
innodb_buffer_pool_size = 128M
innodb_log_file_size = 32M
max_connections = 20
key_buffer_size = 16M
query_cache_size = 16M
table_open_cache = 200
```
Then restart the service:
```bash
sudo systemctl restart mariadb
```
