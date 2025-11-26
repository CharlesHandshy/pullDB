# pullDB Service Operations Guide

> **Quick Reference for System Administrators**
>
> This document covers day-to-day operations of the pullDB service installed at `/opt/pulldb.service`.

## Table of Contents

- [Service Management](#service-management)
- [Configuration](#configuration)
- [Directory Structure](#directory-structure)
- [Log Management](#log-management)
- [Troubleshooting](#troubleshooting)
- [Maintenance](#maintenance)

---

## Service Management

### Starting the Service

```bash
sudo systemctl start pulldb-worker
```

### Stopping the Service

```bash
sudo systemctl stop pulldb-worker
```

### Restarting the Service

```bash
sudo systemctl restart pulldb-worker
```

### Checking Service Status

```bash
sudo systemctl status pulldb-worker
```

### Enable Auto-Start on Boot

```bash
sudo systemctl enable pulldb-worker
```

### Disable Auto-Start on Boot

```bash
sudo systemctl disable pulldb-worker
```

### Reset Failed State

If the service has failed too many times and won't restart:

```bash
sudo systemctl reset-failed pulldb-worker
sudo systemctl start pulldb-worker
```

---

## Configuration

### Environment File

The service configuration is stored in `/opt/pulldb.service/.env`:

```bash
# View current configuration
sudo cat /opt/pulldb.service/.env

# Edit configuration
sudo nano /opt/pulldb.service/.env
```

### Key Configuration Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `PULLDB_COORDINATION_SECRET` | AWS Secrets Manager path for MySQL credentials | `aws-secretsmanager:/pulldb/mysql/coordination-db` |
| `PULLDB_AWS_PROFILE` | AWS CLI profile (leave empty for instance profile) | `pr-prod` |
| `PULLDB_LOG_DIR` | Directory for log files | `/mnt/data/logs/pulldb.service` |
| `PULLDB_WORK_DIR` | Directory for temporary work files | `/mnt/data/work/pulldb.service` |
| `PULLDB_LOG_LEVEL` | Logging verbosity | `INFO`, `DEBUG`, `WARNING`, `ERROR` |
| `AWS_DEFAULT_REGION` | AWS region | `us-east-1` |

### Systemd Unit File

The systemd unit file is located at `/etc/systemd/system/pulldb-worker.service`.

After modifying the unit file:

```bash
sudo systemctl daemon-reload
sudo systemctl restart pulldb-worker
```

---

## Directory Structure

```
/opt/pulldb.service/
├── .env                    # Service configuration
├── .aws/                   # AWS config directory (for service user)
├── AWS-SETUP.md            # AWS configuration guide
├── SERVICE-README.md       # This file
├── dist/                   # Python wheel package
├── logs/                   # Default log directory (if not overridden)
├── scripts/                # Management scripts
│   ├── install_pulldb.sh
│   ├── uninstall_pulldb.sh
│   ├── upgrade_pulldb.sh
│   ├── configure_server.sh
│   ├── monitor_jobs.py
│   └── pulldb-worker.service
├── venv/                   # Python virtual environment
│   └── bin/
│       ├── pulldb          # CLI tool
│       └── pulldb-worker   # Worker daemon
└── work/                   # Default work directory (if not overridden)

/usr/share/doc/pulldb/      # Documentation
├── README.md
├── AWS-SETUP.md
├── SERVICE-README.md
└── copyright
```

---

## Log Management

### View Live Logs

```bash
# Follow logs in real-time
sudo journalctl -u pulldb-worker -f

# Follow logs with cleaner output
sudo journalctl -u pulldb-worker -f -o cat
```

### View Recent Logs

```bash
# Last 50 lines
sudo journalctl -u pulldb-worker -n 50 --no-pager

# Last hour
sudo journalctl -u pulldb-worker --since "1 hour ago"

# Today's logs
sudo journalctl -u pulldb-worker --since today
```

### View Logs for a Specific Time Range

```bash
sudo journalctl -u pulldb-worker --since "2025-11-26 00:00:00" --until "2025-11-26 12:00:00"
```

### Export Logs to File

```bash
sudo journalctl -u pulldb-worker --since today > /tmp/pulldb-logs.txt
```

### Log Format

Logs are JSON-formatted for easy parsing:

```json
{
  "timestamp": "2025-11-26 01:50:25,123",
  "level": "INFO",
  "logger": "pulldb.worker",
  "message": "Worker started",
  "phase": "startup"
}
```

---

## Troubleshooting

### Service Won't Start

**Symptom**: `systemctl start pulldb-worker` fails immediately.

**Diagnosis**:
```bash
# Check status and recent logs
sudo systemctl status pulldb-worker
sudo journalctl -u pulldb-worker -n 30 --no-pager
```

**Common Causes**:

1. **Missing `aws-secretsmanager:` prefix in credential reference**
   ```
   Failed to resolve coordination secret: Unsupported credential reference format
   ```
   **Fix**: Edit `/opt/pulldb.service/.env` and ensure the secret has the proper prefix:
   ```
   PULLDB_COORDINATION_SECRET=aws-secretsmanager:/pulldb/mysql/coordination-db
   ```

2. **AWS credentials not available**
   ```
   Unable to locate credentials
   ```
   **Fix**: Ensure EC2 instance profile is attached or `PULLDB_AWS_PROFILE` is set correctly.

3. **MySQL connection failed**
   ```
   Access denied for user 'root'@'localhost'
   ```
   **Fix**: Verify the secret in AWS Secrets Manager contains correct MySQL credentials.

4. **Directory permissions**
   ```
   Permission denied: '/mnt/data/logs/pulldb.service'
   ```
   **Fix**: Ensure directories are owned by `pulldb_service`:
   ```bash
   sudo chown -R pulldb_service:pulldb_service /mnt/data/logs/pulldb.service
   sudo chown -R pulldb_service:pulldb_service /mnt/data/work/pulldb.service
   ```

### Service Keeps Restarting

**Symptom**: Service starts but crashes repeatedly.

**Diagnosis**:
```bash
# Check restart count
sudo systemctl status pulldb-worker

# View crash logs
sudo journalctl -u pulldb-worker -p err -n 50
```

**Common Causes**:

1. **Invalid configuration** - Check `.env` file syntax
2. **Database unavailable** - Verify MySQL is running and accessible
3. **Out of disk space** - Check `PULLDB_WORK_DIR` has sufficient space

### Service Stuck / Not Processing Jobs

**Symptom**: Service is running but jobs are not being processed.

**Diagnosis**:
```bash
# Check for ERROR level logs
sudo journalctl -u pulldb-worker -p err --since "1 hour ago"

# Check worker activity
sudo journalctl -u pulldb-worker --since "10 minutes ago" | grep -i "poll\|job\|processing"
```

**Common Causes**:

1. **S3 access denied** - Verify IAM permissions for S3 bucket
2. **Job stuck in `running` state** - May need manual intervention in database
3. **Disk full** - Check work directory space

### AWS Credential Issues

**Symptom**: `AccessDeniedException` or `Unable to locate credentials`

**Diagnosis**:
```bash
# Test as pulldb_service user
sudo -u pulldb_service aws sts get-caller-identity

# Check if instance profile is available
curl -s http://169.254.169.254/latest/meta-data/iam/security-credentials/
```

**Solutions**:

1. **Instance Profile**: Ensure EC2 instance has `pulldb-instance-profile` attached
2. **Named Profile**: Set `PULLDB_AWS_PROFILE` in `.env` and ensure `~pulldb_service/.aws/credentials` exists
3. **Region**: Ensure `AWS_DEFAULT_REGION=us-east-1` is set

### Secrets Manager Access Denied

**Symptom**: `AccessDeniedException when calling the GetSecretValue operation`

**Diagnosis**:
```bash
# Test secret access
sudo -u pulldb_service aws secretsmanager get-secret-value \
    --secret-id /pulldb/mysql/coordination-db \
    --query SecretString --output text
```

**Solutions**:

1. Verify secret exists in AWS Secrets Manager
2. Check IAM role has `secretsmanager:GetSecretValue` permission
3. Ensure secret is in the correct AWS account/region

---

## Maintenance

### Upgrading pullDB

Using the upgrade script:
```bash
sudo /opt/pulldb.service/scripts/upgrade_pulldb.sh /path/to/new/pulldb-0.0.2-py3-none-any.whl
```

Using apt (if new .deb available):
```bash
sudo apt update
sudo apt upgrade pulldb
```

### Checking Python Environment

```bash
# List installed packages
/opt/pulldb.service/venv/bin/pip list

# Check pulldb version
/opt/pulldb.service/venv/bin/pulldb --version

# Test import
/opt/pulldb.service/venv/bin/python3 -c "import pulldb; print(pulldb.__version__)"
```

### Testing Credential Resolution

```bash
/opt/pulldb.service/venv/bin/python3 << 'EOF'
from pulldb.infra.secrets import CredentialResolver

resolver = CredentialResolver()
creds = resolver.resolve('aws-secretsmanager:/pulldb/mysql/coordination-db')
print(f"✅ Host: {creds.host}")
print(f"✅ User: {creds.username}")
print(f"✅ Port: {creds.port}")
EOF
```

### Uninstalling

Using apt:
```bash
sudo apt remove pulldb      # Keep config files
sudo apt purge pulldb       # Remove everything
```

Manual cleanup:
```bash
sudo systemctl stop pulldb-worker
sudo systemctl disable pulldb-worker
sudo rm -f /etc/systemd/system/pulldb-worker.service
sudo systemctl daemon-reload
sudo rm -rf /opt/pulldb.service
sudo userdel pulldb_service
sudo groupdel pulldb_service
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Start service | `sudo systemctl start pulldb-worker` |
| Stop service | `sudo systemctl stop pulldb-worker` |
| Restart service | `sudo systemctl restart pulldb-worker` |
| Check status | `sudo systemctl status pulldb-worker` |
| View live logs | `sudo journalctl -u pulldb-worker -f` |
| View recent logs | `sudo journalctl -u pulldb-worker -n 50` |
| Edit config | `sudo nano /opt/pulldb.service/.env` |
| Reset failed | `sudo systemctl reset-failed pulldb-worker` |
| Test credentials | `/opt/pulldb.service/venv/bin/python3 -c "from pulldb.infra.secrets import CredentialResolver; print(CredentialResolver().resolve('aws-secretsmanager:/pulldb/mysql/coordination-db'))"` |

---

## Support

- **AWS Setup Guide**: `/opt/pulldb.service/AWS-SETUP.md` or `/usr/share/doc/pulldb/AWS-SETUP.md`
- **Project Documentation**: `/usr/share/doc/pulldb/README.md`

---

**Version**: 0.0.1
**Last Updated**: November 26, 2025
