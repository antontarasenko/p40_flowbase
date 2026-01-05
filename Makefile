S3_BUCKET := s3://antontarasenko
S3_BUCKET_URL := https://antontarasenko.s3.amazonaws.com
S3_PYTHON_PREFIX := registry/p40_flowbase/Id0E3qM8Nx/python
S3_FLAKE_PREFIX := registry/p40_flowbase/Id0E3qM8Nx/nix-flakes
VERSION := $(shell python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])")
SYSTEM := $(shell nix eval --impure --raw --expr 'builtins.currentSystem')

WHEEL_NAME := p40_flowbase-$(VERSION)-py3-none-any.whl
WHEEL_PATH := dist/$(WHEEL_NAME)
WHEEL_LATEST_NAME := p40_flowbase-latest-py3-none-any.whl
FLAKE_TARBALL := p40_flowbase-$(VERSION).tar.gz
FLAKE_LATEST_NAME := p40_flowbase-latest.tar.gz
NIX_RESULT := ./result

.PHONY: all clean build-python build-nix build-flake-tarball upload-python upload-flake upload info help

help:
	@echo "p40_flowbase distribution targets:"
	@echo ""
	@echo "  make build-python       Build Python wheel"
	@echo "  make build-nix          Build Nix package (local test)"
	@echo "  make build-flake-tarball Build flake source tarball"
	@echo "  make build              Build Python wheel and flake tarball"
	@echo ""
	@echo "  make upload-python      Upload Python wheel to S3"
	@echo "  make upload-flake       Upload flake tarball to S3"
	@echo "  make upload             Upload all artifacts"
	@echo ""
	@echo "  make info               Show current version and paths"
	@echo "  make clean              Remove build artifacts"
	@echo ""
	@echo "Current version: $(VERSION)"
	@echo "Current system:  $(SYSTEM)"

all: build upload

info:
	@echo "Version:          $(VERSION)"
	@echo "System:           $(SYSTEM)"
	@echo "Wheel:            $(WHEEL_NAME)"
	@echo "Flake tarball:    $(FLAKE_TARBALL)"
	@echo "S3 bucket:        $(S3_BUCKET)"
	@echo ""
	@echo "Distribution URLs:"
	@echo "  Python wheel (versioned): $(S3_BUCKET_URL)/$(S3_PYTHON_PREFIX)/$(WHEEL_NAME)"
	@echo "  Python wheel (latest):    $(S3_BUCKET_URL)/$(S3_PYTHON_PREFIX)/$(WHEEL_LATEST_NAME)"
	@echo "  Nix flake (versioned):    $(S3_BUCKET_URL)/$(S3_FLAKE_PREFIX)/$(FLAKE_TARBALL)"
	@echo "  Nix flake (latest):       $(S3_BUCKET_URL)/$(S3_FLAKE_PREFIX)/$(FLAKE_LATEST_NAME)"
	@echo ""
	@if [ -L $(NIX_RESULT) ]; then \
		echo "Nix store path: $$(readlink $(NIX_RESULT))"; \
	fi

build: build-python build-flake-tarball

build-python:
	@echo "Building Python wheel..."
	python -m build --wheel
	@echo "Built: $(WHEEL_PATH)"

build-nix:
	@echo "Building Nix package (local test)..."
	nix build
	@echo "Built: $$(readlink $(NIX_RESULT))"

build-flake-tarball:
	@echo "Building flake tarball..."
	git archive --format=tar.gz --prefix=p40_flowbase/ HEAD > $(FLAKE_TARBALL)
	@echo "Built: $(FLAKE_TARBALL)"

upload: upload-python upload-flake

upload-python: $(WHEEL_PATH)
	@echo "Uploading Python wheel to S3..."
	# Upload versioned wheel
	aws s3 cp $(WHEEL_PATH) $(S3_BUCKET)/$(S3_PYTHON_PREFIX)/$(WHEEL_NAME)
	# Upload as latest
	aws s3 cp $(WHEEL_PATH) $(S3_BUCKET)/$(S3_PYTHON_PREFIX)/$(WHEEL_LATEST_NAME)
	@echo "Uploaded to:"
	@echo "  $(S3_BUCKET_URL)/$(S3_PYTHON_PREFIX)/$(WHEEL_NAME)"
	@echo "  $(S3_BUCKET_URL)/$(S3_PYTHON_PREFIX)/$(WHEEL_LATEST_NAME)"

upload-flake: $(FLAKE_TARBALL)
	@echo "Uploading flake tarball to S3..."
	# Upload versioned tarball
	aws s3 cp $(FLAKE_TARBALL) $(S3_BUCKET)/$(S3_FLAKE_PREFIX)/$(FLAKE_TARBALL)
	# Upload as latest
	aws s3 cp $(FLAKE_TARBALL) $(S3_BUCKET)/$(S3_FLAKE_PREFIX)/$(FLAKE_LATEST_NAME)
	@echo "Uploaded to:"
	@echo "  $(S3_BUCKET_URL)/$(S3_FLAKE_PREFIX)/$(FLAKE_TARBALL)"
	@echo "  $(S3_BUCKET_URL)/$(S3_FLAKE_PREFIX)/$(FLAKE_LATEST_NAME)"

# Ensure wheel exists before upload
$(WHEEL_PATH):
	$(MAKE) build-python

# Ensure flake tarball exists before upload
$(FLAKE_TARBALL):
	$(MAKE) build-flake-tarball

clean:
	rm -rf dist/ build/ *.egg-info/
	rm -f result $(FLAKE_TARBALL)
	@echo "Cleaned build artifacts"

# Print sha256 for Python wheel (for step1/pyproject.toml)
print-wheel-sha256:
	@echo "Wheel SHA256 (for pip):"
	@nix-prefetch-url --type sha256 $(S3_BUCKET_URL)/$(S3_PYTHON_PREFIX)/$(WHEEL_NAME) 2>/dev/null || \
		echo "Wheel not yet uploaded. Run 'make upload-python' first."
