import json
import logging
import os
import time
from typing import Optional, Tuple

logger = logging.getLogger("DigiBook.RFID")

try:
    import fcntl
except ImportError:
    fcntl = None

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
    # RuntimeError occurs on non-Raspberry Pi OS (e.g., "Must be run on a Raspberry Pi")
    pass

LOCK_PATH = "/tmp/digibook_rfid.lock"


class RFIDReader:
    """
    Interface for the RC522 RFID reader.
    Handles SPI communication on Raspberry Pi with cross-process locking
    to allow simultaneous operation between run.py and webapp services.
    """

    def __init__(self, simulation: bool = False):
        self.simulation = simulation
        self.reader = None
        self._sim_instance = None

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
                    # Maximize antenna gain (48dB) for superior detection distance
                    try:
                        self.reader.READER.Write_MFRC522(self.reader.READER.RFCfgReg, 0x07 << 4)
                        self.reader.READER.AntennaOn()
                    except Exception:
                        pass
                    logger.info("RC522 RFID reader initialized successfully on SPI (Gain: 48dB).")
                except Exception as e:
                    logger.error("Failed to initialize RC522 hardware: %s. Falling back to simulation.", e)
                    self.simulation = True

    def wait_for_card(self, timeout: Optional[float] = None) -> Optional[Tuple[str, str]]:
        """
        Block until an RFID card is presented or timeout is reached.
        Returns: (rfid_key, card_text) or None if timeout.
        """
        if self.simulation:
            return self._simulated_wait_for_card(timeout)

        # 1. Fast check for recently broadcast card from companion process (e.g., run.py)
        broadcast_uid = get_broadcast_scanned_card(max_age=1.8)
        if broadcast_uid:
            return broadcast_uid, ""

        start_time = time.time()
        while True:
            card = self.read_card_nonblocking()
            if card is not None:
                return card

            if timeout is not None and (time.time() - start_time) >= timeout:
                return None

            time.sleep(0.04)

    def read_card_nonblocking(self) -> Optional[Tuple[str, str]]:
        """
        Non-blocking read attempt with cross-process concurrency locking.
        Uses fast anticollision UID detection, WUPA (PICC_REQALL) for halted cards,
        and shared IPC broadcast file to sync seamlessly between run.py and web services.
        Returns: (rfid_key, card_text) or None if no card is present.
        """
        # 1. Fast check: did another process scan a card in the last 1.2s?
        recent_broadcast = get_broadcast_scanned_card(max_age=1.2)
        if recent_broadcast:
            return recent_broadcast, ""

        if self.simulation or self.reader is None:
            return None

        # 2. Cross-process non-blocking file lock so run.py and web services share SPI cleanly
        lock_fd = None
        if fcntl and os.name != "nt":
            try:
                lock_fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o666)
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, OSError, PermissionError):
                if lock_fd is not None:
                    try:
                        os.close(lock_fd)
                    except Exception:
                        pass
                return None

        try:
            m = self.reader.READER
            # Always ensure transmitter antenna is active and gain is maximized to 48dB
            try:
                m.Write_MFRC522(m.RFCfgReg, 0x07 << 4)
                m.AntennaOn()
            except Exception:
                pass

            card_id = None

            # Strategy A: PICC_REQALL (WUPA 0x52) - wakes cards in IDLE, READY, and HALT states
            try:
                status, _ = m.MFRC522_Request(m.PICC_REQALL)
                if status == m.MI_OK:
                    status_ac, raw_uid = m.MFRC522_Anticoll()
                    if status_ac == m.MI_OK and raw_uid:
                        card_id = self.reader.uid_to_num(raw_uid)
            except Exception:
                pass

            # Strategy B: PICC_REQIDL (REQA 0x26) fallback for standard cards in IDLE state
            if card_id is None:
                try:
                    status, _ = m.MFRC522_Request(m.PICC_REQIDL)
                    if status == m.MI_OK:
                        status_ac, raw_uid = m.MFRC522_Anticoll()
                        if status_ac == m.MI_OK and raw_uid:
                            card_id = self.reader.uid_to_num(raw_uid)
                except Exception:
                    pass

            # Strategy C: SimpleMFRC522 standard high-level read_id_no_block()
            if card_id is None:
                try:
                    card_id = self.reader.read_id_no_block()
                except Exception:
                    pass

            if card_id is not None:
                rfid_key = str(card_id).strip()
                broadcast_scanned_card(rfid_key)
                logger.info("RFID card detected: UID=%s", rfid_key)
                return rfid_key, ""
        except Exception as e:
            logger.debug("Error in read_card_nonblocking: %s", e)
        finally:
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    os.close(lock_fd)
                except Exception:
                    pass

        return None

    def _simulated_wait_for_card(self, timeout: Optional[float] = None) -> Optional[Tuple[str, str]]:
        """Fallback simulation prompt if accessed directly."""
        if self._sim_instance is None:
            from hardware.simulation import SimulatedRFID
            self._sim_instance = SimulatedRFID()
        return self._sim_instance.wait_for_card(timeout=timeout)

    def cleanup(self):
        """Clean up GPIO resources."""
        if RPI_RFID_AVAILABLE and not self.simulation:
            try:
                import RPi.GPIO as GPIO
                GPIO.cleanup()
                logger.info("RFID GPIO resources cleaned up.")
            except Exception as e:
                logger.debug("Error during GPIO cleanup: %s", e)
