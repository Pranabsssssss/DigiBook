import time
from typing import Optional, Tuple
from core.auth import authenticate_rfid_step1
from core.models import Student

try:
    import pygame
except ImportError:
    pygame = None


class RFIDScanScreen:
    """
    Local Raspberry Pi screen waiting for student RFID card scan.
    """

    def __init__(self, screen_width: int, screen_height: int, simulation_mode: bool = False):
        self.width = screen_width
        self.height = screen_height
        self.simulation_mode = simulation_mode

        self.error_message: Optional[str] = None
        self.error_expiry: float = 0.0
        self.info_message: Optional[str] = None

        if pygame and pygame.font.get_init():
            self.font_title = pygame.font.SysFont("Arial", 42, bold=True)
            self.font_sub = pygame.font.SysFont("Arial", 26)
            self.font_msg = pygame.font.SysFont("Arial", 28, bold=True)
            self.font_hint = pygame.font.SysFont("Arial", 18)
        else:
            self.font_title = None

    def show_error(self, message: str, duration: float = 3.5):
        self.error_message = message
        self.error_expiry = time.time() + duration

    def show_info(self, message: str):
        self.info_message = message

    def process_card_scan(self, rfid_key: str, db=None) -> Tuple[str, Optional[Student]]:
        """
        Handle a scanned RFID card.
        Returns:
            ("NOT_FOUND", None)
            ("NEEDS_PIN_CREATION", student)
            ("NEEDS_PIN_ENTRY", student)
        """
        status, student = authenticate_rfid_step1(rfid_key, db=db)
        if status == "NOT_FOUND":
            self.show_error(f"UID {rfid_key}: Not in Database (Please Register)", duration=4.5)
        return status, student

    def render(self, surface):
        if pygame is None or surface is None:
            return

        now = time.time()
        surface.fill((14, 18, 24))

        # Main Header
        if self.font_title:
            title_surf = self.font_title.render("DIGIBOOK", True, (0, 240, 255))
            surface.blit(title_surf, (self.width // 2 - title_surf.get_width() // 2, self.height // 2 - 160))

            sub_surf = self.font_sub.render("RFID Digital Whiteboard System", True, (200, 220, 240))
            surface.blit(sub_surf, (self.width // 2 - sub_surf.get_width() // 2, self.height // 2 - 100))

        # RFID Card Icon / Visual Target
        card_box = pygame.Rect(self.width // 2 - 180, self.height // 2 - 40, 360, 160)
        pygame.draw.rect(surface, (24, 30, 42), card_box, border_radius=12)
        pygame.draw.rect(surface, (0, 240, 255), card_box, 2, border_radius=12)

        if self.font_sub:
            scan_text = self.font_sub.render("Please Scan Your RFID Card", True, (0, 240, 255))
            surface.blit(scan_text, (card_box.centerx - scan_text.get_width() // 2, card_box.centery - 15))

        # Error / Status Banner
        if self.error_message and now < self.error_expiry:
            err_box = pygame.Rect(self.width // 2 - 320, self.height // 2 + 150, 640, 55)
            pygame.draw.rect(surface, (80, 20, 20), err_box, border_radius=8)
            pygame.draw.rect(surface, (255, 60, 60), err_box, 2, border_radius=8)
            if self.font_msg:
                err_surf = self.font_msg.render(self.error_message, True, (255, 100, 100))
                surface.blit(err_surf, (err_box.centerx - err_surf.get_width() // 2, err_box.centery - err_surf.get_height() // 2))

        # Hardware vs Simulation mode status footer
        if self.font_hint:
            if self.simulation_mode:
                hint_txt = self.font_hint.render("[Simulation Mode: Press 'R' on keyboard to scan default RFID]", True, (100, 120, 140))
            else:
                hint_txt = self.font_hint.render("📡 RC522 Hardware Active: Hold RFID card against reader (Press 'R' to test)", True, (0, 240, 255))
            surface.blit(hint_txt, (self.width // 2 - hint_txt.get_width() // 2, self.height - 40))
