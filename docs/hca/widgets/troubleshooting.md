# pullDB Troubleshooting Guide

> **Solutions for common issues and error messages**
>
> This guide covers service startup failures, connectivity issues, restore errors,
> and operational problems with pullDB.

## Table of Contents

- [Service Issues](#service-issues)
- [Authentication Issues](#authentication-issues)
- [Job/Restore Issues](#jobrestore-issues)
- [AWS/S3 Issues](#awss3-issues)
- [MySQL Issues](#mysql-issues)
- [Client/CLI Issues](#clientcli-issues)
- [Log Locations](#log-locations)
- [Health Checks](#health-checks)

---

## Service Issues

### Service Fails to Start

#### Symptom
```
systemctl status pulldb-web
● pulldb-web.service - pullDB Web UI Service
   Active: failed (Result: exit-code)
```

#### Check the logs
```bash
sudo journalctl -u pulldb-web -n 50 --no-pager
```

### Port Binding: Permission Denied

#### Symptom
```
ERROR: [Errno 13] error while attempting to bind on address ('0.0.0.0', 80): permission denied
```

#### Cause
Binding to ports below 1024 requires root or special capabilities.

#### Solution
Add `CAP_NET_BIND_SERVICE` capability to the service:

```bash
# Create override file
sudo mkdir -p /etc/systemd/system/pulldb-web.service.d

echo -e "[Service]\nAmbientCapabilities=CAP_NET_BIND_SERVICE" | \
    sudo tee /etc/systemd/system/pulldb-web.service.d/override.conf

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart pulldb-web
```

#### Alternative
Use port 8000 instead (recommended for non-production):

```bash
# In .env
PULLDB_WEB_PORT=8000
```

### Port Already in Use

#### Symptom
```
ERROR: [Errno 98] Address already in use
```

#### Solution
```bash
# Find what's using the port
sudo ss -tlnp | grep :8000

# Kill the process or choose a different port
sudo kill <PID>
# or
export PULLDB_WEB_PORT=8001
```

### Service Restart Loop

#### Symptom
```
Start request repeated too quickly
Failed with result 'exit-code'
```

#### Cause
Service is crashing repeatedly. Check for:
- Configuration errors
- Missing dependencies
- Database connection failures

#### Solution
```bash
# Reset the failure counter
sudo systemctl reset-failed pulldb-web

# Check detailed logs
sudo journalctl -u pulldb-web --since "5 minutes ago"

# Try starting manually for better error output
/opt/pulldb.service/venv/bin/pulldb-web
```

---

## Authentication Issues

### "Session Expired"

#### Symptom
Redirected to login page with "Session expired" message.

#### Cause
Session token has exceeded its TTL (default 24 hours).

#### Solution
Login again. To extend session duration:

```bash
# In .env
PULLDB_SESSION_TTL_HOURS=168  # 7 days
```

### "Invalid username or password"

#### Checklist
1. Username is case-sensitive
2. Account is not disabled
3. Password hasn't been force-reset by admin

#### Verify account status
```bash
pulldb-admin users show <username>
```

### CLI: "401 Unauthorized"

#### Symptom
```
Error: 401 Unauthorized - Authentication required
```

#### Cause
- `PULLDB_AUTH_MODE=session` but CLI sending header
- User doesn't exist in database

#### Solution
```bash
# Check auth mode
grep AUTH_MODE /opt/pulldb.service/.env

# If session mode, use login:
pulldb login

# Or register if new user:
pulldb register
```

---

## Job/Restore Issues

### Job Stuck in "queued"

#### Symptom
Job stays in `queued` status indefinitely.

#### Checklist
1. **Worker running?**
   ```bash
   sudo systemctl status pulldb-worker@1
   ```

2. **Worker polling?** Check logs:
   ```bash
   sudo journalctl -u pulldb-worker@1 -f
   ```

3. **Database connection?**
   ```bash
   mysql -u pulldb_worker -p pulldb_service -e "SELECT COUNT(*) FROM jobs WHERE status='queued'"
   ```

### Job Failed: "Download failed"

#### Symptom
```
Status: failed
Error: Download failed: Access Denied
```

#### Cause
S3 permissions issue.

#### Solution
```bash
# Test S3 access
aws s3 ls s3://bucket/path/ --profile pr-staging

# Verify IAM role
aws sts get-caller-identity
```

See [AWS/S3 Issues](#awss3-issues) for more details.

### Job Failed: "myloader failed"

#### Symptom
```
Error: myloader failed with exit code 1
```

#### Check myloader logs
```bash
cat /opt/pulldb.service/work/<job_id>/myloader.log
```

#### Common causes
1. **Disk space**: Check `/opt/pulldb.service/work/`
2. **MySQL permissions**: Verify `pulldb_loader` grants
3. **Corrupt backup**: Try a different backup date

### Job Failed: "Target database exists"

#### Symptom
```
Error: Target database 'cust_12345' already exists and overwrite=false
```

#### Solution
Either:
- Set `overwrite=true` in job request
- Use a suffix: `pulldb restore acme --suffix=b`
- Drop the existing database manually

### Cancel Not Working

#### Symptom
Job shows "cancel requested" but keeps running.

#### Cause
Job is in a non-interruptible operation (e.g., myloader).

#### Expected behavior
- **Queued jobs**: Cancel immediately
- **Running jobs**: Complete current phase, then stop
- Cancel may take up to 30 seconds to take effect

---

## AWS/S3 Issues

### "Access Denied" on S3

#### Symptom
```
botocore.exceptions.ClientError: An error occurred (AccessDenied)
```

#### Checklist
1. **Instance profile attached?**
   ```bash
   curl -s http://169.254.169.254/latest/meta-data/iam/security-credentials/
   ```

2. **Correct bucket policy?**
   ```bash
   aws s3api get-bucket-policy --bucket <bucket>
   ```

3. **Cross-account role?**
   - Check trust policy includes your account
   - Verify external ID matches

### "Unable to locate credentials"

#### Symptom
```
botocore.exceptions.NoCredentialsError: Unable to locate credentials
```

#### For Service
```bash
# Verify instance profile
aws sts get-caller-identity
# Should show: assumed-role/pulldb-ec2-service-role/...
```

#### For Developer
```bash
# Check profile exists
cat ~/.aws/credentials | grep pr-dev

# Test profile
aws sts get-caller-identity --profile pr-dev
```

### Secrets Manager: "AccessDeniedException"

#### Symptom
```
AccessDeniedException when calling GetSecretValue
```

#### Solution
```bash
# Verify secret exists
aws secretsmanager describe-secret --secret-id /pulldb/mysql/api

# Check IAM policy allows GetSecretValue
aws iam get-role-policy --role-name pulldb-ec2-service-role \
    --policy-name pulldb-secrets-manager-access
```

---

## MySQL Issues

### "Can't connect to MySQL server"

#### Symptom
```
Error: Can't connect to MySQL server on 'localhost' (111)
```

#### Checklist
```bash
# MySQL running?
sudo systemctl status mysql

# Socket exists?
ls -la /var/run/mysqld/mysqld.sock

# Test connection
mysql -u pulldb_api -p -e "SELECT 1"
```

### "Access denied for user"

#### Symptom
```
Access denied for user 'pulldb_api'@'localhost'
```

#### Cause
- Wrong password in Secrets Manager
- User doesn't exist
- Missing grants

#### Solution
```bash
# Verify password in Secrets Manager matches MySQL
aws secretsmanager get-secret-value \
    --secret-id /pulldb/mysql/api \
    --query SecretString --output text

# Test with that password
mysql -u pulldb_api -p'<password>' pulldb_service
```

### "Lock wait timeout exceeded"

#### Symptom
```
Lock wait timeout exceeded; try restarting transaction
```

#### Cause
Another process is holding a lock on the table.

#### Solution
```bash
# Find blocking queries
mysql -e "SHOW PROCESSLIST" | grep -v Sleep

# Kill blocking process if safe
mysql -e "KILL <process_id>"
```

---

## Client/CLI Issues

### Python Version Error (Ubuntu 20.04)

#### Symptom
```
python3.12: command not found
```

#### Cause
Ubuntu 20.04 ships with Python 3.8. deadsnakes PPA no longer supports Ubuntu 20.04.

#### Solution: Build Python 3.12 from source

```bash
# Install build dependencies
sudo apt-get install -y build-essential zlib1g-dev libncurses5-dev \
    libgdbm-dev libnss3-dev libssl-dev libreadline-dev libffi-dev \
    libsqlite3-dev wget libbz2-dev

# Download and build
cd /tmp
wget https://www.python.org/ftp/python/3.12.4/Python-3.12.4.tgz
tar -xf Python-3.12.4.tgz
cd Python-3.12.4
./configure --enable-optimizations --prefix=/usr/local
make -j$(nproc)
sudo make altinstall

# Verify
python3.12 --version
```

Then install the client package:
```bash
sudo dpkg -i pulldb-client_*.deb
```

### dpkg Lock Error During Install

#### Symptom
```
E: Could not get lock /var/lib/dpkg/lock-frontend
```

#### Cause
- Another package manager is running
- System is auto-updating

#### Solution
```bash
# Wait for other process to finish
sudo lsof /var/lib/dpkg/lock-frontend

# Or if safe to interrupt
sudo kill <PID>
sudo dpkg --configure -a
```

### CLI: "Connection refused"

#### Symptom
```
Error: Connection refused - http://localhost:8000
```

#### Checklist
1. **Service running?**
   ```bash
   sudo systemctl status pulldb-api pulldb-web
   ```

2. **Correct URL?**
   ```bash
   echo $PULLDB_API_URL
   # Should be http://server:8000 or http://server:8080
   ```

3. **Firewall?**
   ```bash
   sudo ufw status
   sudo iptables -L -n | grep 8000
   ```

---

## Log Locations

| Component | Log Location | Command |
|-----------|-------------|---------|
| API Service | journald | `sudo journalctl -u pulldb-api -f` |
| Web Service | journald | `sudo journalctl -u pulldb-web -f` |
| Worker | journald | `sudo journalctl -u pulldb-worker@1 -f` |
| Application | File | `tail -f /var/log/pulldb/pulldb.log` |
| myloader | Job dir | `cat /opt/pulldb.service/work/<job_id>/myloader.log` |
| nginx | File | `tail -f /var/log/nginx/access.log` |

### Increasing Log Verbosity

```bash
# In .env
PULLDB_LOG_LEVEL=DEBUG

# Restart services
sudo systemctl restart pulldb-api pulldb-web pulldb-worker@1
```

---

## Health Checks

### Quick Health Check

```bash
# API health
curl -s http://localhost:8000/api/health
# {"status": "ok"}

# System status
curl -s http://localhost:8000/api/status
# {"queue_depth": 0, "active_restores": 0, "service": "api"}
```

### Full System Check

```bash
# Check all services
for svc in pulldb-api pulldb-web pulldb-worker@1; do
    echo "=== $svc ==="
    sudo systemctl is-active $svc
done

# Check MySQL
mysql -u pulldb_api -p -e "SELECT COUNT(*) as jobs FROM jobs"

# Check S3 access
aws s3 ls s3://pestroutesrdsdbs/daily/stg/ | head -1

# Check Secrets Manager
aws secretsmanager get-secret-value --secret-id /pulldb/mysql/api \
    --query SecretString --output text | jq -r '.host'
```

### Service Recovery

If things are badly broken:

```bash
# Stop everything
sudo systemctl stop pulldb-api pulldb-web pulldb-worker@{1,2,3}

# Clear work directory (optional, loses in-progress jobs)
sudo rm -rf /opt/pulldb.service/work/*

# Restart services
sudo systemctl start pulldb-api pulldb-web pulldb-worker@1
```

---

## Getting Help

If you're still stuck:

1. **Check logs** with DEBUG level
2. **Search existing docs** - many issues are covered
3. **File an issue** with:
   - Error message (full text)
   - Log output (relevant section)
   - Steps to reproduce
   - Environment (Ubuntu version, Python version)

---

## See Also

- [AWS Setup Guide](../AWS-SETUP.md) - AWS configuration
- [Security Model](../widgets/security.md) - Authentication details
- [Runbook: Failure Handling](../widgets/runbook-failure.md) - Operational recovery
