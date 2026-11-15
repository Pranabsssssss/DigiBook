import cv2
import numpy as np
import pytest
from hardware.detector import IRDetector
from hardware.simulation import SimulatedCamera, SimulatedRFID, SimulatedDetector
from hardware import create_hardware


def test_green_led_synthetic_detection():
    """Verify that IRDetector in green mode detects green LED spots and rejects ambient/white light."""
    detector = IRDetector(led_type="green", threshold=110)

    # 1. Blank frame -> No detection
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    pt, _, _, meta = detector.detect_debug(blank)
    assert pt is None
    assert meta["is_emitting"] is False

    # 2. Authentic green LED spot: (B=30, G=245, R=30)
    green_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.circle(green_frame, (320, 240), 10, (30, 245, 30), -1)
    pt_g, _, _, meta_g = detector.detect_debug(green_frame)
    assert pt_g is not None
    assert abs(pt_g[0] - 320) < 5
    assert abs(pt_g[1] - 240) < 5
    assert meta_g["is_emitting"] is True
    assert meta_g["green_excess"] >= 24.0

    # 3. White light spot (B=255, G=255, R=255) -> Must be rejected
    white_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.circle(white_frame, (320, 240), 10, (255, 255, 255), -1)
    pt_w, _, _, meta_w = detector.detect_debug(white_frame)
    assert pt_w is None
    assert meta_w["is_emitting"] is False

    # 4. Warm incandescent / red-yellow spot (B=30, G=180, R=255) -> Must be rejected
    warm_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.circle(warm_frame, (320, 240), 10, (30, 180, 255), -1)
    pt_y, _, _, meta_y = detector.detect_debug(warm_frame)
    assert pt_y is None
    assert meta_y["is_emitting"] is False


def test_simulated_camera_and_detector():
    """Test simulated camera producing frames and integration with detector."""
    cam = SimulatedCamera(width=640, height=480, fps=30)
    cam.start()
    assert cam.running is True

    # Capture blank
    frame = cam.capture_frame()
    assert frame.shape == (480, 640, 3)

    # Set synthetic green LED point
    cam.set_synthetic_point((200, 150))
    frame_with_led = cam.capture_frame()

    detector = IRDetector(led_type="green", threshold=110)
    pt, _, _, meta = detector.detect_debug(frame_with_led)
    assert pt is not None
    assert abs(pt[0] - 200) < 5
    assert abs(pt[1] - 150) < 5

    cam.stop()
    assert cam.running is False


def test_simulated_rfid_queue():
    """Test SimulatedRFID queuing and scanning mechanism."""
    rfid = SimulatedRFID()
    rfid.queue_card("TEST_UID_999", "Student Test")

    card = rfid.read_card_nonblocking()
    assert card is not None
    assert card[0] == "TEST_UID_999"
    assert card[1] == "Student Test"

    # Queue should now be empty
    assert rfid.read_card_nonblocking() is None

    # Wait with timeout on empty queue
    assert rfid.wait_for_card(timeout=0.05) is None


def test_hardware_factory():
    """Test create_hardware factory in simulation mode."""
    rfid, cam, det = create_hardware(simulation=True)
    assert isinstance(rfid, SimulatedRFID)
    assert isinstance(cam, SimulatedCamera)
    assert isinstance(det, IRDetector)
