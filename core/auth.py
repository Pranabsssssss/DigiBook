import re
import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any
import bcrypt

from config.settings import (
    PIN_MAX_ATTEMPTS,
    PIN_LOCKOUT_MINUTES,
    SESSION_TIMEOUT_HOURS_LOCAL,
    SESSION_TIMEOUT_HOURS_WEB,
)
from core.database import get_db, DatabasePool
from core.models import Student

logger = logging.getLogger("DigiBook.Auth")

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class AuthError(Exception):
    """Base exception for authentication errors."""
    pass


class StudentNotFoundError(AuthError):
    pass


class InvalidPinError(AuthError):
    pass


class PinNotSetError(AuthError):
    """Raised when web authentication is attempted before the student creates their PIN at the whiteboard."""
    pass


class AccountLockedError(AuthError):
    pass


class DuplicateFieldError(AuthError):
    pass


# === Password Hashing Utilities ===

def hash_pin(pin: str) -> str:
    """Hash a 4-digit PIN using bcrypt with 12 work rounds."""
    if not (pin.isdigit() and len(pin) == 4):
        raise ValueError("PIN must be exactly 4 numeric digits.")
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pin.encode("utf-8"), salt).decode("utf-8")


def verify_pin(pin: str, pin_hash: str) -> bool:
    """Verify a plain 4-digit PIN against its stored bcrypt hash."""
    if not pin or not pin_hash:
        return False
    try:
        return bcrypt.checkpw(pin.encode("utf-8"), pin_hash.encode("utf-8"))
    except Exception as e:
        logger.error("Error verifying PIN hash: %s", e)
        return False


# === Rate Limiting & Audit Helpers ===

def is_rate_limited(identifier: str, db: Optional[DatabasePool] = None) -> bool:
    """
    Check if the student or IP has exceeded maximum failed PIN attempts
    within the lockout window (e.g., 5 failures in 15 minutes).
    """
    db = db or get_db()
    since = datetime.now() - timedelta(minutes=PIN_LOCKOUT_MINUTES)
    sql = """
        SELECT COUNT(*) AS fail_count
        FROM audit_log
        WHERE event_type = 'LOGIN_FAIL'
          AND (event_detail LIKE %s OR ip_address = %s)
          AND created_at >= %s
    """
    pattern = f"%{identifier}%"
    row = db.execute_one(sql, (pattern, identifier, since))
    if row and row.get("fail_count", 0) >= PIN_MAX_ATTEMPTS:
        return True
    return False


def log_audit_event(
    event_type: str,
    student_id: Optional[int] = None,
    detail: Optional[str] = None,
    ip_address: Optional[str] = None,
    db: Optional[DatabasePool] = None,
):
    """Record an event into the audit_log table."""
    db = db or get_db()
    try:
        sql = """
            INSERT INTO audit_log (student_id, event_type, event_detail, ip_address, created_at)
            VALUES (%s, %s, %s, %s, NOW())
        """
        db.execute_insert(sql, (student_id, event_type, detail, ip_address))
    except Exception as e:
        logger.error("Failed to write audit log (%s): %s", event_type, e)


# === Student Registration ===

def register_student(
    student_name: str,
    student_id: str,
    rfid_key: str,
    class_name: str,
    email: str,
    pin: Optional[str] = None,
    db: Optional[DatabasePool] = None,
) -> Student:
    """
    Register a new student into the MySQL database.
    Validates required fields, uniqueness, and optional initial PIN.
    """
    db = db or get_db()

    student_name = student_name.strip()
    student_id = student_id.strip()
    rfid_key = rfid_key.strip()
    class_name = class_name.strip()
    email = email.strip().lower()

    if not student_name:
        raise ValueError("Student name is required.")
    if not student_id:
        raise ValueError("Student ID is required.")
    if not rfid_key:
        raise ValueError("RFID key is required.")
    if not class_name:
        raise ValueError("Class is required.")
    if not email or not EMAIL_REGEX.match(email):
        raise ValueError("A valid email address is required.")

    # Check for duplicate unique keys
    existing_sql = """
        SELECT student_id, rfid_key, email
        FROM students
        WHERE student_id = %s OR rfid_key = %s OR email = %s
        LIMIT 1
    """
    existing = db.execute_one(existing_sql, (student_id, rfid_key, email))
    if existing:
        if existing.get("student_id") == student_id:
            raise DuplicateFieldError(f"Student ID '{student_id}' is already registered.")
        if existing.get("rfid_key") == rfid_key:
            raise DuplicateFieldError(f"RFID card '{rfid_key}' is already assigned to another student.")
        if existing.get("email") == email:
            raise DuplicateFieldError(f"Email '{email}' is already registered.")

    pin_hash = None
    pin_set = False
    if pin:
        pin_hash = hash_pin(pin)
        pin_set = True

    insert_sql = """
        INSERT INTO students (student_name, student_id, rfid_key, class, email, pin_hash, pin_set, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
    """
    new_id = db.execute_insert(
        insert_sql,
        (student_name, student_id, rfid_key, class_name, email, pin_hash, pin_set),
    )

    log_audit_event("REGISTER", student_id=new_id, detail=f"Student ID: {student_id}, RFID: {rfid_key}", db=db)

    return get_student_by_id(new_id, db=db)


