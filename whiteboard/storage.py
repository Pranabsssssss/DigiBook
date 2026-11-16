import base64
import json
import logging
from typing import List, Optional, Dict, Any
import cv2
import numpy as np

from core.database import get_db, DatabasePool
from core.models import Whiteboard, Stroke, WhiteboardStrokeRecord, Point
from whiteboard.tools import COLOR_PALETTE

logger = logging.getLogger("DigiBook.Storage")


# === Whiteboard Metadata Persistence ===

def create_whiteboard(
    student_id: int, title: str = "Untitled", db: Optional[DatabasePool] = None
) -> Whiteboard:
    """Create a new whiteboard entry for a student."""
    db = db or get_db()
    sql = """
        INSERT INTO whiteboards (student_id, title, is_deleted, created_at, updated_at)
        VALUES (%s, %s, FALSE, NOW(), NOW())
    """
    wb_id = db.execute_insert(sql, (student_id, title.strip()))
    return get_whiteboard(wb_id, db=db)


def list_student_whiteboards(
    student_id: int, include_deleted: bool = False, db: Optional[DatabasePool] = None
) -> List[Whiteboard]:
    """Retrieve all active whiteboards belonging to a student, ordered by last updated."""
    db = db or get_db()
    if include_deleted:
        sql = """
            SELECT * FROM whiteboards
            WHERE student_id = %s
            ORDER BY updated_at DESC
        """
        rows = db.execute(sql, (student_id,))
    else:
        sql = """
            SELECT * FROM whiteboards
            WHERE student_id = %s AND is_deleted = FALSE
            ORDER BY updated_at DESC
        """
        rows = db.execute(sql, (student_id,))
    return [Whiteboard.from_row(r) for r in rows]


def get_whiteboard(
    whiteboard_id: int, student_id: Optional[int] = None, db: Optional[DatabasePool] = None
) -> Optional[Whiteboard]:
    """Retrieve a single whiteboard by ID, optionally verifying student ownership."""
    db = db or get_db()
    if student_id is not None:
        sql = "SELECT * FROM whiteboards WHERE id = %s AND student_id = %s AND is_deleted = FALSE"
        row = db.execute_one(sql, (whiteboard_id, student_id))
    else:
        sql = "SELECT * FROM whiteboards WHERE id = %s AND is_deleted = FALSE"
        row = db.execute_one(sql, (whiteboard_id,))
    return Whiteboard.from_row(row) if row else None


def update_whiteboard_metadata(
    whiteboard_id: int, student_id: int, title: str, db: Optional[DatabasePool] = None
) -> bool:
    """Update title for a student's whiteboard."""
    db = db or get_db()
    sql = """
        UPDATE whiteboards
        SET title = %s, updated_at = NOW()
        WHERE id = %s AND student_id = %s AND is_deleted = FALSE
    """
    rows = db.execute_commit(sql, (title.strip(), whiteboard_id, student_id))
    return rows > 0


def delete_whiteboard(whiteboard_id: int, student_id: int, db: Optional[DatabasePool] = None) -> bool:
    """Soft-delete a student's whiteboard."""
    db = db or get_db()
    sql = """
        UPDATE whiteboards
        SET is_deleted = TRUE, updated_at = NOW()
        WHERE id = %s AND student_id = %s
    """
    rows = db.execute_commit(sql, (whiteboard_id, student_id))
    return rows > 0


# === Whiteboard Stroke Persistence ===

def save_whiteboard_strokes(
    whiteboard_id: int,
    strokes: List[Stroke],
    thumbnail_b64: Optional[str] = None,
    db: Optional[DatabasePool] = None,
) -> bool:
    """
    Persist all strokes for a whiteboard.
    Replaces existing stroke records atomically.
    """
    db = db or get_db()

    # Generate thumbnail automatically if not supplied
    if thumbnail_b64 is None:
        thumbnail_b64 = generate_thumbnail_base64(strokes)

    with db.cursor() as cur:
        # Delete old strokes for this whiteboard
        cur.execute("DELETE FROM whiteboard_strokes WHERE whiteboard_id = %s", (whiteboard_id,))

        # Fast bulk insert new strokes in a single batch
        if strokes:
            insert_sql = """
                INSERT INTO whiteboard_strokes (whiteboard_id, stroke_index, stroke_data, created_at)
                VALUES (%s, %s, %s, NOW())
            """
            batch_data = [
                (whiteboard_id, idx, json.dumps(s.to_dict() if hasattr(s, "to_dict") else s))
                for idx, s in enumerate(strokes)
            ]
            if hasattr(cur, "executemany"):
                cur.executemany(insert_sql, batch_data)
            else:
                for row in batch_data:
                    cur.execute(insert_sql, row)

        # Update whiteboard thumbnail and updated_at
        cur.execute(
            """
            UPDATE whiteboards
            SET thumbnail_b64 = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (thumbnail_b64, whiteboard_id),
        )

    logger.info("Saved %d strokes for whiteboard ID %d.", len(strokes), whiteboard_id)
    return True


def load_whiteboard_strokes(whiteboard_id: int, db: Optional[DatabasePool] = None) -> List[Stroke]:
    """Retrieve all structured strokes for a whiteboard, sorted by stroke_index."""
    db = db or get_db()
    sql = """
        SELECT stroke_data
        FROM whiteboard_strokes
        WHERE whiteboard_id = %s
        ORDER BY stroke_index ASC
    """
    rows = db.execute(sql, (whiteboard_id,))
    strokes: List[Stroke] = []
    for r in rows:
        raw = r["stroke_data"]
        if isinstance(raw, str):
            raw = json.loads(raw)
        strokes.append(Stroke.from_dict(raw))
    return strokes


# === Base64 Thumbnail Generator ===

def generate_thumbnail_base64(strokes: List[Stroke], width: int = 240, height: int = 135) -> str:
    """
    Render a clean thumbnail of the whiteboard canvas using OpenCV and return base64 data URL.
    Aspect ratio defaults to 16:9 (240x135 px).
    """
    img = np.zeros((height, width, 3), dtype=np.uint8)

    for stroke in strokes:
        if not stroke.points:
            continue

        # Resolve color
        if stroke.tool == "eraser":
            bgr = (0, 0, 0)
        else:
            rgb = COLOR_PALETTE.get(stroke.color, (255, 255, 255))
            bgr = (rgb[2], rgb[1], rgb[0])  # Convert RGB to BGR for OpenCV

        thickness = max(1, int(stroke.width * height * 1.5))

        # Draw stroke points
        pts = np.array(
            [[int(p.x * width), int(p.y * height)] for p in stroke.points],
            dtype=np.int32,
        )

        if len(pts) == 1:
            cv2.circle(img, (pts[0][0], pts[0][1]), thickness, bgr, -1)
        else:
            cv2.polylines(img, [pts], isClosed=False, color=bgr, thickness=thickness, lineType=cv2.LINE_AA)

    success, buf = cv2.imencode(".png", img)
    if not success:
        return ""
    b64_str = base64.b64encode(buf).decode("utf-8")
    return f"data:image/png;base64,{b64_str}"
