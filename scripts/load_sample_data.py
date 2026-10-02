"""Upload the census and every sample file to a running API, in manifest order,
and check each result against expected_outcomes.json. Exits 1 on any mismatch.

Standard library only, so it runs anywhere Python does.

Usage:
    uv run python scripts/load_sample_data.py [--api http://localhost:8080]
"""

import argparse
import json
import sys
import urllib.request
import uuid
from pathlib import Path

SAMPLE_DIR = Path(__file__).parent.parent / "sample_data"


def upload(method: str, url: str, path: Path) -> dict:
    """Send one file as multipart/form-data, the format the API expects."""
    boundary = uuid.uuid4().hex
    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + path.read_bytes()
        + f"\r\n--{boundary}--\r\n".encode()
    )
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8080")
    args = parser.parse_args()

    manifest = json.loads((SAMPLE_DIR / "expected_outcomes.json").read_text())
    print(upload("PUT", f"{args.api}/census", SAMPLE_DIR / manifest["census"]))

    failures = 0
    for entry in manifest["files"]:
        url = f"{args.api}/files?connector_id={entry['connector']}"
        summary = upload("POST", url, SAMPLE_DIR / entry["file"])
        report = get(f"{args.api}/files/{summary['file_id']}/report")

        expected = {r["row"]: r["reasons"] for r in entry.get("rejections", [])}
        actual = {
            r["source_row"]: r["reasons"] for r in report["records"] if r["outcome"] == "rejected"
        }
        ok = (
            summary["outcome"] == entry["outcome"]
            and summary["file_reasons"] == entry.get("file_reasons", [])
            and actual == expected
        )
        # A file that was already loaded comes back as resubmitted with its original result.
        status = "ok" if ok else "MISMATCH"
        print(
            f"{status:8} {entry['file']:40} {summary['outcome']:9} accepted={summary['accepted']}"
            f" rejected={summary['rejected']} resubmitted={summary['resubmitted']}"
        )
        failures += not ok

    print(f"{failures} mismatches")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
