# Development Box Routing Setup

> **Scope:** This document describes the nginx-based dual-backend routing setup used on a
> pullDB development host. It allows a single external port (8000/8080) to serve both the
> stable production instance and a new candidate release side-by-side, selected via a query
> parameter with cookie stickiness.

---

> **1.3.1 Note:** Starting in 1.3.1, the web UI and API will be served on a **single port**
> (no separate API port). The API will also adopt versioned paths — `/api/v1/...` going
> forward. When setting up a dev box for 1.3.1+, the second nginx server block (port 8080)
> and the `pulldb-api` systemd override can be dropped. The upstream map for the API will
> point to the same upstream as the web block, and all API traffic will flow through port
> 8000 with the same `?be=` cookie routing.

---

## Overview

Two pullDB instances run simultaneously on one host:

| Instance | Version | Process | Web port | API port |
|----------|---------|---------|----------|----------|
| **prod** | 1.2.x (stable) | systemd (`pulldb-web`, `pulldb-api`) | 8002 (internal) | 8082 (internal) |
| **dev**  | 1.3.x (candidate) | Docker (`pulldb-blue`) | 8001 (internal) | 8081 (internal) |

nginx sits in front on the public ports and routes based on a `?be=` query parameter,
persisted in a session cookie so the user does not have to repeat the parameter on every
request.

```
Browser
  └── https://host:8000  (web)    ─┐
  └── https://host:8080  (API)    ─┤  nginx
                                   ├── ?be=dev  or  cookie=dev  ──▶  Docker :8001 / :8081
                                   └── default  or  cookie=prod ──▶  systemd :8002 / :8082
```

---

## Port Map

| Port | Listener | Forwards to |
|------|----------|-------------|
| **8000** | nginx (public) | :8002 (prod) or :8001 (dev) |
| **8001** | docker-proxy | 1.3.x web (direct, bypass nginx) |
| **8002** | pulldb-web systemd | 1.2.x web |
| **8080** | nginx (public) | :8082 (prod) or :8081 (dev) |
| **8081** | docker-proxy | 1.3.x API (direct, bypass nginx) |
| **8082** | pulldb-api systemd | 1.2.x API |

All listeners bind to `0.0.0.0`.

---

## Routing Rules

| Condition | Selected backend |
|-----------|-----------------|
| `?be=dev` in URL | dev (1.3.x) — sets cookie `pulldb_be=dev` |
| `?be=prod` in URL | prod (1.2.x) — sets cookie `pulldb_be=prod` |
| No `?be=` param, cookie `pulldb_be=dev` | dev |
| No `?be=` param, cookie `pulldb_be=prod` | prod |
| No param, no cookie (first visit) | prod (default) |

Cookie: `pulldb_be`, `Path=/`, `HttpOnly`, `Secure`, `SameSite=Lax`.

---

## Setup Steps

### 1. Install nginx

```bash
sudo apt-get install -y nginx
```

### 2. Move stable (1.2.x) services to internal ports

Create systemd overrides so the stable services free up ports 8000/8080 for nginx:

```bash
sudo mkdir -p /etc/systemd/system/pulldb-web.service.d \
              /etc/systemd/system/pulldb-api.service.d

sudo tee /etc/systemd/system/pulldb-web.service.d/port-override.conf > /dev/null <<'EOF'
[Service]
Environment=PULLDB_WEB_PORT=8002
EOF

sudo tee /etc/systemd/system/pulldb-api.service.d/port-override.conf > /dev/null <<'EOF'
[Service]
Environment=PULLDB_API_PORT=8082
EOF

sudo systemctl daemon-reload
sudo systemctl restart pulldb-web pulldb-api
```

### 3. Deploy the candidate release as a Docker container

The Docker container already binds to ports 8001/8081 via `/etc/pulldb/.env.blue`:

```ini
PULLDB_IMAGE=pulldb:1.3.0
CONTAINER_NAME=pulldb-blue
PORT_WEB=8001
PORT_API=8081
HOST_IP=0.0.0.0
```

```bash
sudo docker compose -p pulldb-blue \
  --env-file /etc/pulldb/.env.blue \
  -f /home/charleshandshy/Projects/pullDB/compose/docker-compose.yml \
  up -d
```

### 4. Write the nginx config

Place the following at `/etc/nginx/sites-available/pulldb.conf`:

