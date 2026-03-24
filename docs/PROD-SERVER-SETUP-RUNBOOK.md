# Production Server Setup Runbook

> **Audience:** Claude Sonnet 4.6 executing this runbook on a fresh bare-metal or EC2
> instance. Read the entire document before starting. Execute each step in order. Confirm
> each section is healthy before moving to the next.
>
> **What this builds:**
> - Docker + nginx installed and configured on the host
> - nginx routing traffic on port 443 by domain name:
>   - `services.dev.use1.pestroutes.local` → static services landing page
>   - `pulldb.dev.use1.pestroutes.local`   → pullDB 1.2.0 container
> - pullDB 1.2.0 running in Docker with production database restored from backup
>
> **What you need before starting:**
> - The transfer package from `/mnt/data/pulldb-1.2.0-export/` on the old host, copied to
>   this server (suggested: `/opt/pulldb-import/`)
> - SSH/sudo access on the new host
> - The `pullDB` git repository cloned at `/home/<user>/Projects/pullDB`

---

## Pre-flight Checks

Run these first. Do not proceed if any fail.

```bash
# Confirm OS
lsb_release -a

# Confirm sudo works
sudo whoami   # must print: root

# Confirm import package is present
ls -lh /opt/pulldb-import/
# Expected files:
#   pulldb-1.2.0.tar.gz
#   pulldb_service.sql.gz
#   env.blue.example
#   env.service
#   MANIFEST.txt

# Confirm git repo is present
ls ~/Projects/pullDB/compose/docker-compose.yml
```

---

## Step 1 — Install Docker

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

sudo systemctl enable --now docker
sudo docker run --rm hello-world   # must print "Hello from Docker!"
```

---

## Step 2 — Install nginx

```bash
sudo apt-get install -y nginx

# Disable the default site
sudo rm -f /etc/nginx/sites-enabled/default

sudo systemctl enable nginx
sudo nginx -t   # must print: syntax is ok / test is successful
```

---

## Step 3 — Generate the shared TLS certificate

One wildcard-style cert covers all `*.dev.use1.pestroutes.local` subdomains.

```bash
sudo mkdir -p /etc/nginx/tls

sudo openssl req -x509 \
    -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
    -nodes \
    -keyout /etc/nginx/tls/dev.use1.pestroutes.local.key \
    -out    /etc/nginx/tls/dev.use1.pestroutes.local.crt \
    -days 3650 \
    -subj "/CN=*.dev.use1.pestroutes.local/O=PestRoutes" \
    -addext "subjectAltName=\
DNS:*.dev.use1.pestroutes.local,\
DNS:services.dev.use1.pestroutes.local,\
DNS:pulldb.dev.use1.pestroutes.local"

sudo chmod 600 /etc/nginx/tls/dev.use1.pestroutes.local.key
sudo chmod 644 /etc/nginx/tls/dev.use1.pestroutes.local.crt

# Trust it locally so health checks with curl work
sudo cp /etc/nginx/tls/dev.use1.pestroutes.local.crt \
        /usr/local/share/ca-certificates/dev.use1.pestroutes.local.crt
sudo update-ca-certificates
```

---

## Step 4 — Create the services landing page

```bash
sudo mkdir -p /var/www/services

