import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user

from core.database import get_db
from core.auth import (
    register_student,
    authenticate_email_pin,
    DuplicateFieldError,
    InvalidPinError,
    PinNotSetError,
    StudentNotFoundError,
    AccountLockedError,
)
from whiteboard.storage import list_student_whiteboards, get_whiteboard, create_whiteboard
from webapp.auth_web import WebUser

logger = logging.getLogger("DigiBook.Views")
views_bp = Blueprint("views", __name__)


@views_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("views.dashboard"))
    return redirect(url_for("views.signin"))


@views_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("views.dashboard"))

    if request.method == "POST":
        student_name = request.form.get("student_name", "").strip()
        student_id = request.form.get("student_id", "").strip()
        rfid_key = request.form.get("rfid_key", "").strip()
        class_name = request.form.get("class", "").strip()
        email = request.form.get("email", "").strip().lower()

        db = getattr(request, "_db", None) or get_db()

        try:
            student = register_student(
                student_name=student_name,
                student_id=student_id,
                rfid_key=rfid_key,
                class_name=class_name,
                email=email,
                pin=None,  # PIN is exclusively created at the physical whiteboard
                db=db,
            )
            flash(
                f"Registration successful for {student.student_name}! Please scan your RFID card on the whiteboard to set your 4-digit PIN before signing in.",
                "success"
            )
            return redirect(url_for("views.signin"))
        except (DuplicateFieldError, ValueError) as e:
            flash(str(e), "danger")
        except Exception as e:
            logger.error("Signup error: %s", e)
            flash("An unexpected error occurred during registration.", "danger")

    return render_template("signup.html")


@views_bp.route("/signin", methods=["GET", "POST"])
def signin():
    if current_user.is_authenticated:
        return redirect(url_for("views.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pin = request.form.get("pin", "").strip()
        db = getattr(request, "_db", None) or get_db()

        try:
            student, _ = authenticate_email_pin(email, pin, ip_address=request.remote_addr, db=db)
            web_user = WebUser(student)
            login_user(web_user)
            return redirect(url_for("views.dashboard"))
        except PinNotSetError as e:
            flash(str(e), "warning")
        except (InvalidPinError, StudentNotFoundError) as e:
            flash(str(e), "danger")
        except AccountLockedError as e:
            flash(str(e), "warning")
        except Exception as e:
            logger.error("Signin error: %s", e)
            flash("Login failed. Please verify your credentials.", "danger")

    return render_template("signin.html")


@views_bp.route("/dashboard")
@login_required
def dashboard():
    db = getattr(request, "_db", None) or get_db()
    whiteboards = list_student_whiteboards(int(current_user.id), db=db)
    return render_template("dashboard.html", whiteboards=whiteboards, student=current_user)


@views_bp.route("/whiteboard/<int:wb_id>")
@login_required
def whiteboard(wb_id: int):
    db = getattr(request, "_db", None) or get_db()
    wb = get_whiteboard(wb_id, student_id=int(current_user.id), db=db)
    if not wb:
        flash("Whiteboard not found or permission denied.", "danger")
        return redirect(url_for("views.dashboard"))
    return render_template("whiteboard.html", whiteboard=wb, student=current_user)


@views_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("views.signin"))


@views_bp.route("/db", methods=["GET", "POST"])
def db_viewer():
    """
    Diagnostic Database Studio for inspecting tables, schemas, and stored rows.
    Protected by password '8520'.
    """
    from flask import session
    from config.settings import DB_HOST

    # Handle explicit logout / lock
    if request.args.get("logout"):
        session.pop("db_studio_auth", None)
        return redirect(url_for("views.db_viewer"))

    # Check password via POST or query parameter or existing session
    password = request.form.get("password") or request.args.get("pin")
    if password:
        if str(password).strip() == "8520":
            session["db_studio_auth"] = True
            flash("Database Studio unlocked successfully.", "success")
            return redirect(url_for("views.db_viewer"))
        else:
            flash("Invalid PIN. Access denied.", "danger")

    authenticated = session.get("db_studio_auth", False)
    if not authenticated:
        return render_template("db_viewer.html", authenticated=False)

    db = getattr(request, "_db", None) or get_db()
    available_tables = ["students", "whiteboards", "whiteboard_strokes", "sessions", "audit_log"]

    # Table counts
    table_counts = {}
    for tbl in available_tables:
        try:
            cnt_row = db.execute_one(f"SELECT COUNT(*) as cnt FROM `{tbl}`")
            table_counts[tbl] = cnt_row["cnt"] if cnt_row else 0
        except Exception:
            table_counts[tbl] = 0

    active_table = request.args.get("table", "students")
    if active_table not in available_tables:
        active_table = "students"

    schema = []
    rows = []
    try:
        schema = db.execute(f"DESCRIBE `{active_table}`")
        rows = db.execute(f"SELECT * FROM `{active_table}` ORDER BY id DESC LIMIT 50")
    except Exception as e:
        flash(f"Error querying table {active_table}: {e}", "danger")

    return render_template(
        "db_viewer.html",
        authenticated=True,
        db_host=DB_HOST,
        tables=available_tables,
        table_counts=table_counts,
        active_table=active_table,
        schema=schema,
        rows=rows,
    )
