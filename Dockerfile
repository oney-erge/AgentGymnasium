FROM node:22-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 AS uv

FROM python:3.12-slim-bookworm@sha256:0f5b26b9518d002b6173fd61daad821fa340635ebfec5bba471013f9ca114579 AS builder
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY backend/ ./backend/
COPY --from=frontend /build/backend/agentgymnasium/static ./backend/agentgymnasium/static
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-bookworm@sha256:0f5b26b9518d002b6173fd61daad821fa340635ebfec5bba471013f9ca114579 AS runtime
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 agentgymnasium
WORKDIR /app
COPY --from=builder --chown=agentgymnasium:agentgymnasium /app /app
RUN mkdir -p /app/runs && chown agentgymnasium:agentgymnasium /app/runs
USER agentgymnasium
EXPOSE 8765
VOLUME ["/app/runs"]
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=12 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=2)"]
CMD ["agentgymnasium", "serve", "--host", "0.0.0.0", "--port", "8765", "--no-reload"]
