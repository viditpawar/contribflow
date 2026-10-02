import shutil
from datetime import date
from decimal import Decimal

import pytest

from contribflow import metrics
from contribflow.connector import load_connector
from contribflow.models import CanonicalContribution
from contribflow.pipeline import process_file
from contribflow.validation import rules
from contribflow.validation.engine import validate_record
from contribflow.validation.ledger import MemoryLedger
from tests.oracle import assert_matches_manifest


def make_record(**overrides):
    """A clean record for EMP000002 (3% pretax, 5% Roth in the seed 42 census)."""
    values = {
        "connector_id": "provider_a",
        "source_row": 2,
        "employer_id": "ER0001",
        "employee_id": "EMP000002",
        "pay_period_start": date(2025, 12, 21),
        "pay_period_end": date(2026, 1, 3),
        "pay_date": date(2026, 1, 9),
        "gross_pay": Decimal("5383.23"),
        "pretax_deferral": Decimal("161.50"),
        "roth_deferral": Decimal("269.16"),
        "employer_match": Decimal("161.50"),
    }
    values.update(overrides)
    return CanonicalContribution(**values)


def test_clean_record_is_accepted(census, limits):
    assert validate_record(make_record(), census, limits, MemoryLedger()) == ("accepted", [])


def test_employee_under_another_employer_is_not_in_census(census, limits):
    outcome, reasons = validate_record(
        make_record(employer_id="ER0002"), census, limits, MemoryLedger()
    )
    assert reasons == ["EMPLOYEE_NOT_IN_CENSUS"]


def test_election_within_tolerance_is_accepted(census, limits):
    record = make_record(pretax_deferral=Decimal("161.51"))
    assert validate_record(record, census, limits, MemoryLedger()) == ("accepted", [])


def test_election_outside_tolerance_is_rejected(census, limits):
    record = make_record(roth_deferral=Decimal("269.18"))
    assert validate_record(record, census, limits, MemoryLedger()) == (
        "rejected",
        ["ELECTION_MISMATCH"],
    )


def test_malformed_gross_does_not_also_report_election_mismatch(census, limits):
    record = make_record(gross_pay=None, field_errors={"gross_pay": "MALFORMED_FIELD"})
    assert validate_record(record, census, limits, MemoryLedger()) == (
        "rejected",
        ["MALFORMED_FIELD"],
    )


def test_identical_record_is_already_posted_and_changed_record_is_duplicate(census, limits):
    ledger = MemoryLedger()
    ledger.post(make_record(), "file-1")
    assert validate_record(make_record(source_row=9), census, limits, ledger) == (
        "already_posted",
        [],
    )
    changed = make_record(employer_match=Decimal("100.00"))
    assert validate_record(changed, census, limits, ledger) == (
        "rejected",
        ["DUPLICATE_PAY_PERIOD"],
    )


def test_plan_year_without_limits_is_rejected(census, limits):
    record = make_record(pay_date=date(2031, 1, 9))
    assert validate_record(record, census, limits, MemoryLedger()) == (
        "rejected",
        ["PLAN_YEAR_NOT_CONFIGURED"],
    )


def read(path):
    return path.name, path.read_bytes()


def process_in_manifest_order(sample, census, limits):
    out, manifest = sample
    ledger = MemoryLedger()
    results = []
    for entry in manifest["files"]:
        connector = load_connector(entry["connector"])
        results.append(process_file(*read(out / entry["file"]), connector, census, limits, ledger))
    return ledger, results


def test_pipeline_matches_expected_outcomes(sample, census, limits):
    _, manifest = sample
    _, results = process_in_manifest_order(sample, census, limits)

    for entry, result in zip(manifest["files"], results, strict=True):
        assert_matches_manifest(entry, result)


def test_resubmitting_identical_file_changes_nothing(sample, census, limits):
    out, manifest = sample
    ledger, results = process_in_manifest_order(sample, census, limits)
    first = manifest["files"][0]

    again = process_file(
        *read(out / first["file"]), load_connector(first["connector"]), census, limits, ledger
    )
    assert again.resubmitted
    assert again.records == results[0].records


def test_reexported_file_posts_nothing_new(sample, census, limits, tmp_path):
    out, manifest = sample
    ledger, results = process_in_manifest_order(sample, census, limits)
    first = manifest["files"][0]

    # Same content with Windows line endings: different bytes, so a different file hash.
    reexport = tmp_path / first["file"]
    reexport.write_bytes((out / first["file"]).read_bytes().replace(b"\n", b"\r\n"))
    totals_before = dict(ledger.year_to_date)

    result = process_file(
        *read(reexport), load_connector(first["connector"]), census, limits, ledger
    )
    assert not result.resubmitted
    assert result.count("accepted") == 0
    assert result.count("already_posted") == results[0].count("accepted")
    assert result.count("rejected") == results[0].count("rejected")
    assert ledger.year_to_date == totals_before


def test_rejected_file_posts_nothing(sample, census, limits, tmp_path):
    out, _ = sample
    bad = tmp_path / "provider_c_bad.dat"
    shutil.copy(out / "provider_c_2026-01-23_bad_trailer.dat", bad)
    ledger = MemoryLedger()

    result = process_file(*read(bad), load_connector("provider_c"), census, limits, ledger)
    assert result.outcome == "rejected"
    assert result.records == []
    assert ledger.posted_hashes == {}


def test_metric_reason_lists_cover_every_reason_in_sample_data(sample):
    _, manifest = sample
    for entry in manifest["files"]:
        assert set(entry.get("file_reasons", [])) <= set(metrics.FILE_REASONS)
        for rejection in entry.get("rejections", []):
            assert set(rejection["reasons"]) <= set(metrics.RECORD_RULES)


@pytest.mark.parametrize(
    "age, expected",
    [
        (49, Decimal("24500.00")),
        (50, Decimal("32500.00")),
        (59, Decimal("32500.00")),
        (60, Decimal("35750.00")),
        (63, Decimal("35750.00")),
        (64, Decimal("32500.00")),
    ],
)
def test_annual_limit_by_age(limits, age, expected):
    assert rules.annual_limit(limits.plan_years[2026], age) == expected
