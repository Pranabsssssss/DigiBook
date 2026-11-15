from config.settings import SIMULATION_MODE
from config.hardware import CAMERA_BACKEND, CAMERA_DEVICE_INDEX, LED_TYPE
from hardware.camera import Camera, normalize_backend
from hardware.detector import IRDetector, LEDDetector
from hardware.transformer import CoordinateTransformer
from hardware.rfid import RFIDReader
from hardware.simulation import SimulatedRFID, SimulatedCamera, SimulatedDetector


def create_hardware(simulation: bool = None):
    """
    Factory function to initialize or simulate hardware components.

    Returns:
        (rfid_reader, camera, detector)
    """
    if simulation is None:
        simulation = SIMULATION_MODE

    if simulation:
        rfid = SimulatedRFID()
        camera = SimulatedCamera()
        detector = IRDetector(led_type=LED_TYPE)
        return rfid, camera, detector
    else:
        rfid = RFIDReader(simulation=False)
        camera = Camera(backend=CAMERA_BACKEND, device_index=CAMERA_DEVICE_INDEX)
        detector = IRDetector(led_type=LED_TYPE)
        return rfid, camera, detector


__all__ = [
    "Camera",
    "IRDetector",
    "LEDDetector",
    "CoordinateTransformer",
    "RFIDReader",
    "SimulatedRFID",
    "SimulatedCamera",
    "SimulatedDetector",
    "create_hardware",
]
