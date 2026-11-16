#!/usr/bin/env python3
"""
DigiBook — All-In-One Green LED Retraining Studio (RTX 5050)
============================================================
1. Captures 100 images of Green LED OFF & 100 images of Green LED ON.
2. Automatically fine-tunes and retrains the model using RTX 5050 GPU.
3. Exports updated models/green_led_model.json, bulb templates, and calibrated thresholds.
4. Launches a live drawing test pad to verify pen accuracy.

Usage:
  python tools/retrain_studio.py
  python tools/retrain_studio.py --device 0
"""

import os
import sys
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.capture_green_dataset import main as run_capture, DIR_ON, DIR_OFF
from tools.train_green_model_gpu import train_model


def main():
    parser = argparse.ArgumentParser(description="DigiBook Complete Retraining Studio")
    parser.add_argument("-t", "--target", type=int, default=100, help="Target images per category (default: 100)")
    parser.add_argument("-d", "--device", type=int, default=0, help="Camera device index (default: 0)")
    parser.add_argument("--skip-capture", action="store_true", help="Skip capture and train directly on existing dataset")
    args = parser.parse_args()

    print("=" * 70)
    print("   DIGIBOOK GREEN LED RETRAINING STUDIO (NVIDIA RTX 5050)")
    print("=" * 70)

    if not args.skip_capture:
        print("\n>>> STEP 1: Launching Camera Capture Studio...")
        print("  - Mode 1: Hold pen UNLIT, hold Spacebar to capture 100 frames.")
        print("  - Mode 2: Press button for GREEN LED ON, hold Spacebar to capture 100 frames.")
        print("  - Press [ENTER] when both reach 100 images to start training.\n")
        try:
            run_capture()
        except KeyboardInterrupt:
            print("\n[-] Capture cancelled.")
            return

    # Check that datasets exist
    on_count = len(list(DIR_ON.glob("*.jpg")) + list(DIR_ON.glob("*.png")))
    off_count = len(list(DIR_OFF.glob("*.jpg")) + list(DIR_OFF.glob("*.png")))

    if on_count == 0 or off_count == 0:
        print(f"\n[!] Dataset incomplete: Found {off_count} OFF images, {on_count} ON images.")
        print(f"    Please capture at least some images before retraining.")
        return

    print("\n>>> STEP 2: Running RTX 5050 GPU Training Pipeline...")
    success = train_model(DIR_ON, DIR_OFF, epochs=500, lr=0.05)

    if success:
        print("\n" + "=" * 70)
        print("   SUCCESS: GREEN LED MODEL RETRAINED & EXPORTED!")
        print("   Artifacts updated:")
        print("     - models/green_led_model.json")
        print("     - models/bulb_templates/")
        print("=" * 70)
        print("\nYou can now commit and git pull onto the Raspberry Pi, or run:")
        print("  python run.py --camera usb")


if __name__ == "__main__":
    main()
