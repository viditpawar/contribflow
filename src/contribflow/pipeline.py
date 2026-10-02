"""Process one payroll file end to end: parse, normalize, check, validate, post."""

import dataclasses
import hashlib
import uuid
from dataclasses import dataclass, field

from contribflow.config import Limits
from contribflow.connector import Connector
from contribflow.models import CensusEmployee
from contribflow.parsing import parse_file
from contribflow.parsing.file_checks import check_trailer
from contribflow.parsing.normalize import normalize
from contribflow.validation.engine import validate_record


@dataclass
class RecordResult:
    source_row: int
    employee_id: str | None
    outcome: str  # accepted, rejected or already_posted
    reasons: list[str]


@dataclass
class FileResult:
    file_id: str
    file_name: str
    connector_id: str
    file_hash: str
    outcome: str  # processed or rejected
    record_count: int
    file_reasons: list[str] = field(default_factory=list)
    records: list[RecordResult] = field(default_factory=list)
    # True when these exact bytes were processed before and this is the stored result.
    resubmitted: bool = False

    def count(self, outcome: str) -> int:
        return sum(1 for r in self.records if r.outcome == outcome)


def process_file(
    file_name: str,
    content: bytes,
    connector: Connector,
    census: dict[str, CensusEmployee],
    limits: Limits,
    ledger,
) -> FileResult:
    file_hash = hashlib.sha256(content).hexdigest()
    previous = ledger.file_result(file_hash)
    if previous is not None:
        return dataclasses.replace(previous, resubmitted=True)

    result = FileResult(
        file_id=str(uuid.uuid4()),
        file_name=file_name,
        connector_id=connector.id,
        file_hash=file_hash,
        outcome="processed",
        record_count=0,
    )

    records = []
    try:
        # utf-8-sig also strips the byte order mark that spreadsheet exports often add.
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = None
        result.file_reasons = ["UNREADABLE_FILE"]

    if text is not None:
        parsed = parse_file(text, connector)
        records = [normalize(row, connector) for row in parsed.rows]
        result.record_count = len(records)
        result.file_reasons = list(parsed.file_errors)
        if parsed.trailer is not None:
            result.file_reasons += check_trailer(parsed.trailer, records, connector)

    # A rejected file posts nothing (D24).
    if result.file_reasons:
        result.outcome = "rejected"
    else:
        for record in records:
            outcome, reasons = validate_record(record, census, limits, ledger)
            if outcome == "accepted":
                ledger.post(record, result.file_id)
            result.records.append(
                RecordResult(record.source_row, record.employee_id, outcome, reasons)
            )

    ledger.save_file_result(result)
    return result
