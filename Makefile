PYTHON ?= python3
PIP ?= pip

.PHONY: all client server clean help

help:
	@echo "pullDB Build System"
	@echo "-------------------"
	@echo "Targets:"
	@echo "  make all      - Build both client and server packages"
	@echo "  make client   - Build the standalone client CLI package (wheel + installer)"
	@echo "  make server   - Build the full server package (wheel + debian)"
	@echo "  make clean    - Remove all build artifacts"

all: client server

client:
	@echo "=== Building Client Package (Debian) ==="
	./scripts/build_client_deb.sh

server:
	@echo "=== Building Server Package (Wheel) ==="
	# Ensure build tool is installed
	$(PIP) install --quiet build --break-system-packages || $(PIP) install --quiet build
	$(PYTHON) -m build .
	@echo "=== Building Server Package (Debian) ==="
	./scripts/build_deb.sh

clean:
	@echo "Cleaning up..."
	rm -rf build/ dist/ build_client/ dist_client_package/ *.egg-info src/*.egg-info
	rm -rf pulldb.egg-info
