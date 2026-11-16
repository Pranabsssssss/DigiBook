#!/usr/bin/env python3
"""
DigiBook — Interactive Green LED Dataset Capture Tool
=====================================================
Captures 100 real-world images of:
  1. Green LED OFF (unlit pen tip & barrel in hand)
  2. Green LED ON  (active green LED emission & light pool)

Usage:
  python tools/capture_green_dataset.py
  python tools/capture_green_dataset.py --target 100 --device 0
"""

import os
import sys
import time
import argparse
from pathlib import Path
import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config.hardware import CAMERA_DEVICE_INDEX, CAMERA_WIDTH, CAMERA_HEIGHT
try:
    from config.settings import DATASET_DIR
    DATASET_ROOT = Path(DATASET_DIR)
except Exception:
    DATASET_ROOT = BASE_DIR / "dataset"
DIR_OFF = DATASET_ROOT / "green_led_off"
DIR_ON = DATASET_ROOT / "green_led_on"

CATEGORIES = {
    1: {
        "key": "green_led_off",
        "name": "GREEN LED OFF (Unlit Stylus / Button Released)",
        "dir": DIR_OFF,
        "color": (255, 200, 0),   # Cyan/Amber HUD
        "target": 100,
        "instructions": "Hold pen UNLIT in hand. Rotate, move closer/farther, point tip at camera."
    },
    2: {
        "key": "green_led_on",
        "name": "GREEN LED ON (Button Pressed / Active Green Light)",
        "dir": DIR_ON,
        "color": (0, 240, 255),   # Electric Cyan HUD
        "target": 100,
        "instructions": "Press button to turn GREEN LED ON. Move across screen at various angles."
    }
}


def parse_args():
    parser = argparse.ArgumentParser(description="Capture Green LED Dataset for Model Retraining at Full Camera Resolution")
    parser.add_argument("-t", "--target", type=int, default=100, help="Target images per category (default: 100)")
    parser.add_argument("-d", "--device", type=int, default=CAMERA_DEVICE_INDEX, help="Camera device index (default: 0)")
    parser.add_argument("-W", "--width", type=int, default=0, help="Target camera width (0 for max hardware resolution)")
    parser.add_argument("-H", "--height", type=int, default=0, help="Target camera height (0 for max hardware resolution)")
    parser.add_argument("-s", "--scale", type=float, default=0.0, help="Display window scale (0 for auto-fit to screen)")
    return parser.parse_args()


def measure_green_meter(frame_bgr: np.ndarray) -> tuple:
    """Measure green channel dominance and excess: (G - R) + (G - B)."""
    if frame_bgr is None or frame_bgr.size == 0:
        return False, 0.0

    b = frame_bgr[:, :, 0].astype(np.int16)
    g = frame_bgr[:, :, 1].astype(np.int16)
    r = frame_bgr[:, :, 2].astype(np.int16)

    gr = g - r
    gb = g - b
    excess = gr + gb

    # Authentic green emission condition
    mask = (gr >= 6) & (gb >= 6) & (excess >= 20)
    if np.any(mask):
        max_exc = float(np.max(excess[mask]))
        return True, max_exc
    return False, 0.0


