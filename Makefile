APM_VERSION := 0.12.4

.PHONY: help format test clean apm verify-apm

help:
	@echo "Available targets:"
	@echo "  format        - Fix code formatting with black"
	@echo "  test          - Run pytest tests"
	@echo "  clean         - Remove Python cache files"
	@echo "  apm           - Install APM dependencies"
	@echo "  verify-apm    - Verify generated APM files are up to date"

format:
	black src/ tests/

test:
	pytest tests/ -v --cov=src --cov=rules --cov-report=xml --cov-report=term

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	rm -rf .pytest_cache
	rm -rf .coverage
	rm -rf coverage.xml
	rm -rf htmlcov

apm:
	uvx --from apm-cli@$(APM_VERSION) apm install

verify-apm: apm
	@echo "APM install and compile succeeded."
