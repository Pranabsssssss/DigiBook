import pytest
from core.auth import (
    hash_pin,
    verify_pin,
    register_student,
    authenticate_rfid_step1,
    authenticate_rfid_pin,
    authenticate_email_pin,
    set_student_pin,
    create_session,
    validate_session,
    revoke_session,
    InvalidPinError,
    DuplicateFieldError,
    StudentNotFoundError,
)
from core.models import Student, Stroke, Point, Whiteboard


class MockDatabase:
    """In-memory mock database implementing DatabasePool interface for unit testing."""

    def __init__(self):
        self.students = {}       # id -> dict
        self.sessions = {}       # token -> dict
        self.whiteboards = {}    # id -> dict
        self.audit_logs = []
        self._next_student_id = 1
        self._next_wb_id = 1

    def execute_one(self, sql: str, params=()):
        sql_clean = " ".join(sql.strip().split()).upper()

        if "FROM STUDENTS" in sql_clean:
            if "WHERE ID = %S" in sql_clean:
                return self.students.get(params[0])
            if "WHERE RFID_KEY = %S" in sql_clean:
                for s in self.students.values():
                    if s["rfid_key"] == params[0]:
                        return s
                return None
            if "WHERE EMAIL = %S" in sql_clean:
                for s in self.students.values():
                    if s["email"] == params[0]:
                        return s
                return None
            if "WHERE STUDENT_ID = %S OR RFID_KEY = %S OR EMAIL = %S" in sql_clean:
                for s in self.students.values():
                    if (s["student_id"] == params[0] or
                        s["rfid_key"] == params[1] or
                        s["email"] == params[2]):
                        return s
                return None

        if "FROM WHITEBOARDS" in sql_clean:
            if "WHERE ID = %S" in sql_clean:
                wid = params[0]
                wb = self.whiteboards.get(wid)
                if wb and not wb.get("is_deleted"):
                    return wb
                return None
            if "WHERE STUDENT_ID = %S" in sql_clean:
                sid = params[0]
                return [w for w in self.whiteboards.values() if w["student_id"] == sid and not w.get("is_deleted")]

        if "FROM SESSIONS" in sql_clean:
            token = params[0]
            sess = self.sessions.get(token)
            if sess and sess.get("is_active"):
                student_id = sess["student_id"]
                st = self.students.get(student_id)
                if st:
                    combined = dict(st)
                    combined["expires_at"] = sess["expires_at"]
                    combined["is_active"] = sess["is_active"]
                    return combined
            return None

        if "SELECT 1 AS ALIVE" in sql_clean:
            return {"alive": 1}

        return None

    def execute_insert(self, sql: str, params=()):
        sql_clean = " ".join(sql.strip().split()).upper()
        if "INSERT INTO STUDENTS" in sql_clean:
            sid = self._next_student_id
            self._next_student_id += 1
            self.students[sid] = {
                "id": sid,
                "student_name": params[0],
                "student_id": params[1],
                "rfid_key": params[2],
                "class": params[3],
                "email": params[4],
                "pin_hash": params[5],
                "pin_set": params[6],
                "created_at": None,
                "updated_at": None,
                "last_login_at": None,
            }
            return sid
        if "INSERT INTO WHITEBOARDS" in sql_clean:
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
        if "INSERT INTO SESSIONS" in sql_clean:
            token = params[1]
            self.sessions[token] = {
                "student_id": params[0],
                "session_token": token,
                "session_type": params[2],
                "expires_at": params[3],
                "is_active": True,
            }
            return len(self.sessions)
        if "INSERT INTO AUDIT_LOG" in sql_clean:
            self.audit_logs.append(params)
            return len(self.audit_logs)
        return 1

    def execute_commit(self, sql: str, params=()):
        sql_clean = " ".join(sql.strip().split()).upper()
        if "UPDATE STUDENTS" in sql_clean and "PIN_HASH" in sql_clean:
            student_id = params[1]
            if student_id in self.students:
                self.students[student_id]["pin_hash"] = params[0]
                self.students[student_id]["pin_set"] = True
                return 1
        if "UPDATE SESSIONS SET IS_ACTIVE = FALSE" in sql_clean:
            if "WHERE SESSION_TOKEN = %S" in sql_clean:
                token = params[0]
                if token in self.sessions:
                    self.sessions[token]["is_active"] = False
                    return 1
            if "WHERE STUDENT_ID = %S AND SESSION_TYPE = 'LOCAL'" in sql_clean:
                sid = params[0]
                count = 0
                for s in self.sessions.values():
                    if s["student_id"] == sid and s["session_type"] == "local":
                        s["is_active"] = False
                        count += 1
                return count
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
                pass
            elif "INSERT INTO WHITEBOARD_STROKES" in sql_u:
                pass
            elif "UPDATE WHITEBOARDS" in sql_u and "THUMBNAIL_B64" in sql_u:
                wid = params[1]
                if wid in self.parent.whiteboards:
                    self.parent.whiteboards[wid]["thumbnail_b64"] = params[0]

    def cursor(self):
        return self.MockCursorContext(self)

    def execute(self, sql: str, params=()):
        sql_clean = " ".join(sql.strip().split()).upper()
        if "FROM WHITEBOARDS" in sql_clean:
            sid = params[0]
            return [w for w in self.whiteboards.values() if w["student_id"] == sid and not w.get("is_deleted")]
        if "FROM WHITEBOARD_STROKES" in sql_clean:
            return []
        return []


