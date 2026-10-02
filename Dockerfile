FROM node:22-slim AS console
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY frontend frontend
COPY airlock/static airlock/static
COPY scripts/package_console.mjs scripts/package_console.mjs
RUN npm run build

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home airlock && mkdir /data && chown 10001:10001 /data
COPY --chown=10001:10001 airlock airlock
COPY --from=console --chown=10001:10001 /build/airlock/console airlock/console
COPY --chown=10001:10001 scripts scripts
USER 10001:10001
CMD ["python","-m","uvicorn","airlock.api:create_app","--factory","--host","0.0.0.0","--port","8000","--no-access-log"]
