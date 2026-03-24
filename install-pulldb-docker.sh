#!/usr/bin/env bash
# =============================================================================
# pullDB — Docker Station Installer
# =============================================================================
# One-step installer for a fresh Ubuntu host. Installs Docker + Compose plugin,
# authenticates with ECR using the host EC2 instance role, pulls the image,
# writes config, and starts pullDB via Docker Compose.
#
# On subsequent runs, this script detects an existing install and hands off
# to scripts/upgrade.sh for the full blue/green upgrade.
#
# Usage:
#   sudo ./install-pulldb-docker.sh <image-uri>
#
# Example:
#   sudo ./install-pulldb-docker.sh \
#       123456789012.dkr.ecr.us-east-1.amazonaws.com/pulldb:1.3.0
#
# Options:
#   --validate-s3-path  PATH    S3 path for QA restore validation
#   --yes                       Non-interactive: skip confirmation prompts
#   --dry-run                   Print plan without making changes
# =============================================================================
set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================
STATE_DIR="/etc/pulldb"
ACTIVE_COLOR_FILE="${STATE_DIR}/.active-color"
DATA_ROOT="/mnt/data"
COMPOSE_FILE_SRC="compose/docker-compose.yml"
COMPOSE_DEST="${STATE_DIR}/docker-compose.yml"
LOG_FILE="/tmp/pulldb-install-$(date +%Y%m%d-%H%M%S).log"

PORT_WEB=8000
PORT_API=8080

# Detect the primary external host IP (first non-loopback, non-docker interface)
HOST_IP=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1); exit}')
HOST_IP=${HOST_IP:-0.0.0.0}

# =============================================================================
# Output helpers
# =============================================================================
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

log_info()   { echo -e "${GREEN}[install]${NC}  $*" | tee -a "$LOG_FILE"; }
log_warn()   { echo -e "${YELLOW}[install]${NC}  $*" | tee -a "$LOG_FILE"; }
log_error()  { echo -e "${RED}[install]${NC}  $*" >&2 | tee -a "$LOG_FILE" >&2; }
log_step()   { echo -e "\n${BLUE}══ $* ${NC}" | tee -a "$LOG_FILE"; }
log_dry()    { echo -e "  ${YELLOW}[DRY RUN]${NC} $*"; }

die() { log_error "$*"; exit 1; }

# =============================================================================
# Argument parsing
# =============================================================================
IMAGE=""
VALIDATE_S3_PATH=""
YES=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --validate-s3-path) VALIDATE_S3_PATH="$2"; shift 2 ;;
        --yes)              YES=true;  shift ;;
        --dry-run)          DRY_RUN=true; shift ;;
        --*)                die "Unknown option: $1" ;;
        *)                  IMAGE="$1"; shift ;;
    esac
done

[[ -z "$IMAGE" ]] && die "Usage: $0 [options] <image-uri>"

# Derive ECR region from image URI
# e.g. 123456789012.dkr.ecr.us-east-1.amazonaws.com/pulldb:1.3.0
ECR_REGISTRY=$(echo "$IMAGE" | cut -d'/' -f1)
ECR_REGION=$(echo "$ECR_REGISTRY" | sed -n 's/.*\.ecr\.\(.*\)\.amazonaws\.com/\1/p')
[[ -z "$ECR_REGION" ]] && die "Cannot parse ECR region from image URI: ${IMAGE}"

# =============================================================================
# Pre-flight
# =============================================================================
preflight() {
    log_step "Pre-flight"

    [[ $EUID -ne 0 ]] && die "Must run as root"

    log_info "Image:   ${IMAGE}"
    log_info "Region:  ${ECR_REGION}"
    log_info "Log:     ${LOG_FILE}"

    # Detect existing install
    if [[ -f "$ACTIVE_COLOR_FILE" ]]; then
        local current_color
        current_color=$(cat "$ACTIVE_COLOR_FILE")
        local current_container="pulldb-${current_color}"
        local state
        state=$(docker inspect --format '{{.State.Status}}' "$current_container" 2>/dev/null || echo "absent")

        if [[ "$state" == "running" ]]; then
            echo ""
            log_warn "Existing pullDB installation detected:"
            log_warn "  Active color:     ${current_color}"
            log_warn "  Container:        ${current_container}  (running)"
            echo ""
            log_info "This looks like an UPGRADE. Handing off to upgrade.sh..."
            echo ""

            local upgrade_args=("$IMAGE")
            [[ "$YES"     == true ]] && upgrade_args+=(--yes)
            [[ "$DRY_RUN" == true ]] && upgrade_args+=(--dry-run)

            exec "$(dirname "${BASH_SOURCE[0]}")/scripts/upgrade.sh" "${upgrade_args[@]}"
        fi
    fi

    if [[ "$YES" != true && "$DRY_RUN" != true && -t 0 ]]; then
        echo ""
        echo "  This will install pullDB on this host."
        echo "  Image: ${IMAGE}"
        echo ""
        read -r -p "  Continue? [Y/n] " confirm
        case "$confirm" in [nN]*) echo "Aborted."; exit 0 ;; esac
    fi

    log_info "Fresh install — proceeding"
}

