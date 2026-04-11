import paramiko, os, time

HOST = "s84.mydevil.net"
USER = "MagicParty"
PASS = "Radkon123!"
REMOTE = "/usr/home/MagicParty/domains/magicparty.usermd.net/public_python"
LOCAL = r"C:\Users\User\Documents\Agent Krypto"

files = [
    "app/models.py",
    "app/database.py",
    "app/main.py",
    "app/services/binance_api.py",
    "app/services/agent_cycle.py",
    "app/services/ai_advisor.py",
    "app/static/app.js",
    "app/static/styles.css",
    "app/templates/index.html",
]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS)
sftp = ssh.open_sftp()

for f in files:
    local_path = os.path.join(LOCAL, f)
    remote_path = f"{REMOTE}/{f}"
    print(f"Uploading {f} ...")
    sftp.put(local_path, remote_path)
    print(f"  OK -> {remote_path}")

sftp.close()

# Restart uvicorn
restart = (
    "pkill -f 'uvicorn app.main' ; sleep 2 ; "
    f"cd {REMOTE} ; "
    "nohup /usr/local/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port 12345 > /tmp/uvicorn.log 2>&1 &"
)
print("Restarting uvicorn ...")
stdin, stdout, stderr = ssh.exec_command(restart)
time.sleep(5)
print("Checking process ...")
stdin2, stdout2, stderr2 = ssh.exec_command("pgrep -fa uvicorn")
print(stdout2.read().decode())

# Check startup log for errors
stdin3, stdout3, stderr3 = ssh.exec_command("tail -20 /tmp/uvicorn.log")
print("--- LOG ---")
print(stdout3.read().decode())

ssh.close()
print("Deploy complete!")
