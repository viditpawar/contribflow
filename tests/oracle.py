"""Compare a pipeline result with its entry in expected_outcomes.json (D16)."""


def assert_matches_manifest(entry, result):
    name = entry["file"]
    assert result.outcome == entry["outcome"], name
    assert result.record_count == entry["record_count"], name
    assert result.file_reasons == entry.get("file_reasons", []), name

    expected = {r["row"]: r["reasons"] for r in entry.get("rejections", [])}
    actual = {r.source_row: r.reasons for r in result.records if r.outcome == "rejected"}
    assert actual == expected, name
    if result.outcome == "processed":
        assert result.count("accepted") == entry["record_count"] - len(expected), name
