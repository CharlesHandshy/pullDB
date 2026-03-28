PYTHON ?= python3
PIP ?= pip

.PHONY: all wheel client server server-signed client-signed all-signed clean help dev-install changes lint image push deploy bundle release

help:
	@echo "pullDB Build System"
	@echo "==================="
	@echo ""
	@echo "Development:"
	@echo "  make dev-install      - Install in dev mode + restore pulldb-admin wrapper"
	@echo "  make changes          - Show uncommitted changes (filters binaries)"
	@echo ""
	@echo "Build Targets:"
	@echo "  make all              - Build wheel + all .deb packages (server + client)"
	@echo "  make wheel            - Build Python wheel only"
	@echo "  make server           - Build server .deb (full install with services)"
	@echo "  make client           - Build client .deb (CLI only)"
	@echo "  make server-signed    - Build signed server .deb (requires GPG_KEY_ID)"
	@echo "  make client-signed    - Build signed client .deb (requires GPG_KEY_ID)"
	@echo "  make all-signed       - Build wheel + all signed .deb packages"
	@echo "  make clean            - Remove all build artifacts"
	@echo ""
	@echo "Docker / ECR Targets (requires ECR_REGISTRY and ECR_REGION env vars):"
	@echo "  make image            - Build Docker image (tags as pulldb:<version>)"
	@echo "  make bundle           - Build image + package into self-contained upgrade tar.gz"
	@echo "  make release          - bundle + create GitHub release + upload asset"
	@echo "                         (target: wget <url>, no git/ECR required)"
	@echo "  make push             - ECR login + push image (requires dev IAM permissions)"
	@echo "  make deploy HOST=...  - SSH to HOST and run upgrade.sh with latest image"
	@echo ""
	@echo "Version is read from pyproject.toml (or PULLDB_VERSION env var for CI)."
	@echo ""
	@echo "Output files:"
	@echo "  dist/pulldb-*.whl                    - Python wheel (shared by all packages)"
	@echo "  pulldb_<version>_amd64.deb           - Full server package (includes web UI)"
	@echo "  pulldb-client_<version>_amd64.deb    - Client-only package (CLI)"

# Build wheel first (shared by both packages)
wheel:
	@echo "=== Building Python Wheel ==="
	$(PIP) install --quiet build --break-system-packages 2>/dev/null || $(PIP) install --quiet build
	$(PYTHON) -m build --wheel .

# Server package depends on wheel
server: wheel
	@echo "=== Building Server Package (Debian) ==="
	./scripts/build_deb.sh

# Client package builds its own minimal wheel (CLI only, no server components)
client:
	@echo "=== Building Client Package (Debian with minimal wheel) ==="
	./scripts/build_client_deb.sh

# Build everything
all: wheel server client
	@echo ""
	@echo "=== Build Complete ==="
	@ls -la *.deb 2>/dev/null || true

# Signed build targets (requires GPG_KEY_ID environment variable)
server-signed: wheel
	@echo "=== Building Signed Server Package (Debian) ==="
	GPG_KEY_ID=$(GPG_KEY_ID) ./scripts/build_deb.sh

client-signed: wheel
	@echo "=== Building Signed Client Package (Debian) ==="
	GPG_KEY_ID=$(GPG_KEY_ID) ./scripts/build_client_deb.sh

all-signed: wheel server-signed client-signed
	@echo ""
	@echo "=== Signed Build Complete ==="
	@ls -la *.deb 2>/dev/null || true

clean:
	@echo "Cleaning up..."
	rm -rf build/ dist/ dist-client/ *.egg-info pulldb.egg-info pulldb_client.egg-info
	rm -f *.deb
	@echo "Clean complete."

# =============================================================================
# Docker / ECR targets
# =============================================================================
# Required env vars:
#   ECR_REGISTRY  — e.g. 123456789012.dkr.ecr.us-east-1.amazonaws.com
#   ECR_REGION    — e.g. us-east-1
#   HOST          — SSH target for 'make deploy' (e.g. ubuntu@10.0.0.5)
# =============================================================================

