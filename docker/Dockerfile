# =============================================================================
# pullDB — self-contained service image
# =============================================================================
# Includes: MySQL 8.0, Python 3.12, pulldb server, myloader, supervisord
#
# Build:
#   make image                     # builds using version from pyproject.toml
#   PULLDB_VERSION=1.3.0 make image
#
# The .deb is extracted (not installed) to skip MySQL-dependent postinst steps.
# All MySQL initialization happens at runtime via entrypoint.sh.
# =============================================================================
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PULLDB_INSTALL_PREFIX=/opt/pulldb.service \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ---------------------------------------------------------------------------
# System packages
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Python 3.12
    software-properties-common \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    # MySQL
    mysql-server \
    default-mysql-client \
    # Process management
    supervisor \
    # TLS / certificates
    openssl \
    ca-certificates \
    # Utilities
    curl \
    jq \
    sudo \
    unzip \
    zstd \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# AWS CLI v2 (awscli package removed from Ubuntu 24.04 apt repos)
# ---------------------------------------------------------------------------
RUN curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/awscliv2.zip /tmp/aws

# ---------------------------------------------------------------------------
# Extract pulldb package contents (skips MySQL-dependent postinst)
# ---------------------------------------------------------------------------
ARG PULLDB_VERSION=1.3.0
COPY pulldb_${PULLDB_VERSION}_amd64.deb /tmp/pulldb.deb
RUN dpkg-deb -x /tmp/pulldb.deb / && rm /tmp/pulldb.deb

# ---------------------------------------------------------------------------
# Python virtual environment
# ---------------------------------------------------------------------------
RUN python3.12 -m venv /opt/pulldb.service/venv \
    && /opt/pulldb.service/venv/bin/pip install --quiet --upgrade pip \
    && /opt/pulldb.service/venv/bin/pip install --quiet \
         /opt/pulldb.service/dist/pulldb-*.whl

# ---------------------------------------------------------------------------
# System user
# ---------------------------------------------------------------------------
RUN addgroup --system pulldb_service \
    && adduser --system --ingroup pulldb_service \
               --home /opt/pulldb.service \
               --shell /usr/sbin/nologin \
               pulldb_service

# ---------------------------------------------------------------------------
# CLI symlinks + pulldb-admin wrapper + sudoers
# ---------------------------------------------------------------------------
RUN ln -sf /opt/pulldb.service/venv/bin/pulldb /usr/local/bin/pulldb \
    && printf '#!/bin/bash\nexec sudo -u pulldb_service /opt/pulldb.service/venv/bin/pulldb-admin "$@"\n' \
         > /usr/local/bin/pulldb-admin \
    && chmod 755 /usr/local/bin/pulldb-admin \
    && printf 'Cmnd_Alias PULLDB_ADMIN = /opt/pulldb.service/venv/bin/pulldb-admin\nALL ALL=(pulldb_service) NOPASSWD: PULLDB_ADMIN\n' \
         > /etc/sudoers.d/pulldb-admin \
    && chmod 440 /etc/sudoers.d/pulldb-admin

# ---------------------------------------------------------------------------
# Container-specific runtime files
# ---------------------------------------------------------------------------
COPY supervisord.conf   /etc/supervisor/conf.d/pulldb.conf
COPY wait-for-mysql.sh  /docker/wait-for-mysql.sh
COPY entrypoint.sh      /entrypoint.sh
COPY pulldb-mysql.cnf   /etc/mysql/conf.d/pulldb.cnf
RUN chmod +x /docker/wait-for-mysql.sh /entrypoint.sh

# ---------------------------------------------------------------------------
# Directory scaffolding (actual data lands on mounted volumes at runtime)
# ---------------------------------------------------------------------------
RUN mkdir -p \
    /mnt/data/logs/pulldb \
    /mnt/data/work/pulldb.service \
    /mnt/data/tmp \
    /opt/pulldb.service/tls \
    && chown -R pulldb_service:pulldb_service /mnt/data /opt/pulldb.service

# ---------------------------------------------------------------------------
# MySQL: point datadir at a location that survives container restarts
# Note: datadir is inside the container layer — use upgrade.sh for migration
# ---------------------------------------------------------------------------
RUN mkdir -p /var/lib/mysql /var/run/mysqld \
    && chown -R mysql:mysql /var/lib/mysql /var/run/mysqld

EXPOSE 8000 8080

VOLUME ["/mnt/data"]

ENTRYPOINT ["/entrypoint.sh"]
