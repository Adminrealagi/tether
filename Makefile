.PHONY: build build-sidecars build-ui dev-ui install install-all install-codex install-system start start-codex test test-all verify venv

# =============================================================================
# Native mode (recommended)
# =============================================================================

VENV ?= $(CURDIR)/.venv
PYTHON ?= $(VENV)/bin/python
PIP := $(PYTHON) -m pip

$(PYTHON):
	python3 -m venv $(VENV)

venv: $(PYTHON)

# Install dependencies (run once)
install: venv
	cd agent && $(PIP) install -e ".[dev,discord]"
	cd ui && npm ci
	npm install --workspaces

install-all: venv
	cd agent && $(PIP) install -e ".[dev,telegram,slack,discord,ssh,litellm,mcp]"
	cd ui && npm ci
	npm install --workspaces

install-sidecars:
	cd codex-src/sdk/typescript && npm install --ignore-scripts
	npm install --workspaces

install-codex: install-sidecars

build: build-ui build-sidecars

# Build UI for production
build-ui:
	cd ui && npm run build
	rm -rf agent/tether/static_ui
	cp -r ui/dist agent/tether/static_ui

# Build TypeScript sidecars into bundled JS for the Python package
build-sidecars:
	./scripts/build-sidecars.sh

# Start agent natively (Claude auto-detect works out of the box)
start: build-ui build-sidecars
	cd agent && $(PYTHON) -m tether.main

# Start agent + Codex sidecar locally (recommended)
start-codex: build-ui
	./scripts/start-codex-local.sh

# Run UI dev server (hot reload) - run agent separately
dev-ui:
	cd ui && npm run dev

# Run tests
test:
	cd agent && $(PYTHON) -m pytest

test-all:
	cd agent && $(PYTHON) -m pytest
	cd ui && npm run test:run
	npm test --workspace @tether/sidecar-common
	npm test --workspace opencode-sdk-sidecar
	npm test --workspace codex-sdk-sidecar

install-system: build
	./scripts/install-system-editable.sh

# Verify setup (agent must be running)
verify:
	./scripts/verify.sh
