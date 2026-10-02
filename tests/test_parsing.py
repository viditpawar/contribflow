from decimal import Decimal

import pytest

from contribflow.connector import load_connector
from contribflow.parsing import parse_file
from contribflow.parsing.file_checks import check_trailer
from contribflow.parsing.normalize import normalize, parse_amount

FIELD_REASONS = {"MISSING_FIELD", "MALFORMED_FIELD"}


def parse_and_normalize(path, connector):
    parsed = parse_file(path.read_text(encoding="utf-8"), connector)
    records = [normalize(row, connector) for row in parsed.rows]
    return parsed, records


@pytest.mark.parametrize("connector_id", ["provider_a", "provider_b", "provider_c"])
def test_connectors_load(connector_id):
    assert load_connector(connector_id).id == connector_id


def test_sample_files_parse_with_expected_field_errors(sample):
    out, manifest = sample
    for entry in manifest["files"]:
        if entry["outcome"] != "processed":
            continue
        connector = load_connector(entry["connector"])
        parsed, records = parse_and_normalize(out / entry["file"], connector)

        assert parsed.file_errors == [], entry["file"]
        assert len(records) == entry["record_count"], entry["file"]

        expected = {}
        for rejection in entry["rejections"]:
            field_reasons = FIELD_REASONS.intersection(rejection["reasons"])
            if field_reasons:
                expected[rejection["row"]] = field_reasons
        actual = {r.source_row: set(r.field_errors.values()) for r in records if r.field_errors}
        assert actual == expected, entry["file"]


def test_good_trailers_pass_and_bad_trailer_fails(sample):
    out, manifest = sample
    connector = load_connector("provider_c")
    for entry in manifest["files"]:
        if entry["connector"] != "provider_c":
            continue
        parsed, records = parse_and_normalize(out / entry["file"], connector)
        errors = parsed.file_errors + check_trailer(parsed.trailer, records, connector)
        assert errors == entry.get("file_reasons", []), entry["file"]


def test_normalized_values_are_typed(sample):
    out, _ = sample
    _, records = parse_and_normalize(
        out / "provider_b_2026-01-09.csv", load_connector("provider_b")
    )
    record = next(r for r in records if not r.field_errors)
    assert isinstance(record.gross_pay, Decimal)
    assert record.plan_year == 2026


@pytest.mark.parametrize(
    "text, style, expected",
    [
        ("1234.56", "plain", Decimal("1234.56")),
        ("$1,234.56", "currency", Decimal("1234.56")),
        ("$999.00", "currency", Decimal("999.00")),
        ("0000123456", "implied_cents", Decimal("1234.56")),
    ],
)
def test_parse_amount_accepts(text, style, expected):
    assert parse_amount(text, style) == expected


@pytest.mark.parametrize(
    "text, style",
    [
        ("-10.00", "plain"),
        ("NaN", "plain"),
        ("1e5", "plain"),
        ("12.3", "plain"),
        ("1,234.56", "currency"),
        ("$1234.56", "currency"),
        ("12A4", "implied_cents"),
    ],
)
def test_parse_amount_rejects(text, style):
    with pytest.raises(ValueError):
        parse_amount(text, style)


def test_csv_missing_column_rejects_file(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("employer_id,employee_id\nER0001,EMP000001\n")
    parsed = parse_file(path.read_text(encoding="utf-8"), load_connector("provider_a"))
    assert parsed.file_errors == ["COLUMN_MISSING"]


def test_fixed_width_without_trailer_rejects_file(sample, tmp_path):
    out, _ = sample
    lines = (out / "provider_c_2026-01-09.dat").read_text().splitlines()
    path = tmp_path / "no_trailer.dat"
    path.write_text("\n".join(lines[:-1]) + "\n")
    parsed = parse_file(path.read_text(encoding="utf-8"), load_connector("provider_c"))
    assert parsed.file_errors == ["TRAILER_MISSING"]


def test_fixed_width_count_mismatch(sample, tmp_path):
    out, _ = sample
    lines = (out / "provider_c_2026-01-09.dat").read_text().splitlines()
    path = tmp_path / "dropped_row.dat"
    # Drop the last detail record (just before the trailer); count and total no longer match.
    path.write_text("\n".join(lines[:-2] + lines[-1:]) + "\n")
    connector = load_connector("provider_c")
    parsed, records = parse_and_normalize(path, connector)
    assert check_trailer(parsed.trailer, records, connector) == [
        "TRAILER_COUNT_MISMATCH",
        "TRAILER_TOTAL_MISMATCH",
    ]
