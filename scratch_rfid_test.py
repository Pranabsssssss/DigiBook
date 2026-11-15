import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.1.52', username='book', password='book')

test_code = """import inspect
from mfrc522 import MFRC522

print('=== MFRC522_Anticoll: ===')
print(inspect.getsource(MFRC522.MFRC522_Anticoll))
print('=== MFRC522_Request: ===')
print(inspect.getsource(MFRC522.MFRC522_Request))
"""

sftp = client.open_sftp()
with sftp.file('/tmp/inspect_anticoll.py', 'w') as f:
    f.write(test_code)
sftp.close()

stdin, stdout, stderr = client.exec_command('/home/book/Desktop/DigiBook/venv/bin/python3 /tmp/inspect_anticoll.py')
print("STDOUT:\n", stdout.read().decode())
print("STDERR:\n", stderr.read().decode())
client.close()