# === Student Lookups ===

def get_student_by_id(id_: int, db: Optional[DatabasePool] = None) -> Optional[Student]:
    """Retrieve student by primary key ID."""
    db = db or get_db()
    row = db.execute_one("SELECT * FROM students WHERE id = %s", (id_,))
    return Student.from_row(row) if row else None


def get_student_by_rfid(rfid_key: str, db: Optional[DatabasePool] = None) -> Optional[Student]:
    """Retrieve student by scanned RFID key."""
    db = db or get_db()
    row = db.execute_one("SELECT * FROM students WHERE rfid_key = %s", (rfid_key.strip(),))
    return Student.from_row(row) if row else None


def get_student_by_email(email: str, db: Optional[DatabasePool] = None) -> Optional[Student]:
    """Retrieve student by registered email."""
    db = db or get_db()
    row = db.execute_one("SELECT * FROM students WHERE email = %s", (email.strip().lower(),))
    return Student.from_row(row) if row else None


# === PIN Management & Setup ===

def set_student_pin(student_id: int, pin: str, db: Optional[DatabasePool] = None) -> bool:
    """Set or update a student's 4-digit PIN."""
    db = db or get_db()
    hashed = hash_pin(pin)
    sql = """
        UPDATE students
        SET pin_hash = %s, pin_set = TRUE, updated_at = NOW()
        WHERE id = %s
    """
    rows = db.execute_commit(sql, (hashed, student_id))
    if rows > 0:
        log_audit_event("PIN_SET", student_id=student_id, detail="4-digit PIN established/updated", db=db)
        return True
    return False


# === Authentication Workflows ===

def authenticate_rfid_step1(
    rfid_key: str, db: Optional[DatabasePool] = None
) -> Tuple[str, Optional[Student]]:
    """
    Step 1 of RFID Authentication (Local App):
    Returns status:
      - 'NOT_FOUND': Card is not in database.
      - 'NEEDS_PIN_CREATION': Student exists but has never set a PIN.
      - 'NEEDS_PIN_ENTRY': Student exists with pre-set PIN.
    """
    student = get_student_by_rfid(rfid_key, db=db)
    if not student:
        log_audit_event("RFID_UNKNOWN", detail=f"Unknown RFID scanned: {rfid_key}", db=db)
        return "NOT_FOUND", None
    if not student.pin_set or not student.pin_hash:
        return "NEEDS_PIN_CREATION", student
    return "NEEDS_PIN_ENTRY", student


def authenticate_rfid_pin(
    rfid_key: str, pin: str, ip_address: Optional[str] = None, db: Optional[DatabasePool] = None
) -> Tuple[Student, str]:
    """
    Step 2 of RFID Authentication: verify 4-digit PIN for the card.
    Returns: (Student, session_token)
    """
    db = db or get_db()
    rfid_key = rfid_key.strip()

    if is_rate_limited(rfid_key, db=db):
        log_audit_event("LOCKOUT", detail=f"Rate-limited attempt for RFID {rfid_key}", ip_address=ip_address, db=db)
        raise AccountLockedError("Too many failed attempts. Please wait 15 minutes.")

    student = get_student_by_rfid(rfid_key, db=db)
    if not student:
        raise StudentNotFoundError("Not Present in Database")

    if not student.pin_set or not student.pin_hash:
        raise InvalidPinError("Student PIN has not been initialized.")

    if not verify_pin(pin, student.pin_hash):
        log_audit_event("LOGIN_FAIL", student_id=student.id, detail=f"Invalid PIN for RFID: {rfid_key}", ip_address=ip_address, db=db)
        raise InvalidPinError("Invalid 4-digit PIN.")

    # Successful authentication
    token = create_session(student.id, session_type="local", db=db)
    db.execute_commit("UPDATE students SET last_login_at = NOW() WHERE id = %s", (student.id,))
    log_audit_event("LOGIN", student_id=student.id, detail="Local RFID+PIN Login", ip_address=ip_address, db=db)
    return student, token


