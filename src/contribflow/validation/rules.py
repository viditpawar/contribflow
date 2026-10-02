"""One function per validation rule (D15).

Each rule returns a reason code, or None if the record passes. A rule whose
inputs are missing or malformed returns None: that problem is already reported
as MISSING_FIELD or MALFORMED_FIELD, and guessing would add misleading reasons.
"""

from decimal import ROUND_HALF_UP, Decimal

from contribflow.config import Limits, PlanYearLimits
from contribflow.models import CanonicalContribution, CensusEmployee

CENTS = Decimal("0.01")


def percent_of(amount: Decimal, pct: Decimal) -> Decimal:
    return (amount * pct / 100).quantize(CENTS, rounding=ROUND_HALF_UP)


def find_employee(
    record: CanonicalContribution, census: dict[str, CensusEmployee]
) -> CensusEmployee | None:
    employee = census.get(record.employee_id)
    # An employee who exists under a different employer is not this employer's employee.
    if employee is None or employee.employer_id != record.employer_id:
        return None
    return employee


def check_in_census(record: CanonicalContribution, employee: CensusEmployee | None) -> str | None:
    if record.employee_id is None or record.employer_id is None:
        return None
    if employee is None:
        return "EMPLOYEE_NOT_IN_CENSUS"
    return None


def check_election(
    record: CanonicalContribution, employee: CensusEmployee | None, tolerance: Decimal
) -> str | None:
    if employee is None or None in (record.gross_pay, record.pretax_deferral, record.roth_deferral):
        return None
    expected_pretax = percent_of(record.gross_pay, employee.pretax_election_pct)
    expected_roth = percent_of(record.gross_pay, employee.roth_election_pct)
    if (
        abs(record.pretax_deferral - expected_pretax) > tolerance
        or abs(record.roth_deferral - expected_roth) > tolerance
    ):
        return "ELECTION_MISMATCH"
    return None


def check_duplicate(record: CanonicalContribution, ledger) -> str | None:
    if record.record_key is None:
        return None
    posted = ledger.posted_hash(record.record_key)
    # Same key and same content is a replay, handled before rules run (D14).
    if posted is not None and posted != record.content_hash():
        return "DUPLICATE_PAY_PERIOD"
    return None


def annual_limit(year_limits: PlanYearLimits, age: int) -> Decimal:
    """Base limit plus the catch up the employee qualifies for (D35)."""
    if year_limits.enhanced_catch_up_min_age <= age <= year_limits.enhanced_catch_up_max_age:
        return year_limits.deferral_limit + year_limits.enhanced_catch_up_limit
    if age >= year_limits.catch_up_age:
        return year_limits.deferral_limit + year_limits.catch_up_limit
    return year_limits.deferral_limit


def check_annual_limit(
    record: CanonicalContribution, employee: CensusEmployee | None, limits: Limits, ledger
) -> str | None:
    if employee is None or None in (record.plan_year, record.pretax_deferral, record.roth_deferral):
        return None
    year_limits = limits.plan_years.get(record.plan_year)
    if year_limits is None:
        return "PLAN_YEAR_NOT_CONFIGURED"

    # Age reached by December 31 of the plan year decides catch up eligibility.
    age = record.plan_year - employee.date_of_birth.year
    limit = annual_limit(year_limits, age)

    so_far = ledger.deferrals_year_to_date(record.employer_id, record.employee_id, record.plan_year)
    if so_far + record.pretax_deferral + record.roth_deferral > limit:
        return "OVER_ANNUAL_LIMIT"
    return None
