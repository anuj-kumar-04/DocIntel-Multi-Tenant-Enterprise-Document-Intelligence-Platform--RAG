.PHONY: help up down build logs restart migrate revision test test-cov lint format seed eval

help:
	@echo "DocIntel Makefile Commands:"
	@echo "  make up          - Start all containers with Docker Compose"
	@echo "  make down        - Stop and tear down all containers"
	@echo "  make build       - Rebuild Docker images"
	@echo "  make logs        - Tail live logs from all containers"
	@echo "  make migrate     - Run database migrations via Alembic"
	@echo "  make revision    - Create a new Alembic migration revision"
	@echo "  make test        - Run test suite with pytest"
	@echo "  make test-cov    - Run tests with code coverage"
	@echo "  make lint        - Run Ruff and Mypy code checks"
	@echo "  make format      - Format code with Ruff"
	@echo "  make seed        - Populate database with realistic demo data"
	@echo "  make eval        - Run the RAGAS golden dataset benchmark"

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

restart:
	docker compose restart

migrate:
	docker compose exec api alembic upgrade head

revision:
	docker compose exec api alembic revision --autogenerate -m "$(m)"

test:
	pytest backend/tests/ -v

test-cov:
	pytest backend/tests/ --cov=backend/app --cov-report=term-missing

lint:
	ruff check backend/app backend/tests
	mypy backend/app

format:
	ruff format backend/app backend/tests

seed:
	python backend/app/scripts/seed.py

eval:
	python eval/run_eval.py
