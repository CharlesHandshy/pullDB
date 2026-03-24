# Production Bare-Metal Routing Setup

> **Scope:** nginx domain-based virtual hosting for a shared bare-metal development server
> in the `us-east-1` internal network. Each service gets its own subdomain rather than a
> port or query parameter. This document covers the nginx structure and the DNS naming
> convention — individual service configuration lives in its own file under
> `sites-available/`.

---

> **Contrast with dev box:** The [dev box setup](DEV-BOX-ROUTING-SETUP.md) uses a single
> port (`8000`) and routes prod vs. dev via a `?be=` query parameter. On bare metal we use
> domain names instead — each service has a dedicated subdomain and nginx selects the
> upstream by `server_name`.

---

## Naming Convention

```
<service>.dev.use1.pestroutes.local
```

| Part | Meaning |
|------|---------|
| `<service>` | Service identifier (e.g. `pulldb`, `services`) |
| `dev` | Environment tier |
| `use1` | AWS region shorthand — us-east-1 |
| `pestroutes.local` | Internal DNS domain |

---

## Planned Services

| Domain | Purpose |
|--------|---------|
| `services.dev.use1.pestroutes.local` | Directory — lists all services available on this host |
| `pulldb.dev.use1.pestroutes.local` | pullDB restore service |

Add a new `sites-available/<service>.conf` for each service added to the host.

---

## nginx Structure

```
/etc/nginx/
├── nginx.conf                          # main config — includes sites-enabled/*
├── sites-available/
│   ├── services.conf                   # service directory
│   └── pulldb.conf                     # pullDB
└── sites-enabled/
    ├── services.conf -> ../sites-available/services.conf
    └── pulldb.conf   -> ../sites-available/pulldb.conf
```

No shared map blocks are needed — routing is purely by `server_name`, so each file is
self-contained.

---

## TLS

All services share the same self-signed wildcard-style certificate, or each gets its own.
The simplest approach on an internal host is a single cert covering all `*.dev.use1.pestroutes.local` SANs generated once:

```bash
openssl req -x509 \
    -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
    -nodes \
    -keyout /etc/nginx/tls/dev.use1.pestroutes.local.key \
    -out    /etc/nginx/tls/dev.use1.pestroutes.local.crt \
    -days 3650 \
    -subj "/CN=*.dev.use1.pestroutes.local/O=PestRoutes" \
    -addext "subjectAltName=DNS:*.dev.use1.pestroutes.local,DNS:services.dev.use1.pestroutes.local,DNS:pulldb.dev.use1.pestroutes.local"

chmod 600 /etc/nginx/tls/dev.use1.pestroutes.local.key
```

Reference these paths in every `server` block.

---

## Site Configs

### `sites-available/pulldb.conf`

> **1.3.1+ note:** pullDB will serve web and API on a single port. Only one upstream and
> one `proxy_pass` are needed. The API will be available at `/api/v1/...` on the same
> domain. Prior to 1.3.1, proxy the web port and API port separately if needed.

```nginx
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name pulldb.dev.use1.pestroutes.local;

    ssl_certificate     /etc/nginx/tls/dev.use1.pestroutes.local.crt;
    ssl_certificate_key /etc/nginx/tls/dev.use1.pestroutes.local.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    server_tokens       off;

    location / {
        proxy_pass          https://127.0.0.1:8000;   # pullDB (web + API on single port, 1.3.1+)
        proxy_ssl_verify    off;
        proxy_set_header    Host              $http_host;
        proxy_set_header    X-Real-IP         $remote_addr;
        proxy_set_header    X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header    X-Forwarded-Proto https;
        proxy_read_timeout  60s;
        proxy_buffering     off;
    }
}

# Redirect plain HTTP to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name pulldb.dev.use1.pestroutes.local;
    return 301 https://$host$request_uri;
}
```

### `sites-available/services.conf`

A lightweight landing page listing the services on this host. Can be a static HTML file
served by nginx directly, or a small app.

```nginx
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
```

Minimal `/var/www/services/index.html` example:

```html
<!DOCTYPE html>
<html>
<head><title>Dev Services — us-east-1</title></head>
<body>
  <h1>Dev Services (use1)</h1>
  <ul>
    <li><a href="https://pulldb.dev.use1.pestroutes.local">pullDB</a> — database restore tool</li>
  </ul>
</body>
</html>
```

---

## DNS

These domains must resolve to the bare-metal host IP on the internal network. Options:

**Option A — Internal DNS (preferred)**
Add A records in Route 53 Private Hosted Zone or the internal DNS server:
```
pulldb.dev.use1.pestroutes.local    A  <host-private-ip>
services.dev.use1.pestroutes.local  A  <host-private-ip>
```

**Option B — `/etc/hosts` on each client machine (quick and dirty)**
```
<host-private-ip>  pulldb.dev.use1.pestroutes.local
<host-private-ip>  services.dev.use1.pestroutes.local
```

---

## Adding a New Service

1. Deploy the service on the host (any internal port — not 443/80).
2. Add `<service>.dev.use1.pestroutes.local` to DNS.
3. Create `/etc/nginx/sites-available/<service>.conf` following the pulldb template above.
4. Enable it: `sudo ln -s /etc/nginx/sites-available/<service>.conf /etc/nginx/sites-enabled/`
5. Add the SAN to the TLS cert (or regenerate it).
6. Reload nginx: `sudo systemctl reload nginx`
7. Add an entry to `/var/www/services/index.html`.

---

## Files on the Host

| Path | Purpose |
|------|---------|
| `/etc/nginx/sites-available/pulldb.conf` | pullDB virtual host |
| `/etc/nginx/sites-available/services.conf` | Service directory virtual host |
| `/etc/nginx/tls/dev.use1.pestroutes.local.crt` | Shared TLS certificate |
| `/etc/nginx/tls/dev.use1.pestroutes.local.key` | Shared TLS private key |
| `/var/www/services/index.html` | Service directory page |