def draw_hud(frame_bgr: np.ndarray, cat_idx: int, counts: dict, target: int,
             is_recording: bool, green_on: bool, green_excess: float) -> np.ndarray:
    """Render high-contrast HUD for dataset capture."""
    hud = frame_bgr.copy()
    h, w = hud.shape[:2]
    cat = CATEGORIES[cat_idx]

    # Top banner
    overlay = hud.copy()
    cv2.rectangle(overlay, (0, 0), (w, 85), (14, 18, 24), -1)
    cv2.addWeighted(overlay, 0.85, hud, 0.15, 0, hud)

    status_str = "● RECORDING (HOLD SPACE)" if is_recording else "PAUSED (HOLD SPACE TO BURST CAPTURE)"
    status_col = (0, 60, 255) if is_recording else (170, 190, 210)
    cv2.putText(hud, status_str, (16, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.60, status_col, 2)

    cat_title = f"MODE [{cat_idx}/2]: {cat['name']}"
    cv2.putText(hud, cat_title, (16, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.58, cat['color'], 2)

    # Meter
    if green_on:
        meter_str = f"GREEN METER: +{green_excess:.1f} [EMITTING]"
        meter_col = (0, 240, 255)
    else:
        meter_str = f"GREEN METER: +{green_excess:.1f} [IDLE]"
        meter_col = (130, 150, 170)
    cv2.putText(hud, meter_str, (w - 320, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.52, meter_col, 2)

    # Progress bar for active category
    cur_count = counts.get(cat_idx, 0)
    pct = min(1.0, cur_count / max(1, target))
    bar_w = 260
    bar_h = 16
    bx, by = w - 320, 42
    cv2.rectangle(hud, (bx, by), (bx + bar_w, by + bar_h), (40, 50, 65), -1)
    cv2.rectangle(hud, (bx, by), (bx + int(bar_w * pct), by + bar_h), cat['color'], -1)
    cv2.rectangle(hud, (bx, by), (bx + bar_w, by + bar_h), (180, 200, 220), 1)

    prog_str = f"{cur_count}/{target} ({int(pct*100)}%)"
    cv2.putText(hud, prog_str, (bx + 10, by + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 255, 255), 1)

    # Bottom instructions bar
    overlay_btm = hud.copy()
    cv2.rectangle(overlay_btm, (0, h - 55), (w, h), (14, 18, 24), -1)
    cv2.addWeighted(overlay_btm, 0.85, hud, 0.15, 0, hud)

    cv2.putText(hud, cat['instructions'], (16, h - 34), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (220, 235, 250), 1)
    footer_keys = "[1] LED OFF Mode  |  [2] LED ON Mode  |  [SPACE] Burst  |  [C] Single  |  [R] Reset  |  [ESC] Exit"
    cv2.putText(hud, footer_keys, (16, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (140, 160, 180), 1)

    return hud


def main():
    args = parse_args()
    target = args.target

    for cat in CATEGORIES.values():
        cat['dir'].mkdir(parents=True, exist_ok=True)
        cat['target'] = target

    cap = cv2.VideoCapture(args.device)

    # Request full maximum possible hardware resolution
    req_w = args.width if args.width > 0 else 3840
    req_h = args.height if args.height > 0 else 2160
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, req_w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, req_h)

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    if not cap.isOpened() or actual_w <= 0:
        print(f"[!] Error: Could not open camera device {args.device}")
        sys.exit(1)

    print(f"[*] Camera Initialized at Full Native Resolution: {actual_w}x{actual_h} @ {fps:.0f} FPS")

    # Compute preview display window resolution (max 1280x720 so it fits nicely on screen)
    if args.scale > 0.0:
        disp_w = int(actual_w * args.scale)
        disp_h = int(actual_h * args.scale)
    else:
        disp_scale = min(1.0, 1280.0 / max(1, actual_w), 720.0 / max(1, actual_h))
        disp_w = int(actual_w * disp_scale)
        disp_h = int(actual_h * disp_scale)

    counts = {
        1: len(list(DIR_OFF.glob("*.jpg"))),
        2: len(list(DIR_ON.glob("*.jpg")))
    }

    current_cat = 1 if counts[1] < target else (2 if counts[2] < target else 1)
    is_recording = False
    last_capture_time = 0.0
    capture_interval = 0.08  # ~12 fps during burst

    window_name = f"DigiBook — Green LED Capture Studio ({actual_w}x{actual_h} Full Res)"
    use_pygame_fallback = False
    pg_screen = None
    pg_clock = None

    try:
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(window_name, disp_w, disp_h)
    except Exception as e:
        print(f"[*] OpenCV HighGUI note ({e}). Falling back to Pygame display...")
        use_pygame_fallback = True
        try:
            import pygame
            pygame.init()
            pg_screen = pygame.display.set_mode((disp_w, disp_h))
            pygame.display.set_caption(window_name)
            pg_clock = pygame.time.Clock()
        except Exception as pe:
            print(f"[!] Could not initialize display: {pe}")
            sys.exit(1)

    print("=" * 65)
    print(f"   DIGIBOOK FULL RESOLUTION DATASET CAPTURE ({actual_w}x{actual_h})")
    print(f"   Target: {target} images OFF, {target} images ON")
    print("=" * 65)
    print("Controls:")
    print("  [1]     Switch to Mode 1 (Green LED OFF - 100 images)")
    print("  [2]     Switch to Mode 2 (Green LED ON  - 100 images)")
    print("  [SPACE] Hold Spacebar to burst-capture images as you move the pen")
    print("  [C]     Press 'C' to capture a single frame")
    print("  [R]     Reset / clear active category")
    print("  [ENTER] Proceed to Model Training on RTX 5050")
    print("  [ESC]   Exit")
    print("-" * 65)

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            time.sleep(0.01)
            continue

        green_on, green_excess = measure_green_meter(frame)

        # Burst capture logic
        now = time.time()
        if is_recording and (now - last_capture_time >= capture_interval):
            cat = CATEGORIES[current_cat]
            if counts[current_cat] < target:
                counts[current_cat] += 1
                fname = cat['dir'] / f"{cat['key']}_{counts[current_cat]:04d}.jpg"
                cv2.imwrite(str(fname), frame)
                last_capture_time = now
                if counts[current_cat] >= target:
                    is_recording = False
                    print(f"\n[✓] Completed {target} images for {cat['name']}!")
                    if current_cat == 1 and counts[2] < target:
                        current_cat = 2
                        print(f"[*] Auto-switched to Mode 2: Green LED ON.")

        hud_frame = draw_hud(frame, current_cat, counts, target, is_recording, green_on, green_excess)
        disp = cv2.resize(hud_frame, (disp_w, disp_h))

        key = None
        if not use_pygame_fallback:
            try:
                cv2.imshow(window_name, disp)
                cv_k = cv2.waitKey(1) & 0xFF
                if cv_k != 255:
                    key = cv_k
            except Exception:
                use_pygame_fallback = True
                import pygame
                pygame.init()
                pg_screen = pygame.display.set_mode((disp_w, disp_h))
                pygame.display.set_caption(window_name)
                pg_clock = pygame.time.Clock()

        if use_pygame_fallback and pg_screen is not None:
            import pygame
            # Convert BGR to RGB for Pygame surface
            disp_rgb = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
            surf = pygame.image.frombuffer(disp_rgb.tobytes(), (disp_w, disp_h), 'RGB')
            pg_screen.blit(surf, (0, 0))
            pygame.display.flip()
            if pg_clock:
                pg_clock.tick(30)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    key = 27
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        key = 27
                    elif event.key == pygame.K_1:
                        key = ord('1')
                    elif event.key == pygame.K_2:
                        key = ord('2')
                    elif event.key == pygame.K_SPACE:
                        key = ord(' ')
                    elif event.key == pygame.K_c:
                        key = ord('c')
                    elif event.key == pygame.K_r:
                        key = ord('r')
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        key = 13

        if key is not None:
            if key == 27:  # ESC
                break
            elif key == ord('1'):
                current_cat = 1
                is_recording = False
            elif key == ord('2'):
                current_cat = 2
                is_recording = False
            elif key == ord('c') or key == ord('C'):
                cat = CATEGORIES[current_cat]
                counts[current_cat] += 1
                fname = cat['dir'] / f"{cat['key']}_{counts[current_cat]:04d}.jpg"
                cv2.imwrite(str(fname), frame)
                print(f"[+] Saved {fname.name} ({counts[current_cat]}/{target})")
            elif key == ord(' '):
                is_recording = not is_recording
            elif key == ord('r') or key == ord('R'):
                cat = CATEGORIES[current_cat]
                for f in cat['dir'].glob("*.jpg"):
                    try:
                        f.unlink()
                    except Exception:
                        pass
                counts[current_cat] = 0
                print(f"[-] Cleared all images in {cat['dir']}")
            elif key == 13:  # ENTER
                if counts[1] >= target and counts[2] >= target:
                    print("\n[✓] Both categories complete! Ready for RTX 5050 training.")
                    break
                else:
                    print(f"[!] Need {target} images each. Current: OFF={counts[1]}/{target}, ON={counts[2]}/{target}")

    cap.release()
    if not use_pygame_fallback:
        cv2.destroyAllWindows()
    else:
        try:
            import pygame
            pygame.quit()
        except Exception:
            pass

    print("\nCapture Summary:")
    print(f"  Green LED OFF images: {counts[1]}/{target} in {DIR_OFF}")
    print(f"  Green LED ON  images: {counts[2]}/{target} in {DIR_ON}")


if __name__ == "__main__":
    main()
