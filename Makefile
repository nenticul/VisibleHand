# VisibleHand Makefile
# Targets: test, lint, score, ingest, seed, migrate, run

PYTHON := .venv/Scripts/python.exe
PIP    := .venv/Scripts/pip.exe
PYTEST := $(PYTHON) -m pytest
UVICORN := $(PYTHON) -m uvicorn

.DEFAULT_GOAL := help

.PHONY: help test lint type-check score migrate seed run ingest clean install \
        worldstate worldstate-train worldstate-export

help:
	@echo "VisibleHand dev targets:"
	@echo "  make install       — create venv and install all dependencies"
	@echo "  make test          — run all tests (unit + integration)"
	@echo "  make lint          — ruff linting"
	@echo "  make type-check    — mypy strict type check"
	@echo "  make migrate       — run alembic migrations (upgrade head)"
	@echo "  make seed          — seed demo data into the DB"
	@echo "  make score CC=BR   — score a country (e.g. make score CC=BR)"
	@echo "  make ingest CC=BR  — ingest live data for a country"
	@echo "  make run           — start API server on port 8000"
	@echo "  make worldstate    — materialise VH-WSM features + embeddings + analogues"
	@echo "  make worldstate-train  — train hazard baselines + conformal calibrator"
	@echo "  make worldstate-export — export static world-state JSON to public/api"
	@echo "  make clean         — remove __pycache__, .pytest_cache, visiblehand.db"

install:
	python -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install scipy ruff mypy

test:
	$(PYTEST) tests/ -v --tb=short

test-unit:
	$(PYTEST) tests/test_scoring.py tests/test_nlp.py -v

test-api:
	$(PYTEST) tests/test_api.py tests/test_ingestion.py -v

lint:
	$(PYTHON) -m ruff check core/ api/ tests/ scripts/ --fix

type-check:
	$(PYTHON) -m mypy core/ api/ --ignore-missing-imports

migrate:
	$(PYTHON) -m alembic upgrade head

seed: migrate
	$(PYTHON) -m scripts.seed_demo_data

score:
	@if [ -z "$(CC)" ]; then echo "Usage: make score CC=BR"; exit 1; fi
	$(PYTHON) -m scripts.smoke_test $(CC)

ingest:
	@if [ -z "$(CC)" ]; then echo "Usage: make ingest CC=BR"; exit 1; fi
	$(PYTHON) -c "import asyncio; from core.ingestion.worldbank import fetch_world_bank; print(asyncio.run(fetch_world_bank('$(CC)')))"

run:
	$(UVICORN) api.main:app --reload --host 0.0.0.0 --port 8000

# ── VH-WSM World-State Model ──────────────────────────────────────────────────
worldstate:
	$(PYTHON) -m scripts.materialize_worldstate --date today --all
	$(PYTHON) -m scripts.build_analogue_index

worldstate-train: worldstate
	$(PYTHON) -m scripts.train_hazard_models --all
	$(PYTHON) -m scripts.evaluate_worldstate

worldstate-export:
	$(PYTHON) -m scripts.export_static_worldstate --out public/api

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -f visiblehand.db
