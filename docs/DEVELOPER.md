# Developer Guide (Setup & Deployment)

This guide explains how to run the CITWIN API locally and on a server.

---

## Architecture overview

- **FastAPI app:** `api/app.py`
- **Job execution model:** in-process queue + background worker thread (`JOB_QUEUE`, `job_worker`)
- **Pipelines:**
  - `pipeline_access` → `run_pipeline_access(...)`
  - `pipeline_access_simple` → `run_pipeline_access_simple(...)`
  - `pipeline_netascore` → `run_pipeline_netascore(...)`
- **Storage:** per-job working directory under `JOBS_DIR` (see `api/paths.py`)
- **Cleanup:** a background thread removes job folders older than ~31 days

---

## Configuration (environment variables)

The app reads environment variables via `pydantic-settings` (`api/config.py`).

Required variables:

- `API_KEY` – API key used for `x-api-key` header auth
- `DB_HOST`
- `DB_PORT`
- `DB_NAME`
- `DB_USERNAME`
- `DB_PASSWORD`

Optional:

- `API_ROOT_PATH` – set the FastAPI `root_path` (default: `/`)

Example files provided:

- `.env.local.example` – for local runs
- `.env.docker.example` – for Docker Compose (uses the bundled PostGIS container)
- `.env.deploy.example` – for the provided deploy scripts

---

## Local development (without Docker)

### 1) Create your env file

Copy:
```bash
cp .env.local.example .env.local
```

Fill in:
- `API_KEY`
- your database connection info (Postgres/PostGIS if required by NetAScore steps)

### 2) Install dependencies

Option A – conda (recommended for local development):
```bash
conda env create -f environment.yml
conda activate citwin-api
```

Option B – pip:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3) Run the API

```bash
python main.py
```

This starts uvicorn with:
- host: `localhost`
- port: `8000`
- reload: enabled

Swagger UI is available at:
- `http://localhost:8000/docs`

---

## Docker (recommended for servers)

The repository includes a Dockerfile that installs GDAL and related tools.

### 1) Create `.env.docker`

```bash
cp .env.docker.example .env.docker
```

### 2) Start services

```bash
docker compose up --build
```

This starts:
- `web` (the FastAPI API)
- `netascore-db` (PostGIS: `postgis/postgis:17-3.5`)

By default, the API is reachable at:
- `http://localhost:8000`

---

## Production notes

### API key security
- The API uses a simple API-key header check (`x-api-key`) with constant-time compare.
- Put the API behind HTTPs and keep the key out of logs.

### Root path behind a reverse proxy
If you mount the API under a sub-path (e.g. `/citwin`), set:
- `API_ROOT_PATH=/citwin`

This is passed into `FastAPI(root_path=...)` so OpenAPI docs and URLs work correctly behind the proxy.

### Concurrency and scaling
- The API uses an **in-process** worker thread and queue. With `--workers 1` (default), only one job runs at a time.
- If you increase uvicorn workers, each worker has its own in-memory queue and job store.  
  For multi-worker / multi-instance scaling, you would typically move jobs to an external queue (Redis/RQ, Celery, etc.) and store job metadata in a database.

### Job retention
- A cleanup thread deletes jobs older than ~31 days from disk.

---

## Deployment scripts

The repo contains:
- `deploy.sh`
- `undeploy.sh`
- `.env.deploy.example`

These appear designed to:
- clone/pull the repo on a remote host,
- configure environment,
- run the API (commonly via Docker) under a deployment path.

Check the scripts before use and adapt to your infrastructure (systemd, Docker Compose, Kubernetes, etc.).

---

## Troubleshooting

### GDAL / GeoPandas issues
If running without Docker, you may need system packages for GDAL that match the Python wheels/headers. Using Docker avoids most of these issues.
