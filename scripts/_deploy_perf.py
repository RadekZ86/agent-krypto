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

files = [
    "app/services/bybit_market.py",
    "app/services/backtest.py",
    "app/main.py",
]
for f in files:
    local = os.path.join(local_base, f.replace("/", os.sep))
    remote = remote_base + f
    sftp.put(local, remote)
    print(f"Uploaded: {f}")

sftp.close()

restart_cmd = (
    'pkill -f "uvicorn app.main" ; sleep 2; '
    "cd /usr/home/MagicParty/domains/magicparty.usermd.net/public_python; "
    "nohup /usr/local/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port 12345 > /tmp/uvicorn.log 2>&1 &"
)
stdin, stdout, stderr = ssh.exec_command(restart_cmd)
print("Restart sent, waiting 6s...")
time.sleep(6)

# Cold cache test
cmd = 'curl -s -o /dev/null -w "HTTP %{http_code} Time: %{time_total}s" http://127.0.0.1:12345/api/dashboard'
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=300)
out = stdout.read().decode()
print(f"COLD CACHE: {out}")

# Warm cache test
time.sleep(1)
stdin2, stdout2, stderr2 = ssh.exec_command(cmd, timeout=60)
out2 = stdout2.read().decode()
print(f"WARM CACHE: {out2}")

ssh.close()
print("Done")
