# DigiBook — Production Deployment & Service Configuration

This guide provides end-to-end instructions for deploying DigiBook on a **Raspberry Pi 3B+** running **Raspberry Pi OS (64-bit Bookworm or Bullseye)** with domain **`https://digibook.pranab.space`** exposed via **Cloudflare Tunnel**.

---

## 1. Hardware Preparation

1. **Raspberry Pi 3B+**:
   - Raspberry Pi OS 64-bit installed.
   - Connected to display/projector via HDMI.
2. **Logitech USB Camera**:
   - Plugged into any USB port (default device index `0`).
3. **RC522 RFID Reader**:
   - Wired to Raspberry Pi SPI pins:
     - SDA (SS) → GPIO 8 (CE0, Pin 24)
     - SCK → GPIO 11 (SCLK, Pin 23)
     - MOSI → GPIO 10 (MOSI, Pin 19)
     - MISO → GPIO 9 (MISO, Pin 21)
     - GND → Ground (Pin 6)
     - RST → GPIO 25 (Pin 22)
     - 3.3V → 3.3V Power (Pin 1)

---

## 2. Operating System & Hardware Interface Setup

Enable SPI on the Raspberry Pi:
```bash
sudo raspi-config
# Navigate: Interface Options -> SPI -> Enable -> Finish
sudo reboot
```

Verify SPI device is present:
```bash
ls -l /dev/spidev0.*
# Expected output: /dev/spidev0.0 and /dev/spidev0.1
```

---

## 3. MariaDB Database Installation & Initialization

Install MariaDB server:
```bash
sudo apt update
sudo apt install -y mariadb-server
sudo systemctl enable mariadb
sudo systemctl start mariadb
```

Apply DigiBook initialization and schema:
```bash
cd /home/pi/DigiBook
sudo mysql < SQL/init_database.sql
sudo mysql digibook < SQL/schema.sql
```

(Optional) Apply Raspberry Pi performance tuning to `/etc/mysql/mariadb.conf.d/50-server.cnf` under `[mysqld]`:
```ini
[mysqld]
innodb_buffer_pool_size = 128M
innodb_log_file_size = 32M
max_connections = 20
key_buffer_size = 16M
table_open_cache = 200
```
Then restart:
```bash
sudo systemctl restart mariadb
```

---

## 4. Python Virtual Environment & Dependencies

On Raspberry Pi OS Bookworm (Debian 12), create a virtual environment with `--system-site-packages` so pre-installed `picamera2` and system bindings are accessible:
```bash
cd /home/pi/DigiBook
python3 -m venv venv --system-site-packages
source venv/bin/activate
pip install -r requirements.txt
pip install mfrc522 RPi.GPIO spidev
```

Configure your `.env` file:
```bash
cp .env.example .env
nano .env
# Set secure FLASK_SECRET_KEY, DB_PASSWORD, etc.
```

---

## 5. Cloudflare Tunnel Configuration (`digibook.pranab.space`)

Install `cloudflared` on Raspberry Pi:
```bash
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
sudo dpkg -i cloudflared.deb
```

Authenticate and create tunnel:
```bash
cloudflared tunnel login
cloudflared tunnel create digibook
```

Route the DNS record to the tunnel:
```bash
cloudflared tunnel route dns digibook digibook.pranab.space
```

Configure tunnel ingress:
```bash
sudo mkdir -p /etc/cloudflared
sudo cp deployment/cloudflare-tunnel.yml /etc/cloudflared/config.yml
# Update config.yml with your actual Tunnel UUID
```

Install cloudflared as a system service:
```bash
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
```

---

## 6. Systemd Services Installation

DigiBook runs two managed services on the Raspberry Pi:
1. `digibook-web.service`: Gunicorn WSGI server exposing the Flask web application locally on port 5000 (which Cloudflare Tunnel forwards to `https://digibook.pranab.space`).
2. `digibook-local.service`: Fullscreen Pygame whiteboard, RFID scanner, and Logitech camera green LED tracker.

Install unit files:
```bash
sudo cp deployment/digibook-web.service /etc/systemd/system/
sudo cp deployment/digibook-local.service /etc/systemd/system/

sudo systemctl daemon-reload
```

Enable and start services:
```bash
# Enable services to launch automatically on boot:
sudo systemctl enable digibook-web.service
sudo systemctl enable digibook-local.service

# Start the web server:
sudo systemctl start digibook-web.service

# Start the local GUI application:
sudo systemctl start digibook-local.service
```

Check service status and logs:
```bash
sudo systemctl status digibook-web
sudo systemctl status digibook-local
journalctl -u digibook-web -f
journalctl -u digibook-local -f
```

---

## 7. Daily Database Backup Cronjob

Make backup script executable:
```bash
chmod +x /home/pi/DigiBook/deployment/backup_database.sh
```

Add daily cron task at 3:00 AM:
```bash
crontab -e
# Add line:
0 3 * * * /home/pi/DigiBook/deployment/backup_database.sh >> /home/pi/DigiBook/logs/backup.log 2>&1
```
