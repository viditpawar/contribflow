"""Data models shared across the pipeline."""

import hashlib
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

ID_FIELDS = ("employer_id", "employee_id")
DATE_FIELDS = ("pay_period_start", "pay_period_end", "pay_date")
AMOUNT_FIELDS = ("gross_pay", "pretax_deferral", "roth_deferral", "employer_match")

# Every field a connector must map from the source file (D12).
INPUT_FIELDS = ID_FIELDS + DATE_FIELDS + AMOUNT_FIELDS


class CensusEmployee(BaseModel):
    employee_id: str
    employer_id: str
    date_of_birth: date
    pretax_election_pct: Decimal
    roth_election_pct: Decimal


class CanonicalContribution(BaseModel):
    """One normalized contribution record.

    A field that was missing or malformed in the source file is None, and
    field_errors records why (field name to reason code). record_id,
    source_file_id and content_hash are assigned when records are persisted.
    """

    connector_id: str
    source_row: int
    employer_id: str | None = None
    employee_id: str | None = None
    pay_period_start: date | None = None
    pay_period_end: date | None = None
    pay_date: date | None = None
    gross_pay: Decimal | None = None
    pretax_deferral: Decimal | None = None
    roth_deferral: Decimal | None = None
    employer_match: Decimal | None = None
    field_errors: dict[str, str] = {}

    @property
    def plan_year(self) -> int | None:
        # The annual limit applies by the calendar year the contribution is paid (D12).
        return self.pay_date.year if self.pay_date else None

    @property
    def record_key(self) -> tuple[str, str, date] | None:
        """The idempotency key (D14), or None if any part of it is missing."""
        if self.employer_id is None or self.employee_id is None or self.pay_period_end is None:
            return None
        return (self.employer_id, self.employee_id, self.pay_period_end)

    def content_hash(self) -> str:
        """sha256 of the normalized input fields, independent of file format (D14)."""
        text = "|".join(str(getattr(self, field)) for field in INPUT_FIELDS)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
