import hmac
import queue
import threading
import traceback
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from api.config import settings
from api.paths import BASE_JOBS_DIR
from api.pipeline.run import run_pipeline


class CreateJobResponse(BaseModel):
    job_id: str = Field(..., description="unique job ID", examples=["550e8400-e29b-41d4-a716-446655440000"])
    status: str = Field(..., description="status of job", examples=["queued"])


class OutputFormat(str, Enum):
    geojson = "GeoJSON"
    gpkg = "GPKG"


API_KEY = settings.api_key


def verify_api_key(request: Request):
    api_key = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        api_key = auth_header.split(" ", 1)[1]

    if not api_key:
        api_key = request.query_params.get("api_key")

    if not api_key or not hmac.compare_digest(api_key, API_KEY):
        raise HTTPException(status_code=401, detail="unauthorized: invalid api key")


# ======================================================================================================================
# Jobs + Worker
# ======================================================================================================================

Job = Dict[str, Any]
JOBS: Dict[str, Job] = {}
JOB_QUEUE: "queue.Queue[str]" = queue.Queue()
JOBS_LOCK = threading.Lock()


def job_worker():
    while True:
        try:
            job_id = JOB_QUEUE.get(timeout=0.5)
        except queue.Empty:
            continue

        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if not job:
                JOB_QUEUE.task_done()
                continue
            job["status"] = "running"
            job["started_at"] = datetime.now(timezone.utc).isoformat()

        try:
            outputs = run_pipeline(
                od_clusters_a=Path(job.get("od_clusters_a")),
                od_clusters_b=Path(job.get("od_clusters_b")),
                od_table=Path(job.get("od_table")),
                stops=Path(job.get("stops")),

                od_clusters_a_id_field=job.get("od_clusters_a_id_field"),
                od_clusters_a_count_field=job.get("od_clusters_a_count_field"),
                od_clusters_b_id_field=job.get("od_clusters_b_id_field"),
                od_clusters_b_count_field=job.get("od_clusters_b_count_field"),
                od_table_a_id_field=job.get("od_table_a_id_field"),
                od_table_b_id_field=job.get("od_table_b_id_field"),
                od_table_trips_field=job.get("od_table_trips_field"),

                netascore_gpkg=Path(job.get("netascore_gpkg")) if job.get("netascore_gpkg") else None,
                output_format=job.get("output_format"),
                seed=job.get("seed"),

                job_dir=Path(job.get("job_dir")),
            )
            with JOBS_LOCK:
                job["status"] = "done"
                job["outputs"] = {k: str(v) for k, v in outputs.items()}
                job["finished_at"] = datetime.now(timezone.utc).isoformat()
        except Exception as e:
            with JOBS_LOCK:
                job["status"] = "failed"
                job["error"] = str(e)
                job["traceback"] = traceback.format_exc()
                job["finished_at"] = datetime.now(timezone.utc).isoformat()
        finally:
            JOB_QUEUE.task_done()


WORKER_THREAD = threading.Thread(target=job_worker, daemon=True)
WORKER_THREAD.start()

# ======================================================================================================================
# FastAPI
# ======================================================================================================================

