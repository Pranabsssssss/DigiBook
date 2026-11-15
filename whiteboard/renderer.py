import math
from typing import Tuple, List, Optional
import numpy as np

try:
    import pygame
except ImportError:
    pygame = None

from core.models import Stroke, Point
from whiteboard.tools import COLOR_PALETTE


class Viewport:
    """
    Manages a virtual viewport into the normalized [0.0, 1.0] whiteboard space.
    Enables smooth zoom-in, zoom-out, and panning while preserving exact stroke geometry.
    """

    def __init__(self, min_zoom: float = 1.0, max_zoom: float = 8.0):
        self.zoom_level: float = 1.0
        self.center_x: float = 0.5
        self.center_y: float = 0.5
        self.min_zoom = min_zoom
        self.max_zoom = max_zoom

    def visible_rect(self) -> Tuple[float, float, float, float]:
        """Returns (left, top, width, height) in normalized coordinates."""
        span_w = 1.0 / self.zoom_level
        span_h = 1.0 / self.zoom_level
        left = self.center_x - span_w / 2.0
        top = self.center_y - span_h / 2.0

        # Clamp boundaries so viewport doesn't drift outside canvas
        left = max(0.0, min(1.0 - span_w, left))
        top = max(0.0, min(1.0 - span_h, top))

        return left, top, span_w, span_h

    def normalized_to_screen(
        self, norm_x: float, norm_y: float, canvas_w: int, canvas_h: int, offset_x: int = 0, offset_y: int = 0
    ) -> Tuple[int, int]:
        """Convert normalized [0.0, 1.0] whiteboard point to screen pixel."""
        left, top, span_w, span_h = self.visible_rect()
        sx = offset_x + int(((norm_x - left) / span_w) * canvas_w)
        sy = offset_y + int(((norm_y - top) / span_h) * canvas_h)
        return sx, sy

    def screen_to_normalized(
        self, screen_x: int, screen_y: int, canvas_w: int, canvas_h: int, offset_x: int = 0, offset_y: int = 0
    ) -> Tuple[float, float]:
        """Convert screen pixel to normalized [0.0, 1.0] whiteboard point."""
        left, top, span_w, span_h = self.visible_rect()
        rel_x = (screen_x - offset_x) / max(1, canvas_w)
        rel_y = (screen_y - offset_y) / max(1, canvas_h)
        norm_x = left + rel_x * span_w
        norm_y = top + rel_y * span_h
        return max(0.0, min(1.0, norm_x)), max(0.0, min(1.0, norm_y))

    def zoom_in(self, factor: float = 1.25, focus_norm_x: Optional[float] = None, focus_norm_y: Optional[float] = None):
        """Zoom in towards focus point or center."""
        if focus_norm_x is not None and focus_norm_y is not None:
            self.center_x = focus_norm_x
            self.center_y = focus_norm_y
        self.zoom_level = min(self.max_zoom, self.zoom_level * factor)

    def zoom_out(self, factor: float = 1.25):
        """Zoom out towards center."""
        self.zoom_level = max(self.min_zoom, self.zoom_level / factor)
        if self.zoom_level == 1.0:
            self.center_x = 0.5
            self.center_y = 0.5

    def pan(self, dx_norm: float, dy_norm: float):
        """Pan viewport by a normalized delta."""
        span_w = 1.0 / self.zoom_level
        span_h = 1.0 / self.zoom_level
        self.center_x = max(span_w / 2.0, min(1.0 - span_w / 2.0, self.center_x + dx_norm))
        self.center_y = max(span_h / 2.0, min(1.0 - span_h / 2.0, self.center_y + dy_norm))

    def reset(self):
        """Reset viewport to 1.0x fit."""
        self.zoom_level = 1.0
        self.center_x = 0.5
        self.center_y = 0.5


class WhiteboardRenderer:
    """
    Renders resolution-independent strokes to a Pygame Surface
    with aspect-ratio preservation and Viewport zoom support.
    """

    TARGET_ASPECT_RATIO = 16.0 / 9.0

    def __init__(self, display_width: int, display_height: int):
        self.display_width = display_width
        self.display_height = display_height
        self.viewport = Viewport()

        # Compute letterboxed 16:9 canvas dimensions
        self._calculate_canvas_geometry()

    def _calculate_canvas_geometry(self):
        disp_aspect = self.display_width / max(1, self.display_height)
        if disp_aspect > self.TARGET_ASPECT_RATIO:
            # Display is wider than 16:9 -> Pillarbox (bars on left/right)
            self.canvas_h = self.display_height
            self.canvas_w = int(self.canvas_h * self.TARGET_ASPECT_RATIO)
            self.offset_x = (self.display_width - self.canvas_w) // 2
            self.offset_y = 0
        else:
            # Display is taller than 16:9 -> Letterbox (bars on top/bottom)
            self.canvas_w = self.display_width
            self.canvas_h = int(self.canvas_w / self.TARGET_ASPECT_RATIO)
            self.offset_x = 0
            self.offset_y = (self.display_height - self.canvas_h) // 2

    def update_display_size(self, width: int, height: int):
        self.display_width = width
        self.display_height = height
        self._calculate_canvas_geometry()

    def render_to_surface(self, surface, strokes: List[Stroke]):
        """Render all strokes onto a target Pygame surface."""
        if pygame is None or surface is None:
            return

        # Fill letterboxed background
        surface.fill((10, 12, 16))

        # Fill main drawing canvas with black
        canvas_rect = pygame.Rect(self.offset_x, self.offset_y, self.canvas_w, self.canvas_h)
        pygame.draw.rect(surface, (0, 0, 0), canvas_rect)

        # Draw strokes
        for stroke in strokes:
            if not stroke.points:
                continue

            color = (0, 0, 0) if stroke.tool == "eraser" else COLOR_PALETTE.get(stroke.color, (255, 255, 255))
            scaled_radius = max(1, int(stroke.width * self.canvas_h * self.viewport.zoom_level * 0.5))

            # Transform points via viewport
            pts = [
                self.viewport.normalized_to_screen(
                    p.x, p.y, self.canvas_w, self.canvas_h, self.offset_x, self.offset_y
                )
                for p in stroke.points
            ]

            if len(pts) == 1:
                pygame.draw.circle(surface, color, pts[0], scaled_radius)
            else:
                for i in range(len(pts) - 1):
                    p1 = pts[i]
                    p2 = pts[i + 1]
                    pygame.draw.line(surface, color, p1, p2, scaled_radius * 2)
                    pygame.draw.circle(surface, color, p1, scaled_radius)
                pygame.draw.circle(surface, color, pts[-1], scaled_radius)

        # Draw crisp border around active canvas
        pygame.draw.rect(surface, (40, 50, 70), canvas_rect, 2)
