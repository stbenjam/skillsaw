# Makefile for {{MARKETPLACE_NAME}}

.PHONY: help lint docs new-plugin

help: ## Show this help message
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

lint: ## Run plugin linter (verbose, strict mode)
	skillsaw -v --strict

docs: ## Generate documentation
	skillsaw docs --format html -o docs/

new-plugin: ## Create a new plugin (usage: make new-plugin NAME=my-plugin)
	@if [ -z "$(NAME)" ]; then \
		echo "Error: NAME is required. Usage: make new-plugin NAME=my-plugin"; \
		exit 1; \
	fi
	skillsaw add plugin $(NAME)

.DEFAULT_GOAL := help
