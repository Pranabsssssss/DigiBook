import base64
import io
import time
from typing import List, Optional, Tuple, Callable
from core.models import Student, Whiteboard
from whiteboard.storage import list_student_whiteboards, create_whiteboard
from local.input_manager import InteractiveZone

try:
    import pygame
except ImportError:
    pygame = None


class LocalDashboard:
    """
    Local student dashboard running on Raspberry Pi.
    Shows whiteboard cards and '+' card operated via green LED pen dwell.
    """

    def __init__(self, screen_width: int, screen_height: int, student: Student, on_open_whiteboard: Callable, on_logout: Callable):
        self.width = screen_width
        self.height = screen_height
        self.student = student
        self.on_open_whiteboard = on_open_whiteboard
        self.on_logout = on_logout

        self.whiteboards: List[Whiteboard] = []
        self.thumbnail_surfaces: dict = {}  # wb_id -> pygame.Surface

        self.current_page = 0
        self.cards_per_page = 6

        self.zones: List[InteractiveZone] = []

        if pygame and pygame.font.get_init():
            self.font_header = pygame.font.SysFont("Arial", 28, bold=True)
            self.font_user = pygame.font.SysFont("Arial", 20)
            self.font_card_title = pygame.font.SysFont("Arial", 18, bold=True)
            self.font_card_sub = pygame.font.SysFont("Arial", 14)
            self.font_plus = pygame.font.SysFont("Arial", 64, bold=True)
            self.font_btn = pygame.font.SysFont("Arial", 16, bold=True)
        else:
            self.font_header = None

    def refresh_whiteboards(self, db=None):
        """Fetch updated whiteboard list from database and cache thumbnails."""
        self.whiteboards = list_student_whiteboards(self.student.id, db=db)
        self.thumbnail_surfaces.clear()

        if pygame:
            for wb in self.whiteboards:
                if wb.thumbnail_b64 and wb.thumbnail_b64.startswith("data:image/png;base64,"):
                    try:
                        raw_b64 = wb.thumbnail_b64.split(",", 1)[1]
                        png_bytes = base64.b64decode(raw_b64)
                        buf = io.BytesIO(png_bytes)
                        surf = pygame.image.load(buf).convert()
                        self.thumbnail_surfaces[wb.id] = surf
                    except Exception:
                        pass

        self._build_dashboard_zones(db=db)

    def _build_dashboard_zones(self, db=None):
        """Build clickable zones for cards, pagination, and logout."""
        self.zones.clear()

        # Top Bar Logout Button
        logout_btn_w = 110
        logout_btn_h = 42
        logout_rect = (self.width - logout_btn_w - 30, 20, logout_btn_w, logout_btn_h)
        self.zones.append(
            InteractiveZone(
                zone_id="BTN_LOGOUT",
                rect=logout_rect,
                action_callback=self.on_logout,
                dwell_time=0.8,
            )
        )

        # Card Grid Layout: 3 columns x 2 rows
        cols = 3
        rows = 2
        card_w = min(260, (self.width - 120) // cols)
        card_h = min(170, (self.height - 200) // rows)
        gap_x = 24
        gap_y = 20

        grid_w = cols * card_w + (cols - 1) * gap_x
        start_x = (self.width - grid_w) // 2
        start_y = 100

        # Current page slice
        start_idx = self.current_page * self.cards_per_page
        page_wbs = self.whiteboards[start_idx : start_idx + self.cards_per_page]

        # Whiteboard Cards
        for idx, wb in enumerate(page_wbs):
            r = idx // cols
            c = idx % cols
            cx = start_x + c * (card_w + gap_x)
            cy = start_y + r * (card_h + gap_y)
            wb_id = wb.id
            self.zones.append(
                InteractiveZone(
                    zone_id=f"CARD_WB_{wb_id}",
                    rect=(cx, cy, card_w, card_h),
                    action_callback=lambda wid=wb_id: self.on_open_whiteboard(wid),
                    dwell_time=0.75,
                )
            )

        # Dedicated '+' New Whiteboard Card
        # Positioned right after the last whiteboard on the page, or at end
        plus_idx = len(page_wbs)
        if plus_idx < self.cards_per_page:
            r = plus_idx // cols
            c = plus_idx % cols
            px = start_x + c * (card_w + gap_x)
            py = start_y + r * (card_h + gap_y)
            self.zones.append(
                InteractiveZone(
                    zone_id="CARD_NEW_PLUS",
                    rect=(px, py, card_w, card_h),
                    action_callback=lambda: self._create_and_open_new(db=db),
                    dwell_time=0.75,
                )
            )

    def _create_and_open_new(self, db=None):
        """Create a new whiteboard in database and immediately open it."""
        new_title = f"Whiteboard {len(self.whiteboards) + 1}"
        new_wb = create_whiteboard(self.student.id, title=new_title, db=db)
        self.on_open_whiteboard(new_wb.id)

    def render(self, surface):
        if pygame is None or surface is None:
            return

        surface.fill((16, 20, 28))

        # Top Navigation Header
        pygame.draw.rect(surface, (22, 28, 40), (0, 0, self.width, 76))
        pygame.draw.line(surface, (40, 52, 72), (0, 76), (self.width, 76), 2)

        if self.font_header:
            title_surf = self.font_header.render("DigiBook Whiteboard Dashboard", True, (0, 240, 255))
            surface.blit(title_surf, (30, 22))

        if self.font_user:
            user_lbl = f"{self.student.student_name} ({self.student.class_name})"
            user_surf = self.font_user.render(user_lbl, True, (200, 220, 240))
            surface.blit(user_surf, (self.width - 320, 26))

        # Render Zones & Cards
        for zone in self.zones:
            rx, ry, rw, rh = zone.rect
            is_hovered = zone.dwell_progress > 0

            if zone.zone_id == "BTN_LOGOUT":
                bg = (100, 30, 30) if is_hovered else (60, 20, 20)
                border = (255, 80, 80) if is_hovered else (180, 50, 50)
                pygame.draw.rect(surface, bg, zone.rect, border_radius=6)
                pygame.draw.rect(surface, border, zone.rect, 2, border_radius=6)
                if self.font_btn:
                    btn_txt = self.font_btn.render("LOGOUT", True, (255, 255, 255))
                    surface.blit(btn_txt, (rx + (rw - btn_txt.get_width()) // 2, ry + (rh - btn_txt.get_height()) // 2))

            elif zone.zone_id == "CARD_NEW_PLUS":
                # Dedicated '+' Card
                bg = (20, 45, 60) if is_hovered else (18, 24, 34)
                border = (0, 240, 255) if is_hovered else (45, 65, 85)
                pygame.draw.rect(surface, bg, zone.rect, border_radius=10)
                pygame.draw.rect(surface, border, zone.rect, 3 if is_hovered else 2, border_radius=10)

                # Render large '+' symbol
                if self.font_plus:
                    plus_col = (0, 240, 255) if is_hovered else (120, 150, 180)
                    plus_txt = self.font_plus.render("+", True, plus_col)
                    surface.blit(plus_txt, (rx + (rw - plus_txt.get_width()) // 2, ry + (rh - plus_txt.get_height()) // 2 - 12))

                if self.font_card_sub:
                    new_lbl = self.font_card_sub.render("New Whiteboard", True, (160, 180, 200))
                    surface.blit(new_lbl, (rx + (rw - new_lbl.get_width()) // 2, ry + rh - 30))

            elif zone.zone_id.startswith("CARD_WB_"):
                wb_id = int(zone.zone_id.replace("CARD_WB_", ""))
                wb_item = next((w for w in self.whiteboards if w.id == wb_id), None)
                if not wb_item:
                    continue

                bg = (30, 42, 60) if is_hovered else (20, 26, 38)
                border = (0, 240, 255) if is_hovered else (50, 70, 95)
                pygame.draw.rect(surface, bg, zone.rect, border_radius=10)
                pygame.draw.rect(surface, border, zone.rect, 2, border_radius=10)

                # Render Thumbnail inside card if available
                thumb_surf = self.thumbnail_surfaces.get(wb_id)
                thumb_h = rh - 50
                if thumb_surf:
                    scaled_thumb = pygame.transform.smoothscale(thumb_surf, (rw - 8, thumb_h))
                    surface.blit(scaled_thumb, (rx + 4, ry + 4))
                else:
                    # Black placeholder preview
                    pygame.draw.rect(surface, (0, 0, 0), (rx + 4, ry + 4, rw - 8, thumb_h), border_radius=6)

                # Title & Date
                if self.font_card_title:
                    title_txt = self.font_card_title.render(wb_item.title, True, (255, 255, 255))
                    surface.blit(title_txt, (rx + 10, ry + rh - 40))
                if self.font_card_sub and wb_item.updated_at:
                    date_str = wb_item.updated_at.strftime("%b %d, %H:%M")
                    date_txt = self.font_card_sub.render(date_str, True, (130, 150, 175))
                    surface.blit(date_txt, (rx + 10, ry + rh - 20))
