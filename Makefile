.PHONY: up down test integration lint build lock
up:
	docker compose up --build -d
down:
	docker compose down
test:
	uv run pytest -m 'not integration and not live'
integration:
	uv run pytest -m integration
lint:
	uv run ruff check backend tests scripts
	uv run ruff format --check backend tests scripts
	cd frontend && npm run check
build:
	cd frontend && npm run build
lock:
	uv lock
	uv export --frozen --no-dev --no-emit-project --output-file requirements.lock
