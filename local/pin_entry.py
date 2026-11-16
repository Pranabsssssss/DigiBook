import time
import threading
from typing import Optional, Tuple, List, Callable
from core.models import Student
from core.auth import authenticate_rfid_pin, set_student_pin, InvalidPinError, AccountLockedError
from local.input_manager import InteractiveZone

try:
    import pygame
except ImportError:
    pygame = None


class PINEntryScreen:
    """
    On-screen PIN entry screen operated completely via LED pen dwell.
    Supports both First-Time PIN Creation and Subsequent RFID+PIN Login.
    """

    MODE_LOGIN = "login"
    MODE_CREATE = "create"

    def __init__(self, screen_width: int, screen_height: int, student: Student, mode: str = MODE_LOGIN):
        self.width = screen_width
        self.height = screen_height
        self.student = student
        self.mode = mode

        # PIN input state
        self.entered_pin: str = ""
        self.creation_confirm_pin: str = ""
        self.is_confirming: bool = False

        self.error_message: Optional[str] = None
        self.error_expiry: float = 0.0

        # UI Zones
        self.zones: List[InteractiveZone] = []
        self._build_keypad_zones()

        # Fonts
        if pygame and pygame.font.get_init():
            self.font_title = pygame.font.SysFont("Arial", 32, bold=True)
            self.font_sub = pygame.font.SysFont("Arial", 22)
            self.font_btn = pygame.font.SysFont("Arial", 28, bold=True)
            self.font_msg = pygame.font.SysFont("Arial", 20, bold=True)
        else:
            self.font_title = None

    def _build_keypad_zones(self):
        """Construct the 3x4 on-screen keypad zones."""
        self.zones.clear()
        btn_w = 90
        btn_h = 75
        gap = 18
        grid_w = 3 * btn_w + 2 * gap
        grid_h = 4 * btn_h + 3 * gap

        start_x = (self.width - grid_w) // 2
        start_y = (self.height - grid_h) // 2 + 50

        # Digits 1-9
        for num in range(1, 10):
            r = (num - 1) // 3
            c = (num - 1) % 3
            bx = start_x + c * (btn_w + gap)
            by = start_y + r * (btn_h + gap)
            digit_str = str(num)
            self.zones.append(
                InteractiveZone(
                    zone_id=f"KEY_{digit_str}",
                    rect=(bx, by, btn_w, btn_h),
                    action_callback=lambda d=digit_str: self._on_digit_pressed(d),
                    dwell_time=0.65,
                )
            )

        # Row 4: Backspace (⌫), 0, Clear (C)
        by4 = start_y + 3 * (btn_h + gap)
        # Clear
        self.zones.append(
            InteractiveZone(
                zone_id="KEY_CLEAR",
                rect=(start_x, by4, btn_w, btn_h),
                action_callback=self._on_clear_pressed,
                dwell_time=0.65,
            )
        )
        # 0
        self.zones.append(
            InteractiveZone(
                zone_id="KEY_0",
                rect=(start_x + (btn_w + gap), by4, btn_w, btn_h),
                action_callback=lambda: self._on_digit_pressed("0"),
                dwell_time=0.65,
            )
        )
        # Backspace
        self.zones.append(
            InteractiveZone(
                zone_id="KEY_BACK",
                rect=(start_x + 2 * (btn_w + gap), by4, btn_w, btn_h),
                action_callback=self._on_back_pressed,
                dwell_time=0.65,
            )
        )

    def _on_digit_pressed(self, digit: str):
        if len(self.entered_pin) < 4:
            self.entered_pin += digit

    def _on_back_pressed(self):
        if len(self.entered_pin) > 0:
            self.entered_pin = self.entered_pin[:-1]

    def _on_clear_pressed(self):
        self.entered_pin = ""

    def show_error(self, msg: str, duration: float = 3.0):
        self.error_message = msg
        self.error_expiry = time.time() + duration
        self.entered_pin = ""

    def check_submission(self, db=None) -> Tuple[bool, Optional[str]]:
        """
        Check if 4 digits have been entered and submit asynchronously.
        Returns: (success, session_token_or_error)
        """
        if getattr(self, "is_verifying", False):
            if hasattr(self, "_submission_result"):
                res = self._submission_result
                self.is_verifying = False
                del self._submission_result
                return res
            return False, None

        if len(self.entered_pin) != 4:
            return False, None

        if self.mode == self.MODE_CREATE:
            if not self.is_confirming:
                # Move to confirmation step
                self.creation_confirm_pin = self.entered_pin
                self.entered_pin = ""
                self.is_confirming = True
                return False, None
            else:
                # Check match
                if self.entered_pin != self.creation_confirm_pin:
                    self.show_error("PINs do not match. Please try again.")
                    self.creation_confirm_pin = ""
                    self.is_confirming = False
                    return False, None

                self.is_verifying = True
                pin_val = self.entered_pin

                def _verify_create():
                    try:
                        set_student_pin(self.student.id, pin_val, db=db)
                        self.student.pin_set = True
                        _, token = authenticate_rfid_pin(self.student.rfid_key, pin_val, db=db)
                        self._submission_result = (True, token)
                    except Exception as e:
                        self.show_error(f"Error setting PIN: {e}")
                        self._submission_result = (False, None)

                threading.Thread(target=_verify_create, daemon=True).start()
                return False, None

        elif self.mode == self.MODE_LOGIN:
            self.is_verifying = True
            pin_val = self.entered_pin

            def _verify_login():
                try:
                    _, token = authenticate_rfid_pin(self.student.rfid_key, pin_val, db=db)
                    self._submission_result = (True, token)
                except InvalidPinError:
                    self.show_error("Invalid PIN. Please try again.")
                    self._submission_result = (False, None)
                except AccountLockedError:
                    self.show_error("Account locked: Too many failed attempts.")
                    self._submission_result = (False, None)
                except Exception as e:
                    self.show_error(f"Network error: {e}")
                    self._submission_result = (False, None)

            threading.Thread(target=_verify_login, daemon=True).start()
            return False, None

        return False, None

    def render(self, surface):
        if pygame is None or surface is None:
            return

        now = time.time()
        surface.fill((16, 20, 28))

        # Title / Instructions
        if self.font_title:
            if self.mode == self.MODE_CREATE:
                hdr = "Confirm Your 4-Digit PIN" if self.is_confirming else "Create a 4-Digit PIN"
            else:
                hdr = f"Welcome, {self.student.student_name}!"
            title_surf = self.font_title.render(hdr, True, (0, 240, 255))
            surface.blit(title_surf, (self.width // 2 - title_surf.get_width() // 2, 40))

        if self.font_sub:
            sub = "Re-enter the same 4 digits" if self.is_confirming else "Click with mouse or point pen at digits to enter PIN"
            sub_surf = self.font_sub.render(sub, True, (190, 210, 230))
            surface.blit(sub_surf, (self.width // 2 - sub_surf.get_width() // 2, 85))

        # PIN Dot Indicators
        dot_spacing = 45
        dot_start_x = self.width // 2 - int(1.5 * dot_spacing)
        dot_y = 145
        for i in range(4):
            dx = dot_start_x + i * dot_spacing
            is_filled = i < len(self.entered_pin)
            col = (0, 240, 255) if is_filled else (50, 65, 85)
            pygame.draw.circle(surface, col, (dx, dot_y), 14, 0 if is_filled else 2)

        # Render Keypad Buttons
        for zone in self.zones:
            rx, ry, rw, rh = zone.rect
            is_hovered = zone.dwell_progress > 0
            bg_col = (35, 55, 80) if is_hovered else (24, 30, 42)
            border_col = (0, 240, 255) if is_hovered else (50, 70, 95)
            pygame.draw.rect(surface, bg_col, zone.rect, border_radius=10)
            pygame.draw.rect(surface, border_col, zone.rect, 2, border_radius=10)

            # Label
            label = zone.zone_id.replace("KEY_", "")
            if label == "BACK":
                label = "DEL"
            elif label == "CLEAR":
                label = "CLR"
            if self.font_btn:
                btn_lbl = self.font_btn.render(label, True, (255, 255, 255))
                surface.blit(btn_lbl, (rx + (rw - btn_lbl.get_width()) // 2, ry + (rh - btn_lbl.get_height()) // 2))

        # Verifying Status Banner
        if getattr(self, "is_verifying", False):
            v_box = pygame.Rect(self.width // 2 - 220, self.height - 70, 440, 45)
            pygame.draw.rect(surface, (18, 38, 54), v_box, border_radius=8)
            pygame.draw.rect(surface, (0, 240, 255), v_box, 2, border_radius=8)
            if self.font_msg:
                v_surf = self.font_msg.render("Verifying PIN with DigiBook Cloud...", True, (0, 240, 255))
                surface.blit(v_surf, (v_box.centerx - v_surf.get_width() // 2, v_box.centery - v_surf.get_height() // 2))

        # Error Message Banner
        elif self.error_message and now < self.error_expiry:
            err_box = pygame.Rect(self.width // 2 - 240, self.height - 70, 480, 45)
            pygame.draw.rect(surface, (90, 25, 25), err_box, border_radius=8)
            pygame.draw.rect(surface, (255, 80, 80), err_box, 2, border_radius=8)
            if self.font_msg:
                err_surf = self.font_msg.render(self.error_message, True, (255, 120, 120))
                surface.blit(err_surf, (err_box.centerx - err_surf.get_width() // 2, err_box.centery - err_surf.get_height() // 2))
