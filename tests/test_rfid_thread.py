import time
import pytest
from hardware.rfid import RFIDReader


def test_rfid_reader_simulation_nonblocking():
    """Verify that RFIDReader in simulation mode returns None when unread."""
    reader = RFIDReader(simulation=True)
    card = reader.read_card_nonblocking()
    assert card is None
    reader.cleanup()


def test_rfid_reader_buffer_consumption():
    """Verify that a captured card is consumed once and debounced."""
    reader = RFIDReader(simulation=True)
    # Manually inject a scanned card into the buffer
    with reader._lock:
        reader._unread_card = ("941185239036", "")

    # First read consumes the card
    card1 = reader.read_card_nonblocking()
    assert card1 is not None
    assert card1[0] == "941185239036"

    # Second immediate read should be None (consumed)
    card2 = reader.read_card_nonblocking()
    assert card2 is None
    reader.cleanup()


def test_rfid_reader_wait_timeout():
    """Verify wait_for_card returns None after timeout without hanging."""
    reader = RFIDReader(simulation=True)
    t0 = time.time()
    res = reader.wait_for_card(timeout=0.1)
    elapsed = time.time() - t0

    assert res is None
    assert 0.08 <= elapsed <= 0.35
    reader.cleanup()


def test_rfid_relay_server_integration(monkeypatch):
    """Verify RFIDReader can connect and send command feedback to real-time relay."""
    import urllib.request
    from unittest.mock import MagicMock

    reader = RFIDReader(simulation=True)
    assert reader.server_url.startswith("https://")
    assert reader.auth_token == "00000000"

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp

    with monkeypatch.context() as m:
        m.setattr(urllib.request, "urlopen", MagicMock(return_value=mock_resp))
        sent = reader.send_command(command="ping", action="test", message="Unit Test Ping")
        assert sent is True, "Expected relay server to accept valid ping command"
    reader.cleanup()
