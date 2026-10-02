import json

from generator.generate import RECORD_WIDTH, generate


def test_same_seed_produces_identical_files(tmp_path):
    generate(42, tmp_path / "first")
    generate(42, tmp_path / "second")

    first_files = sorted(p.name for p in (tmp_path / "first").iterdir())
    second_files = sorted(p.name for p in (tmp_path / "second").iterdir())
    assert first_files == second_files
    for name in first_files:
        assert (tmp_path / "first" / name).read_bytes() == (tmp_path / "second" / name).read_bytes()


def test_manifest_record_counts_match_files(tmp_path):
    generate(42, tmp_path)
    manifest = json.loads((tmp_path / "expected_outcomes.json").read_text())

    for entry in manifest["files"]:
        lines = (tmp_path / entry["file"]).read_text().splitlines()
        # CSV has one header line; fixed width has a header and a trailer record.
        non_data_lines = 2 if entry["file"].endswith(".dat") else 1
        assert len(lines) - non_data_lines == entry["record_count"], entry["file"]


def test_every_defect_type_is_injected(tmp_path):
    generate(42, tmp_path)
    manifest = json.loads((tmp_path / "expected_outcomes.json").read_text())

    reasons = set()
    for entry in manifest["files"]:
        reasons.update(entry.get("file_reasons", []))
        for rejection in entry.get("rejections", []):
            reasons.update(rejection["reasons"])

    assert reasons == {
        "MISSING_FIELD",
        "MALFORMED_FIELD",
        "EMPLOYEE_NOT_IN_CENSUS",
        "ELECTION_MISMATCH",
        "DUPLICATE_PAY_PERIOD",
        "OVER_ANNUAL_LIMIT",
        "TRAILER_TOTAL_MISMATCH",
    }


def test_fixed_width_records_have_fixed_width(tmp_path):
    generate(42, tmp_path)

    for path in tmp_path.glob("*.dat"):
        for line in path.read_text().splitlines():
            assert len(line) == RECORD_WIDTH, (path.name, line)