def authenticate_email_pin(
    email: str, pin: str, ip_address: Optional[str] = None, db: Optional[DatabasePool] = None
) -> Tuple[Student, str]:
    """
    Web Authentication: authenticate using registered email and 4-digit PIN.
    Returns: (Student, session_token)
    """
    db = db or get_db()
    email = email.strip().lower()

    if is_rate_limited(email, db=db):
        log_audit_event("LOCKOUT", detail=f"Rate-limited attempt for email {email}", ip_address=ip_address, db=db)
        raise AccountLockedError("Too many failed attempts. Please wait 15 minutes.")

    student = get_student_by_email(email, db=db)
    if not student:
        log_audit_event("LOGIN_FAIL", detail=f"Non-existent email login: {email}", ip_address=ip_address, db=db)
        raise StudentNotFoundError("Invalid email or PIN.")

    if not student.pin_set or not student.pin_hash:
        log_audit_event("LOGIN_BLOCKED_NO_PIN", student_id=student.id, detail="Web login blocked: PIN not set on whiteboard yet", ip_address=ip_address, db=db)
        raise PinNotSetError("Your 4-digit PIN has not been set yet. Please scan your RFID card on the physical whiteboard to create your PIN before signing in online.")

    if not verify_pin(pin, student.pin_hash):
        log_audit_event("LOGIN_FAIL", student_id=student.id, detail=f"Invalid PIN for email: {email}", ip_address=ip_address, db=db)
        raise InvalidPinError("Invalid email or PIN.")

    # Successful authentication
    token = create_session(student.id, session_type="web", db=db)
    db.execute_commit("UPDATE students SET last_login_at = NOW() WHERE id = %s", (student.id,))
    log_audit_event("LOGIN", student_id=student.id, detail="Web Email+PIN Login", ip_address=ip_address, db=db)
    return student, token


# === Session Management ===

def create_session(student_id: int, session_type: str = "local", db: Optional[DatabasePool] = None) -> str:
    """Generate and persist a cryptographically secure session token."""
    db = db or get_db()
    token = secrets.token_hex(32)  # 64-character hex string
    hours = SESSION_TIMEOUT_HOURS_LOCAL if session_type == "local" else SESSION_TIMEOUT_HOURS_WEB
    expires_at = datetime.now() + timedelta(hours=hours)

    # Deactivate existing sessions of the same type for this student if local
    if session_type == "local":
        db.execute_commit(
            "UPDATE sessions SET is_active = FALSE WHERE student_id = %s AND session_type = 'local'",
            (student_id,),
        )

    sql = """
        INSERT INTO sessions (student_id, session_token, session_type, created_at, expires_at, is_active)
        VALUES (%s, %s, %s, NOW(), %s, TRUE)
    """
    db.execute_insert(sql, (student_id, token, session_type, expires_at))
    return token


def validate_session(token: str, db: Optional[DatabasePool] = None) -> Optional[Student]:
    """Validate a session token and return the associated Student if active."""
    if not token:
        return None
    db = db or get_db()
    sql = """
        SELECT s.*, sess.expires_at, sess.is_active
        FROM sessions sess
        JOIN students s ON s.id = sess.student_id
        WHERE sess.session_token = %s
          AND sess.is_active = TRUE
          AND sess.expires_at > NOW()
        LIMIT 1
    """
    row = db.execute_one(sql, (token,))
    if not row:
        return None
    return Student.from_row(row)


def revoke_session(token: str, db: Optional[DatabasePool] = None) -> bool:
    """Revoke/logout an active session."""
    if not token:
        return False
    db = db or get_db()
    rows = db.execute_commit("UPDATE sessions SET is_active = FALSE WHERE session_token = %s", (token,))
    return rows > 0
