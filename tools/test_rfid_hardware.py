#!/usr/bin/env python3
"""
DigiBook — Interactive RFID Hardware Diagnostic & Tester
Run this tool directly on the Raspberry Pi to test RC522 wiring, antenna, and card detection:
    python3 tools/test_rfid_hardware.py
"""

import os
import sys
import time

# Ensure repository root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    import hardware.rfid  # Applies Python 3.13 transceiver loop patch
    from mfrc522 import SimpleMFRC522, MFRC522
    import RPi.GPIO as GPIO
    GPIO.setwarnings(False)
except ImportError as e:
    print(f"Error importing hardware libraries: {e}")
    print("Please install via: pip install mfrc522 RPi.GPIO spidev")
    sys.exit(1)


def main():
    print("=" * 60)
    print("   DIGIBOOK — RC522 RFID HARDWARE DIAGNOSTIC STUDIO")
    print("=" * 60)

    try:
        m = MFRC522()
    except Exception as e:
        print(f"\n[FATAL] Could not initialize SPI / MFRC522: {e}")
        print("Check that SPI is enabled: sudo raspi-config nonint do_spi 0")
        sys.exit(1)

    # 1. Inspect Firmware Register
    ver = m.Read_MFRC522(m.VersionReg)
    print(f"\n[1] MFRC522 Firmware Register (0x37): 0x{ver:02X}")
    if ver in (0x91, 0x92):
        print("    -> Authentic NXP MFRC522 detected (v1.0 / v2.0). SPI communication is PERFECT.")
    elif ver in (0x82, 0x88, 0x12):
        print(f"    -> Compatible RC522/FM17522 clone detected (0x{ver:02X}). SPI communication is WORKING.")
    elif ver == 0x00:
        print("    -> [ERROR 0x00] No SPI response. Check:")
        print("       - 3.3V Power (Pin 1) & GND (Pin 6)")
        print("       - RST (GPIO 25, Pin 22)")
        sys.exit(1)
    elif ver == 0xFF:
        print("    -> [ERROR 0xFF] SPI bus float (all 1s). Check:")
        print("       - MOSI (Pin 19), MISO (Pin 21), SCK (Pin 23), SDA/SS (Pin 24)")
        sys.exit(1)
    else:
        print(f"    -> Register returned: 0x{ver:02X}")

    # 2. Check Antenna Carrier (13.56 MHz)
    m.Write_MFRC522(m.RFCfgReg, 0x07 << 4)  # 48dB max gain
    m.AntennaOn()
    tx = m.Read_MFRC522(m.TxControlReg)
    antenna_active = bool(tx & 0x03)
    print(f"\n[2] Antenna Status (TxControlReg 0x14): 0x{tx:02X}")
    print(f"    -> RF Carrier (13.56 MHz): {'ON (Active)' if antenna_active else 'OFF'}")
    print(f"    -> Receiver Gain (RFCfgReg): 0x{m.Read_MFRC522(m.RFCfgReg):02X} (48dB Maximum)")

    # 3. Interactive Continuous Card Polling Loop
    print("\n[3] Continuous Card Polling Active...")
    print("    Hold your RFID card or blue keyfob FLAT against the RC522 antenna.")
    print("    (Press Ctrl+C to exit)\n")

    dots = [".  ", ".. ", "...", "   "]
    count = 0

    try:
        while True:
            found = False
            # Try WUPA (Wake-Up All 0x52)
            status, tag_type = m.MFRC522_Request(m.PICC_REQALL)
            if status != m.MI_OK:
                # Try REQIDL (0x26)
                status, tag_type = m.MFRC522_Request(m.PICC_REQIDL)

            if status == m.MI_OK:
                status_c, uid = m.MFRC522_Anticoll()
                if status_c == m.MI_OK and uid:
                    # Calculate standard UID integer
                    num = 0
                    for b in uid:
                        num = (num << 8) + b

                    print(f"\n\n{'*'*50}")
                    print(f"  CARD DETECTED SUCCESSFULLY!")
                    print(f"  Raw UID Bytes : {uid}")
                    print(f"  Decimal UID   : {num}")
                    print(f"  Hex UID       : {''.join(f'{b:02X}' for b in uid[:4])}")
                    print(f"{'*'*50}\n")
                    time.sleep(1.0)
                    continue

            # Animated spinner while waiting
            spin = dots[count % len(dots)]
            sys.stdout.write(f"\r    [Sensor Active] Waiting for RFID card{spin} (Hold tag touching the antenna)")
            sys.stdout.flush()
            count += 1
            time.sleep(0.08)

    except KeyboardInterrupt:
        print("\n\nDiagnostic stopped by user.")
        GPIO.cleanup()


if __name__ == "__main__":
    main()