# === Test Cases ===

def test_pin_hashing_and_verification():
    """Verify bcrypt PIN hashing works and correctly validates match/mismatch."""
    pin = "4829"
    hashed = hash_pin(pin)
    assert hashed != pin
    assert len(hashed) > 20
    assert verify_pin("4829", hashed) is True
    assert verify_pin("0000", hashed) is False
    assert verify_pin("4828", hashed) is False


def test_pin_validation_constraints():
    """Verify PIN must be strictly 4 numeric digits."""
    with pytest.raises(ValueError):
        hash_pin("123")  # Too short
    with pytest.raises(ValueError):
        hash_pin("12345")  # Too long
    with pytest.raises(ValueError):
        hash_pin("abcd")  # Non-numeric
    with pytest.raises(ValueError):
        hash_pin("12a4")


def test_student_registration_and_duplicate_prevention():
    """Verify student registration and rejection of duplicates."""
    mock_db = MockDatabase()

    student = register_student(
        student_name="Jordan Lee",
        student_id="STU1001",
        rfid_key="RFID_ABC_123",
        class_name="CS-101",
        email="jordan.lee@school.edu",
        pin="5566",
        db=mock_db,
    )
    assert student.id == 1
    assert student.student_name == "Jordan Lee"
    assert student.pin_set is True

    # Duplicate student_id
    with pytest.raises(DuplicateFieldError):
        register_student(
            student_name="Duplicate ID",
            student_id="STU1001",
            rfid_key="RFID_NEW",
            class_name="CS-101",
            email="other@school.edu",
            db=mock_db,
        )

    # Duplicate RFID
    with pytest.raises(DuplicateFieldError):
        register_student(
            student_name="Duplicate RFID",
            student_id="STU1002",
            rfid_key="RFID_ABC_123",
            class_name="CS-101",
            email="unique@school.edu",
            db=mock_db,
        )


def test_rfid_login_step1_and_pin_entry():
    """Test RFID step 1 lookup and subsequent PIN entry."""
    mock_db = MockDatabase()

    # 1. Unregistered card
    status, stu = authenticate_rfid_step1("UNKNOWN_CARD", db=mock_db)
    assert status == "NOT_FOUND"
    assert stu is None

    # 2. Register student with NO PIN
    register_student(
        student_name="Maya Lin",
        student_id="STU2001",
        rfid_key="RFID_MAYA",
        class_name="Art-1",
        email="maya@school.edu",
        pin=None,
        db=mock_db,
    )
    status, stu = authenticate_rfid_step1("RFID_MAYA", db=mock_db)
    assert status == "NEEDS_PIN_CREATION"
    assert stu.student_name == "Maya Lin"

    # Set PIN
    set_student_pin(stu.id, "9988", db=mock_db)
    status, stu = authenticate_rfid_step1("RFID_MAYA", db=mock_db)
    assert status == "NEEDS_PIN_ENTRY"

    # Authenticate with correct PIN
    authed_student, token = authenticate_rfid_pin("RFID_MAYA", "9988", db=mock_db)
    assert authed_student.id == stu.id
    assert len(token) == 64

    # Invalid PIN
    with pytest.raises(InvalidPinError):
        authenticate_rfid_pin("RFID_MAYA", "0000", db=mock_db)


def test_session_management():
    """Test session creation, validation, and revocation."""
    mock_db = MockDatabase()
    student = register_student(
        student_name="Test Session",
        student_id="STU_SESS",
        rfid_key="RFID_SESS",
        class_name="Physics",
        email="session@school.edu",
        pin="1122",
        db=mock_db,
    )

    token = create_session(student.id, session_type="local", db=mock_db)
    val_student = validate_session(token, db=mock_db)
    assert val_student is not None
    assert val_student.id == student.id

    # Revoke session
    revoke_session(token, db=mock_db)
    assert validate_session(token, db=mock_db) is None
