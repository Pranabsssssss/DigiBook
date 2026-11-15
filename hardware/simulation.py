import logging
import time
import queue
from typing import Optional, Tuple, Dict, Any
import numpy as np

logger = logging.getLogger("DigiBook.Simulation")


class SimulatedRFID:
    """
    Simulated RFID reader for development and testing without physical RC522 hardware.
    Supports queued cards for automated unit testing and interactive input.
    """

    DEFAULT_TEST_CARDS = {
        "1234567890": "Alex Rivera (No PIN)",
        "0987654321": "Sam Taylor (PIN: 1234)",
        "5555666677": "New Student (Unregistered)",
    }

    def __init__(self, default_uid: str = "1234567890"):
        self.default_uid = default_uid
        self._card_queue: queue.Queue = queue.Queue()
        self.simulation = True

    def queue_card(self, uid: str, text: str = ""):
        """Inject a card scan event into the queue for automated tests."""
        self._card_queue.put((str(uid).strip(), text.strip()))

    def wait_for_card(self, timeout: Optional[float] = None) -> Optional[Tuple[str, str]]:
        """
        Wait for a queued card or return the default test card.
        """
        start = time.time()
        while True:
            try:
                card = self._card_queue.get_nowait()
                logger.info("[SimulatedRFID] Card popped from queue: UID=%s", card[0])
                return card
            except queue.Empty:
                pass

            if timeout is not None:
                if time.time() - start >= timeout:
                    return None
                time.sleep(0.05)
            else:
                # In interactive mode, return default test card
                logger.info("[SimulatedRFID] Simulating scan of default card: %s", self.default_uid)
                return self.default_uid, self.DEFAULT_TEST_CARDS.get(self.default_uid, "Test Card")

    def read_card_nonblocking(self) -> Optional[Tuple[str, str]]:
        """Non-blocking check of the card queue."""
        try:
            card = self._card_queue.get_nowait()
            logger.info("[SimulatedRFID] Non-blocking read: UID=%s", card[0])
            return card
        except queue.Empty:
            return None

    def cleanup(self):
        while not self._card_queue.empty():
            try:
                self._card_queue.get_nowait()
            except queue.Empty:
                break


class SimulatedCamera:
    """
    Simulated camera returning synthetic frames of shape (H, W, 3).
    Allows complete application lifecycle testing without USB/CSI video capture devices.
    """

    def __init__(self, width: int = 640, height: int = 480, fps: int = 30):
        self.width = width
        self.height = height
        self.fps = fps
        self.running = False
        self._synthetic_green_point: Optional[Tuple[int, int]] = None

    def start(self):
        self.running = True
        logger.info("[SimulatedCamera] Started (%dx%d @ %dfps)", self.width, self.height, self.fps)

    def set_synthetic_point(self, pt: Optional[Tuple[int, int]]):
        """Simulate an active green LED spot in the camera frame."""
        self._synthetic_green_point = pt

    def capture_frame(self) -> np.ndarray:
        if not self.running:
            raise RuntimeError("Camera not started.")

        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        if self._synthetic_green_point is not None:
            import cv2
            cx, cy = self._synthetic_green_point
            # Emulate realistic 5mm green LED: high G, low R & B
            cv2.circle(frame, (cx, cy), 10, (30, 245, 30), -1)
            cv2.circle(frame, (cx, cy), 4, (120, 255, 120), -1)

        return frame

    def stop(self):
        self.running = False
        logger.info("[SimulatedCamera] Stopped.")


class SimulatedDetector:
    """
    Simulated detector mapping mouse / direct points to detection output.
    """

    def __init__(self):
        self.led_type = "green"
        self.simulated_point: Optional[Tuple[float, float]] = None
        self.is_emitting = False

    def set_state(self, point: Optional[Tuple[float, float]], is_emitting: bool = True):
        self.simulated_point = point
        self.is_emitting = is_emitting

    def detect_debug(self, frame: np.ndarray, threshold: Optional[int] = None, display_quad=None):
        h, w = (frame.shape[:2]) if frame is not None else (480, 640)
        annotated = np.zeros((h, w, 3), dtype=np.uint8)
        thresh_rgb = np.zeros((h, w, 3), dtype=np.uint8)

        metadata = {
            "threshold": threshold or 110,
            "bulb_state": "EMITTING" if self.is_emitting else "SEARCHING",
            "is_emitting": self.is_emitting,
            "bulb_pos": self.simulated_point,
            "led_type": self.led_type,
            "excess": 45.0 if self.is_emitting else 0.0,
            "green_excess": 45.0 if self.is_emitting else 0.0,
            "in_display_area": True,
            "status": "EMITTING_DRAWING" if self.is_emitting else "SEARCHING",
        }

        if self.is_emitting and self.simulated_point is not None:
            return self.simulated_point, annotated, thresh_rgb, metadata
        return None, annotated, thresh_rgb, metadata
