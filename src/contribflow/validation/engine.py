"""Decide the outcome of one record: accepted, rejected or already_posted."""

from contribflow.config import Limits
from contribflow.models import CanonicalContribution, CensusEmployee
from contribflow.validation import rules


def validate_record(
    record: CanonicalContribution, census: dict[str, CensusEmployee], limits: Limits, ledger
) -> tuple[str, list[str]]:
    # A record identical to one already posted is a harmless replay (D14).
    if record.record_key is not None:
        if ledger.posted_hash(record.record_key) == record.content_hash():
            return "already_posted", []

    employee = rules.find_employee(record, census)
    reasons = set(record.field_errors.values())
    for reason in (
        rules.check_in_census(record, employee),
        rules.check_election(record, employee, limits.election_tolerance),
        rules.check_duplicate(record, ledger),
        rules.check_annual_limit(record, employee, limits, ledger),
    ):
        if reason is not None:
            reasons.add(reason)

    if reasons:
        return "rejected", sorted(reasons)
    return "accepted", []
