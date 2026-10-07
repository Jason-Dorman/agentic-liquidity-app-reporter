# Front door for every command (T-22). Each target is one line over uv.
# `make` with no target prints this list.

.DEFAULT_GOAL := help
.PHONY: help setup test lint check run pull render

help: ## List the targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  %-8s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Install dependencies: uv sync
	uv sync

test: ## Run every test: uv run pytest
	uv run pytest

lint: ## Lint: uv run ruff check src tests
	uv run ruff check src tests

check: lint test ## Lint, then test. The gate before every commit

run: ## Full run: health, pull, derive, agent, render, save
	uv run daily-review run

pull: ## Save the data pack and derived.json, no agent: daily-review pull-only
	uv run daily-review pull-only

render: ## Re-render a saved report: make render DATE=YYYY-MM-DD
	@test -n "$(DATE)" || { echo "usage: make render DATE=YYYY-MM-DD" >&2; exit 1; }; uv run daily-review render reports/$(DATE).json