sudo tee /var/www/services/index.html > /dev/null << 'HTML'
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Dev Services — us-east-1</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
           max-width: 640px; margin: 80px auto; padding: 0 24px; color: #1a1a1a; }
    h1   { font-size: 1.4rem; font-weight: 600; margin-bottom: 8px; }
    p    { color: #555; margin-bottom: 32px; font-size: 0.95rem; }
    ul   { list-style: none; padding: 0; }
    li   { margin-bottom: 16px; }
    a    { color: #0070f3; text-decoration: none; font-weight: 500; font-size: 1rem; }
    a:hover { text-decoration: underline; }
    .desc { color: #777; font-size: 0.85rem; margin-top: 2px; }
  </style>
</head>
<body>
  <h1>Dev Services &mdash; us-east-1</h1>
  <p>Internal development tooling. Access from the PestRoutes VPN.</p>
  <ul>
    <li>
      <a href="https://pulldb.dev.use1.pestroutes.local">pullDB</a>
      <div class="desc">Production database restore tool &mdash; MySQL backups from S3</div>
    </li>
  </ul>
</body>
</html>
HTML
```

---

## Step 5 — Write nginx virtual host configs

### `services.dev.use1.pestroutes.local`

```bash
sudo tee /etc/nginx/sites-available/services.conf > /dev/null << 'NGINX'
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name services.dev.use1.pestroutes.local;

    ssl_certificate     /etc/nginx/tls/dev.use1.pestroutes.local.crt;
    ssl_certificate_key /etc/nginx/tls/dev.use1.pestroutes.local.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    server_tokens       off;

    root  /var/www/services;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}

server {
    listen 80;
    listen [::]:80;
    server_name services.dev.use1.pestroutes.local;
    return 301 https://$host$request_uri;
}
NGINX
```

### `pulldb.dev.use1.pestroutes.local`

> **1.3.1+ note:** pullDB will merge web + API onto a single port. When that happens,
> remove the separate `/api` block below and point everything at one upstream port.

```bash
sudo tee /etc/nginx/sites-available/pulldb.conf > /dev/null << 'NGINX'
# pullDB 1.2.0 runs web on container port 8000, API on container port 8080.
# Both are mapped to host ports below (set in /etc/pulldb/.env.pulldb-prod).
upstream pulldb_web { server 127.0.0.1:8000; }
upstream pulldb_api { server 127.0.0.1:8080; }

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name pulldb.dev.use1.pestroutes.local;

    ssl_certificate     /etc/nginx/tls/dev.use1.pestroutes.local.crt;
    ssl_certificate_key /etc/nginx/tls/dev.use1.pestroutes.local.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    server_tokens       off;

    # Web UI
    location / {
        proxy_pass          https://pulldb_web;
        proxy_ssl_verify    off;
        proxy_set_header    Host              $http_host;
        proxy_set_header    X-Real-IP         $remote_addr;
        proxy_set_header    X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header    X-Forwarded-Proto https;
        proxy_read_timeout  60s;
        proxy_buffering     off;
    }

    # API
    location /api/ {
        proxy_pass          https://pulldb_api;
        proxy_ssl_verify    off;
        proxy_set_header    Host              $http_host;
        proxy_set_header    X-Real-IP         $remote_addr;
        proxy_set_header    X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header    X-Forwarded-Proto https;
        proxy_read_timeout  60s;
        proxy_buffering     off;
    }
}

server {
    listen 80;
    listen [::]:80;
    server_name pulldb.dev.use1.pestroutes.local;
    return 301 https://$host$request_uri;
}
NGINX
```

### Enable both sites and reload

```bash
sudo ln -sf /etc/nginx/sites-available/services.conf /etc/nginx/sites-enabled/
sudo ln -sf /etc/nginx/sites-available/pulldb.conf   /etc/nginx/sites-enabled/

sudo nginx -t       # must pass
sudo systemctl reload nginx

# Verify listeners
sudo ss -tlnp | grep nginx   # should show :80 and :443
```

---

## Step 6 — Load the pullDB 1.2.0 Docker image

```bash
sudo docker load < /opt/pulldb-import/pulldb-1.2.0.tar.gz

# Confirm image is present
sudo docker images pulldb
# Expected:
#   REPOSITORY   TAG     IMAGE ID       CREATED        SIZE
#   pulldb       1.2.0   <sha>          <date>         ~1.2GB
```

---

## Step 7 — Configure the pullDB container

```bash
sudo mkdir -p /etc/pulldb /mnt/data/mysql-pulldb-prod

# Write the env file — edit HOST_IP to match this server's internal IP
HOST_IP=$(ip -4 route get 1.1.1.1 | awk '{print $7; exit}')

sudo tee /etc/pulldb/.env.pulldb-prod > /dev/null << EOF
PULLDB_IMAGE=pulldb:1.2.0
CONTAINER_NAME=pulldb-prod
PORT_WEB=8000
PORT_API=8080
HOST_IP=0.0.0.0
PULLDB_MYSQL_DATA_DIR=/mnt/data/mysql-pulldb-prod
EOF

echo "Using HOST_IP: $HOST_IP"
```

Copy the AWS credentials and any service-specific settings from the old
`env.service` in the import package into `/etc/pulldb/.env.pulldb-prod` as needed
(S3 bucket, AWS region, secret manager paths, etc.).

```bash
# Review old env for keys to carry forward
sudo cat /opt/pulldb-import/env.service | grep -v "^#\|^$\|MYSQL_PASSWORD\|MYSQL_SOCKET"
```

---

## Step 8 — Start the container (fresh init)

```bash
sudo docker compose \
  -p pulldb-prod \
  --env-file /etc/pulldb/.env.pulldb-prod \
  -f ~/Projects/pullDB/compose/docker-compose.yml \
  up -d

# Watch init logs — wait for "Starting supervisord..."
sudo docker logs -f pulldb-prod 2>&1 | grep -E "entrypoint|FATAL|ERROR|supervisord"
# Press Ctrl-C once you see "Starting supervisord..."
```

Wait for the container health check to pass:

```bash
until sudo docker inspect pulldb-prod \
  --format '{{.State.Health.Status}}' 2>/dev/null | grep -q "healthy"; do
    echo "Waiting for healthy..."; sleep 5
done
echo "Container is healthy"
```

---

## Step 9 — Restore the production database

```bash
# Restore the dump into the running container
zcat /opt/pulldb-import/pulldb_service.sql.gz \
  | sudo docker exec -i pulldb-prod \
      mysql -S /tmp/mysql.sock pulldb_service

echo "Restore exit code: $?"   # must be 0
```

Restart the container so the entrypoint re-creates MySQL service users
against the restored database:

```bash
sudo docker restart pulldb-prod

# Wait for healthy again
until sudo docker inspect pulldb-prod \
  --format '{{.State.Health.Status}}' 2>/dev/null | grep -q "healthy"; do
    echo "Waiting for healthy..."; sleep 5
done
echo "Container healthy after restart"
```

---

## Step 10 — Verify end-to-end

```bash
# API health through nginx
curl -sk https://pulldb.dev.use1.pestroutes.local/api/health
# Expected: {"status":"ok"}

# Web UI landing page (follow redirect)
curl -skL https://pulldb.dev.use1.pestroutes.local/ -o /dev/null -w "HTTP %{http_code}\n"
# Expected: HTTP 200

# Services page
curl -sk https://services.dev.use1.pestroutes.local/ -o /dev/null -w "HTTP %{http_code}\n"
# Expected: HTTP 200
```

If any check fails, inspect logs:

```bash
sudo docker logs pulldb-prod --tail 50
sudo journalctl -u nginx --no-pager -n 30
```

---

## Step 11 — DNS

Add A records in Route 53 Private Hosted Zone (or `/etc/hosts` on each client):

```
<server-private-ip>  pulldb.dev.use1.pestroutes.local
<server-private-ip>  services.dev.use1.pestroutes.local
```

Get the server's private IP:
```bash
ip -4 route get 1.1.1.1 | awk '{print $7; exit}'
```

---

## Adding Future Services

1. Deploy the service on any internal port (not 80/443).
2. Add `<service>.dev.use1.pestroutes.local` DNS record.
3. Create `/etc/nginx/sites-available/<service>.conf` following the pulldb template.
4. `sudo ln -sf /etc/nginx/sites-available/<service>.conf /etc/nginx/sites-enabled/`
5. Add the SAN to `/etc/nginx/tls/dev.use1.pestroutes.local.crt` (regenerate the cert).
6. `sudo systemctl reload nginx`
7. Add a `<li>` entry to `/var/www/services/index.html`.

---

## Reference

| Path | Purpose |
|------|---------|
| `/etc/pulldb/.env.pulldb-prod` | Container env (image, ports, data dir) |
| `/mnt/data/mysql-pulldb-prod/` | Persistent MySQL data volume |
| `/mnt/data/pulldb-prod/` | Container logs and work directory |
| `/etc/nginx/sites-available/pulldb.conf` | nginx pullDB virtual host |
| `/etc/nginx/sites-available/services.conf` | nginx services directory virtual host |
| `/etc/nginx/tls/` | Shared TLS certificate and key |
| `/var/www/services/index.html` | Services landing page |
| `~/Projects/pullDB/compose/docker-compose.yml` | Docker Compose definition |
| `~/Projects/pullDB/docs/PROD-BAREMETAL-ROUTING-SETUP.md` | nginx architecture reference |
