"""Deploy Bybit integration files to production server."""
import paramiko
import time

HOST = "s84.mydevil.net"
USER = "MagicParty"
PW = "Radkon123!"
REMOTE_BASE = "/usr/home/MagicParty/domains/magicparty.usermd.net/public_python/"

FILES = [
    ("app/services/bybit_api.py", "app/services/bybit_api.py"),
    ("app/main.py", "app/main.py"),
    ("app/static/app.js", "app/static/app.js"),
    ("app/static/styles.css", "app/static/styles.css"),
    ("app/templates/index.html", "app/templates/index.html"),
]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PW)
sftp = ssh.open_sftp()

for local, remote in FILES:
    rp = REMOTE_BASE + remote
    print(f"Uploading {local} -> {rp}")
    sftp.put(local, rp)
    print("  OK")

sftp.close()

# Restart
restart = (
    "pkill -f 'uvicorn app.main' ; sleep 2; "
    "cd /usr/home/MagicParty/domains/magicparty.usermd.net/public_python; "
    "nohup /usr/local/bin/python3 -m uvicorn app.main:app "
    "--host 127.0.0.1 --port 12345 > /tmp/uvicorn.log 2>&1 &"
)
print("Restarting server...")
stdin, stdout, stderr = ssh.exec_command(restart)
stdout.channel.recv_exit_status()
print("Restart sent")

time.sleep(5)

# Health check
stdin2, stdout2, stderr2 = ssh.exec_command(
    'curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:12345/'
)
code = stdout2.read().decode().strip()
print(f"Health check: HTTP {code}")

ssh.close()
print("Done!")
