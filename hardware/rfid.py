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
    from mfrc522 import SimpleMFRC522
    import RPi.GPIO as GPIO
    RPI_RFID_AVAILABLE = True
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
                        self.reader.READER.SetAntennaGain(0x07 << 4)
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
