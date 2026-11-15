import pytest
import json
from webapp.app import create_app
from tests.test_auth import MockDatabase


@pytest.fixture
def app_and_mock_db():
    mock_db = MockDatabase()
    app = create_app({"TESTING": True, "SECRET_KEY": "test-key"})
    app._test_db = mock_db

    @app.before_request
    def attach_mock_db():
        from flask import request
        request._db = mock_db

    return app, mock_db


@pytest.fixture
def client(app_and_mock_db):
    app, _ = app_and_mock_db
    return app.test_client()


def test_api_register_and_login(client):
    """Test student registration and subsequent email+PIN login via API."""
    # 1. Attempt registration with PIN (must be rejected)
    res_rejected = client.post("/api/v1/auth/register", json={
        "student_name": "Robin Sparkles",
        "student_id": "STU_ROBIN",
        "rfid_key": "RFID_ROBIN_99",
        "class": "Music-101",
        "email": "robin@school.edu",
        "pin": "7788",
    })
    assert res_rejected.status_code == 400
    assert "PIN cannot be set during registration" in res_rejected.get_json()["error"]

    # 2. Register student properly without PIN
    reg_payload = {
        "student_name": "Robin Sparkles",
        "student_id": "STU_ROBIN",
        "rfid_key": "RFID_ROBIN_99",
        "class": "Music-101",
        "email": "robin@school.edu",
    }
    res = client.post("/api/v1/auth/register", json=reg_payload)
    assert res.status_code == 201
    data = res.get_json()
    assert data["success"] is True
    assert data["student"]["student_name"] == "Robin Sparkles"
    student_id = data["student"]["id"]

    # 3. Setting PIN at whiteboard
    res_set_pin = client.post("/api/v1/auth/set-pin", json={
        "student_id": student_id,
        "pin": "7788"
    })
    assert res_set_pin.status_code == 200

    # 4. Login with correct email and newly established PIN
    login_payload = {
        "email": "robin@school.edu",
        "pin": "7788",
    }
    res_login = client.post("/api/v1/auth/login", json=login_payload)
    assert res_login.status_code == 200
    login_data = res_login.get_json()
    assert login_data["success"] is True
    assert "session_token" in login_data
    token = login_data["session_token"]
    assert len(token) == 64

    # 5. Login with wrong PIN
    res_wrong = client.post("/api/v1/auth/login", json={"email": "robin@school.edu", "pin": "0000"})
    assert res_wrong.status_code == 401


def test_api_rfid_lookup_and_set_pin(client):
    """Test RFID card lookup and PIN creation workflow."""
    # Register a student with no PIN
    client.post(
        "/api/v1/auth/register",
        json={
            "student_name": "No Pin Student",
            "student_id": "STU_NOPIN",
            "rfid_key": "RFID_NOPIN",
            "class": "Math",
            "email": "nopin@school.edu",
        },
    )

    # Lookup by RFID
    res_lookup = client.post("/api/v1/auth/rfid-lookup", json={"rfid_key": "RFID_NOPIN"})
    assert res_lookup.status_code == 200
    lookup_data = res_lookup.get_json()
    assert lookup_data["needs_pin_creation"] is True
    student_id = lookup_data["student"]["id"]

    # Set PIN
    res_pin = client.post("/api/v1/auth/set-pin", json={"student_id": student_id, "pin": "4321"})
    assert res_pin.status_code == 200

    # RFID login with newly set PIN
    res_rfid_login = client.post(
        "/api/v1/auth/login",
        json={"rfid_key": "RFID_NOPIN", "pin": "4321"},
    )
    assert res_rfid_login.status_code == 200
    assert "session_token" in res_rfid_login.get_json()


def test_api_whiteboard_crud(client, app_and_mock_db):
    """Test whiteboard creation, listing, stroke saving, and deletion."""
    _, mock_db = app_and_mock_db

    # Register & Login
    reg_res = client.post(
        "/api/v1/auth/register",
        json={
            "student_name": "WB Tester",
            "student_id": "STU_WB",
            "rfid_key": "RFID_WB",
            "class": "Science",
            "email": "wb@school.edu",
        },
    )
    assert reg_res.status_code == 201
    wb_student_id = reg_res.get_json()["student"]["id"]
    client.post("/api/v1/auth/set-pin", json={"student_id": wb_student_id, "pin": "1234"})

    login_res = client.post("/api/v1/auth/login", json={"email": "wb@school.edu", "pin": "1234"})
    token = login_res.get_json()["session_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. List whiteboards (initially empty)
    res_list = client.get("/api/v1/whiteboards", headers=headers)
    assert res_list.status_code == 200

    # 2. Create whiteboard
    res_create = client.post("/api/v1/whiteboards", json={"title": "Physics Notes"}, headers=headers)
    assert res_create.status_code == 201
    wb_data = res_create.get_json()["whiteboard"]
    wb_id = wb_data["id"]
    assert wb_data["title"] == "Physics Notes"

    # Mock the created whiteboard in mock_db for get_whiteboard / strokes
    mock_db.whiteboards[wb_id] = {
        "id": wb_id,
        "student_id": wb_data["student_id"],
        "title": "Physics Notes",
        "created_at": None,
        "updated_at": None,
        "is_deleted": False,
        "thumbnail_b64": None,
    }

    # 3. Save strokes
    strokes_payload = {
        "strokes": [
            {
                "version": 1,
                "tool": "pen",
                "color": "#39FF14",
                "width": 0.005,
                "points": [{"x": 0.1, "y": 0.1, "t": 0}],
            }
        ]
    }
    res_strokes = client.put(f"/api/v1/whiteboards/{wb_id}/strokes", json=strokes_payload, headers=headers)
    assert res_strokes.status_code == 200

    # 4. Delete whiteboard
    res_del = client.delete(f"/api/v1/whiteboards/{wb_id}", headers=headers)
    assert res_del.status_code == 200


def test_api_hardware_rfid_scan(client):
    """Test polling the hardware RFID reader endpoint."""
    res = client.get("/api/v1/hardware/rfid-scan?timeout=0.2")
    assert res.status_code == 200
    data = res.get_json()
    assert "success" in data
    assert "rfid_key" in data


def test_api_web_login_blocked_without_whiteboard_pin(client):
    """Verify web API /auth/login returns 403 Forbidden for students without whiteboard PIN."""
    # Register student without PIN
    res_reg = client.post("/api/v1/auth/register", json={
        "student_name": "No Pin Web",
        "student_id": "STU_NOPIN_API",
        "rfid_key": "RFID_NOPIN_API",
        "class": "English",
        "email": "nopin_api@school.edu",
    })
    assert res_reg.status_code == 201
    stu_id = res_reg.get_json()["student"]["id"]

    # Attempting web login before whiteboard PIN creation
    res_login = client.post("/api/v1/auth/login", json={
        "email": "nopin_api@school.edu",
        "pin": "1234"
    })
    assert res_login.status_code == 403
    assert res_login.get_json()["code"] == "PIN_NOT_SET"

    # Set PIN at whiteboard
    res_set = client.post("/api/v1/auth/set-pin", json={
        "student_id": stu_id,
        "pin": "1234"
    })
    assert res_set.status_code == 200

    # Web login now succeeds
    res_login_ok = client.post("/api/v1/auth/login", json={
        "email": "nopin_api@school.edu",
        "pin": "1234"
    })
    assert res_login_ok.status_code == 200
    assert "session_token" in res_login_ok.get_json()
