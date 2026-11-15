#!/usr/bin/env python3
"""
DigiBook — Main Application Entry Point
Hardware: Raspberry Pi 3B+ (or Windows/Linux PC in simulation mode)
RC522 RFID reader · Logitech USB Camera · Green LED Pen · Projector/Display
"""

import os
import sys
import time
import argparse
import logging
import numpy as np

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config.settings import SCREEN_WIDTH, SCREEN_HEIGHT, SIMULATION_MODE, is_raspberry_pi
from config.hardware import CAMERA_DEVICE_INDEX, CAMERA_BACKEND, LED_TYPE
from core.database import get_db
from hardware import create_hardware, CoordinateTransformer
from hardware.calibration import calibration_exists, load_calibration
from local.input_manager import LEDInputManager, InputEvent
from local.rfid_screen import RFIDScanScreen
from local.pin_entry import PINEntryScreen
from local.dashboard import LocalDashboard
from local.whiteboard_view import LocalWhiteboardView

try:
    import pygame
except ImportError:
    pygame = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("DigiBook.Main")


# Application State Machine constants
STATE_WAIT_RFID = "wait_rfid"
STATE_PIN_CREATE = "pin_create"
STATE_PIN_LOGIN = "pin_login"
STATE_DASHBOARD = "dashboard"
STATE_WHITEBOARD = "whiteboard"


def parse_args():
    parser = argparse.ArgumentParser(description="DigiBook — RFID Digital Whiteboard System")
    parser.add_argument("-c", "--camera", type=str, default=CAMERA_BACKEND, help="Camera backend ('usb', 'ribbon', 'auto')")
    parser.add_argument("-d", "--device", type=int, default=CAMERA_DEVICE_INDEX, help="USB camera device index (default: 0)")
    parser.add_argument("-s", "--simulate", action="store_true", default=False, help="Force simulation mode (default: use physical hardware on Raspberry Pi)")
    parser.add_argument("-w", "--windowed", action="store_true", help="Run windowed instead of fullscreen")
    parser.add_argument("--skip-calibration", action="store_true", help="Skip display calibration studio on startup")
    return parser.parse_args()