app = FastAPI()
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.post("/jobs", response_model=CreateJobResponse, dependencies=[Depends(verify_api_key)])
async def create_job(
        od_clusters_a: UploadFile = File(..., description="origin clusters file", examples=["b_klynger.gpkg"]),
        od_clusters_b: UploadFile = File(..., description="destination clusters file", examples=["a_klynger.gpkg"]),
        od_table: UploadFile = File(..., description="origin-destination table file", examples=["Data_2023_0099_Tabel_1.csv"]),
        stops: UploadFile = File(..., description="public transport stops file", examples=["dynlayer.gpkg"]),

        od_clusters_a_id_field: str = Form(..., description="id field for origin clusters", examples=["klynge_id"]),
        od_clusters_a_count_field: str = Form(..., description="count field for origin clusters", examples=["Beboere"]),
        od_clusters_b_id_field: str = Form(..., description="id field for destination clusters", examples=["klynge_id"]),
        od_clusters_b_count_field: str = Form(..., description="count field for destination clusters", examples=["Arbejdere"]),
        od_table_a_id_field: str = Form(..., description="id field for origin clusters in origin-destination table", examples=["Bopael_klynge_id"]),
        od_table_b_id_field: str = Form(..., description="id field for destination clusters in origin-destination table", examples=["Arbejde_klynge_id"]),
        od_table_trips_field: str = Form(..., description="trips field in origin-destination table", examples=["Antal"]),

        netascore_gpkg: Optional[UploadFile] = File(None, description="pre-generated netascore file"),
        output_format: Optional[OutputFormat] = Form(OutputFormat.geojson, description="output format"),
        seed: Optional[int] = Form(None, description="random seed for reproducibility of results"),
):
    job_id = str(uuid.uuid4())
    job_dir = (BASE_JOBS_DIR / job_id)
    job_dir.mkdir(parents=True, exist_ok=True)

    od_clusters_a_path = job_dir / f"od_clusters_a{Path(od_clusters_a.filename).suffix}"
    od_clusters_a_path.write_bytes(await od_clusters_a.read())

    od_clusters_b_path = job_dir / f"od_clusters_b{Path(od_clusters_b.filename).suffix}"
    od_clusters_b_path.write_bytes(await od_clusters_b.read())

    od_table_path = job_dir / f"od_table{Path(od_table.filename).suffix}"
    od_table_path.write_bytes(await od_table.read())

    stops_path = job_dir / f"stops{Path(stops.filename).suffix}"
    stops_path.write_bytes(await stops.read())

    netascore_gpkg_path = None
    if netascore_gpkg:
        netascore_gpkg_path = job_dir / f"netascore{Path(netascore_gpkg.filename).suffix}"
        netascore_gpkg_path.write_bytes(await netascore_gpkg.read())

    job = {
        "job_id": job_id,
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "job_dir": str(job_dir),

        "od_clusters_a": str(od_clusters_a_path),
        "od_clusters_b": str(od_clusters_b_path),
        "od_table": str(od_table_path),
        "stops": str(stops_path),

        "od_clusters_a_id_field": od_clusters_a_id_field,
        "od_clusters_a_count_field": od_clusters_a_count_field,
        "od_clusters_b_id_field": od_clusters_b_id_field,
        "od_clusters_b_count_field": od_clusters_b_count_field,
        "od_table_a_id_field": od_table_a_id_field,
        "od_table_b_id_field": od_table_b_id_field,
        "od_table_trips_field": od_table_trips_field,

        "netascore_gpkg": str(netascore_gpkg_path) if netascore_gpkg_path else None,
        "output_format": output_format,
        "seed": seed,
    }

    with JOBS_LOCK:
        JOBS[job_id] = job
    JOB_QUEUE.put(job_id)

    return CreateJobResponse(job_id=job_id, status=job["status"])


@app.get("/jobs/{job_id}", dependencies=[Depends(verify_api_key)])
def get_job(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return {k: v for k, v in job.items() if k in {"job_id", "status", "created_at", "started_at", "error", "finished_at"}}


@app.get("/jobs/{job_id}/downloads", dependencies=[Depends(verify_api_key)])
def list_downloads(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.get("status") != "done":
        raise HTTPException(status_code=409, detail=f"job not finished (status={job.get('status')})")

    outputs: dict[str, str] = job.get("outputs") or {}
    result = []
    for key, path_str in outputs.items():
        p = Path(path_str)
        if p.exists():
            result.append({
                "key": key,
                "filename": p.name,
                "download_url": f"/jobs/{job_id}/download/{key}",
            })

    return JSONResponse(result)


@app.get("/jobs/{job_id}/download/{key}", dependencies=[Depends(verify_api_key)])
def download_output(job_id: str, key: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.get("status") != "done":
        raise HTTPException(status_code=409, detail=f"job not finished (status={job.get('status')})")

    outputs: dict[str, str] = job.get("outputs") or {}
    path_str = outputs.get(key)
    if not path_str:
        raise HTTPException(status_code=404, detail=f"key not found")

    out_path = Path(path_str)
    if not out_path.exists():
        raise HTTPException(status_code=500, detail="file not found")

    return FileResponse(out_path, filename=out_path.name)
