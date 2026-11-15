import logging
import time
from typing import Optional, Tuple

logger = logging.getLogger("DigiBook.RFID")

# Conditional import of RC522 / RPi.GPIO
RPI_RFID_AVAILABLE = False
try:
    from mfrc522 import SimpleMFRC522
    import RPi.GPIO as GPIO
    RPI_RFID_AVAILABLE = True
except (ImportError, RuntimeError):
    # RuntimeError occurs on non-Raspberry Pi OS (e.g., "Must be run on a Raspberry Pi")
    pass


class RFIDReader:
    """
    Interface for the RC522 RFID reader.
    Handles SPI communication on Raspberry Pi with fallback protection.
    """

    def __init__(self, simulation: bool = False):
        self.simulation = simulation
        self.reader = None

        if not self.simulation:
            if not RPI_RFID_AVAILABLE:
                logger.warning(
                    "mfrc522 or RPi.GPIO is not available on this platform. "
                    "Falling back to simulation mode for RFID."
                )
                self.simulation = True
            else:
                try:
                    self.reader = SimpleMFRC522()
                    logger.info("RC522 RFID reader initialized successfully on SPI.")
                except Exception as e:
                    logger.error("Failed to initialize RC522 hardware: %s. Falling back to simulation.", e)
                    self.simulation = True

    def wait_for_card(self, timeout: Optional[float] = None) -> Optional[Tuple[str, str]]:
        """
        Block until an RFID card is presented or timeout is reached.
        Returns: (rfid_key, card_text) or None if timeout.
        The card's hardware UID is converted to a string and used as rfid_key.
        """
        if self.simulation:
            return self._simulated_wait_for_card(timeout)

        start_time = time.time()
        while True:
            try:
                card_id, card_text = self.reader.read_no_block()
                if card_id is not None:
                    rfid_key = str(card_id).strip()
                    text = str(card_text).strip() if card_text else ""
                    logger.info("RFID card scanned: UID=%s", rfid_key)
                    return rfid_key, text
            except Exception as e:
                logger.debug("Error during non-blocking RFID read: %s", e)

            if timeout is not None and (time.time() - start_time) >= timeout:
                return None

            time.sleep(0.05)

    def read_card_nonblocking(self) -> Optional[Tuple[str, str]]:
        """
        Non-blocking read attempt. Returns immediately.
        Returns: (rfid_key, card_text) or None if no card is present.
        """
        if self.simulation or self.reader is None:
            return None

        try:
            card_id, card_text = self.reader.read_no_block()
            if card_id is not None:
                rfid_key = str(card_id).strip()
                text = str(card_text).strip() if card_text else ""
                logger.info("RFID card detected: UID=%s", rfid_key)
                return rfid_key, text
        except Exception as e:
            logger.debug("Error in read_card_nonblocking: %s", e)

        return None

    def _simulated_wait_for_card(self, timeout: Optional[float] = None) -> Optional[Tuple[str, str]]:
        """Fallback simulation prompt if accessed directly."""
        from hardware.simulation import SimulatedRFID
        sim = SimulatedRFID()
        return sim.wait_for_card(timeout=timeout)

    def cleanup(self):
        """Clean up GPIO resources."""
        if RPI_RFID_AVAILABLE and not self.simulation:
            try:
                import RPi.GPIO as GPIO
                GPIO.cleanup()
                logger.info("RFID GPIO resources cleaned up.")
            except Exception as e:
                logger.debug("Error during GPIO cleanup: %s", e)
