APM_VERSION := 0.12.4
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help venv format lint test clean update apm verify-apm generate-example generate-docs

help:
	@echo "Available targets:"
	@echo "  venv          - Create virtualenv and install dev dependencies"
	@echo "  format        - Fix code formatting with black"
	@echo "  lint          - Check code formatting with black"
	@echo "  test          - Run pytest tests"
	@echo "  clean         - Remove Python cache files and virtualenv"
	@echo "  generate-example - Regenerate .skillsaw.yaml.example from builtin rules"
	@echo "  generate-docs - Regenerate Builtin Rules section of README.md"
	@echo "  update        - Regenerate all generated files (APM, example config, docs)"
	@echo "  apm           - Install APM dependencies"
	@echo "  verify-apm    - Verify generated APM files are up to date"

$(VENV)/bin/activate: pyproject.toml
	test -d $(VENV) || python3 -m venv $(VENV)
	$(PIP) install -e '.[dev,vertexai,bedrock]'
	touch $(VENV)/bin/activate

venv: $(VENV)/bin/activate

format: $(VENV)/bin/activate
	$(VENV)/bin/black src/ tests/

lint: $(VENV)/bin/activate
	$(VENV)/bin/black --check src/ tests/

test: $(VENV)/bin/activate
	$(VENV)/bin/pytest tests/ -v --cov=src --cov=rules --cov-report=xml --cov-report=term

# Generate example config in a temp dir to avoid clobbering .skillsaw.yaml
generate-example: $(VENV)/bin/activate
	rm -f .skillsaw.yaml.example
	$(eval TMPDIR := $(shell mktemp -d))
	$(VENV)/bin/skillsaw init $(TMPDIR)
	mv $(TMPDIR)/.skillsaw.yaml .skillsaw.yaml.example
	rm -rf $(TMPDIR)

generate-docs: $(VENV)/bin/activate
	$(PYTHON) scripts/generate-docs.py

generate-claude-readme: $(VENV)/bin/activate
	$(VENV)/bin/skillsaw docs --format markdown -o .claude/README.md

self-lint: $(VENV)/bin/activate
	$(VENV)/bin/skillsaw lint .

update: apm generate-example generate-docs generate-claude-readme format self-lint

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
