import os
import sys

# Try loading python-dotenv if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# === Base Directories ===
CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CONFIG_DIR)

CALIBRATION_DIR = os.path.join(BASE_DIR, "calibration_data")
CALIBRATION_FILE = os.path.join(CALIBRATION_DIR, "calibration.json")
MODELS_DIR = os.path.join(BASE_DIR, "models")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
SAVE_DIR = os.path.join(BASE_DIR, "saves")

os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(CALIBRATION_DIR, exist_ok=True)
os.makedirs(SAVE_DIR, exist_ok=True)

IR_MODEL_FILE = os.path.join(MODELS_DIR, "ir_led_model.json")
GREEN_MODEL_FILE = os.path.join(MODELS_DIR, "green_led_model.json")
PEN_MODEL_FILE = os.path.join(MODELS_DIR, "pen_model.json")

# === Environment & Simulation Detection ===
def is_raspberry_pi() -> bool:
    """Detect if running on Raspberry Pi hardware."""
    try:
        for p in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    if "Raspberry Pi" in f.read():
                        return True
        if os.path.exists("/proc/cpuinfo"):
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                if "Raspberry Pi" in content or "BCM2835" in content or "BCM2711" in content or "BCM2837" in content:
                    return True
        # Check for Pi-specific peripheral hardware devices
        if os.path.exists("/dev/gpiomem") or os.path.exists("/dev/spidev0.0"):
            return True
    except Exception:
        pass
    return False

DIGIBOOK_ENV = os.environ.get("DIGIBOOK_ENV", "development").lower()
_sim_env = os.environ.get("DIGIBOOK_SIMULATE")
if _sim_env is not None:
    SIMULATION_MODE = _sim_env.strip() in ("1", "true", "True")
else:
    # Auto-detect: if not on Raspberry Pi, default to simulation mode
    SIMULATION_MODE = not is_raspberry_pi()

# === Database Configuration ===
DB_HOST = os.environ.get("DB_HOST", "db.aerochrome.in")
DB_PORT = int(os.environ.get("DB_PORT", 3306))
DB_USER = os.environ.get("DB_USER", "u672633758_digibook")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "DigiBook@8520")
DB_NAME = os.environ.get("DB_NAME", "u672633758_digibook")
DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", 3))

# === Security & Session Settings ===
FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "digibook-dev-insecure-secret-key-change-in-prod")
PIN_MAX_ATTEMPTS = int(os.environ.get("PIN_MAX_ATTEMPTS", 5))
PIN_LOCKOUT_MINUTES = int(os.environ.get("PIN_LOCKOUT_MINUTES", 15))
SESSION_TIMEOUT_HOURS_LOCAL = int(os.environ.get("SESSION_TIMEOUT_HOURS_LOCAL", 2))
SESSION_TIMEOUT_HOURS_WEB = int(os.environ.get("SESSION_TIMEOUT_HOURS_WEB", 24))

# === Display Resolution Auto-Detection ===
def get_display_resolution(fallback_w: int = 1920, fallback_h: int = 1080) -> tuple[int, int]:
    """
    Auto-detect the native resolution of the current connected display monitor.
    Works across Windows, Raspberry Pi OS (X11 / Wayland / KMS-DRM), macOS, and Linux.
    """
    try:
        import pygame
        if not pygame.get_init():
            pygame.init()
        info = pygame.display.Info()
        if info.current_w > 0 and info.current_h > 0:
            return int(info.current_w), int(info.current_h)
    except Exception:
        pass
    return fallback_w, fallback_h

DETECTED_SCREEN_WIDTH, DETECTED_SCREEN_HEIGHT = get_display_resolution(1920, 1080)
SCREEN_WIDTH = DETECTED_SCREEN_WIDTH
SCREEN_HEIGHT = DETECTED_SCREEN_HEIGHT
DEFAULT_MODE = "production"

# === Real-Time Cloud / Hardware RFID Relay Configuration ===
RFID_RELAY_URL = os.environ.get("RFID_RELAY_URL", "https://rfid.pranab.space").rstrip("/")
RFID_RELAY_AUTH = os.environ.get("RFID_RELAY_AUTH", "00000000")
