import json
import logging
import os
import time
import threading
import urllib.request
import urllib.error
from typing import Optional, Tuple, Dict, Any

from config.settings import RFID_RELAY_URL, RFID_RELAY_AUTH

logger = logging.getLogger("DigiBook.RFID")

SHARED_CARD_PATH = "/tmp/digibook_rfid_last.json"


def broadcast_scanned_card(rfid_key: str):
    """Write the detected RFID key to a shared JSON file so run.py and webapp stay in sync."""
    if not rfid_key:
        return
    try:
        tmp_target = SHARED_CARD_PATH + ".tmp"
        with open(tmp_target, "w", encoding="utf-8") as f:
            json.dump({"uid": str(rfid_key).strip(), "timestamp": time.time()}, f)
        os.replace(tmp_target, SHARED_CARD_PATH)
        try:
            os.chmod(SHARED_CARD_PATH, 0o666)
        except Exception:
            pass
    except Exception:
        pass


def get_broadcast_scanned_card(max_age: float = 2.0) -> Optional[str]:
    """Retrieve an RFID key detected by another process within the last max_age seconds."""
    try:
        if os.path.exists(SHARED_CARD_PATH):
            with open(SHARED_CARD_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            ts = data.get("timestamp", 0)
            if (time.time() - ts) <= max_age:
                uid = data.get("uid")
                if uid:
                    return str(uid).strip()
    except Exception:
        pass
    return None


class RFIDReader:
    """
    Real-Time Cloud & Local Relay RFID Client for DigiBook.
    Connects to the zero-latency ESP8266 / ESP32 RFID Relay Server (rfid.pranab.space /node).
    Features:
      - Continuous non-blocking background long-polling daemon (instant tap detection).
      - Zero local hardware bus conflicts: no SPI, no GPIO pin collisions, no Python 3.13 issues.
      - Receives 20-character deterministic encrypted discriminant keys.
      - 2-way command feedback: can trigger hardware buzzer / LED flash on access granted.
      - Instant zero-overhead consumption in run.py and webapp registration.
    """

    def __init__(
        self,
        server_url: Optional[str] = None,
        auth_token: Optional[str] = None,
        simulation: bool = False,
    ):
        self.simulation = simulation
        self.server_url = (server_url or RFID_RELAY_URL).rstrip("/")
        self.auth_token = auth_token or RFID_RELAY_AUTH
        self._sim_instance = None

        # Threading & Scan buffer
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._unread_card: Optional[Tuple[str, str]] = None
        self._last_uid: Optional[str] = None
        self._last_scan_time: float = 0.0
        self._worker_thread: Optional[threading.Thread] = None

        if not self.simulation:
            # Start background relay listener daemon
            self._worker_thread = threading.Thread(
                target=self._relay_listener_loop,
                daemon=True,
                name="RFID-Relay-Client"
            )
            self._worker_thread.start()
            logger.info("RFID Relay Client active: listening to %s/node", self.server_url)

    def _relay_listener_loop(self):
        """Continuous long-polling background worker connecting to the RFID Relay Server."""
        logger.info("Connecting to RFID Relay Server: %s/node (Auth: %s)", self.server_url, self.auth_token[:3] + "*****")
        while not self._stop_event.is_set():
            try:
                endpoint = f"{self.server_url}/node?wait=true"
                req = urllib.request.Request(
                    endpoint,
                    headers={
                        "User-Agent": "DigiBook-AI-Agent/2.0",
                        "x-auth-token": self.auth_token,
                        "Authorization": f"Bearer {self.auth_token}",
                        "Accept": "application/json",
                    }
                )
                # 30-second timeout matching server's 25-second wait cycle
                with urllib.request.urlopen(req, timeout=32) as response:
                    raw_data = response.read().decode("utf-8")
                    if not raw_data:
                        continue

                    data = json.loads(raw_data)
                    # Check for RFID scan event
                    if data.get("type") == "rfid":
                        card_key = (
                            data.get("encryptedKey")
                            or data.get("discriminant")
                            or data.get("uid")
                        )
                        if card_key:
                            card_key = str(card_key).strip()
                            now = time.time()
                            with self._lock:
                                # Debounce: new card OR > 1.2s since previous scan of same card
                                if card_key != self._last_uid or (now - self._last_scan_time) > 1.2:
                                    self._last_uid = card_key
                                    self._last_scan_time = now
                                    self._unread_card = (card_key, "")
                                    broadcast_scanned_card(card_key)
                                    logger.info("RFID card scanned via Relay Server: Key=%s", card_key)

            except urllib.error.HTTPError as e:
                logger.warning("RFID Relay Server HTTP Error: %s %s", e.code, e.reason)
                time.sleep(2.0)
            except (urllib.error.URLError, TimeoutError) as e:
                # Normal 25-second poll timeout or network retry
                time.sleep(0.3)
            except Exception as e:
                logger.debug("RFID Relay listener exception: %s", e)
                time.sleep(1.0)

    def read_card_nonblocking(self) -> Optional[Tuple[str, str]]:
        """
        Instantaneous, non-blocking check for scanned RFID card.
        Consumes the buffered card from the background relay listener or IPC broadcast.
        Returns: (rfid_key, card_text) or None.
        """
        # 1. Check local background buffer
        with self._lock:
            if self._unread_card is not None:
                card = self._unread_card
                self._unread_card = None
                return card

        if self.simulation:
            return self._simulated_wait_for_card(timeout=0.0)

        # 2. Check IPC broadcast (if card was scanned by another companion process)
        recent_broadcast = get_broadcast_scanned_card(max_age=1.5)
        if recent_broadcast:
            now = time.time()
            with self._lock:
                if recent_broadcast != self._last_uid or (now - self._last_scan_time) > 1.2:
                    self._last_uid = recent_broadcast
                    self._last_scan_time = now
                    return (recent_broadcast, "")

        return None

    def wait_for_card(self, timeout: Optional[float] = None) -> Optional[Tuple[str, str]]:
        """
        Wait until an RFID card is presented or timeout expires.
        Returns: (rfid_key, card_text) or None if timeout.
        """
        if self.simulation:
            return self._simulated_wait_for_card(timeout)

        start_time = time.time()
        while True:
            card = self.read_card_nonblocking()
            if card is not None:
                return card

            if timeout is not None and (time.time() - start_time) >= timeout:
                return None

            time.sleep(0.03)

    def send_command(
        self,
        command: str = "flash",
        action: str = "access_granted",
        message: str = "Welcome User",
        timeout: float = 3.0,
    ) -> bool:
        """
        Send a 2-way hardware command back to the ESP8266 / ESP32 reader
        (e.g. flash LED, beep buzzer on login success).
        """
        try:
            payload = json.dumps({
                "command": command,
                "action": action,
                "cardKey": self._last_uid,
                "message": message,
            }).encode("utf-8")

            req = urllib.request.Request(
                f"{self.server_url}/node",
                data=payload,
                headers={
                    "User-Agent": "DigiBook-AI-Agent/2.0",
                    "Content-Type": "application/json",
                    "x-auth-token": self.auth_token,
                    "Authorization": f"Bearer {self.auth_token}",
                }
            )
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return res.status == 200
        except Exception as e:
            logger.debug("Failed to send 2-way command to RFID relay: %s", e)
            return False

    def _simulated_wait_for_card(self, timeout: Optional[float] = None) -> Optional[Tuple[str, str]]:
        """Fallback simulation prompt if accessed directly."""
        if self._sim_instance is None:
            from hardware.simulation import SimulatedRFID
            self._sim_instance = SimulatedRFID()
        return self._sim_instance.wait_for_card(timeout=timeout)

    def cleanup(self):
        """Signal background worker to stop."""
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=0.5)
        logger.info("RFID Relay Client stopped.")