```nginx
# Map ?be= param to explicit choice
map $arg_be $be_explicit {
    dev     dev;
    prod    prod;
    default "";
}

# Fall through to cookie when param absent
map $be_explicit $be_with_cookie {
    dev     dev;
    prod    prod;
    default $cookie_pulldb_be;
}

# Normalise — unknown/empty → prod
map $be_with_cookie $pulldb_be {
    dev     dev;
    default prod;
}

upstream web_prod { server 127.0.0.1:8002; }
upstream web_dev  { server 127.0.0.1:8001; }
upstream api_prod { server 127.0.0.1:8082; }
upstream api_dev  { server 127.0.0.1:8081; }

map $pulldb_be $web_upstream {
    dev     web_dev;
    default web_prod;
}

map $pulldb_be $api_upstream {
    dev     api_dev;
    default api_prod;
}

# Web UI — port 8000
server {
    listen 8000 ssl;
    listen [::]:8000 ssl;
    server_name _;

    ssl_certificate     /opt/pulldb.service/tls/cert.pem;
    ssl_certificate_key /opt/pulldb.service/tls/key.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    server_tokens       off;

    add_header Set-Cookie "pulldb_be=$pulldb_be; Path=/; HttpOnly; SameSite=Lax; Secure" always;

    location / {
        proxy_pass          https://$web_upstream;
        proxy_ssl_verify    off;
        proxy_set_header    Host              $http_host;
        proxy_set_header    X-Real-IP         $remote_addr;
        proxy_set_header    X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header    X-Forwarded-Proto https;
        proxy_read_timeout  60s;
        proxy_buffering     off;
    }
}

# API — port 8080
server {
    listen 8080 ssl;
    listen [::]:8080 ssl;
    server_name _;

    ssl_certificate     /opt/pulldb.service/tls/cert.pem;
    ssl_certificate_key /opt/pulldb.service/tls/key.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    server_tokens       off;

    add_header Set-Cookie "pulldb_be=$pulldb_be; Path=/; HttpOnly; SameSite=Lax; Secure" always;

    location / {
        proxy_pass          https://$api_upstream;
        proxy_ssl_verify    off;
        proxy_set_header    Host              $http_host;
        proxy_set_header    X-Real-IP         $remote_addr;
        proxy_set_header    X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header    X-Forwarded-Proto https;
        proxy_read_timeout  60s;
        proxy_buffering     off;
    }
}
```

> **Key detail:** Use `$http_host` (not `$host`) so the backend receives the port number in
> the `Host` header. Without the port, uvicorn constructs redirect URLs pointing at port 443
> instead of the public port, breaking post-login redirects.

### 5. Enable the site and start nginx

```bash
sudo ln -sf /etc/nginx/sites-available/pulldb.conf /etc/nginx/sites-enabled/pulldb.conf
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable --now nginx
```

---

## Dependency Pins (pyproject.toml)

The Docker candidate image must pin Starlette below 1.0.0. FastAPI 0.135+ pulls in
Starlette 1.0.0 which removed the old `TemplateResponse(name, context)` call signature
used throughout the pulldb web layer, causing a `TypeError: unhashable type: 'dict'` crash
on every page render.

```toml
"fastapi>=0.110.0,<0.135.0",
"starlette>=0.27.0,<1.0.0",
```

---

## Usage

| Goal | URL |
|------|-----|
| Use prod (default) | `https://host:8000/` |
| Switch to dev | `https://host:8000/?be=dev` |
| Switch back to prod | `https://host:8000/?be=prod` |
| Direct dev access (bypasses nginx) | `https://host:8001/` |
| Direct prod API | `https://host:8082/api/health` |

Cookie stickiness means once you append `?be=dev` once, all subsequent requests in that
browser session stay on dev without the parameter.

---

## Dev Container Admin Credentials

On first boot the entrypoint generates and logs the admin password. If the container
initialized via volume-copy (existing MySQL data directory present), the password must be
set manually:

```bash
PASS=$(head -c 48 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 16)
sudo docker exec pulldb-blue /opt/pulldb.service/venv/bin/python3 -c "
import sys, bcrypt, mysql.connector
h = bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt(rounds=12)).decode()
conn = mysql.connector.connect(unix_socket='/tmp/mysql.sock', database='pulldb_service')
cur = conn.cursor()
cur.execute('SELECT user_id FROM auth_users WHERE username=%s', ('admin',))
row = cur.fetchone()
if row:
    cur.execute('INSERT INTO auth_credentials (user_id, password_hash) VALUES (%s,%s) ON DUPLICATE KEY UPDATE password_hash=%s', (row[0],h,h))
    conn.commit()
cur.close(); conn.close()
print('Done')
" \"\$PASS\"
echo "admin / \$PASS"
```

Change the password after first login.

---

## Files Changed for This Setup

| File | Change |
|------|--------|
| `/etc/nginx/sites-available/pulldb.conf` | New — nginx proxy config |
| `/etc/systemd/system/pulldb-web.service.d/port-override.conf` | New — moves web to :8002 |
| `/etc/systemd/system/pulldb-api.service.d/port-override.conf` | New — moves API to :8082 |
| `/etc/pulldb/.env.blue` | `HOST_IP=0.0.0.0`, `PORT_WEB=8001`, `PORT_API=8081` |
| `pyproject.toml` | Pinned `fastapi<0.135.0`, `starlette<1.0.0` |
