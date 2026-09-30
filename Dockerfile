FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY apps/web/package*.json ./
RUN npm ci --ignore-scripts
COPY apps/web/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home airlock
COPY airlock/ airlock/
COPY policies/ policies/
COPY --from=web /web/dist apps/web/dist
USER 10001:10001
EXPOSE 8080 8090
CMD ["python", "-m", "airlock.cli", "gateway", "--host", "0.0.0.0"]
