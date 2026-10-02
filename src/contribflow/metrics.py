"""Prometheus metrics (D18, D24). prometheus_client adds the _total suffix to counters."""

from prometheus_client import Counter, Histogram, disable_created_metrics

from contribflow.pipeline import FileResult

# Drop the extra *_created timestamp series; nothing here uses them.
disable_created_metrics()

FILES_PROCESSED = Counter(
    "contribflow_files_processed",
    "Files received, by connector and status (processed, rejected or resubmitted).",
    ["connector", "status"],
)
FILES_REJECTED = Counter(
    "contribflow_files_rejected",
    "File level rejection reasons. A file failing two checks counts once per reason.",
    ["reason"],
)
RECORDS = Counter(
    "contribflow_records",
    "Records in processed files, by connector and outcome.",
    ["connector", "outcome"],
)
RECORDS_REJECTED = Counter(
    "contribflow_records_rejected",
    "Record rejection reasons. A record failing two rules counts once per rule.",
    ["connector", "rule"],
)
PROCESSING_SECONDS = Histogram(
    "contribflow_file_processing_seconds",
    "Time to process one file, including database work.",
    ["connector"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)


def record_file_result(result: FileResult, seconds: float) -> None:
    connector = result.connector_id
    PROCESSING_SECONDS.labels(connector).observe(seconds)

    # A resubmission changes nothing, so it must not count records a second time.
    if result.resubmitted:
        FILES_PROCESSED.labels(connector, "resubmitted").inc()
        return

    FILES_PROCESSED.labels(connector, result.outcome).inc()
    for reason in result.file_reasons:
        FILES_REJECTED.labels(reason).inc()
    for record in result.records:
        RECORDS.labels(connector, record.outcome).inc()
        for rule in record.reasons:
            RECORDS_REJECTED.labels(connector, rule).inc()


# Every reason code the pipeline can produce (D15, D24, D27, D28, D29).
FILE_REASONS = (
    "COLUMN_MISSING",
    "UNKNOWN_RECORD_TYPE",
    "UNREADABLE_FILE",
    "TRAILER_MISSING",
    "TRAILER_MALFORMED",
    "TRAILER_COUNT_MISMATCH",
    "TRAILER_TOTAL_MISMATCH",
)
RECORD_RULES = (
    "MISSING_FIELD",
    "MALFORMED_FIELD",
    "EMPLOYEE_NOT_IN_CENSUS",
    "ELECTION_MISMATCH",
    "DUPLICATE_PAY_PERIOD",
    "OVER_ANNUAL_LIMIT",
    "PLAN_YEAR_NOT_CONFIGURED",
)


def initialize_series(connector_ids: list[str]) -> None:
    """Create every label combination at 0 on startup.

    Prometheus increase() cannot see the first jump of a series that did not exist
    before, so a counter born at 5 would read as 0 on the dashboard (D30).
    """
    for connector in connector_ids:
        for status in ("processed", "rejected", "resubmitted"):
            FILES_PROCESSED.labels(connector, status)
        for outcome in ("accepted", "rejected", "already_posted"):
            RECORDS.labels(connector, outcome)
        for rule in RECORD_RULES:
            RECORDS_REJECTED.labels(connector, rule)
    for reason in FILE_REASONS:
        FILES_REJECTED.labels(reason)
