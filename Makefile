.PHONY: run install serve ui test lint fmt web

# One-command launch (install + build UI if needed + serve + open browser).
# Non-technical users: just run ./run.sh
run:
	./run.sh

install:
	uv sync --all-groups

# Build the production web UI (requires Node 20.19+ or 22.12+).
ui:
	cd frontend && npm install && npm run build

serve:
	uv run agentgymnasium serve --open

test:
	uv run pytest

lint:
	uv run ruff check .

fmt:
	uv run ruff format .

web:
	cd frontend && npm run dev
