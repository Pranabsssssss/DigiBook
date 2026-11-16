#!/usr/bin/env python3
"""
DigiBook — Interactive Ground-Truth LED Annotation Studio
=========================================================
Allows manual marking of exact LED coordinates (x, y) on captured dataset images:
  - Magnifier Loupe (4x zoom) for millimeter-precise clicking on the 5mm bulb tip
  - Auto-suggestion for LED ON (press Space to accept or click to adjust)
  - Supports Go Back, Skip, Delete, and Resume from saved progress
  - Saves exact ground-truth coordinates to dataset/annotations.json

Usage:
  python tools/annotate_dataset.py
  python tools/annotate_dataset.py --dir dataset/green_led_on
"""

import os
import sys
import json
from pathlib import Path
import cv2
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

try:
    from config.settings import DATASET_DIR
    DATASET_ROOT = Path(DATASET_DIR)
except Exception:
    DATASET_ROOT = BASE_DIR / "dataset"
DIR_OFF = DATASET_ROOT / "green_led_off"
DIR_ON = DATASET_ROOT / "green_led_on"
ANNOTATIONS_FILE = DATASET_ROOT / "annotations.json"


def load_annotations() -> dict:
    if ANNOTATIONS_FILE.exists():
        try:
            with open(ANNOTATIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"green_led_on": {}, "green_led_off": {}}


def save_annotations(data: dict):
    ANNOTATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ANNOTATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def find_green_peak_suggestion(img_bgr: np.ndarray) -> tuple:
    """Finds the peak green excess coordinate to suggest as default for LED ON images."""
    if img_bgr is None or img_bgr.size == 0:
        return None

    b = img_bgr[:, :, 0].astype(np.int16)
    g = img_bgr[:, :, 1].astype(np.int16)
    r = img_bgr[:, :, 2].astype(np.int16)

    gr = g - r
    gb = g - b
    excess = gr + gb

    mask = (gr >= 4) & (gb >= 4) & (excess >= 12)
    if np.any(mask):
        max_val = np.max(excess[mask])
        py, px = np.where((excess == max_val) & mask)
        if len(px) > 0:
            return int(px[0]), int(py[0])
    return None


