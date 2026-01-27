PYTHON ?= python3
PIP ?= pip

.PHONY: all wheel client server server-signed client-signed all-signed clean help dev-install changes

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
