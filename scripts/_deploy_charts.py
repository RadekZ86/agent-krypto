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
    "app/main.py",
    "app/static/app.js",
    "app/static/styles.css",
    "app/templates/index.html",
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
print("Restart sent, waiting 5s...")
time.sleep(5)

# Verify main page
cmd = 'curl -s -o /dev/null -w "HTTP %{http_code}" http://127.0.0.1:12345/'
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
code = stdout.read().decode().strip()
print(f"Main page: {code}")

# Verify leverage chart endpoint
cmd2 = 'curl -s -o /dev/null -w "HTTP %{http_code}" http://127.0.0.1:12345/api/leverage/chart/BTC'
stdin2, stdout2, stderr2 = ssh.exec_command(cmd2, timeout=30)
code2 = stdout2.read().decode().strip()
print(f"Leverage chart BTC: {code2}")

# Check content
cmd3 = 'curl -s http://127.0.0.1:12345/api/leverage/chart/BTC | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\\"klines: {len(d.get(\'klines\',[]))}, markers: {len(d.get(\'markers\',[]))}, positions: {len(d.get(\'positions\',[]))}, funding: {d.get(\'funding_rate_pct\',0)}\\")"'
stdin3, stdout3, stderr3 = ssh.exec_command(cmd3, timeout=30)
out3 = stdout3.read().decode().strip()
err3 = stderr3.read().decode().strip()
print(f"Chart data: {out3}")
if err3:
    print(f"Err: {err3}")

ssh.close()
print("Done")