# =============================================================================
# Step 1 — Install Docker
# =============================================================================
install_docker() {
    log_step "Step 1: Docker"

    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        log_info "Docker $(docker --version | awk '{print $3}' | tr -d ','): already installed"
        log_info "Docker Compose plugin: $(docker compose version --short 2>/dev/null || echo 'present')"
        return
    fi

    if [[ "$DRY_RUN" == true ]]; then
        log_dry "Would install Docker Engine + Compose plugin"
        return
    fi

    log_info "Installing Docker Engine..."

    # Update apt and install prerequisites
    apt-get update -qq 2>&1 | tee -a "$LOG_FILE"
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        ca-certificates curl gnupg lsb-release \
        2>&1 | tee -a "$LOG_FILE"

    # Add Docker's official GPG key
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    # Add Docker repository
    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu \
        $(lsb_release -cs) stable" \
        | tee /etc/apt/sources.list.d/docker.list >/dev/null

    apt-get update -qq 2>&1 | tee -a "$LOG_FILE"
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin \
        2>&1 | tee -a "$LOG_FILE"

    systemctl enable docker 2>/dev/null || true
    systemctl start  docker 2>/dev/null || true

    log_info "Docker $(docker --version | awk '{print $3}' | tr -d ','): installed"
    log_info "Docker Compose: $(docker compose version --short 2>/dev/null)"
}

# =============================================================================
# Step 2 — Install AWS CLI (for ECR login)
# =============================================================================
install_awscli() {
    log_step "Step 2: AWS CLI"

    if command -v aws >/dev/null 2>&1; then
        log_info "AWS CLI $(aws --version 2>&1 | awk '{print $1}'): already installed"
        return
    fi

    if [[ "$DRY_RUN" == true ]]; then
        log_dry "Would install AWS CLI v2"
        return
    fi

    log_info "Installing AWS CLI v2..."
    local tmpdir
    tmpdir=$(mktemp -d)
    trap 'rm -rf "$tmpdir"' RETURN

    local arch
    arch=$(uname -m)
    local cli_url="https://awscli.amazonaws.com/awscli-exe-linux-${arch}.zip"

    curl -fsSL "$cli_url" -o "${tmpdir}/awscliv2.zip" 2>&1 | tee -a "$LOG_FILE"

    if command -v unzip >/dev/null 2>&1; then
        unzip -q "${tmpdir}/awscliv2.zip" -d "$tmpdir"
    else
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq unzip 2>&1 | tee -a "$LOG_FILE"
        unzip -q "${tmpdir}/awscliv2.zip" -d "$tmpdir"
    fi

    "${tmpdir}/aws/install" --update 2>&1 | tee -a "$LOG_FILE"
    log_info "AWS CLI $(aws --version 2>&1 | awk '{print $1}'): installed"
}

# =============================================================================
# Step 3 — Set up config directories
# =============================================================================
setup_directories() {
    log_step "Step 3: Config directories"

    local container_data="${DATA_ROOT}/pulldb-blue"

    if [[ "$DRY_RUN" == true ]]; then
        log_dry "Would create ${STATE_DIR} and ${container_data}/{logs/pulldb,work/pulldb.service,tmp}"
        return
    fi

    mkdir -p "${STATE_DIR}"
    chmod 700 "${STATE_DIR}"

    mkdir -p \
        "${container_data}/logs/pulldb" \
        "${container_data}/work/pulldb.service" \
        "${container_data}/tmp"

    # Copy compose file into state dir so it persists independent of installer
    if [[ -f "$COMPOSE_FILE_SRC" ]]; then
        cp "$COMPOSE_FILE_SRC" "$COMPOSE_DEST"
        chmod 644 "$COMPOSE_DEST"
        log_info "Compose file: ${COMPOSE_DEST}"
    else
        log_warn "compose/docker-compose.yml not found in working directory"
        log_warn "Expected to run from the pullDB repo root"
        [[ -f "$COMPOSE_DEST" ]] || die "No compose file at ${COMPOSE_DEST} — cannot proceed"
    fi

    log_info "Directories: ${STATE_DIR}  ${DATA_DIR}"
}

# =============================================================================
# Step 4 — ECR login and pull
# =============================================================================
pull_image() {
    log_step "Step 4: ECR login and image pull"

    if [[ "$DRY_RUN" == true ]]; then
        log_dry "Would: aws ecr get-login-password --region ${ECR_REGION} | docker login ${ECR_REGISTRY}"
        log_dry "Would: docker pull ${IMAGE}"
        return
    fi

    log_info "Authenticating with ECR (host instance role, region: ${ECR_REGION})..."
    aws ecr get-login-password --region "$ECR_REGION" \
        | docker login --username AWS --password-stdin "$ECR_REGISTRY" \
        || die "ECR authentication failed.
  Ensure this EC2 instance's IAM role has:
    ecr:GetAuthorizationToken
    ecr:BatchCheckLayerAvailability
    ecr:GetDownloadUrlForLayer
    ecr:BatchGetImage
  See docs/ecr-setup.md for details."

    log_info "Pulling image: ${IMAGE}"
    docker pull "$IMAGE" 2>&1 | tee -a "$LOG_FILE" \
        || die "docker pull failed — check the image URI and ECR permissions"

    log_info "Image pulled"
}

