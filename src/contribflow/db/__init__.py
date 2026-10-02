"""Postgres access with plain SQL (D13)."""

import uuid
from decimal import Decimal
from pathlib import Path

import psycopg

from contribflow.models import CanonicalContribution, CensusEmployee
from contribflow.pipeline import FileResult, RecordResult

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Any constant works; every processing transaction takes this lock (D29).
PROCESSING_LOCK_ID = 7_401_001


def apply_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))


def lock_for_processing(conn: psycopg.Connection) -> None:
    """Serialize file processing, so two files cannot both pass a year to date check.
    Released automatically when the transaction ends."""
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (PROCESSING_LOCK_ID,))


def replace_census(conn: psycopg.Connection, employees: list[CensusEmployee]) -> None:
    conn.execute("DELETE FROM census")
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO census (employee_id, employer_id, date_of_birth,"
            " pretax_election_pct, roth_election_pct) VALUES (%s, %s, %s, %s, %s)",
            [
                (
                    e.employee_id,
                    e.employer_id,
                    e.date_of_birth,
                    e.pretax_election_pct,
                    e.roth_election_pct,
                )
                for e in employees
            ],
        )


def load_census(conn: psycopg.Connection) -> dict[str, CensusEmployee]:
    rows = conn.execute(
        "SELECT employee_id, employer_id, date_of_birth, pretax_election_pct, roth_election_pct"
        " FROM census"
    ).fetchall()
    return {
        row[0]: CensusEmployee(
            employee_id=row[0],
            employer_id=row[1],
            date_of_birth=row[2],
            pretax_election_pct=row[3],
            roth_election_pct=row[4],
        )
        for row in rows
    }


def load_file_result(conn: psycopg.Connection, column: str, value: str) -> FileResult | None:
    # column is chosen by our code, never by a caller, so formatting it in is safe.
    assert column in ("file_id", "file_hash")
    row = conn.execute(
        "SELECT file_id, file_name, connector_id, file_hash, outcome, record_count, file_reasons"
        f" FROM files WHERE {column} = %s",
        (value,),
    ).fetchone()
    if row is None:
        return None

    records = conn.execute(
        "SELECT source_row, employee_id, outcome, reasons FROM record_results"
        " WHERE file_id = %s ORDER BY source_row",
        (row[0],),
    ).fetchall()
    return FileResult(
        file_id=str(row[0]),
        file_name=row[1],
        connector_id=row[2],
        file_hash=row[3],
        outcome=row[4],
        record_count=row[5],
        file_reasons=row[6],
        records=[RecordResult(r[0], r[1], r[2], r[3]) for r in records],
    )


class PostgresLedger:
    """Same methods as MemoryLedger. Must be used inside one transaction per file."""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def posted_hash(self, record_key) -> str | None:
        row = self.conn.execute(
            "SELECT content_hash FROM contributions"
            " WHERE employer_id = %s AND employee_id = %s AND pay_period_end = %s",
            record_key,
        ).fetchone()
        return row[0] if row else None

    def deferrals_year_to_date(self, employer_id: str, employee_id: str, plan_year: int) -> Decimal:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(pretax_deferral + roth_deferral), 0) FROM contributions"
            " WHERE employer_id = %s AND employee_id = %s AND plan_year = %s",
            (employer_id, employee_id, plan_year),
        ).fetchone()
        return row[0]

    def post(self, record: CanonicalContribution, file_id: str) -> None:
        self.conn.execute(
            "INSERT INTO contributions (record_id, source_file_id, source_row, connector_id,"
            " employer_id, employee_id, pay_period_start, pay_period_end, pay_date, plan_year,"
            " gross_pay, pretax_deferral, roth_deferral, employer_match, content_hash)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                uuid.uuid4(),
                file_id,
                record.source_row,
                record.connector_id,
                record.employer_id,
                record.employee_id,
                record.pay_period_start,
                record.pay_period_end,
                record.pay_date,
                record.plan_year,
                record.gross_pay,
                record.pretax_deferral,
                record.roth_deferral,
                record.employer_match,
                record.content_hash(),
            ),
        )

    def file_result(self, file_hash: str) -> FileResult | None:
        return load_file_result(self.conn, "file_hash", file_hash)

    def save_file_result(self, result: FileResult) -> None:
        self.conn.execute(
            "INSERT INTO files (file_id, file_hash, file_name, connector_id, outcome,"
            " record_count, file_reasons) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                result.file_id,
                result.file_hash,
                result.file_name,
                result.connector_id,
                result.outcome,
                result.record_count,
                result.file_reasons,
            ),
        )
        with self.conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO record_results (file_id, source_row, employee_id, outcome, reasons)"
                " VALUES (%s, %s, %s, %s, %s)",
                [
                    (result.file_id, r.source_row, r.employee_id, r.outcome, r.reasons)
                    for r in result.records
                ],
            )