# Read version the same way the deb build does
PULLDB_VERSION ?= $(shell python3 -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); print(d['project']['version'])" 2>/dev/null \
                   || python3 -c "import tomli; d=tomli.load(open('pyproject.toml','rb')); print(d['project']['version'])" 2>/dev/null \
                   || echo "dev")

IMAGE_NAME  ?= pulldb
IMAGE_TAG   ?= $(PULLDB_VERSION)

ECR_REGISTRY ?= $(error ECR_REGISTRY is not set. Example: export ECR_REGISTRY=123456789012.dkr.ecr.us-east-1.amazonaws.com)
ECR_REGION   ?= $(error ECR_REGION is not set. Example: export ECR_REGION=us-east-1)
FULL_IMAGE    = $(ECR_REGISTRY)/$(IMAGE_NAME):$(IMAGE_TAG)

# Build the Docker image (requires the server .deb to exist)
# Build context is docker/ — Dockerfile COPY paths are relative to that directory.
# The .deb is copied into docker/ temporarily so it is inside the build context.
image: server
	@echo "=== Building Docker image: $(FULL_IMAGE) ==="
	cp pulldb_$(IMAGE_TAG)_amd64.deb docker/pulldb_$(IMAGE_TAG)_amd64.deb
	docker build \
		--build-arg PULLDB_VERSION=$(IMAGE_TAG) \
		-t $(IMAGE_NAME):$(IMAGE_TAG) \
		-t $(IMAGE_NAME):latest \
		-t $(FULL_IMAGE) \
		docker/
	rm -f docker/pulldb_$(IMAGE_TAG)_amd64.deb
	@echo ""
	@echo "Image built: $(FULL_IMAGE)"

# ECR login + push (requires dev IAM role with push permissions — see docs/ecr-setup.md)
push: image
	@echo "=== Pushing to ECR: $(FULL_IMAGE) ==="
	aws ecr get-login-password --region $(ECR_REGION) \
		| docker login --username AWS --password-stdin $(ECR_REGISTRY)
	docker push $(FULL_IMAGE)
	@echo "Pushed: $(FULL_IMAGE)"

# Create a self-contained upgrade bundle for transfer to servers without git/ECR.
# Builds the image locally, saves it as a tar, and packages everything into a
# single archive that can be scp'd to the target and run with no dependencies.
#
# Usage:
#   make bundle
#   scp pulldb-upgrade-1.3.0.tar.gz user@target:/tmp/
#   # On target:
#   #   tar -xzf /tmp/pulldb-upgrade-1.3.0.tar.gz -C /tmp/
#   #   sudo /tmp/upgrade-1.2.0-to-1.3.0/upgrade.sh
BUNDLE_NAME := pulldb-upgrade-$(IMAGE_TAG).tar.gz
BUNDLE_PKG  := packaging/upgrade-1.2.0-to-1.3.0

bundle: server
	@echo "=== Building Docker image (local, no ECR required) ==="
	cp pulldb_$(IMAGE_TAG)_amd64.deb docker/pulldb_$(IMAGE_TAG)_amd64.deb
	docker build \
		--build-arg PULLDB_VERSION=$(IMAGE_TAG) \
		-t $(IMAGE_NAME):$(IMAGE_TAG) \
		-t $(IMAGE_NAME):latest \
		docker/
	rm -f docker/pulldb_$(IMAGE_TAG)_amd64.deb
	@echo "=== Saving image tar (this may take a minute) ==="
	docker save $(IMAGE_NAME):$(IMAGE_TAG) | gzip > $(BUNDLE_PKG)/pulldb-$(IMAGE_TAG).tar.gz
	@echo "=== Creating upgrade bundle: $(BUNDLE_NAME) ==="
	tar -czf $(BUNDLE_NAME) \
		--exclude='upgrade-1.2.0-to-1.3.0/*.deb' \
		--exclude='upgrade-1.2.0-to-1.3.0/rollback-state.env' \
		--exclude='upgrade-1.2.0-to-1.3.0/upgrade-*.log' \
		--exclude='upgrade-1.2.0-to-1.3.0/rollback-*.log' \
		-C packaging upgrade-1.2.0-to-1.3.0/
	rm -f $(BUNDLE_PKG)/pulldb-$(IMAGE_TAG).tar.gz
	@ls -lh $(BUNDLE_NAME)
	@echo ""
	@echo "  scp $(BUNDLE_NAME) user@target:/tmp/"
	@echo "  # On target:"
	@echo "  #   tar -xzf /tmp/$(BUNDLE_NAME) -C /tmp/"
	@echo "  #   sudo /tmp/upgrade-1.2.0-to-1.3.0/upgrade.sh"

