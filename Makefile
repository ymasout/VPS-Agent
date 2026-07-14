.PHONY: dev up down logs ps install check test api-test web-test agent-test

dev: up
up:
	docker compose up --build
down:
	docker compose down
logs:
	docker compose logs -f
ps:
	docker compose ps
install:
	pnpm install
	python -m pip install -r apps/api/requirements-dev.txt
check: web-test api-test agent-test
	pnpm lint:web
	python -m ruff check apps/api
	cd apps/agent && go vet ./...
	pnpm build:web
test: web-test api-test agent-test
web-test:
	pnpm test:web
api-test:
	python -m pytest apps/api/tests
agent-test:
	cd apps/agent && go test ./...
