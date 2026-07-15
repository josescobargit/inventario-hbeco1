PYTHON ?= python3.12
VENV := .venv
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
ALEMBIC := $(VENV)/bin/alembic
UVICORN := $(VENV)/bin/uvicorn

.PHONY: setup test lint backend frontend build db-up db-down db-schema db-current db-seed db-validate db-check

setup:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -r backend/requirements-dev.txt
	cd frontend && npm install

test:
	PYTHONPATH=backend $(PYTEST) backend/tests
	cd frontend && npm test -- --run

lint:
	$(VENV)/bin/ruff check backend
	$(VENV)/bin/ruff format --check backend
	cd frontend && npm run lint

backend:
	PYTHONPATH=backend $(UVICORN) app.main:app --reload --host 127.0.0.1 --port 8000

frontend:
	cd frontend && npm run dev

build:
	cd frontend && npm run build

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

db-schema:
	PYTHONPATH=backend $(ALEMBIC) -c database/alembic.ini upgrade head

db-current:
	PYTHONPATH=backend $(ALEMBIC) -c database/alembic.ini current

db-seed:
	PYTHONPATH=backend $(VENV)/bin/python backend/scripts/seed_products.py

db-validate:
	PYTHONPATH=backend $(ALEMBIC) -c database/alembic.ini upgrade head --sql > /tmp/inventario-schema.sql
	@test -s /tmp/inventario-schema.sql

db-check:
	PYTHONPATH=backend $(VENV)/bin/python backend/scripts/check_db.py
