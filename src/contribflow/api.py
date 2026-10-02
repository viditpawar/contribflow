"""HTTP API (D10). Each request opens its own database connection (D29).

Run locally:
    DATABASE_URL=postgresql://contribflow:contribflow@localhost:5432/contribflow \
        uv run uvicorn contribflow.api:app --reload
"""

import csv
import dataclasses
import io
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from prometheus_client import make_asgi_app

from contribflow import db, metrics
from contribflow.config import load_census_text, load_limits
from contribflow.connector import CONNECTORS_DIR, load_connector
from contribflow.pipeline import FileResult, process_file

DATABASE_URL = os.environ.get("DATABASE_URL", "")
LIMITS_PATH = Path(os.environ.get("CONTRIBFLOW_LIMITS", "config/limits.yaml"))
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    with connect() as conn:
        db.apply_schema(conn)
    metrics.initialize_series(sorted(path.stem for path in CONNECTORS_DIR.glob("*.yaml")))
    yield


app = FastAPI(title="contribflow", lifespan=lifespan)
app.mount("/metrics", make_asgi_app())


async def read_upload(upload: UploadFile) -> bytes:
    content = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"file larger than {MAX_UPLOAD_BYTES} bytes")
    return content


def file_summary(result: FileResult) -> dict:
    return {
        "file_id": result.file_id,
        "file_name": result.file_name,
        "connector_id": result.connector_id,
        "outcome": result.outcome,
        "resubmitted": result.resubmitted,
        "record_count": result.record_count,
        "file_reasons": result.file_reasons,
        "accepted": result.count("accepted"),
        "rejected": result.count("rejected"),
        "already_posted": result.count("already_posted"),
    }


@app.get("/healthz")
def healthz():
    with connect() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@app.put("/census")
async def put_census(file: UploadFile):
    try:
        employees = load_census_text((await read_upload(file)).decode("utf-8-sig"))
    except ValueError as error:  # includes decode and pydantic validation errors
        raise HTTPException(400, f"invalid census file: {error}") from error
    with connect() as conn, conn.transaction():
        # Same lock as file processing, so the census never changes mid file.
        db.lock_for_processing(conn)
        db.replace_census(conn, list(employees.values()))
    return {"employees": len(employees)}


@app.post("/files")
async def post_file(connector_id: str, file: UploadFile):
    known = {path.stem for path in CONNECTORS_DIR.glob("*.yaml")}
    if connector_id not in known:
        raise HTTPException(400, f"unknown connector_id; expected one of {sorted(known)}")
    content = await read_upload(file)
    connector = load_connector(connector_id)
    limits = load_limits(LIMITS_PATH)

    started = time.perf_counter()
    with connect() as conn, conn.transaction():
        db.lock_for_processing(conn)
        census = db.load_census(conn)
        ledger = db.PostgresLedger(conn)
        result = process_file(file.filename or "upload", content, connector, census, limits, ledger)
    # Recorded only after the commit, so a failed transaction is never counted.
    metrics.record_file_result(result, time.perf_counter() - started)
    return file_summary(result)


@app.get("/files/{file_id}/report")
def get_report(file_id: str, format: str = "json"):
    with connect() as conn:
        try:
            result = db.load_file_result(conn, "file_id", file_id)
        except psycopg.errors.InvalidTextRepresentation:
            result = None  # not a valid UUID
    if result is None:
        raise HTTPException(404, "file not found")

    if format == "csv":
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(["source_row", "employee_id", "outcome", "reasons"])
        for r in result.records:
            writer.writerow([r.source_row, r.employee_id or "", r.outcome, ";".join(r.reasons)])
        return PlainTextResponse(out.getvalue(), media_type="text/csv")

    return {**file_summary(result), "records": [dataclasses.asdict(r) for r in result.records]}
