import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("s84.mydevil.net", 22, "MagicParty", "Radkon123!")

# Check logs
stdin, stdout, stderr = ssh.exec_command("tail -80 /tmp/uvicorn.log")
print(stdout.read().decode())

ssh.close()
