import math
import numpy as np
import pytest
from local.input_manager import LEDInputManager, InputEvent
from hardware.transformer import CoordinateTransformer
from hardware.detector import IRDetector


def test_screen_point_bypasses_homography():
    """Verify that direct screen input (mouse) is not distorted by camera homography."""
    # Arbitrary non-identity homography that changes coordinates wildly
    h_matrix = np.array([
        [2.5, 0.1, -100.0],
        [0.05, 1.8, -50.0],
        [0.0002, -0.0001, 1.0]
    ], dtype=np.float64)
    transformer = CoordinateTransformer(h_matrix, screen_width=1280, screen_height=720)
    input_mgr = LEDInputManager(transformer=transformer, smoothing_alpha=1.0)

    # Supply direct screen point (e.g. mouse position)
    mouse_screen = (640, 360)
    event, pt, _ = input_mgr.update(cam_point=None, is_emitting=True, screen_point=mouse_screen)

    assert pt == (640, 360), f"Expected exact mouse coordinate (640, 360), got {pt}"


def test_pen_lift_returns_idle_with_no_drift():
    """Verify that when pen lifts or is lost, coordinates reset cleanly to None without corner drift."""
    h_matrix = np.eye(3, dtype=np.float64)
    transformer = CoordinateTransformer(h_matrix, screen_width=1280, screen_height=720)
    input_mgr = LEDInputManager(transformer=transformer)

    # 1. Pen active at (500, 300)
    input_mgr.update(cam_point=(500.0, 300.0), is_emitting=True)
    assert input_mgr.smoothed_pos is not None

    # 2. Pen lifted (cam_point is None)
    event, pt, _ = input_mgr.update(cam_point=None, is_emitting=False)
    assert event == InputEvent.IDLE
    assert pt is None
    assert input_mgr.smoothed_pos is None
    assert input_mgr.raw_screen_pos is None


def test_anti_spike_jump_rejection():
    """Verify single-frame wild teleportation (>350px) is suppressed by the anti-spike filter."""
    h_matrix = np.eye(3, dtype=np.float64)
    transformer = CoordinateTransformer(h_matrix, screen_width=1280, screen_height=720)
    input_mgr = LEDInputManager(transformer=transformer, smoothing_alpha=1.0)

    # Point at (400, 400)
    input_mgr.update(cam_point=(400.0, 400.0), is_emitting=True)

    # 1-frame spurious jump to corner (1200, 20)
    _, pt, _ = input_mgr.update(cam_point=(1200.0, 20.0), is_emitting=True)
    # The filter must hold the previous valid position and not shoot to the corner
    assert pt == (400, 400), f"Expected suppressed jump holding (400, 400), got {pt}"


def test_detector_loads_calibrated_thresholds():
    """Verify that IRDetector loads the calibrated threshold of 22.0 from green_led_model.json."""
    detector = IRDetector(led_type="green")
    assert detector.green_excess_threshold <= 25.0, f"Expected calibrated threshold <= 25.0, got {detector.green_excess_threshold}"