def main():
    args = parse_args()
    is_rpi = is_raspberry_pi()
    effective_simulation = args.simulate or (not is_rpi)

    logger.info("Initializing DigiBook on %dx%d (Simulation=%s, Physical RPi Hardware=%s)...", SCREEN_WIDTH, SCREEN_HEIGHT, effective_simulation, is_rpi and not effective_simulation)

    # 1. Initialize Pygame Display
    if pygame is None:
        logger.critical("Pygame is required to run the DigiBook local interface. Please install pygame.")
        sys.exit(1)

    pygame.init()
    if args.windowed or effective_simulation:
        screen = pygame.display.set_mode((min(1280, SCREEN_WIDTH), min(720, SCREEN_HEIGHT)))
    else:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)

    width = screen.get_width()
    height = screen.get_height()
    pygame.display.set_caption(f"DigiBook — RFID Digital Whiteboard ({width}x{height})")
    clock = pygame.time.Clock()

    # 2. Database Connection Check
    db = get_db()
    if db.ping():
        logger.info("Connected to local MySQL database successfully.")
    else:
        logger.warning("Could not ping MySQL database on startup. Offline / fallback mode active.")

    # 3. Hardware Initialization
    rfid_reader, camera, detector = create_hardware(simulation=effective_simulation)
    try:
        camera.start()
    except Exception as e:
        logger.error("Could not start camera (%s). Switching to simulated camera.", e)
        from hardware.simulation import SimulatedCamera
        camera = SimulatedCamera()
        camera.start()

    # 4. Interactive Display Calibration Studio
    # First calibrate display boundaries to camera view (Auto DocScanner or Manual Pins)
    homography_matrix = None
    if not args.skip_calibration:
        logger.info("Launching Display Calibration Studio...")
        try:
            from hardware.calibration import run_calibration
            homography_matrix = run_calibration(camera, screen=screen)
            logger.info("Display calibration completed successfully.")
        except KeyboardInterrupt:
            logger.info("Calibration skipped by user, loading saved/default bounds.")
        except Exception as e:
            logger.warning("Calibration studio note (%s); loading saved/default bounds.", e)

    if homography_matrix is None and calibration_exists():
        try:
            homography_matrix = load_calibration()
            logger.info("Loaded previously saved display calibration data.")
        except Exception:
            pass

    if homography_matrix is None:
        # Fallback to linear scale 1:1
        homography_matrix = np.eye(3, dtype=np.float64)
        logger.info("Using 1:1 default coordinate mapping.")

    transformer = CoordinateTransformer(homography_matrix, screen_width=width, screen_height=height)
    input_manager = LEDInputManager(transformer=transformer)

    # 5. UI Views & State Machine
    state = STATE_WAIT_RFID
    current_student = None
    current_session_token = None
    current_whiteboard = None

    rfid_screen = RFIDScanScreen(width, height, simulation_mode=effective_simulation)
    pin_screen = None
    dashboard = None
    whiteboard_view = None

    def on_open_whiteboard(wb_id: int):
        nonlocal state, whiteboard_view, current_whiteboard
        from whiteboard.storage import get_whiteboard
        wb = get_whiteboard(wb_id, student_id=current_student.id, db=db)
        if wb:
            current_whiteboard = wb
            whiteboard_view = LocalWhiteboardView(width, height, wb, on_back=on_back_to_dashboard)
            whiteboard_view.load_from_database(db=db)
            state = STATE_WHITEBOARD
            logger.info("Opened whiteboard ID %d ('%s')", wb.id, wb.title)

    def on_back_to_dashboard():
        nonlocal state, dashboard
        if dashboard:
            dashboard.refresh_whiteboards(db=db)
        state = STATE_DASHBOARD
        logger.info("Returned to dashboard.")

    def on_logout():
        nonlocal state, current_student, current_session_token
        from core.auth import revoke_session
        if current_session_token:
            revoke_session(current_session_token, db=db)
        current_student = None
        current_session_token = None
        state = STATE_WAIT_RFID
        rfid_screen.show_info("Logged out successfully.")
        logger.info("Student logged out.")

    logger.info("DigiBook main loop active.")

    running = True
    try:
        while running:
            # --- Event Handling ---
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        if state == STATE_WHITEBOARD:
                            on_back_to_dashboard()
                        elif state == STATE_DASHBOARD:
                            on_logout()
                        else:
                            running = False
                    elif event.key == pygame.K_r:
                        # Instant card trigger (works in both simulation and hardware mode)
                        test_uid = None
                        if hasattr(rfid_reader, "wait_for_card"):
                            card_res = rfid_reader.wait_for_card(timeout=0.01)
                            if card_res:
                                test_uid = card_res[0]
                        if not test_uid:
                            # Test with registered student in database needing PIN setup
                            try:
                                sample_stu = db.execute_one("SELECT rfid_key FROM students WHERE pin_set = 0 LIMIT 1")
                                if not sample_stu:
                                    sample_stu = db.execute_one("SELECT rfid_key FROM students LIMIT 1")
                                if sample_stu and sample_stu.get("rfid_key"):
                                    test_uid = str(sample_stu["rfid_key"])
                            except Exception:
                                pass
                        if not test_uid:
                            test_uid = "282602309346"

                        logger.info("['R' Key Pressed] Triggering RFID scan for UID: %s", test_uid)
                        scan_status, stu = rfid_screen.process_card_scan(test_uid, db=db)
                        logger.info("RFID Scanned: UID=%s -> Status: %s", test_uid, scan_status)
                        if scan_status == "NEEDS_PIN_CREATION":
                            current_student = stu
                            pin_screen = PINEntryScreen(width, height, stu, mode=PINEntryScreen.MODE_CREATE)
                            state = STATE_PIN_CREATE
                            logger.info("Student '%s' recognized! Starting first-time 4-digit PIN setup.", stu.student_name)
                        elif scan_status == "NEEDS_PIN_ENTRY":
                            current_student = stu
                            pin_screen = PINEntryScreen(width, height, stu, mode=PINEntryScreen.MODE_LOGIN)
                            state = STATE_PIN_LOGIN
                            logger.info("Student '%s' recognized! Prompting for 4-digit PIN.", stu.student_name)
                        elif scan_status == "NOT_FOUND":
                            rfid_screen.show_error(f"UID {test_uid}: Not in Database (Register Student)", duration=4.5)
                            logger.warning("RFID UID '%s' is NOT present in the database! Register student at https://digibook.pranab.space/signup", test_uid)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    # Direct mouse click support for buttons, cards, and keypad
                    mx, my = event.pos
                    if state in (STATE_PIN_CREATE, STATE_PIN_LOGIN) and pin_screen is not None:
                        for zone in pin_screen.zones:
                            if zone.contains((mx, my)):
                                if zone.action_callback:
                                    zone.action_callback()
                                break
                    elif state == STATE_DASHBOARD and dashboard is not None:
                        for zone in dashboard.zones:
                            if zone.contains((mx, my)):
                                if zone.action_callback:
                                    zone.action_callback()
                                break
                    elif state == STATE_WHITEBOARD and whiteboard_view is not None:
                        for zone in whiteboard_view.zones:
                            if zone.contains((mx, my)):
                                if zone.action_callback:
                                    zone.action_callback()
                                break

            # Non-blocking hardware RFID poll when on RFID wait screen
            if state == STATE_WAIT_RFID:
                card = rfid_reader.read_card_nonblocking()
                if card:
                    uid, _ = card
                    scan_status, stu = rfid_screen.process_card_scan(uid, db=db)
                    logger.info("RFID Scanned: UID=%s -> Status: %s", uid, scan_status)
                    if scan_status == "NEEDS_PIN_CREATION":
                        current_student = stu
                        pin_screen = PINEntryScreen(width, height, stu, mode=PINEntryScreen.MODE_CREATE)
                        state = STATE_PIN_CREATE
                        logger.info("Student '%s' recognized! Starting first-time 4-digit PIN setup.", stu.student_name)
                    elif scan_status == "NEEDS_PIN_ENTRY":
                        current_student = stu
                        pin_screen = PINEntryScreen(width, height, stu, mode=PINEntryScreen.MODE_LOGIN)
                        state = STATE_PIN_LOGIN
                        logger.info("Student '%s' recognized! Prompting for 4-digit PIN.", stu.student_name)
                    elif scan_status == "NOT_FOUND":
                        rfid_screen.show_error(f"UID {uid}: Not in Database (Register Student)", duration=4.5)
                        logger.warning("RFID UID '%s' is NOT present in the database! Register student at https://digibook.pranab.space/signup", uid)

            # --- Camera Capture & Green LED Tracking ---
            try:
                frame = camera.capture_frame()
            except Exception:
                frame = np.zeros((480, 640, 3), dtype=np.uint8)

            cam_point, _, _, metadata = detector.detect_debug(frame)
            is_emitting = metadata.get("is_emitting", False)

            # If camera does not see active pen, mouse can provide pointer coordinates
            if cam_point is None and pygame.mouse.get_focused():
                mx, my = pygame.mouse.get_pos()
                m_pressed = pygame.mouse.get_pressed()
                if m_pressed[0]:
                    is_emitting = True
                cam_point = (mx, my)

            # --- Active View Processing & Rendering ---
            if state == STATE_WAIT_RFID:
                rfid_screen.render(screen)

            elif state in (STATE_PIN_CREATE, STATE_PIN_LOGIN) and pin_screen is not None:
                # Mouse hover highlight for keypad buttons
                if pygame.mouse.get_focused():
                    mx, my = pygame.mouse.get_pos()
                    for z in pin_screen.zones:
                        if z.contains((mx, my)):
                            z.dwell_progress = max(z.dwell_progress, 0.5)

                event_type, scr_pt, _ = input_manager.update(
                    cam_point=cam_point,
                    is_emitting=is_emitting,
                    zones=pin_screen.zones,
                    is_drawing_mode=False,
                )
                pin_screen.render(screen)
                input_manager.render_cursor(screen)

                # Check submission
                success, token = pin_screen.check_submission(db=db)
                if success:
                    current_session_token = token
                    dashboard = LocalDashboard(width, height, current_student, on_open_whiteboard, on_logout)
                    dashboard.refresh_whiteboards(db=db)
                    state = STATE_DASHBOARD
                    logger.info("Authentication complete. Switched to dashboard.")

            elif state == STATE_DASHBOARD and dashboard is not None:
                # Mouse hover highlight for cards and buttons
                if pygame.mouse.get_focused():
                    mx, my = pygame.mouse.get_pos()
                    for z in dashboard.zones:
                        if z.contains((mx, my)):
                            z.dwell_progress = max(z.dwell_progress, 0.5)

                event_type, scr_pt, _ = input_manager.update(
                    cam_point=cam_point,
                    is_emitting=is_emitting,
                    zones=dashboard.zones,
                    is_drawing_mode=False,
                )
                dashboard.render(screen)
                input_manager.render_cursor(screen)

            elif state == STATE_WHITEBOARD and whiteboard_view is not None:
                # Mouse hover highlight for toolbar buttons
                if pygame.mouse.get_focused():
                    mx, my = pygame.mouse.get_pos()
                    for z in whiteboard_view.zones:
                        if z.contains((mx, my)):
                            z.dwell_progress = max(z.dwell_progress, 0.5)

                event_type, scr_pt, _ = input_manager.update(
                    cam_point=cam_point,
                    is_emitting=is_emitting,
                    zones=whiteboard_view.zones,
                    is_drawing_mode=True,
                )

                # Mouse drawing support: left-click and drag on canvas
                mouse_drawing = False
                if pygame.mouse.get_pressed()[0]:
                    mx, my = pygame.mouse.get_pos()
                    over_toolbar = any(z.contains((mx, my)) for z in whiteboard_view.zones)
                    if not over_toolbar:
                        mouse_drawing = True
                        whiteboard_view.handle_screen_point(mx, my, is_emitting=True)

                if not mouse_drawing:
                    if scr_pt:
                        whiteboard_view.handle_screen_point(scr_pt[0], scr_pt[1], is_emitting=is_emitting)
                    else:
                        whiteboard_view.handle_screen_point(0, 0, is_emitting=False)

                whiteboard_view.update_periodic(db=db)
                whiteboard_view.render(screen)
                input_manager.render_cursor(screen)

            pygame.display.flip()
            clock.tick(30)

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received.")
    finally:
        logger.info("Cleaning up resources...")
        camera.stop()
        rfid_reader.cleanup()
        pygame.quit()
        logger.info("DigiBook shutdown complete.")


if __name__ == "__main__":
    main()
