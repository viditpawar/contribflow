"""In memory record of what has been posted. Phase 3 adds a Postgres version
with the same methods, so the pipeline works with either."""

from decimal import Decimal

from contribflow.models import CanonicalContribution


class MemoryLedger:
    def __init__(self):
        self.posted_hashes = {}  # record_key -> content_hash
        self.year_to_date = {}  # (employer_id, employee_id, plan_year) -> deferral total
        self.file_results = {}  # file sha256 -> FileResult

    def posted_hash(self, record_key) -> str | None:
        return self.posted_hashes.get(record_key)

    def deferrals_year_to_date(self, employer_id: str, employee_id: str, plan_year: int) -> Decimal:
        return self.year_to_date.get((employer_id, employee_id, plan_year), Decimal("0.00"))

    def post(self, record: CanonicalContribution, file_id: str) -> None:
        self.posted_hashes[record.record_key] = record.content_hash()
        ytd_key = (record.employer_id, record.employee_id, record.plan_year)
        current = self.year_to_date.get(ytd_key, Decimal("0.00"))
        self.year_to_date[ytd_key] = current + record.pretax_deferral + record.roth_deferral

    def file_result(self, file_hash: str):
        return self.file_results.get(file_hash)

    def save_file_result(self, result) -> None:
        self.file_results[result.file_hash] = result
