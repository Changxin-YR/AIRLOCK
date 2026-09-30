FROM node:22.16.0-bookworm-slim AS web
WORKDIR /build
COPY apps/web/package*.json ./
RUN npm ci --ignore-scripts
COPY apps/web/ ./
RUN npm run build

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY airlock/ ./airlock/
COPY migrations/ ./migrations/
COPY policies/ ./policies/
COPY scripts/ ./scripts/
COPY alembic.ini pyproject.toml ./
COPY --from=web /build/dist ./apps/web/dist
USER 10001:10001
CMD ["python", "-m", "uvicorn", "airlock.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
