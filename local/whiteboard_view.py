import time
import threading
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

    def save_to_database(self, db=None, async_save: bool = True):
        """Persist current strokes to MySQL without freezing the UI."""
        self.engine.end_stroke()
        strokes_snapshot = list(self.engine.strokes)
        if not strokes_snapshot:
            return

        self.last_autosave_time = time.time()
        self.show_notification("Saving to Cloud...")

        def _worker():
            try:
                save_whiteboard_strokes(self.whiteboard.id, strokes_snapshot, db=db)
                self.show_notification("Saved to Cloud!")
            except Exception as e:
                self.show_notification("Saved (Local Only)")

        if async_save:
            t = threading.Thread(target=_worker, daemon=True)
            t.start()
        else:
            _worker()

    def show_notification(self, msg: str, duration: float = 2.5):
        self.notification = msg
        self.notification_expiry = time.time() + duration

    def _build_toolbar_zones(self):
        """Create on-screen button zones cleanly arranged without overlapping."""
        self.zones.clear()

        btn_h = 42
        gap = 8
        y = 11

        # 1. Back button (top left)
        self.zones.append(
            InteractiveZone(
                zone_id="BTN_BACK",
                rect=(16, y, 82, btn_h),
                action_callback=self._handle_back_pressed,
                dwell_time=0.7,
                label="< BACK",
            )
        )

        # 2. Toolbar items on the right side: (zone_id, label, callback, width, color_swatch)
        buttons = [
            ("BTN_PEN", "PEN", lambda: self.engine.select_tool(TOOL_PEN.name), 66, None),
            ("BTN_ERASER", "ERASER", lambda: self.engine.select_tool(TOOL_ERASER.name), 76, None),
            ("BTN_COLOR_WHITE", "", lambda: self.engine.set_color("#FFFFFF"), 44, "#FFFFFF"),
            ("BTN_COLOR_CYAN", "", lambda: self.engine.set_color("#00F0FF"), 44, "#00F0FF"),
            ("BTN_COLOR_YELLOW", "", lambda: self.engine.set_color("#FFB800"), 44, "#FFB800"),
            ("BTN_ZOOM_IN", "+", lambda: self.renderer.viewport.zoom_in(1.3), 44, None),
            ("BTN_ZOOM_OUT", "-", lambda: self.renderer.viewport.zoom_out(1.3), 44, None),
            ("BTN_CLEAR", "CLEAR", self.engine.clear, 68, None),
            ("BTN_SAVE", "SAVE", self.save_to_database, 66, None),
        ]

        total_w = sum(w for _, _, _, w, _ in buttons) + gap * (len(buttons) - 1)
        start_x = max(110, self.width - total_w - 16)

        curr_x = start_x
        for bid, lbl, cb, bw, swatch in buttons:
            self.zones.append(
                InteractiveZone(
                    zone_id=bid,
                    rect=(curr_x, y, bw, btn_h),
                    action_callback=cb,
                    dwell_time=0.6,
                    label=lbl,
                    color_swatch=swatch,
                )
            )
            curr_x += bw + gap

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
        """Handle background auto-saving without frame rate hitches."""
        now = time.time()
        if (now - self.last_autosave_time) >= self.autosave_interval:
            self.last_autosave_time = now
            if self.engine.strokes:
                self.save_to_database(db=db, async_save=True)

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

            # Active color highlight
            is_active_color = False
            if zone.color_swatch and getattr(self.engine, "active_color", None):
                if self.engine.active_color.upper() == zone.color_swatch.upper() and self.engine.active_tool != TOOL_ERASER.name:
                    is_active_color = True

            if zone.zone_id == "BTN_BACK":
                bg = (60, 20, 20) if is_hovered else (35, 20, 20)
                border = (255, 80, 80) if is_hovered else (150, 50, 50)
            elif is_active_tool or is_active_color:
                bg = (18, 55, 85)
                border = (0, 240, 255)
            elif is_hovered:
                bg = (40, 60, 85)
                border = (0, 240, 255)
            else:
                bg = (25, 32, 45)
                border = (60, 75, 95)

            pygame.draw.rect(surface, bg, zone.rect, border_radius=6)
            pygame.draw.rect(
                surface,
                border,
                zone.rect,
                2 if (is_active_tool or is_active_color or is_hovered) else 1,
                border_radius=6
            )

            # Dwell progress feedback bar
            if zone.dwell_progress > 0:
                prog_w = max(2, int(rw * min(1.0, zone.dwell_progress)))
                pygame.draw.rect(surface, (0, 240, 255), (rx, ry + rh - 4, prog_w, 4), border_radius=2)

            # Color swatch button: render centered circular swatch
            if zone.color_swatch:
                cx = rx + rw // 2
                cy = ry + rh // 2
                hex_str = zone.color_swatch.lstrip("#")
                cr, cg, cb = tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))
                if is_active_color:
                    pygame.draw.circle(surface, (0, 240, 255), (cx, cy), 13, 2)
                    pygame.draw.circle(surface, (cr, cg, cb), (cx, cy), 9)
                else:
                    pygame.draw.circle(surface, (cr, cg, cb), (cx, cy), 10)
                    pygame.draw.circle(surface, (70, 85, 105), (cx, cy), 10, 1)

            elif zone.label and self.font_btn:
                btn_txt = self.font_btn.render(zone.label, True, (255, 255, 255))
                surface.blit(btn_txt, (rx + (rw - btn_txt.get_width()) // 2, ry + (rh - btn_txt.get_height()) // 2))

        # Notification Banner
        if self.notification and now < self.notification_expiry:
            if self.font_status:
                notif_txt = self.font_status.render(self.notification, True, (220, 240, 255))
                nb_rect = pygame.Rect(self.width // 2 - 180, self.height - 50, 360, 38)
                pygame.draw.rect(surface, (20, 45, 70), nb_rect, border_radius=6)
                pygame.draw.rect(surface, (0, 220, 255), nb_rect, 1, border_radius=6)
                surface.blit(notif_txt, (nb_rect.centerx - notif_txt.get_width() // 2, nb_rect.centery - notif_txt.get_height() // 2))
