.DEFAULT_GOAL := help

VENV ?= .venv
BIN := $(VENV)/bin
COMPOSE ?= docker compose
ARGS ?=

.PHONY: help install test distill search search-judge search-eval backfill index-supabase docker-build docker-shell docker-test docker-distill docker-search docker-search-judge docker-search-eval docker-backfill docker-index-supabase docker-up-indexer docker-logs-indexer docker-stop-indexer

help:
	@printf "Targets:\n"
	@printf "  make install\n"
	@printf "  make test\n"
	@printf "  make distill ARGS='--file path/to/input.md --out-dir distill_out'\n"
	@printf "  make search ARGS='--db distill_out/chunks.sqlite --npz distill_out/embeddings.npz --query \"risk\"'\n"
	@printf "  make search-judge ARGS='--db distill_out/chunks.sqlite --npz distill_out/embeddings.npz --query \"risk\" --output eval/risk.md'\n"
	@printf "  make search-eval ARGS='--db distill_out/chunks.sqlite --npz distill_out/embeddings.npz --queries eval/queries.jsonl'\n"
	@printf "  make backfill ARGS='--db distill_out/chunks.sqlite'\n"
	@printf "  make index-supabase ARGS='--out-dir distill_out --poll-limit 25'\n"
	@printf "  make docker-build\n"
	@printf "  make docker-shell\n"
	@printf "  make docker-test\n"
	@printf "  make docker-distill ARGS='...'\n"
	@printf "  make docker-search ARGS='...'\n"
	@printf "  make docker-search-judge ARGS='...'\n"
	@printf "  make docker-search-eval ARGS='...'\n"
	@printf "  make docker-backfill ARGS='...'\n"
	@printf "  make docker-index-supabase ARGS='...'\n"
	@printf "  make docker-up-indexer\n"
	@printf "  make docker-logs-indexer\n"
	@printf "  make docker-stop-indexer\n"

install:
	python3 -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e .

test:
	$(BIN)/pytest -q

distill:
	$(BIN)/distill $(ARGS)

search:
	$(BIN)/distill-search $(ARGS)

search-judge:
	$(BIN)/python -m distill_tool.judge_cli $(ARGS)

search-eval:
	$(BIN)/python -m distill_tool.eval_cli $(ARGS)

backfill:
	$(BIN)/distill-backfill $(ARGS)

index-supabase:
	$(BIN)/distill-index-supabase $(ARGS)

docker-build:
	$(COMPOSE) build app

docker-shell:
	$(COMPOSE) run --rm app bash

docker-test:
	$(COMPOSE) run --rm app pytest -q

docker-distill:
	$(COMPOSE) run --rm app distill $(ARGS)

docker-search:
	$(COMPOSE) run --rm app distill-search $(ARGS)

docker-search-judge:
	$(COMPOSE) run --rm app python -m distill_tool.judge_cli $(ARGS)

docker-search-eval:
	$(COMPOSE) run --rm app python -m distill_tool.eval_cli $(ARGS)

docker-backfill:
	$(COMPOSE) run --rm app distill-backfill $(ARGS)

docker-index-supabase:
	$(COMPOSE) run --rm app distill-index-supabase $(ARGS)

docker-up-indexer:
	$(COMPOSE) up -d indexer

docker-logs-indexer:
	$(COMPOSE) logs -f indexer

docker-stop-indexer:
	$(COMPOSE) stop indexer
