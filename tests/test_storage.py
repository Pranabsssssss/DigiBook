import base64
import json
import pytest
from core.models import Point, Stroke, Whiteboard
from whiteboard.storage import (
    generate_thumbnail_base64,
    create_whiteboard,
    list_student_whiteboards,
    get_whiteboard,
    save_whiteboard_strokes,
    load_whiteboard_strokes,
)


class MockStorageDatabase:
    """Mock database for whiteboard storage tests."""

    def __init__(self):
        self.whiteboards = {}  # id -> dict
        self.strokes = {}      # wb_id -> list of stroke_data dicts
        self._next_wb_id = 1

    def execute_insert(self, sql: str, params=()):
        sql_u = " ".join(sql.strip().split()).upper()
        if "INSERT INTO WHITEBOARDS" in sql_u:
            wid = self._next_wb_id
            self._next_wb_id += 1
            self.whiteboards[wid] = {
                "id": wid,
                "student_id": params[0],
                "title": params[1],
                "created_at": None,
                "updated_at": None,
                "is_deleted": False,
                "thumbnail_b64": None,
            }
            return wid
        return 1

    def execute(self, sql: str, params=()):
        sql_u = " ".join(sql.strip().split()).upper()
        if "FROM WHITEBOARDS" in sql_u:
            student_id = params[0]
            res = [w for w in self.whiteboards.values() if w["student_id"] == student_id and not w["is_deleted"]]
            return res
        if "FROM WHITEBOARD_STROKES" in sql_u:
            wb_id = params[0]
            return [{"stroke_data": s} for s in self.strokes.get(wb_id, [])]
        return []

    def execute_one(self, sql: str, params=()):
        sql_u = " ".join(sql.strip().split()).upper()
        if "FROM WHITEBOARDS WHERE ID = %S" in sql_u:
            wid = params[0]
            wb = self.whiteboards.get(wid)
            if wb and not wb["is_deleted"]:
                return wb
        return None

    def execute_commit(self, sql: str, params=()):
        sql_u = " ".join(sql.strip().split()).upper()
        if "UPDATE WHITEBOARDS SET IS_DELETED = TRUE" in sql_u:
            wid = params[0]
            if wid in self.whiteboards:
                self.whiteboards[wid]["is_deleted"] = True
                return 1
        return 1

    class MockCursorContext:
        def __init__(self, parent):
            self.parent = parent

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def execute(self, sql: str, params=()):
            sql_u = " ".join(sql.strip().split()).upper()
            if "DELETE FROM WHITEBOARD_STROKES" in sql_u:
                wid = params[0]
                self.parent.strokes[wid] = []
            elif "INSERT INTO WHITEBOARD_STROKES" in sql_u:
                wid = params[0]
                if wid not in self.parent.strokes:
                    self.parent.strokes[wid] = []
                self.parent.strokes[wid].append(params[2])
            elif "UPDATE WHITEBOARDS" in sql_u and "THUMBNAIL_B64" in sql_u:
                wid = params[1]
                if wid in self.parent.whiteboards:
                    self.parent.whiteboards[wid]["thumbnail_b64"] = params[0]

    def cursor(self):
        return self.MockCursorContext(self)


def test_stroke_serialization():
    """Verify Stroke dataclass serialization and deserialization."""
    stroke = Stroke(
        version=1,
        tool="pen",
        color="#39FF14",
        width=0.005,
        points=[Point(x=0.1, y=0.2, t=0), Point(x=0.15, y=0.25, t=15)],
    )
    s_dict = stroke.to_dict()
    assert s_dict["tool"] == "pen"
    assert s_dict["color"] == "#39FF14"
    assert len(s_dict["points"]) == 2

    # Reconstitute from dict
    restored = Stroke.from_dict(s_dict)
    assert restored.color == "#39FF14"
    assert len(restored.points) == 2
    assert restored.points[1].x == 0.15


def test_thumbnail_generation():
    """Verify base64 PNG thumbnail generator produces a valid image data URL."""
    strokes = [
        Stroke(
            tool="pen",
            color="#FFFFFF",
            width=0.01,
            points=[Point(x=0.1, y=0.1), Point(x=0.9, y=0.9)],
        )
    ]
    data_url = generate_thumbnail_base64(strokes, width=160, height=90)
    assert data_url.startswith("data:image/png;base64,")
    b64_content = data_url.replace("data:image/png;base64,", "")
    decoded = base64.b64decode(b64_content)
    # Check PNG magic bytes: \x89PNG\r\n\x1a\n
    assert decoded[:8] == b"\x89PNG\r\n\x1a\n"


def test_whiteboard_crud_and_strokes():
    """Test whiteboard creation, listing, stroke saving, and stroke loading."""
    mock_db = MockStorageDatabase()

    # 1. Create whiteboard
    wb = create_whiteboard(student_id=42, title="Algebra Notes", db=mock_db)
    assert wb.id == 1
    assert wb.title == "Algebra Notes"

    # 2. List whiteboards
    wbs = list_student_whiteboards(student_id=42, db=mock_db)
    assert len(wbs) == 1
    assert wbs[0].id == 1

    # 3. Save strokes
    strokes = [
        Stroke(tool="pen", color="#00F0FF", width=0.005, points=[Point(x=0.2, y=0.3)]),
        Stroke(tool="pen", color="#FFFFFF", width=0.005, points=[Point(x=0.5, y=0.5)]),
    ]
    save_whiteboard_strokes(wb.id, strokes, db=mock_db)

    # 4. Load strokes
    loaded = load_whiteboard_strokes(wb.id, db=mock_db)
    assert len(loaded) == 2
    assert loaded[0].color == "#00F0FF"
    assert loaded[1].points[0].x == 0.5
