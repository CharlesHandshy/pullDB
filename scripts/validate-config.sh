#!/bin/bash
# Comprehensive configuration validation for pullDB
# Verifies: AWS profile, Parameter Store references, MySQL connectivity, directory readiness.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

if [[ ! -f .env ]]; then
  error ".env not found. Create from .env.example first."
  exit 1
fi

info "Loading .env"; set -o allexport; grep -v '^#' .env | grep -E '^[A-Z_]+=.*' | while IFS= read -r line; do key="${line%%=*}"; val="${line#*=}"; printf -v "$key" '%s' "$val"; done; set +o allexport

echo ""
info "Validating AWS profile"
if [[ -z "${PULLDB_AWS_PROFILE:-}" ]]; then
  error "PULLDB_AWS_PROFILE not set"
  exit 1
fi
export AWS_PROFILE="$PULLDB_AWS_PROFILE"
if ! aws sts get-caller-identity >/dev/null 2>&1; then
  error "AWS profile '$PULLDB_AWS_PROFILE' not usable (sts get-caller-identity failed)"
  exit 1
fi
info "AWS profile '$PULLDB_AWS_PROFILE' OK"

echo ""
info "Checking Parameter Store references"
PARAM_FAIL=0
for var in PULLDB_MYSQL_HOST PULLDB_MYSQL_USER PULLDB_MYSQL_PASSWORD PULLDB_MYSQL_DATABASE; do
  val="${!var:-}"
  if [[ "$val" == /* ]]; then
    if RESOLVED=$(aws ssm get-parameter --name "$val" --with-decryption --query 'Parameter.Value' --output text 2>/dev/null); then
      info "$var parameter resolved: ${RESOLVED:0:60}$( [[ ${#RESOLVED} -gt 60 ]] && echo '…')"
    else
      warn "$var references '$val' but resolution failed"
      PARAM_FAIL=1
    fi
  else
    info "$var uses direct value (dev mode)"
  fi
done
if [[ $PARAM_FAIL -eq 1 ]]; then
  warn "One or more Parameter Store references failed resolution."
fi

echo ""
info "Testing MySQL connectivity"
MYSQL_HOST_VALUE=${PULLDB_MYSQL_HOST}
if [[ "$MYSQL_HOST_VALUE" == /* ]]; then
  MYSQL_HOST_VALUE=$(aws ssm get-parameter --name "$PULLDB_MYSQL_HOST" --with-decryption --query 'Parameter.Value' --output text 2>/dev/null || echo '<unresolved>')
fi
MYSQL_USER_VALUE=${PULLDB_MYSQL_USER}
if [[ "$MYSQL_USER_VALUE" == /* ]]; then
  MYSQL_USER_VALUE=$(aws ssm get-parameter --name "$PULLDB_MYSQL_USER" --with-decryption --query 'Parameter.Value' --output text 2>/dev/null || echo 'root')
fi
MYSQL_PASS_VALUE=${PULLDB_MYSQL_PASSWORD}
if [[ "$MYSQL_PASS_VALUE" == /* ]]; then
  MYSQL_PASS_VALUE=$(aws ssm get-parameter --name "$PULLDB_MYSQL_PASSWORD" --with-decryption --query 'Parameter.Value' --output text 2>/dev/null || echo '')
fi
MYSQL_DB_VALUE=${PULLDB_MYSQL_DATABASE:-pulldb}
if [[ "$MYSQL_DB_VALUE" == /* ]]; then
  MYSQL_DB_VALUE=$(aws ssm get-parameter --name "$PULLDB_MYSQL_DATABASE" --with-decryption --query 'Parameter.Value' --output text 2>/dev/null || echo 'pulldb')
fi

if ! mysql -h "$MYSQL_HOST_VALUE" -u "$MYSQL_USER_VALUE" ${MYSQL_PASS_VALUE:+-p"$MYSQL_PASS_VALUE"} -e "SHOW DATABASES LIKE '$MYSQL_DB_VALUE';" >/dev/null 2>&1; then
  warn "MySQL connectivity check failed (host=$MYSQL_HOST_VALUE user=$MYSQL_USER_VALUE db=$MYSQL_DB_VALUE)"
else
  info "MySQL connectivity OK (database '$MYSQL_DB_VALUE' visible)"
fi

echo ""
info "Validating work directories"
WORKDIR=${PULLDB_WORK_DIR:-/tmp/pulldb-work}
if [[ ! -d "$WORKDIR" ]]; then
  info "Creating work directory: $WORKDIR"
  mkdir -p "$WORKDIR"
fi
touch "$WORKDIR/.writable_test" && rm -f "$WORKDIR/.writable_test" && info "Work directory writable"

echo ""
info "Listing configured settings (if settings table populated)"
if mysql -h "$MYSQL_HOST_VALUE" -u "$MYSQL_USER_VALUE" ${MYSQL_PASS_VALUE:+-p"$MYSQL_PASS_VALUE"} -D "$MYSQL_DB_VALUE" -e "SHOW TABLES LIKE 'settings';" | grep -q settings; then
  mysql -h "$MYSQL_HOST_VALUE" -u "$MYSQL_USER_VALUE" ${MYSQL_PASS_VALUE:+-p"$MYSQL_PASS_VALUE"} -D "$MYSQL_DB_VALUE" -e "SELECT setting_key, LEFT(setting_value,80) FROM settings;" || warn "Unable to read settings table"
else
  warn "settings table not found; run schema setup script"
fi

echo ""
info "Configuration validation complete"
if [[ $PARAM_FAIL -eq 1 ]]; then
  warn "Completed with parameter resolution warnings"
  exit 2
fi
exit 0
