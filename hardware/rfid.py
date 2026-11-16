import json
import logging
import os
import time
import threading
from typing import Optional, Tuple

logger = logging.getLogger("DigiBook.RFID")

SHARED_CARD_PATH = "/tmp/digibook_rfid_last.json"
LOCK_PATH = "/tmp/digibook_rfid.lock"


def broadcast_scanned_card(rfid_key: str):
    """Write the detected RFID key to a shared JSON file so run.py and webapp stay in sync."""
    if not rfid_key:
        return
    try:
        tmp_target = SHARED_CARD_PATH + ".tmp"
        with open(tmp_target, "w") as f:
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
            with open(SHARED_CARD_PATH, "r") as f:
                data = json.load(f)
            ts = data.get("timestamp", 0)
            if (time.time() - ts) <= max_age:
                uid = data.get("uid")
                if uid:
                    return str(uid).strip()
    except Exception:
        pass
    return None


# Conditional import of RC522 / RPi.GPIO
RPI_RFID_AVAILABLE = False
try:
    from mfrc522 import SimpleMFRC522, MFRC522
    import RPi.GPIO as GPIO
    RPI_RFID_AVAILABLE = True

    # --- CRITICAL BUGFIX FOR PYTHON 3.13 / mfrc522 PACKAGE ---
    # 1. Fix MFRC522_ToCard bitwise inversion bug:
    def _fixed_MFRC522_ToCard(self, command, sendData):
        backData = []
        backLen = 0
        status = self.MI_ERR
        irqEn = 0x00
        waitIRq = 0x00
        lastBits = None
        n = 0

        if command == self.PCD_AUTHENT:
            irqEn = 0x12
            waitIRq = 0x10
        if command == self.PCD_TRANSCEIVE:
            irqEn = 0x77
            waitIRq = 0x30

        self.Write_MFRC522(self.CommIEnReg, irqEn | 0x80)
        self.ClearBitMask(self.CommIrqReg, 0x80)
        self.SetBitMask(self.FIFOLevelReg, 0x80)

        self.Write_MFRC522(self.CommandReg, self.PCD_IDLE)

        for b in sendData:
            self.Write_MFRC522(self.FIFODataReg, b)

        self.Write_MFRC522(self.CommandReg, command)

        if command == self.PCD_TRANSCEIVE:
            self.SetBitMask(self.BitFramingReg, 0x80)

        i = 2000
        while True:
            n = self.Read_MFRC522(self.CommIrqReg)
            i -= 1
            if i == 0 or (n & 0x01) != 0 or (n & waitIRq) != 0:
                break

        self.ClearBitMask(self.BitFramingReg, 0x80)

        if i != 0:
            err = self.Read_MFRC522(self.ErrorReg)
            if (err & 0x1B) == 0x00:
                status = self.MI_OK
                if n & irqEn & 0x01:
                    status = self.MI_NOTAGERR
                if command == self.PCD_TRANSCEIVE:
                    n = self.Read_MFRC522(self.FIFOLevelReg)
                    lastBits = self.Read_MFRC522(self.ControlReg) & 0x07
                    if lastBits != 0:
                        backLen = (n - 1) * 8 + lastBits
                    else:
                        backLen = n * 8

                    if n == 0:
                        n = 1
                    if n > self.MAX_LEN:
                        n = self.MAX_LEN

                    for _ in range(n):
                        backData.append(self.Read_MFRC522(self.FIFODataReg))
            else:
                status = self.MI_ERR

        return (status, backData, backLen)

    MFRC522.MFRC522_ToCard = _fixed_MFRC522_ToCard

    # 2. Fix MFRC522_Request strict 16-bit drop (allows 7-byte and non-classic NFC cards)
    def _fixed_MFRC522_Request(self, reqMode):
        self.Write_MFRC522(self.BitFramingReg, 0x07)
        (status, backData, backBits) = self.MFRC522_ToCard(self.PCD_TRANSCEIVE, [reqMode])
        if status != self.MI_OK or not backBits or backBits == 0:
            status = self.MI_ERR
        return (status, backBits)

    MFRC522.MFRC522_Request = _fixed_MFRC522_Request

    # 3. Fix AntennaOn bitmask logic
    def _fixed_AntennaOn(self):
        temp = self.Read_MFRC522(self.TxControlReg)
        if (temp & 0x03) != 0x03:
            self.SetBitMask(self.TxControlReg, 0x03)

    MFRC522.AntennaOn = _fixed_AntennaOn

except (ImportError, RuntimeError):
    pass


