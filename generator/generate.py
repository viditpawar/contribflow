"""Generate synthetic payroll data for contribflow.

Writes an employee census, payroll contribution files from three providers in
different formats, and expected_outcomes.json, which lists every injected
defect and the outcome the pipeline must produce for it.

Usage:
    uv run python generator/generate.py --seed 42 --out sample_data
"""

import argparse
import csv
import json
import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

EMPLOYEES_PER_EMPLOYER = 50
RUNS = 3
FIRST_PAY_DATE = date(2026, 1, 9)
CENTS = Decimal("0.01")

# Each employer sends payroll through exactly one provider.
EMPLOYERS = {"ER0001": "provider_a", "ER0002": "provider_b", "ER0003": "provider_c"}

# High earners that exercise the annual limit, using the 2026 values in
# config/limits.yaml: 24,500 base, plus 8,000 from age 50, or 11,250 at ages 60 to 63.
# Over limit and catch up: 9,000.00 per run, 27,000.00 by run 3. The employee under 50
# is over in run 3 (limit 24,500); the employee aged 56 is not (limit 32,500).
# Enhanced catch up: 11,500.00 per run, 34,500.00 by run 3. Aged 61, so the limit is
# 35,750 and every run is accepted; with only the regular tier run 3 would be rejected.
OVER_LIMIT_EMPLOYEE = "EMP000001"  # employer ER0001, born 1990
ENHANCED_CATCH_UP_EMPLOYEE = "EMP000051"  # employer ER0002, born 1965
CATCH_UP_EMPLOYEE = "EMP000101"  # employer ER0003, born 1970
HIGH_EARNERS = {
    # employee_id: (date_of_birth, biweekly gross pay, pretax election percent)
    OVER_LIMIT_EMPLOYEE: (date(1990, 5, 14), Decimal("20000.00"), Decimal(45)),
    ENHANCED_CATCH_UP_EMPLOYEE: (date(1965, 8, 21), Decimal("23000.00"), Decimal(50)),
    CATCH_UP_EMPLOYEE: (date(1970, 3, 2), Decimal("20000.00"), Decimal(45)),
}
OVER_LIMIT_RUN = 2  # zero based index of the run that crosses the limit

# Defects injected in the first run. Each inner list lands on one otherwise clean
# employee; a list with two entries produces a record that fails two rules.
FIRST_RUN_DEFECTS = {
    "provider_a": [
        [("missing", "pay_date")],
        [("malformed", "gross_pay")],
        [("unknown_employee", None)],
        [("election_mismatch", None)],
        [("malformed", "pay_period_end"), ("election_mismatch", None)],
    ],
    "provider_b": [
        [("missing", "pay_date")],
        [("malformed", "pay_date")],
        [("unknown_employee", None)],
        [("election_mismatch", None)],
    ],
    "provider_c": [
        [("missing", "pay_date")],
        [("malformed", "gross_pay")],
        [("unknown_employee", None)],
        [("election_mismatch", None)],
    ],
}

DATE_FIELDS = ("pay_period_start", "pay_period_end", "pay_date")
AMOUNT_FIELDS = ("gross_pay", "pretax_deferral", "roth_deferral", "employer_match")

# How each provider writes dates and amounts, and what a malformed value looks like.
STYLES = {
    "provider_a": {
        "date": lambda d: d.isoformat(),
        "amount": lambda a: f"{a:.2f}",
        "bad_date": "2026-02-30",
        "bad_amount": "12.3.4",
    },
    "provider_b": {
        "date": lambda d: d.strftime("%m/%d/%Y"),
        "amount": lambda a: f"${a:,.2f}",
        "bad_date": "13/45/2026",
        "bad_amount": "$1,2x4.00",
    },
    "provider_c": {
        "date": lambda d: d.strftime("%Y%m%d"),
        "amount": lambda a: f"{int(a * 100):010d}",
        "bad_date": "20260230",
        "bad_amount": "00012A4567",
    },
}

# (header in file, canonical field)
PROVIDER_A_COLUMNS = [(field, field) for field in ("employer_id", "employee_id", *DATE_FIELDS)]
PROVIDER_A_COLUMNS += [(field, field) for field in AMOUNT_FIELDS]
PROVIDER_B_COLUMNS = [
    ("Worker ID", "employee_id"),
    ("Company Code", "employer_id"),
    ("Check Date", "pay_date"),
    ("Period Begin", "pay_period_start"),
    ("Period End", "pay_period_end"),
    ("Gross Wages", "gross_pay"),
    ("Pretax Deferral", "pretax_deferral"),
    ("Roth Deferral", "roth_deferral"),
    ("Employer Match", "employer_match"),
]

