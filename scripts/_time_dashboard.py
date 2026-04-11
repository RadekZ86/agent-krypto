import paramiko, time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("s84.mydevil.net", 22, "MagicParty", "Radkon123!")

# Time the dashboard call from the server itself (localhost = no network latency)
cmd = 'time curl -s -o /dev/null -w "HTTP %{http_code} Time: %{time_total}s" http://127.0.0.1:12345/api/dashboard'
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=120)
out = stdout.read().decode()
err = stderr.read().decode()
print("stdout:", out)
print("stderr:", err)

ssh.close()
