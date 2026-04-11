import paramiko, time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("s84.mydevil.net", 22, "MagicParty", "Radkon123!")

# Restart to clear caches
restart_cmd = (
    'pkill -f "uvicorn app.main" ; sleep 2; '
    "cd /usr/home/MagicParty/domains/magicparty.usermd.net/public_python; "
    "nohup /usr/local/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port 12345 > /tmp/uvicorn.log 2>&1 &"
)
ssh.exec_command(restart_cmd)
print("Restarting...")
time.sleep(5)

# Cold cache call
cmd = 'curl -s -o /dev/null -w "HTTP %{http_code} Time: %{time_total}s" http://127.0.0.1:12345/api/dashboard'
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=300)
out = stdout.read().decode()
err = stderr.read().decode()
print(f"COLD CACHE: {out}")

# Warm cache call
time.sleep(1)
stdin2, stdout2, stderr2 = ssh.exec_command(cmd, timeout=60)
out2 = stdout2.read().decode()
print(f"WARM CACHE: {out2}")

ssh.close()
