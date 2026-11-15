import time
import math
from typing import Optional, Tuple, Dict, Any, List

try:
    import pygame
except ImportError:
    pygame = None


class InputEvent:
    IDLE = "idle"           # Pen not seen
    HOVER = "hover"         # Pen tracked, hovering
    DWELL_TICK = "dwell"    # Hovering with active dwell progress
    CLICK = "click"         # Dwell completed or button triggered click
    DRAW = "draw"           # Active continuous drawing on whiteboard


class InteractiveZone:
    """Represents a clickable or hoverable zone on screen."""

    def __init__(self, zone_id: str, rect: Tuple[int, int, int, int], action_callback=None, dwell_time: float = 0.8):
        self.zone_id = zone_id
        self.rect = rect  # (x, y, w, h)
        self.action_callback = action_callback
        self.dwell_time = dwell_time
        self.dwell_progress = 0.0  # 0.0 to 1.0

    def contains(self, pt: Tuple[int, int]) -> bool:
        px, py = pt
        rx, ry, rw, rh = self.rect
        return rx <= px <= rx + rw and ry <= py <= ry + rh


class LEDInputManager:
    """
    Translates raw LED detector positions into virtual clicks,
    dwell selections, and drawing strokes.
    """

    def __init__(
        self,
        transformer=None,
        dwell_duration: float = 0.8,
        smoothing_alpha: float = 0.65,
    ):
        self.transformer = transformer
        self.dwell_duration = dwell_duration
        self.smoothing_alpha = smoothing_alpha

        # Smoothed screen position
        self.smoothed_pos: Optional[Tuple[float, float]] = None
        self.raw_screen_pos: Optional[Tuple[int, int]] = None
        self.is_emitting = False

        # Dwell tracking
        self.active_zone: Optional[InteractiveZone] = None
        self.dwell_start_time: float = 0.0
        self.last_trigger_time: float = 0.0

    def update(
        self,
        cam_point: Optional[Tuple[float, float]],
        is_emitting: bool = False,
        zones: Optional[List[InteractiveZone]] = None,
        is_drawing_mode: bool = False,
    ) -> Tuple[str, Optional[Tuple[int, int]], Optional[str]]:
        """
        Process a single frame tracking output.

        Returns:
            (event_type, screen_point, triggered_zone_id)
        """
        now = time.time()
        self.is_emitting = is_emitting

        if cam_point is None:
            self.smoothed_pos = None
            self.raw_screen_pos = None
            self._reset_dwell()
            return InputEvent.IDLE, None, None

        # Transform to screen coordinate space
        if self.transformer is not None:
            scr_x, scr_y = self.transformer.transform(cam_point)
        else:
            scr_x, scr_y = cam_point

        # Apply Exponential Moving Average (EMA) smoothing
        if self.smoothed_pos is None:
            self.smoothed_pos = (scr_x, scr_y)
        else:
            prev_x, prev_y = self.smoothed_pos
            sm_x = self.smoothing_alpha * scr_x + (1.0 - self.smoothing_alpha) * prev_x
            sm_y = self.smoothing_alpha * scr_y + (1.0 - self.smoothing_alpha) * prev_y
            self.smoothed_pos = (sm_x, sm_y)

        int_pt = (int(self.smoothed_pos[0]), int(self.smoothed_pos[1]))
        self.raw_screen_pos = int_pt

        # In whiteboard drawing mode:
        if is_drawing_mode:
            # If pointer is over a UI button (e.g. Save, Eraser, Zoom), handle dwell
            if zones:
                for zone in zones:
                    if zone.contains(int_pt):
                        return self._process_zone_dwell(zone, int_pt, now)

            # Not over any button -> Drawing action
            self._reset_dwell()
            return InputEvent.DRAW, int_pt, None

        # In UI / Dashboard / PIN Entry navigation mode:
        if zones:
            for zone in zones:
                if zone.contains(int_pt):
                    return self._process_zone_dwell(zone, int_pt, now)

        self._reset_dwell()
        return InputEvent.HOVER, int_pt, None

    def _process_zone_dwell(
        self, zone: InteractiveZone, pt: Tuple[int, int], now: float
    ) -> Tuple[str, Tuple[int, int], Optional[str]]:
        """Handle dwell timer progression on a hovered interactive zone."""
        if self.active_zone != zone:
            self.active_zone = zone
            self.dwell_start_time = now
            zone.dwell_progress = 0.0
            return InputEvent.HOVER, pt, None

        # Same zone continued
        elapsed = now - self.dwell_start_time
        progress = min(1.0, elapsed / max(0.1, zone.dwell_time))
        zone.dwell_progress = progress

        # Dwell complete -> Trigger click!
        if progress >= 1.0:
            if (now - self.last_trigger_time) > 0.6:  # Debounce
                self.last_trigger_time = now
                self._reset_dwell()
                if zone.action_callback:
                    try:
                        zone.action_callback()
                    except Exception:
                        pass
                return InputEvent.CLICK, pt, zone.zone_id

        return InputEvent.DWELL_TICK, pt, None

    def _reset_dwell(self):
        if self.active_zone is not None:
            self.active_zone.dwell_progress = 0.0
            self.active_zone = None

    def render_cursor(self, surface):
        """Draw a responsive electric cyan target cursor with dwell ring (never triggers green optical feedback)."""
        if pygame is None or surface is None or self.raw_screen_pos is None:
            return

        cx, cy = self.raw_screen_pos

        # Base reticle (Electric Cyan)
        cyan_color = (0, 220, 255)
        pygame.draw.circle(surface, cyan_color, (cx, cy), 14, 2)
        pygame.draw.circle(surface, (255, 255, 255), (cx, cy), 3, -1)
        pygame.draw.line(surface, cyan_color, (cx - 18, cy), (cx - 6, cy), 2)
        pygame.draw.line(surface, cyan_color, (cx + 6, cy), (cx + 18, cy), 2)
        pygame.draw.line(surface, cyan_color, (cx, cy - 18), (cx, cy - 6), 2)
        pygame.draw.line(surface, cyan_color, (cx, cy + 6), (cx, cy + 18), 2)

        # If hovering with dwell progress, render radial fill ring
        if self.active_zone is not None and self.active_zone.dwell_progress > 0:
            prog = self.active_zone.dwell_progress
            ring_rect = pygame.Rect(cx - 22, cy - 22, 44, 44)
            # Render arc
            start_angle = -math.pi / 2.0
            end_angle = start_angle + (prog * 2.0 * math.pi)
            if prog > 0.05:
                pygame.draw.arc(surface, (255, 220, 0), ring_rect, start_angle, end_angle, 4)
