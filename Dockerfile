FROM python:3.13-slim AS sqlite-runtime
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential ca-certificates && rm -rf /var/lib/apt/lists/*
COPY configs/sqlite-runtime.json configs/sqlite-runtime.json
COPY scripts/build_sqlite_runtime.py scripts/build_sqlite_runtime.py
RUN python scripts/build_sqlite_runtime.py --prefix /opt/airlock-sqlite --output /opt/airlock-sqlite/build-report.json

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
COPY --from=sqlite-runtime /opt/airlock-sqlite /opt/airlock-sqlite
COPY configs/sqlite-runtime.json configs/sqlite-runtime.json
RUN printf '%s\n' /opt/airlock-sqlite/lib > /etc/ld.so.conf.d/00-airlock-sqlite.conf && ldconfig
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home airlock && mkdir /data && chown 10001:10001 /data
COPY --chown=10001:10001 airlock airlock
COPY --from=console --chown=10001:10001 /build/airlock/console airlock/console
COPY --chown=10001:10001 scripts scripts
RUN python -m airlock.sqlite_runtime --pin-file configs/sqlite-runtime.json --build-report /opt/airlock-sqlite/build-report.json --output /opt/airlock-sqlite/linked-report.json
USER 10001:10001
CMD ["python","-m","uvicorn","airlock.api:create_app","--factory","--host","0.0.0.0","--port","8000","--no-access-log"]
