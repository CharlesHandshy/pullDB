PYTHON ?= python3
PIP ?= pip

.PHONY: all wheel client server clean help

help:
	@echo "pullDB Build System"
	@echo "==================="
	@echo ""
	@echo "Targets:"
	@echo "  make all      - Build wheel + both .deb packages (server + client)"
	@echo "  make wheel    - Build Python wheel only"
	@echo "  make server   - Build server .deb (full install with services)"
	@echo "  make client   - Build client .deb (CLI only)"
	@echo "  make clean    - Remove all build artifacts"
	@echo ""
	@echo "Version is read from pyproject.toml (or PULLDB_VERSION env var for CI)."
	@echo ""
	@echo "Output files:"
	@echo "  dist/pulldb-*.whl              - Python wheel (shared by both packages)"
	@echo "  pulldb_<version>_amd64.deb     - Full server package"
	@echo "  pulldb-client_<version>_amd64.deb - Client-only package"

# Build wheel first (shared by both packages)
wheel:
	@echo "=== Building Python Wheel ==="
	$(PIP) install --quiet build --break-system-packages 2>/dev/null || $(PIP) install --quiet build
	$(PYTHON) -m build --wheel .

# Server package depends on wheel
server: wheel
	@echo "=== Building Server Package (Debian) ==="
	./scripts/build_deb.sh

# Client package depends on wheel (uses same wheel as server)
client: wheel
	@echo "=== Building Client Package (Debian) ==="
	./scripts/build_client_deb.sh

# Build everything
all: wheel server client
	@echo ""
	@echo "=== Build Complete ==="
	@ls -la *.deb 2>/dev/null || true

clean:
	@echo "Cleaning up..."
	rm -rf build/ dist/ *.egg-info pulldb.egg-info
	rm -f *.deb
	@echo "Clean complete."
