from typing import Optional
from flask_login import UserMixin
from core.models import Student
from core.auth import get_student_by_id, get_student_by_email, authenticate_email_pin


class WebUser(UserMixin):
    """Flask-Login user adapter wrapping Student dataclass."""

    def __init__(self, student: Student):
        self.student = student
        self.id = str(student.id)

    @property
    def student_id(self) -> str:
        return self.student.student_id

    @property
    def student_name(self) -> str:
        return self.student.student_name

    @property
    def email(self) -> str:
        return self.student.email

    @property
    def class_name(self) -> str:
        return self.student.class_name

    @classmethod
    def get(cls, user_id: str, db=None) -> Optional["WebUser"]:
        try:
            sid = int(user_id)
            student = get_student_by_id(sid, db=db)
            if not student or not student.pin_set or not student.pin_hash:
                return None
            return cls(student)
        except (ValueError, TypeError):
            return None
