"""Integration tests against a real Postgres.

Skipped unless TEST_DATABASE_URL is set. Locally:
    docker compose up -d db
    export TEST_DATABASE_URL=postgresql://contribflow:contribflow@localhost:5432/contribflow_test
    uv run pytest
The database is wiped before each test, so never point this at the dev database.
"""

import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from contribflow import api, db
from contribflow.connector import load_connector
from contribflow.pipeline import process_file
from tests.oracle import assert_matches_manifest

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture
def conn():
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        db.apply_schema(conn)
        yield conn


def process_in_transaction(conn, path, connector_id, limits):
    """What the API does for one upload: lock, load census, process, commit."""
    with conn.transaction():
        db.lock_for_processing(conn)
        census = db.load_census(conn)
        ledger = db.PostgresLedger(conn)
        connector = load_connector(connector_id)
        return process_file(path.name, path.read_bytes(), connector, census, limits, ledger)


def count_contributions(conn):
    return conn.execute("SELECT count(*) FROM contributions").fetchone()[0]


def test_postgres_pipeline_matches_expected_outcomes(conn, sample, census, limits):
    out, manifest = sample
    db.replace_census(conn, list(census.values()))

    for entry in manifest["files"]:
        result = process_in_transaction(conn, out / entry["file"], entry["connector"], limits)
        assert_matches_manifest(entry, result)

        stored = db.load_file_result(conn, "file_id", result.file_id)
        assert stored.records == result.records


def test_postgres_resubmission_and_reexport_post_nothing(conn, sample, census, limits, tmp_path):
    out, manifest = sample
    db.replace_census(conn, list(census.values()))
    first = manifest["files"][0]
    path = out / first["file"]

    original = process_in_transaction(conn, path, first["connector"], limits)
    posted = count_contributions(conn)
    assert posted == original.count("accepted")

    again = process_in_transaction(conn, path, first["connector"], limits)
    assert again.resubmitted
    assert again.file_id == original.file_id

    reexport = tmp_path / first["file"]
    reexport.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    result = process_in_transaction(conn, reexport, first["connector"], limits)
    assert result.count("already_posted") == original.count("accepted")
    assert count_contributions(conn) == posted


def test_api_end_to_end(conn, sample, monkeypatch):
    out, manifest = sample
    monkeypatch.setattr(api, "DATABASE_URL", DATABASE_URL)

    with TestClient(api.app) as client:
        census_bytes = (out / "census.csv").read_bytes()
        response = client.put("/census", files={"file": ("census.csv", census_bytes)})
        assert response.json() == {"employees": 150}

        first = manifest["files"][0]
        upload = {"file": (first["file"], (out / first["file"]).read_bytes())}
        params = {"connector_id": first["connector"]}
        summary = client.post("/files", params=params, files=upload).json()
        assert summary["accepted"] == 45
        assert summary["rejected"] == 5
        assert summary["resubmitted"] is False

        again = client.post("/files", params=params, files=upload).json()
        assert again["resubmitted"] is True
        assert again["file_id"] == summary["file_id"]

        report = client.get(f"/files/{summary['file_id']}/report").json()
        assert len(report["records"]) == 50

        csv_report = client.get(f"/files/{summary['file_id']}/report", params={"format": "csv"})
        assert csv_report.text.splitlines()[0] == "source_row,employee_id,outcome,reasons"

        assert client.get("/files/not-a-uuid/report").status_code == 404
        bad = client.post("/files", params={"connector_id": "nope"}, files=upload)
        assert bad.status_code == 400


def metric_value(text, name, labels):
    for line in text.splitlines():
        if line.startswith(name + "{") and all(f'{k}="{v}"' in line for k, v in labels.items()):
            return float(line.rsplit(" ", 1)[1])
    return 0.0


def test_api_metrics(conn, sample, monkeypatch):
    out, _ = sample
    monkeypatch.setattr(api, "DATABASE_URL", DATABASE_URL)

    with TestClient(api.app) as client:
        client.put("/census", files={"file": ("census.csv", (out / "census.csv").read_bytes())})
        before = client.get("/metrics/").text

        bad_name = "provider_c_2026-01-23_bad_trailer.dat"
        upload = {"file": (bad_name, (out / bad_name).read_bytes())}
        client.post("/files", params={"connector_id": "provider_c"}, files=upload)
        after = client.get("/metrics/").text

    name = "contribflow_files_rejected_total"
    labels = {"reason": "TRAILER_TOTAL_MISMATCH"}
    assert metric_value(after, name, labels) == metric_value(before, name, labels) + 1
    # A rejected file posts no records, so no record metrics move.
    record_labels = {"connector": "provider_c", "outcome": "accepted"}
    assert metric_value(after, "contribflow_records_total", record_labels) == metric_value(
        before, "contribflow_records_total", record_labels
    )
