import logging
import threading
from typing import Optional
from functools import wraps
from flask import Blueprint, request, jsonify
from flask_login import current_user

from core.database import get_db
from core.models import Student, Stroke, Point
from core.auth import (
    register_student,
    authenticate_rfid_step1,
    authenticate_rfid_pin,
    authenticate_email_pin,
    set_student_pin,
    validate_session,
    revoke_session,
    AuthError,
    InvalidPinError,
    DuplicateFieldError,
    StudentNotFoundError,
    AccountLockedError,
)
from whiteboard.storage import (
    create_whiteboard,
    list_student_whiteboards,
    get_whiteboard,
    update_whiteboard_metadata,
    delete_whiteboard,
    save_whiteboard_strokes,
    load_whiteboard_strokes,
)

logger = logging.getLogger("DigiBook.API")
api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


def get_current_api_student(db=None) -> tuple[Optional[Student], Optional[str]]:
    """
    Resolve student from either Flask-Login session or Bearer token header.
    Returns: (student, error_message)
    """
    # 1. Check Flask-Login current_user
    if current_user.is_authenticated and hasattr(current_user, "student"):
        return current_user.student, None

    # 2. Check Authorization Header: Bearer <token>
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        student = validate_session(token, db=db)
        if student:
            return student, None
        return None, "Invalid or expired session token."

    # 3. Check X-Session-Token header
    token_hdr = request.headers.get("X-Session-Token")
    if token_hdr:
        student = validate_session(token_hdr.strip(), db=db)
        if student:
            return student, None
        return None, "Invalid or expired session token."

    return None, "Authentication required."


def require_api_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        db = getattr(request, "_db", None) or get_db()
        student, err = get_current_api_student(db=db)
        if not student:
            return jsonify({"success": False, "error": err or "Unauthorized"}), 401
        return f(student, *args, **kwargs)
    return decorated


# === Auth API Routes ===

@api_bp.route("/auth/register", methods=["POST"])
def api_register():
    data = request.get_json(silent=True) or {}
    db = getattr(request, "_db", None) or get_db()

    student_name = data.get("student_name", "")
    student_id = data.get("student_id", "")
    rfid_key = data.get("rfid_key", "")
    class_name = data.get("class", "")
    email = data.get("email", "")
    pin = data.get("pin")  # Optional initial 4-digit PIN

    try:
        student = register_student(
            student_name=student_name,
            student_id=student_id,
            rfid_key=rfid_key,
            class_name=class_name,
            email=email,
            pin=pin,
            db=db,
        )
        return jsonify({
            "success": True,
            "message": "Student registered successfully.",
            "student": student.to_dict(safe=True)
        }), 201
    except DuplicateFieldError as e:
        return jsonify({"success": False, "error": str(e)}), 409
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error("Registration error: %s", e)
        return jsonify({"success": False, "error": "Internal server error."}), 500


@api_bp.route("/auth/rfid-lookup", methods=["POST"])
def api_rfid_lookup():
    data = request.get_json(silent=True) or {}
    rfid_key = data.get("rfid_key", "").strip()
    if not rfid_key:
        return jsonify({"success": False, "error": "RFID key is required."}), 400

    db = getattr(request, "_db", None) or get_db()
    status, student = authenticate_rfid_step1(rfid_key, db=db)

    if status == "NOT_FOUND":
        return jsonify({"success": False, "error": "Not Present in Database", "status": status}), 404

    return jsonify({
        "success": True,
        "status": status,
        "needs_pin_creation": (status == "NEEDS_PIN_CREATION"),
        "student": student.to_dict(safe=True) if student else None
    }), 200


@api_bp.route("/auth/set-pin", methods=["POST"])
def api_set_pin():
    data = request.get_json(silent=True) or {}
    student_id = data.get("student_id")
    pin = data.get("pin", "")

    if not student_id or not pin:
        return jsonify({"success": False, "error": "student_id and 4-digit pin are required."}), 400

    db = getattr(request, "_db", None) or get_db()
    try:
        success = set_student_pin(int(student_id), str(pin), db=db)
        if success:
            return jsonify({"success": True, "message": "PIN created successfully."}), 200
        return jsonify({"success": False, "error": "Student not found."}), 404
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400