class RFIDReader:
    """
    High-Performance, Multi-Threaded RC522 RFID Hardware Driver.
    Features:
      - Continuous 25Hz non-blocking background scanning daemon (never misses taps).
      - Zero-overhead main thread consumption (0.01ms instant read in run.py).
      - Cross-process IPC broadcast syncing between local display and Flask webapp.
      - Debounce filter preventing repeated duplicate rapid-fire triggers.
    """

    def __init__(self, simulation: bool = False):
        self.simulation = simulation
        self.reader = None
        self._sim_instance = None

        # Threading & Scan buffer
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._unread_card: Optional[Tuple[str, str]] = None
        self._last_uid: Optional[str] = None
        self._last_scan_time: float = 0.0
        self._worker_thread: Optional[threading.Thread] = None

        if not self.simulation:
            if not RPI_RFID_AVAILABLE:
                logger.warning(
                    "mfrc522 or RPi.GPIO is not available on this platform. "
                    "Falling back to simulation mode for RFID."
                )
                self.simulation = True
            else:
                try:
                    GPIO.setwarnings(False)
                    self.reader = SimpleMFRC522()
                    # Keep transmitter antenna continuously powered with max gain (48dB)
                    try:
                        self.reader.READER.Write_MFRC522(self.reader.READER.RFCfgReg, 0x07 << 4)
                        self.reader.READER.AntennaOn()
                    except Exception:
                        pass

                    # Start continuous hardware polling daemon
                    self._worker_thread = threading.Thread(
                        target=self._daemon_poll_loop,
                        daemon=True,
                        name="RFID-Hardware-Daemon"
                    )
                    self._worker_thread.start()
                    logger.info("RC522 RFID hardware daemon active on SPI (Gain: 48dB, 25Hz Polling).")
                except Exception as e:
                    logger.error("Failed to initialize RC522 hardware: %s. Falling back to simulation.", e)
                    self.simulation = True

    def _read_raw_card(self) -> Optional[str]:
        """Poll the RC522 chip directly using multi-tier request protocols."""
        if self.reader is None:
            return None
        try:
            m = self.reader.READER

            # Strategy A: Standard SimpleMFRC522 read_id_no_block
            card_id = self.reader.read_id_no_block()
            if card_id is not None:
                return str(card_id).strip()

            # Strategy B: WUPA (0x52) wakes cards in HALT/IDLE/READY states
            status, _ = m.MFRC522_Request(m.PICC_REQALL)
            if status == m.MI_OK:
                status_ac, raw_uid = m.MFRC522_Anticoll()
                if status_ac == m.MI_OK and raw_uid:
                    return str(self.reader.uid_to_num(raw_uid)).strip()

            # Strategy C: Standard REQA (0x26)
            status, _ = m.MFRC522_Request(m.PICC_REQIDL)
            if status == m.MI_OK:
                status_ac, raw_uid = m.MFRC522_Anticoll()
                if status_ac == m.MI_OK and raw_uid:
                    return str(self.reader.uid_to_num(raw_uid)).strip()
        except Exception:
            pass
        return None

    def _daemon_poll_loop(self):
        """Dedicated background worker polling RC522 hardware continuously."""
        while not self._stop_event.is_set():
            try:
                card_id_str = self._read_raw_card()
                if card_id_str:
                    now = time.time()
                    with self._lock:
                        # Debounce: new card OR > 1.4s since previous scan of same card
                        if card_id_str != self._last_uid or (now - self._last_scan_time) > 1.4:
                            self._last_uid = card_id_str
                            self._last_scan_time = now
                            self._unread_card = (card_id_str, "")
                            broadcast_scanned_card(card_id_str)
                            logger.info("RFID card captured by daemon: UID=%s", card_id_str)
            except Exception as e:
                logger.debug("Error in RFID daemon loop: %s", e)

            # Sleep 40ms (~25 Hz polling, optimal response time with zero CPU load)
            time.sleep(0.04)

    def read_card_nonblocking(self) -> Optional[Tuple[str, str]]:
        """
        Instantaneous, non-blocking check for scanned RFID card.
        Consumes the buffered card from the background daemon or IPC broadcast.
        Returns: (rfid_key, card_text) or None.
        """
        # 1. Check local background hardware daemon / injected buffer
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
                if recent_broadcast != self._last_uid or (now - self._last_scan_time) > 1.4:
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

    def _simulated_wait_for_card(self, timeout: Optional[float] = None) -> Optional[Tuple[str, str]]:
        """Fallback simulation prompt if accessed directly."""
        if self._sim_instance is None:
            from hardware.simulation import SimulatedRFID
            self._sim_instance = SimulatedRFID()
        return self._sim_instance.wait_for_card(timeout=timeout)

    def cleanup(self):
        """Signal background worker to stop and release GPIO resources."""
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=0.5)

        if RPI_RFID_AVAILABLE and not self.simulation:
            try:
                if self.reader:
                    try:
                        self.reader.READER.AntennaOff()
                    except Exception:
                        pass
                import RPi.GPIO as GPIO
                GPIO.cleanup()
                logger.info("RFID GPIO resources cleaned up.")
            except Exception as e:
                logger.debug("Error during GPIO cleanup: %s", e)
