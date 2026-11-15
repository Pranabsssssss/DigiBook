from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from datetime import datetime
import json


@dataclass
class Student:
    id: Optional[int]
    student_id: str
    student_name: str
    rfid_key: str
    class_name: str
    email: str
    pin_hash: Optional[str] = None
    pin_set: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None

    def to_dict(self, safe: bool = True) -> Dict[str, Any]:
        """Convert student record to dictionary. If safe=True, omits pin_hash."""
        data = {
            "id": self.id,
            "student_id": self.student_id,
            "student_name": self.student_name,
            "rfid_key": self.rfid_key,
            "class": self.class_name,
            "email": self.email,
            "pin_set": self.pin_set,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }
        if not safe:
            data["pin_hash"] = self.pin_hash
        return data

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Student":
        return cls(
            id=row.get("id"),
            student_id=row.get("student_id", ""),
            student_name=row.get("student_name", ""),
            rfid_key=row.get("rfid_key", ""),
            class_name=row.get("class", ""),
            email=row.get("email", ""),
            pin_hash=row.get("pin_hash"),
            pin_set=bool(row.get("pin_set", False)),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            last_login_at=row.get("last_login_at"),
        )


@dataclass
class Whiteboard:
    id: Optional[int]
    student_id: int
    title: str = "Untitled"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_deleted: bool = False
    thumbnail_b64: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "student_id": self.student_id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_deleted": self.is_deleted,
            "thumbnail_b64": self.thumbnail_b64,
        }

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Whiteboard":
        return cls(
            id=row.get("id"),
            student_id=row.get("student_id"),
            title=row.get("title", "Untitled"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            is_deleted=bool(row.get("is_deleted", False)),
            thumbnail_b64=row.get("thumbnail_b64"),
        )


@dataclass
class Point:
    x: float
    y: float
    t: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"x": round(self.x, 5), "y": round(self.y, 5), "t": self.t}


@dataclass
class Stroke:
    version: int = 1
    tool: str = "pen"           # "pen", "eraser", "highlighter"
    color: str = "#FFFFFF"
    width: float = 0.005        # Normalized width relative to viewport
    points: List[Point] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "tool": self.tool,
            "color": self.color,
            "width": self.width,
            "points": [p.to_dict() if isinstance(p, Point) else p for p in self.points]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Stroke":
        pts = [Point(x=p["x"], y=p["y"], t=p.get("t", 0)) for p in data.get("points", [])]
        return cls(
            version=data.get("version", 1),
            tool=data.get("tool", "pen"),
            color=data.get("color", "#FFFFFF"),
            width=data.get("width", 0.005),
            points=pts
        )


@dataclass
class WhiteboardStrokeRecord:
    id: Optional[int]
    whiteboard_id: int
    stroke_index: int
    stroke: Stroke
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "whiteboard_id": self.whiteboard_id,
            "stroke_index": self.stroke_index,
            "stroke_data": self.stroke.to_dict(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "WhiteboardStrokeRecord":
        raw_data = row.get("stroke_data")
        if isinstance(raw_data, str):
            raw_data = json.loads(raw_data)
        stroke = Stroke.from_dict(raw_data)
        return cls(
            id=row.get("id"),
            whiteboard_id=row.get("whiteboard_id"),
            stroke_index=row.get("stroke_index", 0),
            stroke=stroke,
            created_at=row.get("created_at"),
        )