# Fixed width detail record: (canonical field, width). Total width is 80.
RECORD_WIDTH = 80
PROVIDER_C_DETAIL = [
    ("record_type", 1),
    ("employer_id", 6),
    ("employee_id", 9),
    ("pay_period_start", 8),
    ("pay_period_end", 8),
    ("pay_date", 8),
    ("gross_pay", 10),
    ("pretax_deferral", 10),
    ("roth_deferral", 10),
    ("employer_match", 10),
]


def percent_of(amount, pct):
    return (amount * pct / 100).quantize(CENTS, rounding=ROUND_HALF_UP)


def make_census(rng):
    employees = []
    for employer_id in EMPLOYERS:
        for _ in range(EMPLOYEES_PER_EMPLOYER):
            employees.append(
                {
                    "employee_id": f"EMP{len(employees) + 1:06d}",
                    "employer_id": employer_id,
                    "date_of_birth": date(
                        rng.randint(1962, 2003), rng.randint(1, 12), rng.randint(1, 28)
                    ),
                    "pretax_pct": Decimal(rng.choice([3, 4, 5, 6, 8, 10])),
                    "roth_pct": Decimal(rng.choice([0, 0, 0, 2, 3, 5])),
                    # Biweekly gross pay, constant across runs (salaried).
                    "gross_pay": Decimal(rng.randint(150_000, 600_000)) / 100,
                }
            )

    for employee in employees:
        if employee["employee_id"] in HIGH_EARNERS:
            dob, gross_pay, pretax_pct = HIGH_EARNERS[employee["employee_id"]]
            employee["date_of_birth"] = dob
            employee["gross_pay"] = gross_pay
            employee["pretax_pct"] = pretax_pct
            employee["roth_pct"] = Decimal(0)
    return employees


def pay_runs():
    runs = []
    for i in range(RUNS):
        pay_date = FIRST_PAY_DATE + timedelta(days=14 * i)
        period_end = pay_date - timedelta(days=6)
        runs.append(
            {
                "pay_period_start": period_end - timedelta(days=13),
                "pay_period_end": period_end,
                "pay_date": pay_date,
            }
        )
    return runs


def contribution(employee, run, gross_pay):
    pretax = percent_of(gross_pay, employee["pretax_pct"])
    roth = percent_of(gross_pay, employee["roth_pct"])
    # Employer matches 50% of deferrals on the first 6% of pay.
    matched = min(pretax + roth, percent_of(gross_pay, Decimal(6)))
    return {
        "employer_id": employee["employer_id"],
        "employee_id": employee["employee_id"],
        **run,
        "gross_pay": gross_pay,
        "pretax_deferral": pretax,
        "roth_deferral": roth,
        "employer_match": (matched / 2).quantize(CENTS, rounding=ROUND_HALF_UP),
        "blank": set(),
        "malformed": set(),
        "expected": [],
    }


def apply_defect(row, kind, field, unknown_ids):
    if kind == "missing":
        row["blank"].add(field)
        row["expected"].append("MISSING_FIELD")
    elif kind == "malformed":
        row["malformed"].add(field)
        row["expected"].append("MALFORMED_FIELD")
    elif kind == "unknown_employee":
        row["employee_id"] = next(unknown_ids)
        row["expected"].append("EMPLOYEE_NOT_IN_CENSUS")
    elif kind == "election_mismatch":
        row["pretax_deferral"] += Decimal("25.00")
        row["expected"].append("ELECTION_MISMATCH")


def render(row, field, style):
    if field in row["blank"]:
        return ""
    if field in row["malformed"]:
        return style["bad_date"] if field in DATE_FIELDS else style["bad_amount"]
    if field in DATE_FIELDS:
        return style["date"](row[field])
    if field in AMOUNT_FIELDS:
        return style["amount"](row[field])
    return row[field]


def write_csv_file(path, columns, rows, style):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow([header for header, _ in columns])
        for row in rows:
            writer.writerow([render(row, field, style) for _, field in columns])


def fixed_width(values):
    line = "".join(text.ljust(width) for text, width in values)
    assert len(line) <= RECORD_WIDTH, line
    return line.ljust(RECORD_WIDTH)


