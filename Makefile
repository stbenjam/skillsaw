APM_VERSION := 0.12.4
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help venv format lint test clean apm verify-apm generate-example

help:
	@echo "Available targets:"
	@echo "  venv          - Create virtualenv and install dev dependencies"
	@echo "  format        - Fix code formatting with black"
	@echo "  lint          - Check code formatting with black"
	@echo "  test          - Run pytest tests"
	@echo "  clean         - Remove Python cache files and virtualenv"
	@echo "  generate-example - Regenerate .skillsaw.yaml.example from builtin rules"
	@echo "  apm           - Install APM dependencies"
	@echo "  verify-apm    - Verify generated APM files are up to date"

$(VENV)/bin/activate:
	python3 -m venv $(VENV)
	$(PIP) install -e '.[dev]'

venv: $(VENV)/bin/activate

format: $(VENV)/bin/activate
	$(VENV)/bin/black src/ tests/

lint: $(VENV)/bin/activate
	$(VENV)/bin/black --check src/ tests/

test: $(VENV)/bin/activate
	$(VENV)/bin/pytest tests/ -v --cov=src --cov=rules --cov-report=xml --cov-report=term

generate-example: $(VENV)/bin/activate
	rm -f .skillsaw.yaml.example
	$(VENV)/bin/skillsaw --init
	mv .skillsaw.yaml .skillsaw.yaml.example

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	rm -rf .pytest_cache
	rm -rf .coverage
	rm -rf coverage.xml
	rm -rf htmlcov
	rm -rf $(VENV)

apm:
	uvx --from apm-cli@$(APM_VERSION) apm install

verify-apm: apm
	@echo "APM install and compile succeeded."
