from config.settings import SCREEN_WIDTH, SCREEN_HEIGHT

# === Operating Bench Dimensions ===
DEV_CAMERA_WIDTH = 540
DEV_CAMERA_HEIGHT = 405

# === Camera Configuration ===
# "auto"   - Automatically detect (tries ribbon cable picamera2, then USB/OpenCV)
# "ribbon" - Force Raspberry Pi CSI camera via onboard ribbon cable (picamera2)
# "usb"    - Force USB webcam via OpenCV (Logitech camera default)
CAMERA_BACKEND = "usb"
CAMERA_DEVICE_INDEX = 0

CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 30

CAMERA_EDGE_MARGIN_TOP = 35
CAMERA_EDGE_MARGIN_BOTTOM = 15
CAMERA_EDGE_MARGIN_SIDE = 15

# === LED Optical Configuration & Color Selection ===
LED_TYPE = "green"
LED_PEN_HAS_BUTTON = True

# --- Green LED Spectral Thresholds ---
# Green LEDs emit at ~520-530nm. When active, camera sensor records high Green (G)
# with suppressed Red (R) and Blue (B).
# Green Excess = (G - R) + (G - B).
# Calibrated against 200 ground-truth images on RTX 5050 GPU
GREEN_EXCESS_THRESHOLD = 22.0      # Calibrated 5th-percentile emission baseline
GREEN_SPECTRAL_RATIO_MIN = 1.25    # 2*G / (max(1.0, R + B))
GREEN_THRESHOLD = 115              # Minimum peak brightness for genuine LED emission hotspot
GREEN_MIN_AREA = 14
GREEN_MAX_AREA = 3500

# --- IR / Near-Infrared Spectral Thresholds ---
IR_THRESHOLD = 240
CALIBRATION_IR_THRESHOLD = 210
IR_PURPLE_EXCESS_THRESHOLD = 8.0
IR_SPECTRAL_RATIO_MIN = 1.14
IR_PURPLE_EXCESS_MIN = 8.0
IR_MIN_AREA = 4
IR_MAX_AREA = 1200

# === Pen & Eraser Configuration ===
PEN_COLOR = (255, 255, 255)
PEN_RADIUS = 4
ERASER_RADIUS = 25
PEN_LIFT_TIMEOUT = 0.16
MAX_STROKE_JUMP = 280

# === Calibration Configuration ===
def get_calibration_points(width: int, height: int, margin: int = 50) -> list[tuple[int, int]]:
    """Calculate dynamic calibration target coordinates for any screen resolution."""
    m_x = min(margin, max(25, int(width * 0.035)))
    m_y = min(margin, max(25, int(height * 0.035)))
    return [
        (m_x, m_y),                             # Top-Left
        (width - m_x, m_y),                     # Top-Right
        (width - m_x, height - m_y),            # Bottom-Right
        (m_x, height - m_y),                    # Bottom-Left
        (width // 2, height // 2)               # Center Validation
    ]

CALIBRATION_POINTS = get_calibration_points(SCREEN_WIDTH, SCREEN_HEIGHT)
CALIBRATION_DOT_RADIUS = 30
CALIBRATION_FRAMES = 10
CALIBRATION_TIMEOUT_SEC = 4
MAX_VALIDATION_ERROR_PX = 50

# === UI Zones & Controls ===
def get_button_rects(width: int, height: int) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    """Calculate dynamic ERASER and SAVE button zones anchored to the bottom-right corner."""
    btn_w = min(140, max(100, int(width * 0.08)))
    btn_h = min(60, max(42, int(height * 0.055)))
    margin_right = min(30, max(15, int(width * 0.02)))
    margin_bottom = min(30, max(15, int(height * 0.03)))
    gap = 16

    save_x = width - margin_right - btn_w
    save_y = height - margin_bottom - btn_h
    eraser_x = save_x - gap - btn_w
    eraser_y = save_y

    return (eraser_x, eraser_y, btn_w, btn_h), (save_x, save_y, btn_w, btn_h)

ERASER_BUTTON_RECT, SAVE_BUTTON_RECT = get_button_rects(SCREEN_WIDTH, SCREEN_HEIGHT)
BUTTON_DWELL_FRAMES = 2

# === RC522 RFID Hardware Pin Config (RPi) ===
RFID_SPI_BUS = 0
RFID_SPI_DEVICE = 0
RFID_RST_PIN = 25
