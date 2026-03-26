# =============================================================================
# AgentLake — Project Makefile
# =============================================================================

.DEFAULT_GOAL := help

COMPOSE := docker compose
BACKEND := backend
FRONTEND := frontend

# ---------------------------------------------------------------------------
# Docker Compose
# ---------------------------------------------------------------------------
.PHONY: up down logs build restart reset

up: ## Start all services in the background
	$(COMPOSE) up -d

down: ## Stop all services
	$(COMPOSE) down

logs: ## Follow logs for all services
	$(COMPOSE) logs -f

build: ## Build all Docker images
	$(COMPOSE) build

restart: ## Restart all services
	$(COMPOSE) restart

reset: ## Destroy volumes and recreate infrastructure from scratch
	$(COMPOSE) down -v
	$(COMPOSE) up -d postgres redis minio
	@echo "Waiting for infrastructure services to become healthy..."
	@sleep 5
	$(MAKE) migrate
	$(MAKE) seed
	$(COMPOSE) up -d

# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------
.PHONY: test-backend test-integration test-scale migrate seed fmt-backend lint-backend

test-backend: ## Run backend unit tests
	cd $(BACKEND) && python -m pytest tests/unit/ -v --tb=short

test-integration: ## Run integration tests (requires running services)
	cd $(BACKEND) && python -m pytest tests/integration/ -v --tb=short

test-scale: ## Run scale / load tests
	cd $(BACKEND) && python -m pytest tests/scale/ -v --tb=short

migrate: ## Run Alembic database migrations
	cd $(BACKEND) && alembic upgrade head

seed: ## Seed the database with development data
	cd $(BACKEND) && python -m agentlake.scripts.seed

fmt-backend: ## Auto-format backend code with ruff
	cd $(BACKEND) && ruff format src/ tests/

lint-backend: ## Lint backend code with ruff
	cd $(BACKEND) && ruff check src/ tests/

# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
.PHONY: test-frontend fmt-frontend lint-frontend

test-frontend: ## Run frontend unit tests
	cd $(FRONTEND) && npm test

fmt-frontend: ## Auto-format frontend code with prettier
	cd $(FRONTEND) && npx prettier --write src/

lint-frontend: ## Lint frontend code
	cd $(FRONTEND) && npm run lint

# ---------------------------------------------------------------------------
# Combined
# ---------------------------------------------------------------------------
.PHONY: test fmt lint

test: test-backend test-frontend ## Run all unit tests

fmt: fmt-backend fmt-frontend ## Auto-format all code

lint: lint-backend lint-frontend ## Lint all code

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------
.PHONY: shell-api shell-db backup help

shell-api: ## Open a shell inside the API container
	$(COMPOSE) exec api bash

shell-db: ## Open a psql session against the database
	$(COMPOSE) exec postgres psql -U agentlake -d agentlake

backup: ## Run the backup script
	./scripts/backup.sh

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
