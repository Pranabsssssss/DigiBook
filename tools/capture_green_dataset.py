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
    parser = argparse.ArgumentParser(description="Capture Green LED Dataset for Model Retraining")
    parser.add_argument("-t", "--target", type=int, default=100, help="Target images per category (default: 100)")
    parser.add_argument("-d", "--device", type=int, default=CAMERA_DEVICE_INDEX, help="Camera device index (default: 0)")
    parser.add_argument("-s", "--scale", type=float, default=1.5, help="Display window scale factor (default: 1.5)")
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
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    if not cap.isOpened():
        print(f"[!] Error: Could not open camera device {args.device}")
        sys.exit(1)

    counts = {
        1: len(list(DIR_OFF.glob("*.jpg"))),
        2: len(list(DIR_ON.glob("*.jpg")))
    }

    current_cat = 1 if counts[1] < target else (2 if counts[2] < target else 1)
    is_recording = False
    last_capture_time = 0.0
    capture_interval = 0.08  # ~12 fps during burst

    window_name = "DigiBook — Green LED Dataset Capture Studio"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    print("=" * 65)
    print("   DIGIBOOK GREEN LED DATASET CAPTURE STUDIO")
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

        disp_w = int(640 * args.scale)
        disp_h = int(480 * args.scale)
        disp = cv2.resize(hud_frame, (disp_w, disp_h))
        cv2.imshow(window_name, disp)

        key = cv2.waitKey(1) & 0xFF
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
            # Space toggles or bursts
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
    cv2.destroyAllWindows()

    print("\nCapture Summary:")
    print(f"  Green LED OFF images: {counts[1]}/{target} in {DIR_OFF}")
    print(f"  Green LED ON  images: {counts[2]}/{target} in {DIR_ON}")


if __name__ == "__main__":
    main()