# =============================================================================
# Step 5 — Write initial compose env and start
# =============================================================================
start_container() {
    log_step "Step 5: Initial start"

    # Blue is always first
    local color="blue"
    local container="pulldb-${color}"
    local env_file="${STATE_DIR}/.env.blue"
    local active_env="${STATE_DIR}/.env.active"

    if [[ "$DRY_RUN" == true ]]; then
        log_dry "Would write ${env_file} (blue, fresh install)"
        log_dry "Would docker compose -p pulldb-blue up -d"
        log_dry "Would write ${ACTIVE_COLOR_FILE} = blue"
        return
    fi

    # Write blue env file
    cat > "$env_file" << EOF
# pullDB blue env — initial install
# Generated by install-pulldb-docker.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
PULLDB_IMAGE=${IMAGE}
CONTAINER_NAME=${container}
HOST_IP=${HOST_IP}
PORT_WEB=${PORT_WEB}
PORT_API=${PORT_API}
PULLDB_IMPORT_DUMP=
EOF

    if [[ -n "$VALIDATE_S3_PATH" ]]; then
        echo "PULLDB_VALIDATE_S3_PATH=${VALIDATE_S3_PATH}" >> "$env_file"
    fi
    chmod 600 "$env_file"
    cp "$env_file" "$active_env"
    chmod 600 "$active_env"

    log_info "Starting pulldb-blue..."
    docker compose \
        -p "pulldb-blue" \
        --env-file "$env_file" \
        -f "$COMPOSE_DEST" \
        up -d

    # Record active color
    echo "blue" > "$ACTIVE_COLOR_FILE"

    log_info "Container 'pulldb-blue' starting..."
    log_info "Waiting for API health (may take 60–90s on first start while MySQL initialises)..."

    local attempts=0
    until curl -fsk --max-time 5 "https://localhost:${PORT_API}/api/health" >/dev/null 2>&1; do
        (( attempts++ )) || true
        if (( attempts >= 36 )); then
            log_warn "API not responding after 180s"
            log_warn "  Logs: docker logs pulldb-blue"
            log_warn "  The container may still be initialising — check manually."
            break
        fi
        sleep 5
    done

    if curl -fsk --max-time 5 "https://localhost:${PORT_API}/api/health" >/dev/null 2>&1; then
        log_info "API health: OK"
    fi
}

# =============================================================================
# Completion summary
# =============================================================================
print_completion() {
    local version
    version=$(echo "$IMAGE" | sed 's/.*://')
    local server_ip="${HOST_IP:-$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1); exit}')}"
    server_ip="${server_ip:-<server-ip>}"

    local admin_pass=""
    # Try to read from container
    admin_pass=$(docker exec pulldb-blue \
        cat /opt/pulldb.service/ADMIN_CREDENTIALS.txt 2>/dev/null \
        | grep "^Password:" | awk '{print $2}' || true)

    echo ""
    echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  pullDB ${version} — Installed${NC}"
    echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
    echo ""

    if [[ -n "$admin_pass" ]]; then
        echo "  ┌──────────────────────────────────────────────────────────────┐"
        echo "  │  ADMIN CREDENTIALS (save these — shown once)                 │"
        echo "  │                                                              │"
        printf "  │    Username: %-47s│\n" "admin"
        printf "  │    Password: %-47s│\n" "$admin_pass"
        echo "  │                                                              │"
        echo "  │  Change after first login!                                   │"
        echo "  └──────────────────────────────────────────────────────────────┘"
        echo ""
    fi

    echo "  Web UI:   https://${server_ip}:${PORT_WEB}"
    echo "  REST API: https://${server_ip}:${PORT_API}"
    echo ""
    echo "  Container: pulldb-blue"
    echo "  State dir: ${STATE_DIR}"
    echo "  Data dir:  ${DATA_DIR}"
    echo "  Log:       ${LOG_FILE}"
    echo ""
    echo "  Next steps:"
    echo "    1. Configure /etc/pulldb settings (AWS credentials, S3 paths)"
    echo "    2. To upgrade: sudo ./install-pulldb-docker.sh <new-image-uri>"
    echo "       (automatically hands off to scripts/upgrade.sh)"
    echo ""
}

# =============================================================================
# Main
# =============================================================================
main() {
    echo ""
    echo -e "${BLUE}pullDB Docker Installer${NC}"
    echo "Log: ${LOG_FILE}"
    echo ""

    preflight
    install_docker
    install_awscli
    setup_directories
    pull_image
    start_container
    print_completion
}

main
