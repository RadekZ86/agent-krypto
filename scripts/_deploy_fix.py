import paramiko, os, time

host = "s84.mydevil.net"
user = "MagicParty"
pw = "Radkon123!"
remote_base = "/usr/home/MagicParty/domains/magicparty.usermd.net/public_python/"
local_base = r"C:\Users\User\Documents\Agent Krypto"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(host, 22, user, pw)
sftp = ssh.open_sftp()

local = os.path.join(local_base, "app", "services", "bybit_market.py")
remote = remote_base + "app/services/bybit_market.py"
sftp.put(local, remote)
print(f"Uploaded: {remote}")

sftp.close()

restart_cmd = (
    'pkill -f "uvicorn app.main" ; sleep 2; '
    "cd /usr/home/MagicParty/domains/magicparty.usermd.net/public_python; "
    "nohup /usr/local/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port 12345 > /tmp/uvicorn.log 2>&1 &"
)
stdin, stdout, stderr = ssh.exec_command(restart_cmd)
print("Restart sent")
time.sleep(4)

stdin2, stdout2, stderr2 = ssh.exec_command(
    'curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:12345/'
)
code = stdout2.read().decode().strip()
print(f"HTTP status: {code}")

ssh.close()
print("Done")
