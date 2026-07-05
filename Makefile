APM_VERSION := 0.24.0
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help venv format lint test clean update apm verify-apm generate-example generate-docs generate-site-content serve-site build-site benchmark benchmark-save benchmark-compare profile badge self-lint

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
	@echo "  verify-apm    - Non-destructively verify agent dirs match APM sources (injection/drift gate)"
	@echo "  benchmark     - Benchmark linting speed on a synthetic repo (SCALE=medium)"
	@echo "  benchmark-save    - Save benchmark results as the local baseline"
	@echo "  benchmark-compare - Compare against the local baseline (fails on regression)"
	@echo "  profile       - Profile a lint run with cProfile and print hotspots"

$(VENV)/bin/activate: pyproject.toml
	test -d $(VENV) || python3 -m venv $(VENV)
	$(PIP) install -e '.[dev,docs]'
	touch $(VENV)/bin/activate

venv: $(VENV)/bin/activate

format: $(VENV)/bin/activate
	$(VENV)/bin/black src/ tests/

lint: $(VENV)/bin/activate
	$(VENV)/bin/black --check src/ tests/

test: $(VENV)/bin/activate
	$(VENV)/bin/pytest tests/ -v --cov=src --cov-report=xml --cov-report=term

# Generate example config in a temp dir to avoid clobbering .skillsaw.yaml
generate-example: $(VENV)/bin/activate
	rm -f .skillsaw.yaml.example
	$(eval TMPDIR := $(shell mktemp -d))
	$(VENV)/bin/skillsaw init $(TMPDIR)
	mv $(TMPDIR)/.skillsaw.yaml .skillsaw.yaml.example
	rm -rf $(TMPDIR)

generate-docs: $(VENV)/bin/activate
	$(PYTHON) scripts/generate-docs.py

badge: $(VENV)/bin/activate
	$(VENV)/bin/skillsaw badge .

self-lint: $(VENV)/bin/activate badge
	$(VENV)/bin/skillsaw lint .

update: apm generate-example generate-docs generate-site-content format self-lint

generate-site-content: $(VENV)/bin/activate
	$(PYTHON) scripts/generate-site-content.py

serve-site: generate-site-content
	$(VENV)/bin/mkdocs serve

build-site: generate-site-content
	$(VENV)/bin/mkdocs build

SCALE ?= medium
BENCH_BASELINE ?= .benchmarks/baseline.json

benchmark: $(VENV)/bin/activate
	$(PYTHON) benchmarks/bench.py --scale $(SCALE)

benchmark-save: $(VENV)/bin/activate
	$(PYTHON) benchmarks/bench.py --scale $(SCALE) --save $(BENCH_BASELINE)

benchmark-compare: $(VENV)/bin/activate
	$(PYTHON) benchmarks/bench.py --scale $(SCALE) --compare $(BENCH_BASELINE)

profile: $(VENV)/bin/activate
	$(PYTHON) benchmarks/bench.py --scale $(SCALE) --profile

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
	uvx --from apm-cli@$(APM_VERSION) apm compile

verify-apm:
	APM_VERSION=$(APM_VERSION) ./scripts/verify-apm.sh