@api_bp.route("/auth/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    db = getattr(request, "_db", None) or get_db()
    pin = str(data.get("pin", ""))

    rfid_key = data.get("rfid_key")
    email = data.get("email")

    try:
        if rfid_key:
            student, token = authenticate_rfid_pin(rfid_key, pin, ip_address=request.remote_addr, db=db)
        elif email:
            student, token = authenticate_email_pin(email, pin, ip_address=request.remote_addr, db=db)
        else:
            return jsonify({"success": False, "error": "Must provide either rfid_key or email."}), 400

        return jsonify({
            "success": True,
            "session_token": token,
            "student": student.to_dict(safe=True)
        }), 200
    except (InvalidPinError, StudentNotFoundError) as e:
        return jsonify({"success": False, "error": str(e)}), 401
    except AccountLockedError as e:
        return jsonify({"success": False, "error": str(e)}), 429
    except Exception as e:
        logger.error("Login API error: %s", e)
        return jsonify({"success": False, "error": "Authentication failed."}), 500


@api_bp.route("/auth/logout", methods=["POST"])
def api_logout():
    db = getattr(request, "_db", None) or get_db()
    token = request.headers.get("X-Session-Token") or request.headers.get("Authorization", "").replace("Bearer ", "")
    if token:
        revoke_session(token, db=db)
    return jsonify({"success": True, "message": "Logged out successfully."}), 200


# === Whiteboard API Routes ===

@api_bp.route("/whiteboards", methods=["GET"])
@require_api_auth
def api_list_whiteboards(student: Student):
    db = getattr(request, "_db", None) or get_db()
    wbs = list_student_whiteboards(student.id, db=db)
    return jsonify({
        "success": True,
        "whiteboards": [w.to_dict() for w in wbs]
    }), 200


@api_bp.route("/whiteboards", methods=["POST"])
@require_api_auth
def api_create_whiteboard(student: Student):
    data = request.get_json(silent=True) or {}
    title = data.get("title", "Untitled").strip() or "Untitled"
    db = getattr(request, "_db", None) or get_db()

    wb = create_whiteboard(student.id, title=title, db=db)
    return jsonify({
        "success": True,
        "whiteboard": wb.to_dict()
    }), 201


@api_bp.route("/whiteboards/<int:wb_id>", methods=["GET"])
@require_api_auth
def api_get_whiteboard(student: Student, wb_id: int):
    db = getattr(request, "_db", None) or get_db()
    wb = get_whiteboard(wb_id, student_id=student.id, db=db)
    if not wb:
        return jsonify({"success": False, "error": "Whiteboard not found."}), 404

    strokes = load_whiteboard_strokes(wb_id, db=db)
    wb_dict = wb.to_dict()
    wb_dict["strokes"] = [s.to_dict() for s in strokes]

    return jsonify({"success": True, "whiteboard": wb_dict}), 200


@api_bp.route("/whiteboards/<int:wb_id>", methods=["PUT"])
@require_api_auth
def api_update_whiteboard(student: Student, wb_id: int):
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"success": False, "error": "Title is required."}), 400

    db = getattr(request, "_db", None) or get_db()
    success = update_whiteboard_metadata(wb_id, student.id, title, db=db)
    if not success:
        return jsonify({"success": False, "error": "Whiteboard not found."}), 404

    return jsonify({"success": True, "message": "Updated successfully."}), 200


@api_bp.route("/whiteboards/<int:wb_id>", methods=["DELETE"])
@require_api_auth
def api_delete_whiteboard(student: Student, wb_id: int):
    db = getattr(request, "_db", None) or get_db()
    success = delete_whiteboard(wb_id, student.id, db=db)
    if not success:
        return jsonify({"success": False, "error": "Whiteboard not found."}), 404
    return jsonify({"success": True, "message": "Whiteboard deleted."}), 200


@api_bp.route("/whiteboards/<int:wb_id>/strokes", methods=["PUT"])
@require_api_auth
def api_save_strokes(student: Student, wb_id: int):
    """Full-save of all strokes for a whiteboard."""
    db = getattr(request, "_db", None) or get_db()
    wb = get_whiteboard(wb_id, student_id=student.id, db=db)
    if not wb:
        return jsonify({"success": False, "error": "Whiteboard not found."}), 404

    data = request.get_json(silent=True) or {}
    raw_strokes = data.get("strokes", [])
    thumbnail_b64 = data.get("thumbnail_b64")

    strokes = [Stroke.from_dict(s) for s in raw_strokes]
    save_whiteboard_strokes(wb_id, strokes, thumbnail_b64=thumbnail_b64, db=db)

    return jsonify({
        "success": True,
        "message": f"Saved {len(strokes)} strokes successfully."
    }), 200


@api_bp.route("/whiteboards/<int:wb_id>/thumbnail", methods=["GET"])
@require_api_auth
def api_get_thumbnail(student: Student, wb_id: int):
    db = getattr(request, "_db", None) or get_db()
    wb = get_whiteboard(wb_id, student_id=student.id, db=db)
    if not wb:
        return jsonify({"success": False, "error": "Whiteboard not found."}), 404

    return jsonify({
        "success": True,
        "whiteboard_id": wb.id,
        "thumbnail_b64": wb.thumbnail_b64 or ""
    }), 200


# === Hardware Integration Routes ===

_rfid_reader_instance = None
_rfid_lock = threading.Lock()


def get_rfid_reader_instance():
    """Singleton getter for the hardware RFID reader with thread-safety."""
    global _rfid_reader_instance
    with _rfid_lock:
        if _rfid_reader_instance is None:
            from hardware.rfid import RFIDReader
            _rfid_reader_instance = RFIDReader()
        return _rfid_reader_instance


@api_bp.route("/hardware/rfid-scan", methods=["GET"])
def api_hardware_rfid_scan():
    """
    Poll the connected RC522 RFID reader on Raspberry Pi for an RFID card.
    Used by the registration page to automatically populate the RFID field
    when a student taps their card on the physical reader.
    Query parameters:
        timeout: float in seconds (default 1.5, min 0.2, max 3.0)
    Returns:
        JSON: {"success": true, "rfid_key": "<uid>", "text": "..."}
        or {"success": false, "rfid_key": null}
    """
    try:
        raw_timeout = float(request.args.get("timeout", 1.5))
    except (ValueError, TypeError):
        raw_timeout = 1.5
    timeout = min(max(raw_timeout, 0.2), 3.0)

    try:
        reader = get_rfid_reader_instance()
        with _rfid_lock:
            result = reader.wait_for_card(timeout=timeout)

        if result:
            rfid_key, card_text = result
            return jsonify({
                "success": True,
                "rfid_key": str(rfid_key).strip(),
                "text": str(card_text).strip() if card_text else "",
                "message": "Card detected successfully."
            }), 200

        return jsonify({
            "success": False,
            "rfid_key": None,
            "message": "Waiting for RFID card..."
        }), 200
    except Exception as e:
        logger.error("Error during hardware RFID scan API call: %s", e)
        return jsonify({
            "success": False,
            "rfid_key": None,
            "error": str(e)
        }), 500

