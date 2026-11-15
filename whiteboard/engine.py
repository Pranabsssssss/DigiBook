import math
import time
from typing import List, Optional, Tuple, Dict, Any
from core.models import Point, Stroke
from whiteboard.tools import TOOL_PEN, TOOL_ERASER, ToolConfig


class WhiteboardEngine:
    """
    Resolution-independent whiteboard drawing engine.
    Maintains stroke geometry recorded in normalized [0.0, 1.0] coordinates.
    """

    def __init__(
        self,
        pen_lift_timeout: float = 0.16,
        max_jump_norm: float = 0.28,
    ):
        self.pen_lift_timeout = pen_lift_timeout
        self.max_jump_norm = max_jump_norm

        self.strokes: List[Stroke] = []
        self._redo_stack: List[Stroke] = []

        # Current active tool state
        self.active_tool: str = TOOL_PEN.name
        self.active_color: str = TOOL_PEN.color_hex
        self.active_width: float = TOOL_PEN.default_width

        # Active stroke tracking
        self.current_stroke: Optional[Stroke] = None
        self.last_point_time: float = 0.0
        self.stroke_start_time: float = 0.0

    def select_tool(self, tool_name: str, color_hex: Optional[str] = None, width: Optional[float] = None):
        """Set active drawing tool (pen, eraser, etc.)."""
        if self.current_stroke is not None:
            self.end_stroke()

        self.active_tool = tool_name
        if tool_name == TOOL_ERASER.name:
            self.active_color = TOOL_ERASER.color_hex
            self.active_width = width or TOOL_ERASER.default_width
        else:
            self.active_color = color_hex or self.active_color or TOOL_PEN.color_hex
            self.active_width = width or self.active_width or TOOL_PEN.default_width

    def set_color(self, color_hex: str):
        """Update pen color hex."""
        self.active_color = color_hex

    def set_width(self, width: float):
        """Update stroke width in normalized units."""
        self.active_width = max(0.001, min(0.08, width))

    def handle_point(self, norm_x: float, norm_y: float) -> Tuple[bool, Optional[Stroke]]:
        """
        Process a detected LED pen point in normalized [0.0, 1.0] coordinates.
        Returns: (is_new_stroke, completed_or_active_stroke)
        """
        now = time.time()
        # Clamp to normalized [0.0, 1.0]
        nx = max(0.0, min(1.0, float(norm_x)))
        ny = max(0.0, min(1.0, float(norm_y)))

        is_new = False

        # If pen was lifted past the timeout, close any previous stroke
        if self.current_stroke is not None and (now - self.last_point_time) > self.pen_lift_timeout:
            self.end_stroke()

        if self.current_stroke is None:
            # Start new stroke
            self.stroke_start_time = now
            self.current_stroke = Stroke(
                version=1,
                tool=self.active_tool,
                color=self.active_color,
                width=self.active_width,
                points=[Point(x=nx, y=ny, t=0)],
            )
            is_new = True
            self._redo_stack.clear()
        else:
            # Check jump distance to prevent spurious jumps
            last_pt = self.current_stroke.points[-1]
            dist = math.hypot(nx - last_pt.x, ny - last_pt.y)
            if dist > self.max_jump_norm:
                # Spurious teleport jump -> end current stroke and start fresh
                self.end_stroke()
                self.stroke_start_time = now
                self.current_stroke = Stroke(
                    version=1,
                    tool=self.active_tool,
                    color=self.active_color,
                    width=self.active_width,
                    points=[Point(x=nx, y=ny, t=0)],
                )
                is_new = True
            else:
                elapsed_ms = int((now - self.stroke_start_time) * 1000)
                # Only add if moved slightly (filter redundant identical points)
                if dist >= 0.0005 or len(self.current_stroke.points) == 1:
                    self.current_stroke.points.append(Point(x=nx, y=ny, t=elapsed_ms))

        self.last_point_time = now
        return is_new, self.current_stroke

    def handle_no_point(self):
        """Invoked when no LED light is detected (pen lifted)."""
        if self.current_stroke is not None:
            if (time.time() - self.last_point_time) > self.pen_lift_timeout:
                self.end_stroke()

    def end_stroke(self):
        """Finalize the current stroke and append to the strokes list."""
        if self.current_stroke is not None:
            if len(self.current_stroke.points) > 0:
                self.strokes.append(self.current_stroke)
            self.current_stroke = None

    def undo(self) -> bool:
        """Undo the last drawn stroke."""
        self.end_stroke()
        if self.strokes:
            popped = self.strokes.pop()
            self._redo_stack.append(popped)
            return True
        return False

    def redo(self) -> bool:
        """Redo the last undone stroke."""
        self.end_stroke()
        if self._redo_stack:
            restored = self._redo_stack.pop()
            self.strokes.append(restored)
            return True
        return False

    def clear(self):
        """Clear all strokes on canvas."""
        self.end_stroke()
        self.strokes.clear()
        self._redo_stack.clear()

    def load_strokes(self, strokes: List[Stroke]):
        """Load an existing list of Stroke objects (e.g. from database)."""
        self.clear()
        self.strokes = list(strokes)

    def get_all_strokes(self) -> List[Stroke]:
        """Return all finalized strokes plus current active stroke if in progress."""
        all_s = list(self.strokes)
        if self.current_stroke is not None:
            all_s.append(self.current_stroke)
        return all_s