class AnnotationStudio:
    def __init__(self, category_key: str, folder_path: Path, annotations_dict: dict):
        self.category_key = category_key
        self.folder_path = folder_path
        self.annotations = annotations_dict.setdefault(category_key, {})
        self.all_data = annotations_dict

        self.image_files = sorted(list(folder_path.glob("*.jpg")) + list(folder_path.glob("*.png")))
        self.idx = 0
        self.current_point = None
        self.mouse_pos = (0, 0)
        self.window_name = f"DigiBook Annotator — {category_key.upper()}"

        # Find first unannotated image
        for i, f in enumerate(self.image_files):
            if f.name not in self.annotations:
                self.idx = i
                break

    def on_mouse(self, event, x, y, flags, param):
        self.mouse_pos = (x, y)
        if event == cv2.EVENT_LBUTTONDOWN:
            self.current_point = (x, y)

    def draw_magnifier_loupe(self, canvas: np.ndarray, orig_img: np.ndarray, center: tuple, loupe_x: int, loupe_y: int, size: int = 150, zoom: int = 4):
        """Draws a 4x magnified circular/square loupe showing the area under the cursor."""
        h, w = orig_img.shape[:2]
        cx, cy = center
        half_src = size // (2 * zoom)

        x1 = max(0, cx - half_src)
        y1 = max(0, cy - half_src)
        x2 = min(w, cx + half_src)
        y2 = min(h, cy + half_src)

        crop = orig_img[y1:y2, x1:x2]
        if crop.size == 0 or crop.shape[0] < 4 or crop.shape[1] < 4:
            return

        mag = cv2.resize(crop, (size, size), interpolation=cv2.INTER_NEAREST)

        # Draw loupe border and crosshairs
        cv2.rectangle(canvas, (loupe_x - 2, loupe_y - 2), (loupe_x + size + 2, loupe_y + size + 2), (0, 240, 255), 2)
        canvas[loupe_y:loupe_y+size, loupe_x:loupe_x+size] = mag

        # Center reticle in loupe
        mcx = loupe_x + size // 2
        mcy = loupe_y + size // 2
        cv2.line(canvas, (mcx - 12, mcy), (mcx + 12, mcy), (0, 0, 255), 1)
        cv2.line(canvas, (mcx, mcy - 12), (mcx, mcy + 12), (0, 0, 255), 1)
        cv2.circle(canvas, (mcx, mcy), 3, (0, 255, 255), 1)
        cv2.putText(canvas, f"4x ZOOM ({cx},{cy})", (loupe_x + 6, loupe_y + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 240, 255), 1)

    def run(self):
        if not self.image_files:
            print(f"[*] No images found in {self.folder_path}")
            return

        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(self.window_name, self.on_mouse)

        print("\n" + "=" * 65)
        print(f"   MANUAL GROUND-TRUTH ANNOTATION: {self.category_key.upper()}")
        print(f"   Total Images: {len(self.image_files)}")
        print("=" * 65)
        print("Controls:")
        print("  [LEFT CLICK] Place exact LED coordinate pin")
        print("  [SPACE/ENTER] Confirm coordinate & advance to next image")
        print("  [B / LEFT]    Go back to previous image")
        print("  [S]           Skip this image (blurry or unusable)")
        print("  [D]           Delete this image from dataset")
        print("  [ESC]         Save and exit annotation studio")
        print("-" * 65)

        while 0 <= self.idx < len(self.image_files):
            fpath = self.image_files[self.idx]
            img = cv2.imread(str(fpath))
            if img is None:
                self.idx += 1
                continue

            h, w = img.shape[:2]

            # Determine initial point
            if self.current_point is None:
                if fpath.name in self.annotations:
                    pt_saved = self.annotations[fpath.name]
                    if pt_saved:
                        self.current_point = (int(pt_saved[0]), int(pt_saved[1]))
                elif self.category_key == "green_led_on":
                    suggestion = find_green_peak_suggestion(img)
                    if suggestion:
                        self.current_point = suggestion

            # Draw canvas
            canvas = img.copy()

            # Draw current marked coordinate pin
            if self.current_point is not None:
                px, py = self.current_point
                pin_col = (0, 240, 255) if self.category_key == "green_led_on" else (255, 200, 40)
                cv2.circle(canvas, (px, py), 18, pin_col, 2)
                cv2.circle(canvas, (px, py), 4, (255, 255, 255), -1)
                cv2.drawMarker(canvas, (px, py), (0, 0, 255), cv2.MARKER_CROSS, 22, 1)
                cv2.putText(canvas, f"PIN: ({px},{py})", (px + 14, py - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 2)
                cv2.putText(canvas, f"PIN: ({px},{py})", (px + 14, py - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.48, pin_col, 1)

            # Top Header Card
            overlay = canvas.copy()
            cv2.rectangle(overlay, (0, 0), (w, 65), (14, 18, 24), -1)
            cv2.addWeighted(overlay, 0.85, canvas, 0.15, 0, canvas)

            cat_title = "MODE: GREEN LED ON (Click Center of Glowing LED)" if self.category_key == "green_led_on" else "MODE: GREEN LED OFF (Click 5mm Bulb Tip Dome)"
            cat_col = (0, 240, 255) if self.category_key == "green_led_on" else (255, 200, 40)
            cv2.putText(canvas, cat_title, (16, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.60, cat_col, 2)

            info_str = f"Image [{self.idx + 1}/{len(self.image_files)}] : {fpath.name}  |  Annotated: {len(self.annotations)}/{len(self.image_files)}"
            cv2.putText(canvas, info_str, (16, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (210, 225, 240), 1)

            # Draw Magnifier Loupe in Top-Right
            lx = w - 175
            ly = 80
            hover_target = self.current_point if self.current_point is not None else self.mouse_pos
            self.draw_magnifier_loupe(canvas, img, hover_target, lx, ly, size=160, zoom=4)

            # Bottom Controls bar
            overlay_btm = canvas.copy()
            cv2.rectangle(overlay_btm, (0, h - 38), (w, h), (14, 18, 24), -1)
            cv2.addWeighted(overlay_btm, 0.85, canvas, 0.15, 0, canvas)
            hint_keys = "[CLICK] Place Pin  |  [SPACE/ENTER] Next  |  [B] Previous  |  [S] Skip  |  [D] Delete  |  [ESC] Save & Finish"
            cv2.putText(canvas, hint_keys, (16, h - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (170, 190, 215), 1)

            cv2.imshow(self.window_name, canvas)
            key = cv2.waitKey(20) & 0xFF

            if key == 27:  # ESC
                break
            elif key in (32, 13):  # SPACE or ENTER
                if self.current_point is not None:
                    self.annotations[fpath.name] = [int(self.current_point[0]), int(self.current_point[1])]
                    save_annotations(self.all_data)
                    print(f"  [✓] [{self.idx+1:03d}/{len(self.image_files)}] {fpath.name} -> Marked at ({self.current_point[0]}, {self.current_point[1]})")
                self.idx += 1
                self.current_point = None
            elif key in (ord('b'), ord('B'), 81):  # 'b' or Left Arrow
                if self.idx > 0:
                    self.idx -= 1
                    self.current_point = None
            elif key in (ord('s'), ord('S')):  # Skip
                self.annotations[fpath.name] = None
                save_annotations(self.all_data)
                print(f"  [-] Skipped {fpath.name}")
                self.idx += 1
                self.current_point = None
            elif key in (ord('d'), ord('D')):  # Delete
                try:
                    fpath.unlink()
                    if fpath.name in self.annotations:
                        del self.annotations[fpath.name]
                    save_annotations(self.all_data)
                    print(f"  [x] Deleted {fpath.name}")
                    del self.image_files[self.idx]
                except Exception as e:
                    print(f"Error deleting file: {e}")
                self.current_point = None

        cv2.destroyWindow(self.window_name)
        save_annotations(self.all_data)
        valid_count = sum(1 for v in self.annotations.values() if v is not None)
        print(f"\n[✓] Finished {self.category_key}: {valid_count} ground-truth coordinates saved to {ANNOTATIONS_FILE.name}")


def annotate_all():
    annotations = load_annotations()

    # Step 1: Annotate LED ON images
    if DIR_ON.exists() and len(list(DIR_ON.glob("*.jpg")) + list(DIR_ON.glob("*.png"))) > 0:
        studio_on = AnnotationStudio("green_led_on", DIR_ON, annotations)
        studio_on.run()

    # Step 2: Annotate LED OFF images
    if DIR_OFF.exists() and len(list(DIR_OFF.glob("*.jpg")) + list(DIR_OFF.glob("*.png"))) > 0:
        studio_off = AnnotationStudio("green_led_off", DIR_OFF, annotations)
        studio_off.run()

    print("\n" + "=" * 65)
    print("   GROUND-TRUTH ANNOTATION COMPLETE!")
    print(f"   Coordinates saved to: {ANNOTATIONS_FILE}")
    print("=" * 65)


def main():
    annotate_all()


if __name__ == "__main__":
    main()
