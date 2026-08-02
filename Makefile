.PHONY: dev up down logs ps install check test api-test web-test agent-test recovery-test source-check license-check release-check

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
recovery-test:
	sh deploy/tests/m6-recovery-integration.sh
source-check:
	python scripts/source_release.py check
	python -m pytest apps/api/tests/test_source_release.py
license-check:
	python scripts/dependency_licenses.py --output dist/dependency-licenses.json
	reuse lint
release-check: check source-check license-check
	python scripts/release.py check --version 0.6.1
	sh deploy/tests/m6-release-policy.sh