def write_fixed_width_file(path, rows, employer_id, file_date, total_adjustment=Decimal(0)):
    style = STYLES["provider_c"]
    lines = [fixed_width([("H", 1), (employer_id, 6), (style["date"](file_date), 8)])]
    for row in rows:
        row = {**row, "record_type": "D"}
        lines.append(fixed_width([(render(row, f, style), w) for f, w in PROVIDER_C_DETAIL]))

    # Trailer: detail record count and the deferral total as sent.
    total = sum(row["pretax_deferral"] + row["roth_deferral"] for row in rows) + total_adjustment
    lines.append(fixed_width([("T", 1), (f"{len(rows):08d}", 8), (f"{int(total * 100):012d}", 12)]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")


def write_census(path, census):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(
            [
                "employee_id",
                "employer_id",
                "date_of_birth",
                "pretax_election_pct",
                "roth_election_pct",
            ]
        )
        for e in census:
            writer.writerow(
                [
                    e["employee_id"],
                    e["employer_id"],
                    e["date_of_birth"].isoformat(),
                    e["pretax_pct"],
                    e["roth_pct"],
                ]
            )


def manifest_entry(file_name, provider, rows):
    rejections = [
        {"row": i + 2, "employee_id": row["employee_id"], "reasons": sorted(row["expected"])}
        for i, row in enumerate(rows)
        if row["expected"]
    ]
    return {
        "file": file_name,
        "connector": provider,
        "outcome": "processed",
        "record_count": len(rows),
        "rejections": rejections,
    }


def write_provider_file(out, provider, run, rows, files):
    employer_id = rows[0]["employer_id"]
    base = f"{provider}_{run['pay_date'].isoformat()}"

    if provider == "provider_c":
        file_name = f"{base}.dat"
        write_fixed_width_file(out / file_name, rows, employer_id, run["pay_date"])
    elif provider == "provider_a":
        file_name = f"{base}.csv"
        write_csv_file(out / file_name, PROVIDER_A_COLUMNS, rows, STYLES[provider])
    else:
        file_name = f"{base}.csv"
        write_csv_file(out / file_name, PROVIDER_B_COLUMNS, rows, STYLES[provider])
    files.append(manifest_entry(file_name, provider, rows))


def generate(seed, out):
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)

    census = make_census(rng)
    write_census(out / "census.csv", census)

    # Employees that defects can be injected into, in a seeded random order.
    clean_pool = {}
    for employer_id in EMPLOYERS:
        ids = [
            e["employee_id"]
            for e in census
            if e["employer_id"] == employer_id and e["employee_id"] not in HIGH_EARNERS
        ]
        rng.shuffle(ids)
        clean_pool[employer_id] = ids

    unknown_ids = (f"EMP9{n:05d}" for n in range(1, 1000))
    runs = pay_runs()
    files = []  # manifest entries, in the order the files must be processed

    for run_index, run in enumerate(runs):
        for employer_id, provider in EMPLOYERS.items():
            employees = [e for e in census if e["employer_id"] == employer_id]
            rows = [contribution(e, run, e["gross_pay"]) for e in employees]
            row_by_id = {row["employee_id"]: row for row in rows}

            if run_index == 0:
                for defect in FIRST_RUN_DEFECTS[provider]:
                    row = row_by_id[clean_pool[employer_id].pop()]
                    for kind, field in defect:
                        apply_defect(row, kind, field, unknown_ids)

            if run_index == 1 and provider == "provider_b":
                # Same employee and pay period as an accepted run 1 record, different amounts.
                employee_id = clean_pool[employer_id].pop()
                employee = next(e for e in employees if e["employee_id"] == employee_id)
                duplicate = contribution(employee, runs[0], employee["gross_pay"] + 100)
                duplicate["expected"].append("DUPLICATE_PAY_PERIOD")
                rows.append(duplicate)

            if run_index == OVER_LIMIT_RUN and OVER_LIMIT_EMPLOYEE in row_by_id:
                row_by_id[OVER_LIMIT_EMPLOYEE]["expected"].append("OVER_ANNUAL_LIMIT")

            if run_index == 1 and provider == "provider_c":
                # The provider first sends a file whose trailer total is wrong, then the fix.
                file_name = f"{provider}_{run['pay_date'].isoformat()}_bad_trailer.dat"
                write_fixed_width_file(
                    out / file_name, rows, employer_id, run["pay_date"], Decimal("100.00")
                )
                files.append(
                    {
                        "file": file_name,
                        "connector": provider,
                        "outcome": "rejected",
                        "record_count": len(rows),
                        "file_reasons": ["TRAILER_TOTAL_MISMATCH"],
                    }
                )

            write_provider_file(out, provider, run, rows, files)

    manifest = {"seed": seed, "census": "census.csv", "files": files}
    (out / "expected_outcomes.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline=""
    )


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic payroll data.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("sample_data"))
    args = parser.parse_args()
    generate(args.seed, args.out)


if __name__ == "__main__":
    main()
