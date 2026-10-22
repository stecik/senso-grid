FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS backend
WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.5
COPY pyproject.toml uv.lock ./
COPY backend/ ./backend/
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim AS runtime
RUN groupadd --gid 10001 sensogrid && useradd --uid 10001 --gid sensogrid --create-home sensogrid
WORKDIR /app
COPY --from=backend /app/.venv /app/.venv
COPY --from=frontend /build/dist /app/static
RUN mkdir -p /app/data && chown -R sensogrid:sensogrid /app/data
ENV PATH="/app/.venv/bin:$PATH" SENSOGRID_DATA_DIR=/app/data SENSOGRID_STATIC_DIR=/app/static PYTHONUNBUFFERED=1
USER sensogrid
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["uvicorn", "sensogrid.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
