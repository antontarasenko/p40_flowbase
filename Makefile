VERSION := $(shell git describe --tags --abbrev=0 2>/dev/null || echo "0.0.0")

WHEEL_NAME := p40_flowbase-$(VERSION)-py3-none-any.whl
WHEEL_PATH := dist/$(WHEEL_NAME)

.PHONY: all clean build upload info help

help:
	@echo "p40_flowbase distribution targets:"
	@echo ""
	@echo "  make build              Build Python wheel"
	@echo "  make upload             Upload Python wheel to PyPI"
	@echo ""
	@echo "  make info               Show current version and paths"
	@echo "  make clean              Remove build artifacts"
	@echo ""
	@echo "Current version: $(VERSION)"

all: build upload

info:
	@echo "Version:          $(VERSION)"
	@echo "Wheel:            $(WHEEL_NAME)"
	@echo "PyPI URL:         https://pypi.org/project/p40-flowbase/$(VERSION)/"

build:
	@echo "Building Python wheel..."
	python -m build --wheel
	@echo "Built: $(WHEEL_PATH)"

upload: $(WHEEL_PATH)
	@if ! echo "$(VERSION)" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$$'; then \
		echo "ERROR: version '$(VERSION)' is not a clean release tag (expected X.Y.Z)"; \
		exit 1; \
	fi
	@echo "Checking Python wheel..."
	python -m twine check $(WHEEL_PATH)
	@echo "Uploading Python wheel to PyPI..."
	python -m twine upload $(WHEEL_PATH)
	@echo "Uploaded to: https://pypi.org/project/p40-flowbase/$(VERSION)/"

# Ensure wheel exists before upload
$(WHEEL_PATH):
	$(MAKE) build

clean:
	rm -rf dist/ build/ *.egg-info/
	@echo "Cleaned build artifacts"

