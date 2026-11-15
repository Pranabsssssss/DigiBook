import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.1.52', username='book', password='book')

test_code = '''
import time
from mfrc522 import MFRC522

def patched_ToCard(self, command, sendData):
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
        # CORRECT LOGIC: break if timeout reached or IRQ triggered
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

MFRC522.MFRC522_ToCard = patched_ToCard

m = MFRC522()
# Boost antenna gain to 48dB
m.Write_MFRC522(m.RFCfgReg, 0x07 << 4)
m.AntennaOn()

print("Patched MFRC522_ToCard with correct wait loop!")
print("Firmware 0x%02X. Antenna On: %s" % (m.Read_MFRC522(m.VersionReg), bool(m.Read_MFRC522(m.TxControlReg) & 0x03)))
print("Ready! Polling for 12 seconds. Touch card to reader now...")

start = time.time()
found = False
while time.time() - start < 12:
    status, tag = m.MFRC522_Request(m.PICC_REQALL)
    if status == m.MI_OK:
        status_c, uid = m.MFRC522_Anticoll()
        if status_c == m.MI_OK:
            num = 0
            for byte in uid:
                num = (num << 8) + byte
            print(f"\\n*** CARD DETECTED SUCCESSFULLY! ***\\nRaw UID: {uid}\\nDecimal Key: {num}\\n")
            found = True
            break
    time.sleep(0.05)

if not found:
    print("Test ended: No card was presented during window.")
'''
sftp = client.open_sftp()
with sftp.file('/home/book/Desktop/DigiBook/test_patch_card.py', 'w') as f:
    f.write(test_code)
sftp.close()

stdin, stdout, stderr = client.exec_command("/home/book/Desktop/DigiBook/venv/bin/python /home/book/Desktop/DigiBook/test_patch_card.py")
print(stdout.read().decode())
err = stderr.read().decode()
if err:
    print('ERR:', err)
client.close()
