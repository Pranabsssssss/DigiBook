import time
from typing import Optional, Callable
from core.models import Whiteboard
from whiteboard.engine import WhiteboardEngine
from whiteboard.renderer import WhiteboardRenderer
from whiteboard.storage import save_whiteboard_strokes, load_whiteboard_strokes
from whiteboard.tools import TOOL_PEN, TOOL_ERASER, COLOR_PALETTE
from local.input_manager import InteractiveZone

try:
    import pygame
except ImportError:
    pygame = None


class LocalWhiteboardView:
    """
    Local whiteboard interaction view on Raspberry Pi.
    Combines WhiteboardEngine, WhiteboardRenderer, and LED button toolbar.
    """

    def __init__(
        self,
        screen_width: int,
        screen_height: int,
        whiteboard: Whiteboard,
        on_back: Callable,
    ):
        self.width = screen_width
        self.height = screen_height
        self.whiteboard = whiteboard
        self.on_back = on_back

        self.engine = WhiteboardEngine()
        self.renderer = WhiteboardRenderer(screen_width, screen_height)

        # Notification / status feedback
        self.notification: Optional[str] = None
        self.notification_expiry: float = 0.0

        # Auto-save timer
        self.last_autosave_time: float = time.time()
        self.autosave_interval: float = 30.0

        # Toolbar interactive zones
        self.zones = []
        self._build_toolbar_zones()

        # Fonts
        if pygame and pygame.font.get_init():
            self.font_btn = pygame.font.SysFont("Arial", 16, bold=True)
            self.font_status = pygame.font.SysFont("Arial", 18)
        else:
            self.font_btn = None

    def load_from_database(self, db=None):
        """Load saved strokes from database into the drawing engine."""
        strokes = load_whiteboard_strokes(self.whiteboard.id, db=db)
        self.engine.load_strokes(strokes)
        self.show_notification(f"Loaded {len(strokes)} strokes")

    def save_to_database(self, db=None):
        """Persist current strokes to MySQL."""
        self.engine.end_stroke()
        strokes = self.engine.strokes
        save_whiteboard_strokes(self.whiteboard.id, strokes, db=db)
        self.last_autosave_time = time.time()
        self.show_notification("Whiteboard Saved Successfully!")

    def show_notification(self, msg: str, duration: float = 2.5):
        self.notification = msg
        self.notification_expiry = time.time() + duration

    def _build_toolbar_zones(self):
        """Create on-screen button zones anchored along the top-right."""
        self.zones.clear()

        btn_w = 90
        btn_h = 42
        gap = 12
        y = 12

        # 1. Back button (top left)
        self.zones.append(
            InteractiveZone(
                zone_id="BTN_BACK",
                rect=(20, y, 90, btn_h),
                action_callback=self._handle_back_pressed,
                dwell_time=0.7,
            )
        )

        # Toolbar items on the right side
        buttons = [
            ("BTN_PEN", "PEN", lambda: self.engine.select_tool(TOOL_PEN.name)),
            ("BTN_ERASER", "ERASER", lambda: self.engine.select_tool(TOOL_ERASER.name)),
            ("BTN_COLOR_GREEN", "GREEN", lambda: self.engine.set_color("#39FF14")),
            ("BTN_COLOR_WHITE", "WHITE", lambda: self.engine.set_color("#FFFFFF")),
            ("BTN_COLOR_CYAN", "CYAN", lambda: self.engine.set_color("#00F0FF")),
            ("BTN_ZOOM_IN", "ZOOM +", lambda: self.renderer.viewport.zoom_in(1.3)),
            ("BTN_ZOOM_OUT", "ZOOM -", lambda: self.renderer.viewport.zoom_out(1.3)),
            ("BTN_CLEAR", "CLEAR", self.engine.clear),
            ("BTN_SAVE", "SAVE", self.save_to_database),
        ]

        total_w = len(buttons) * (btn_w + gap) - gap
        start_x = max(130, self.width - total_w - 20)

        for i, (bid, lbl, cb) in enumerate(buttons):
            bx = start_x + i * (btn_w + gap)
            self.zones.append(
                InteractiveZone(
                    zone_id=bid,
                    rect=(bx, y, btn_w, btn_h),
                    action_callback=cb,
                    dwell_time=0.6,
                )
            )

    def _handle_back_pressed(self):
        # Auto-save before navigating back
        try:
            self.save_to_database()
        except Exception:
            pass
        self.on_back()

    def handle_screen_point(self, screen_x: int, screen_y: int, is_emitting: bool):
        """
        Convert screen point to normalized whiteboard coordinate and update drawing engine.
        """
        if is_emitting:
            norm_x, norm_y = self.renderer.viewport.screen_to_normalized(
                screen_x,
                screen_y,
                self.renderer.canvas_w,
                self.renderer.canvas_h,
                self.renderer.offset_x,
                self.renderer.offset_y,
            )
            self.engine.handle_point(norm_x, norm_y)
        else:
            self.engine.handle_no_point()

    def update_periodic(self, db=None):
        """Handle background auto-saving."""
        now = time.time()
        if (now - self.last_autosave_time) >= self.autosave_interval:
            if self.engine.strokes:
                try:
                    self.save_to_database(db=db)
                except Exception:
                    pass
            self.last_autosave_time = now

    def render(self, surface):
        if pygame is None or surface is None:
            return

        now = time.time()

        # Render canvas & strokes
        all_strokes = self.engine.get_all_strokes()
        self.renderer.render_to_surface(surface, all_strokes)

        # Top Bar Background
        top_bar = pygame.Rect(0, 0, self.width, 64)
        pygame.draw.rect(surface, (20, 26, 36), top_bar)
        pygame.draw.line(surface, (40, 52, 72), (0, 64), (self.width, 64), 2)

        # Render Toolbar Buttons
        for zone in self.zones:
            rx, ry, rw, rh = zone.rect
            is_hovered = zone.dwell_progress > 0

            # Active tool highlight
            is_active_tool = False
            if zone.zone_id == "BTN_PEN" and self.engine.active_tool == TOOL_PEN.name:
                is_active_tool = True
            elif zone.zone_id == "BTN_ERASER" and self.engine.active_tool == TOOL_ERASER.name:
                is_active_tool = True

            if zone.zone_id == "BTN_BACK":
                bg = (60, 20, 20) if is_hovered else (35, 20, 20)
                border = (255, 80, 80) if is_hovered else (150, 50, 50)
                lbl = "< BACK"
            elif is_active_tool:
                bg = (35, 75, 45)
                border = (57, 255, 20)
                lbl = zone.zone_id.replace("BTN_", "")
            elif is_hovered:
                bg = (40, 60, 85)
                border = (0, 240, 255)
                lbl = zone.zone_id.replace("BTN_", "")
            else:
                bg = (25, 32, 45)
                border = (60, 75, 95)
                lbl = zone.zone_id.replace("BTN_", "")

            pygame.draw.rect(surface, bg, zone.rect, border_radius=6)
            pygame.draw.rect(surface, border, zone.rect, 2, border_radius=6)

            if self.font_btn:
                btn_txt = self.font_btn.render(lbl, True, (255, 255, 255))
                surface.blit(btn_txt, (rx + (rw - btn_txt.get_width()) // 2, ry + (rh - btn_txt.get_height()) // 2))

        # Notification Banner
        if self.notification and now < self.notification_expiry:
            if self.font_status:
                notif_txt = self.font_status.render(self.notification, True, (240, 255, 240))
                nb_rect = pygame.Rect(self.width // 2 - 180, self.height - 50, 360, 38)
                pygame.draw.rect(surface, (30, 60, 40), nb_rect, border_radius=6)
                pygame.draw.rect(surface, (57, 255, 20), nb_rect, 1, border_radius=6)
                surface.blit(notif_txt, (nb_rect.centerx - notif_txt.get_width() // 2, nb_rect.centery - notif_txt.get_height() // 2))
