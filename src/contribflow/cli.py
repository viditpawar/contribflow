"""Command line entry point.

Example:
    uv run contribflow ingest --census sample_data/census.csv sample_data/provider_a_2026-01-09.csv
"""

import argparse
from pathlib import Path

from contribflow.config import load_census, load_limits
from contribflow.connector import CONNECTORS_DIR, load_connector
from contribflow.pipeline import process_file
from contribflow.report import format_report
from contribflow.validation.ledger import MemoryLedger


def connector_for(path: Path, override: str | None) -> str:
    """Files are named <connector_id>_<anything>, unless --connector is given."""
    if override:
        return override
    for connector_file in sorted(CONNECTORS_DIR.glob("*.yaml")):
        if path.name.startswith(connector_file.stem + "_"):
            return connector_file.stem
    raise SystemExit(
        f"no connector matches {path.name}; name it <connector_id>_... or use --connector"
    )


def ingest(args) -> None:
    census = load_census(args.census)
    limits = load_limits(args.limits)
    ledger = MemoryLedger()
    for path in args.files:
        connector = load_connector(connector_for(path, args.connector))
        result = process_file(path.name, path.read_bytes(), connector, census, limits, ledger)
        print(format_report(result))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="contribflow")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest_parser = commands.add_parser("ingest", help="process payroll files in the order given")
    ingest_parser.add_argument("files", nargs="+", type=Path)
    ingest_parser.add_argument("--census", type=Path, required=True)
    ingest_parser.add_argument("--limits", type=Path, default=Path("config/limits.yaml"))
    ingest_parser.add_argument("--connector", help="connector id for every file")
    ingest_parser.set_defaults(handler=ingest)

    args = parser.parse_args(argv)
    args.handler(args)


if __name__ == "__main__":
    main()
