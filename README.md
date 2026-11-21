# 📚 DigiBook — RFID-Based Digital Whiteboard System

DigiBook is an interactive digital whiteboard system designed for the **Raspberry Pi 3B+**. Students scan their personal **RFID cards** using an **RC522 reader**, authenticate with a **4-digit PIN**, interact with their saved whiteboards using a **green LED pen** and a **Logitech USB tracking camera**, and access their whiteboards remotely via a web application at **`https://digibook.pranab.space`**.

---

## 🛠️ Hardware Requirements

1. **Raspberry Pi 3B+** running Raspberry Pi OS (64-bit).
2. **Logitech USB Camera** for real-time green LED optical tracking.
3. **RC522 RFID Reader** connected via SPI.
4. **Green LED Pen / Stylus** (5mm Green LED emitting ~520–530nm with momentary push button).
5. **Projector / External Display** (HDMI output, any resolution or aspect ratio).

---

## 🏗️ Software Architecture

```
                                  Cloudflare Tunnel
                               (digibook.pranab.space)
                                          │
                                          ▼
┌──────────────────┐            ┌───────────────────┐
│ Local Pygame App │            │  Flask Web App    │
│    (run.py)      │            │ (Gunicorn :5000)  │
└────────┬─────────┘            └─────────┬─────────┘
         │                                │
         └───────────────┬────────────────┘
                         ▼
             ┌───────────────────────┐
             │   Shared Core Modules │
             │  (auth, database,     │
             │   whiteboard storage) │
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │ MySQL/MariaDB Database│
             │       (digibook)      │
             └───────────────────────┘
```

- **Resolution-Independent Coordinates**: All stroke geometry is recorded and stored in normalized `[0.0, 1.0]` coordinates, guaranteeing drawings never distort across different displays or when viewed on the web.
- **Two-Stage Green LED Detector**: Real-time spectral chromaticity detector (`(G - R) + (G - B) >= 24.0`) that guarantees 100% rejection of white screen content and ambient room lights.
- **Dual Interface, Single Backend**: Both the local Raspberry Pi screen and the remote web app share the exact same database, authentication rules, and drawing engine.

---

## 📂 Repository Structure

```
DigiBook/
├── run.py                          # Local application entry point
├── requirements.txt                # Python package dependencies
├── .env.example                    # Environment configuration template
│
├── config/                         # Configuration
│   ├── settings.py                 # Core paths, database, session constants
│   └── hardware.py                 # Camera, LED thresholds, RFID pins
│
├── core/                           # Shared Backend Core
│   ├── database.py                 # Thread-safe MySQL connection pool
│   ├── auth.py                     # RFID lookup, bcrypt PIN hashing, sessions
│   └── models.py                   # Student, Whiteboard, Stroke dataclasses
│
├── hardware/                       # Hardware Abstraction Layer
│   ├── camera.py                   # Logitech USB & CSI camera interface
│   ├── detector.py                 # Two-stage green LED optical detector
│   ├── transformer.py              # Homography coordinate transformation
│   ├── calibration.py              # Screen-to-camera calibration studio
│   ├── rfid.py                     # RC522 RFID reader interface
│   └── simulation.py               # Hardware simulation for PC development
│
├── whiteboard/                     # Drawing & Storage Engine
│   ├── engine.py                   # Normalized stroke recording & anti-spike
│   ├── renderer.py                 # Pygame renderer & Viewport zoom
│   ├── storage.py                  # MySQL JSON persistence & thumbnail generator
│   └── tools.py                    # Pen, Eraser, and color palette definitions
│
├── local/                          # Local Raspberry Pi UI (Pygame)
│   ├── input_manager.py            # LED pen dwell/hover/click event manager
│   ├── rfid_screen.py              # RFID card waiting screen
│   ├── pin_entry.py                # 4-digit PIN entry keypad screen
│   ├── dashboard.py                # Student dashboard & '+' new card
│   └── whiteboard_view.py          # Local whiteboard canvas with toolbar
│
├── webapp/                         # Web Application (Flask)
│   ├── app.py                      # Flask application factory
│   ├── api.py                      # REST API routes (/api/v1/...)
│   ├── views.py                    # HTML routes (/signup, /signin, /dashboard)
│   ├── auth_web.py                 # Flask-Login web authentication
│   ├── templates/                  # Jinja2 HTML templates
│   └── static/                     # CSS, Canvas JS, and API client scripts
│
├── SQL/                            # Database Resources
│   ├── init_database.sql           # Database & user creation
│   ├── schema.sql                  # MySQL/MariaDB table definitions
│   └── seed.sql                    # Test seed data
│
├── deployment/                     # Production Deployment
│   ├── digibook-web.service        # Gunicorn systemd service
│   ├── digibook-local.service      # Local Pygame app systemd service
│   ├── gunicorn.conf.py            # RPi-optimized Gunicorn configuration
│   ├── cloudflare-tunnel.yml       # Cloudflare Tunnel config
│   └── backup_database.sh          # Daily database backup script
│
├── models/                         # Trained ML models & bulb templates
└── tests/                          # Automated Pytest test suite
```

---

## 🚀 Quick Start (Development / Simulation Mode)

You can run and test the complete system on Windows, Linux, or macOS without any physical Raspberry Pi or RFID hardware attached:

### 1. Install Dependencies
```bash
python -m pip install -r requirements.txt
```

### 2. Configure Environment
```bash
cp .env.example .env
```

### 3. Run Automated Tests
```bash
python -m pytest tests/ -v
```

### 4. Launch Local Application (Simulation Mode)
```bash
python run.py --simulate -w
```
- **RFID Scan**: Press **`R`** on the keyboard to simulate scanning a test RFID card.
- **LED Pen**: Use your mouse as the green LED pen (move to hover/dwell on keypad or cards; hold left click to draw on the canvas).

### 5. Launch Web Application
```bash
python -m webapp.app
```
Open **`http://localhost:5000`** in your browser to access the signup, signin, dashboard, and web canvas.

---

## 🍓 Production Raspberry Pi Deployment

For comprehensive deployment instructions, systemd service installation, and Cloudflare Tunnel setup for `https://digibook.pranab.space`, see:
👉 [deployment/README.md](deployment/README.md)

---

## 🎮 Local Whiteboard Controls

| Control | Action |
|---|---|
| **Hover Pen over Card / Button** | Displays dwell circle; triggers click after 0.75 seconds |
| **Press Pen Button on Canvas** | Draws solid stroke at detected LED coordinates |
| **Release Pen Button** | Lifts pen; breaks stroke |
| **Toolbar `ERASER`** | Switches active tool to eraser |
| **Toolbar `ZOOM +` / `ZOOM -`** | Zooms in/out of the resolution-independent canvas |
| **Toolbar `SAVE`** | Saves structured JSON stroke data and thumbnail to MySQL |
| **Toolbar `< BACK`** | Auto-saves and returns to personal student dashboard |
| **`ESC` key** | Returns to previous screen / Exits |

---

## 🔒 Security Architecture

- **Two-Factor Authentication**: Access requires both physical possession of the student's RFID card and their private 4-digit PIN.
- **bcrypt Hashing**: All 4-digit PINs are hashed using bcrypt with 12 work rounds before database storage.
- **Rate Limiting**: Multiple failed PIN attempts trigger automatic IP and account lockouts (5 failed attempts = 15-minute lockout).
- **Parameterized Queries**: All database interactions use strictly parameterized SQL statements through PyMySQL to eliminate SQL injection vulnerabilities.