# Create a GitHub release and upload the upgrade bundle as an asset.
# The bundle can then be downloaded on the target with wget — no git required.
#
# Usage:
#   make release
#   # On target (no git/ECR needed):
#   #   wget <url printed by this target>
#   #   tar -xzf $(BUNDLE_NAME) && sudo ./upgrade-1.2.0-to-1.3.0/upgrade.sh
#
# Requires: gh CLI authenticated (gh auth login)
RELEASE_TAG    := v$(IMAGE_TAG)
REPO_URL       := $(shell git remote get-url origin 2>/dev/null | sed 's/\.git$$//')
RELEASE_DL_URL  = $(REPO_URL)/releases/download/$(RELEASE_TAG)/$(BUNDLE_NAME)

release: bundle
	@echo "=== Creating GitHub release $(RELEASE_TAG) ==="
	gh release create $(RELEASE_TAG) $(BUNDLE_NAME) \
		--title "pullDB $(IMAGE_TAG)" \
		--notes "1.2.0 → $(IMAGE_TAG) upgrade bundle. Self-contained: includes Docker image, scripts, and migrations." \
		|| (echo "Release may already exist — uploading asset only..." && \
		    gh release upload $(RELEASE_TAG) $(BUNDLE_NAME) --clobber)
	@echo ""
	@echo "=== Download on target ==="
	@echo "  wget $(RELEASE_DL_URL)"
	@echo "  tar -xzf $(BUNDLE_NAME) && sudo ./upgrade-1.2.0-to-1.3.0/upgrade.sh"

# Deploy to a host via SSH — copies upgrade script and runs it
# Usage: make deploy HOST=ubuntu@10.0.0.5
deploy:
	@test -n "$(HOST)" || (echo "ERROR: HOST is not set. Usage: make deploy HOST=user@host" && exit 1)
	@echo "=== Deploying $(FULL_IMAGE) to $(HOST) ==="
	scp scripts/upgrade.sh scripts/validate.sh scripts/rollback.sh \
		compose/docker-compose.yml \
		$(HOST):/tmp/pulldb-deploy/
	ssh $(HOST) "sudo /tmp/pulldb-deploy/upgrade.sh $(FULL_IMAGE)"

# Dev install with wrapper restoration
# Use this instead of 'pip install -e .' to preserve pulldb-admin auto-escalation
dev-install:
	@echo "=== Dev Install ==="
	$(PIP) install -e .
	@echo ""
	@echo "=== Restoring pulldb-admin wrapper ==="
	./scripts/restore_admin_wrapper.sh
	@echo ""
	@echo "Dev install complete. pulldb-admin auto-escalation preserved."

# Show uncommitted changes (filters out binary files)
changes:
	@./scripts/git-changes.sh --stat

changes-diff:
	@./scripts/git-changes.sh --diff

# Lint — run ruff + HCA layer enforcement
lint:
	@echo "=== Ruff ==="
	ruff check pulldb/
	@echo "=== import-linter (HCA) ==="
	lint-imports
