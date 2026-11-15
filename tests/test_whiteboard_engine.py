import time
import pytest
from core.models import Point, Stroke
from whiteboard.engine import WhiteboardEngine
from whiteboard.tools import TOOL_PEN, TOOL_ERASER


def test_stroke_creation_and_point_recording():
    """Verify engine starts, records points, and finalizes strokes in normalized coords."""
    engine = WhiteboardEngine(pen_lift_timeout=0.2)
    assert len(engine.strokes) == 0

    # First point starts stroke
    is_new, stroke = engine.handle_point(0.25, 0.5)
    assert is_new is True
    assert stroke is not None
    assert len(stroke.points) == 1
    assert stroke.points[0].x == 0.25
    assert stroke.points[0].y == 0.5

    # Second point within stroke
    is_new2, stroke2 = engine.handle_point(0.26, 0.51)
    assert is_new2 is False
    assert len(stroke2.points) == 2

    # End stroke
    engine.end_stroke()
    assert len(engine.strokes) == 1
    assert len(engine.strokes[0].points) == 2


def test_pen_lift_timeout():
    """Verify that pausing longer than pen_lift_timeout begins a new stroke."""
    engine = WhiteboardEngine(pen_lift_timeout=0.05)
    engine.handle_point(0.1, 0.1)

    # Sleep longer than lift timeout
    time.sleep(0.08)

    # Next point should trigger new stroke
    is_new, stroke = engine.handle_point(0.2, 0.2)
    assert is_new is True
    assert len(engine.strokes) == 1  # previous stroke finalized into list


def test_anti_spike_jump_filter():
    """Verify that a sudden huge teleport jump triggers a fresh stroke."""
    engine = WhiteboardEngine(max_jump_norm=0.20)
    engine.handle_point(0.1, 0.1)
    engine.handle_point(0.12, 0.12)

    # Sudden jump to the far side of the canvas (delta > 0.20)
    is_new, stroke = engine.handle_point(0.9, 0.9)
    assert is_new is True
    assert len(engine.strokes) == 1
    assert len(engine.strokes[0].points) == 2
    assert stroke.points[0].x == 0.9


def test_undo_redo_and_clear():
    """Verify undo, redo, and clear behavior."""
    engine = WhiteboardEngine()
    engine.handle_point(0.1, 0.1)
    engine.end_stroke()
    engine.handle_point(0.2, 0.2)
    engine.end_stroke()
    assert len(engine.strokes) == 2

    # Undo
    assert engine.undo() is True
    assert len(engine.strokes) == 1

    # Redo
    assert engine.redo() is True
    assert len(engine.strokes) == 2

    # Clear
    engine.clear()
    assert len(engine.strokes) == 0


def test_tool_selection():
    """Verify switching tools and updating widths."""
    engine = WhiteboardEngine()
    engine.select_tool(TOOL_PEN.name, color_hex="#39FF14", width=0.005)
    assert engine.active_tool == "pen"
    assert engine.active_color == "#39FF14"
    assert engine.active_width == 0.005

    engine.select_tool(TOOL_ERASER.name)
    assert engine.active_tool == "eraser"
    assert engine.active_color == TOOL_ERASER.color_hex
