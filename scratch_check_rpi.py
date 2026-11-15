import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.1.52', username='book', password='book')

test_code = '''
from config.settings import is_raspberry_pi, SIMULATION_MODE
import os
print("IS_RPI:", is_raspberry_pi())
print("SIMULATION_MODE:", SIMULATION_MODE)
'''
sftp = client.open_sftp()
with sftp.file('/home/book/Desktop/DigiBook/test_rpi_check.py', 'w') as f:
    f.write(test_code)
sftp.close()

stdin, stdout, stderr = client.exec_command("/home/book/Desktop/DigiBook/venv/bin/python /home/book/Desktop/DigiBook/test_rpi_check.py")
print(stdout.read().decode())
err = stderr.read().decode()
if err:
    print("ERR:", err)
client.close()
