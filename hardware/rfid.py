import logging
import os
import time
from typing import Optional, Tuple

logger = logging.getLogger("DigiBook.RFID")

try:
    import fcntl
except ImportError:
    fcntl = None

# Conditional import of RC522 / RPi.GPIO
RPI_RFID_AVAILABLE = False
try:
    from mfrc522 import SimpleMFRC522, MFRC522
    import RPi.GPIO as GPIO
    RPI_RFID_AVAILABLE = True

    # --- CRITICAL BUGFIX FOR PYTHON 3.13 / mfrc522 PACKAGE ---
    # The upstream mfrc522 library contains a fatal bug in MFRC522_ToCard:
    # "if ~((i != 0) and ~(n & 0x01) and ~(n & waitIRq)): break"
    # In Python, ~bool is ALWAYS negative (-1 or -2), which is always truthy!
    # This caused the transceiver loop to abort on cycle 1 before receiving RF response from card.
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
            # Correct Python logical break condition
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
        Uses fast anticollision UID detection and PICC_REQALL (WUPA) fallback.
        Returns: (rfid_key, card_text) or None if no card is present.
        """
        if self.simulation or self.reader is None:
            return None

        # Cross-process non-blocking file lock so run.py and web services share SPI cleanly
        lock_fd = None
        if fcntl and os.name != "nt":
            try:
                lock_fd = open(LOCK_PATH, "w")
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, OSError):
                # Lock held by another process; yield immediately
                if lock_fd:
                    try:
                        lock_fd.close()
                    except Exception:
                        pass
                return None

        try:
            # 1. Fast UID read without slow block authentication
            card_id = self.reader.read_id_no_block()

            # 2. If no card via REQIDL, try WUPA (PICC_REQALL) for cards in HALT state
            if card_id is None:
                try:
                    m = self.reader.READER
                    (status, _) = m.MFRC522_Request(m.PICC_REQALL)
                    if status == m.MI_OK:
                        (status, uid) = m.MFRC522_Anticoll()
                        if status == m.MI_OK:
                            card_id = self.reader.uid_to_num(uid)
                except Exception:
                    pass

            if card_id is not None:
                rfid_key = str(card_id).strip()
                logger.info("RFID card detected: UID=%s", rfid_key)
                return rfid_key, ""
        except Exception as e:
            logger.debug("Error in read_card_nonblocking: %s", e)
        finally:
            if lock_fd:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    lock_fd.close()
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
