# contribflow

[![ci](https://github.com/viditpawar/contribflow/actions/workflows/ci.yml/badge.svg)](https://github.com/viditpawar/contribflow/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-4169E1?logo=postgresql&logoColor=white)
![Kubernetes](https://img.shields.io/badge/Kubernetes-kind-326CE5?logo=kubernetes&logoColor=white)
![Terraform](https://img.shields.io/badge/IaC-Terraform-844FBA?logo=terraform&logoColor=white)
![Prometheus](https://img.shields.io/badge/Metrics-Prometheus-E6522C?logo=prometheus&logoColor=white)
![Grafana](https://img.shields.io/badge/Dashboards-Grafana-F46800?logo=grafana&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

A payroll contribution ingestion pipeline for 401(k) plans. contribflow takes contribution
files from **multiple payroll providers in different formats**, normalizes them into one
canonical record, validates every contribution against the **employee census and the annual
deferral limits**, and posts each one **exactly once**, even when a file is resubmitted or
exported again. Every file gets a reconciliation report saying what was accepted, what was
rejected, and why.

Every pay run, a retirement plan platform receives contributions from each employer's
payroll. A dropped file means an employee's savings never arrive; a double posted file means
money that has to be clawed back. This project is that ingestion layer, built and operated
like a production service: idempotent by design, observable, tested against a known answer
key, and deployed with Terraform and Helm. All data is synthetic, and everything runs locally
at zero cloud cost.

## Contents

- [Screenshots](#screenshots)
- [Architecture](#architecture)
- [Idempotency and reconciliation](#idempotency-and-reconciliation)
- [Testing against an answer key](#testing-against-an-answer-key)
- [Features](#features)
- [Design notes](#design-notes)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Configuration](#configuration)
- [How to demo this](#how-to-demo-this)
- [Quick start](#quick-start)
- [Kubernetes with Terraform](#kubernetes-with-terraform)
- [CI/CD](#cicd)
- [API](#api)
- [Metrics](#metrics)
- [Known limitations](#known-limitations)

## Screenshots

**Ingestion health** after loading every sample file plus one resubmission: files processed
and rejected, records accepted, the record rejection rate, rejections broken down by rule
and by file level reason, outcomes over time, and processing latency. Taken from the
Terraform provisioned kind cluster.

![Grafana dashboard](docs/dashboard.png)

## Architecture

```mermaid
flowchart LR
    subgraph providers["Payroll providers"]
        A["provider_a<br/>CSV, ISO dates"]
        B["provider_b<br/>CSV, $1,234.56, MM/DD/YYYY"]
        C["provider_c<br/>fixed width, header and trailer"]
    end

    subgraph api["contribflow API"]
        P["parse<br/>connector YAML"]
        N["normalize<br/>canonical record"]
        V["validate<br/>census · election · duplicates · limits"]
        R["report<br/>JSON or CSV"]
        M["/metrics"]
        P --> N --> V --> R
    end

    PG[("PostgreSQL<br/>files · contributions<br/>record_results · census")]
    PROM["Prometheus"]
    GRAF["Grafana"]

    A --> P
    B --> P
    C --> P
    V -- "one transaction per file" --> PG
    M --> PROM --> GRAF
```

For each uploaded file, the API does this:

1. Hashes the bytes. A file seen before returns its original result and changes nothing.
2. Parses it with the provider's connector, a YAML file mapping each canonical field to a column or a fixed width position.
3. Normalizes every row into a typed record. Money is `Decimal`, never float, and amounts must match the provider's exact format.
4. Runs file level checks. A fixed width file whose trailer count or total doesn't match its records is **rejected whole**, so nothing is partly posted.
5. Validates each record and posts the accepted ones, inside one transaction holding a Postgres advisory lock.
6. Records every record's outcome for the reconciliation report, then updates the metrics after the commit.

## Idempotency and reconciliation

Payroll files get resubmitted. A provider sends the same file twice, an operator uploads it
again, or the payroll system exports the same pay run again with different line endings or
a new timestamp in the file name. None of these may post a contribution twice. contribflow
handles this at two levels:

| What arrives | What happens |
|---|---|
| The exact same file again | The file's sha256 is already known. The original result comes back with `resubmitted: true`, and nothing is written |
| The same records in a different file | Each record's key (employer, employee, pay period end) is already posted with the same content hash, so the record is `already_posted`, not an error |
| The same pay period with different amounts | Same key, different content: rejected as `DUPLICATE_PAY_PERIOD` for a human to resolve |
| A file with a broken trailer | Rejected whole with `TRAILER_TOTAL_MISMATCH`. The corrected file has a new hash and is processed normally |

The unique constraint on the record key in Postgres is the safety net under this logic. The
pipeline checks first; the database refuses a double post even if the code ever doesn't.

Every record gets an outcome, and every rejection carries every reason that applies, not
just the first:

```text
source_row,employee_id,outcome,reasons
16,EMP000015,rejected,MALFORMED_FIELD
19,EMP000018,rejected,ELECTION_MISMATCH
24,EMP000023,rejected,ELECTION_MISMATCH;MALFORMED_FIELD
25,EMP900001,rejected,EMPLOYEE_NOT_IN_CENSUS
34,EMP000033,rejected,MISSING_FIELD
```

## Testing against an answer key

The synthetic data generator doesn't just write files. It also writes
[expected_outcomes.json](sample_data/expected_outcomes.json): for every file, the outcome it
must get, and for every defect it injected, the row and the exact reason codes the pipeline
must report. The scenarios are designed to cover each rule:

- One of each record defect per provider, plus one record that fails two rules at once
- A pay period resubmitted with different amounts
- A fixed width file with a corrupted trailer, followed by its corrected version
- An employee under 50 who crosses the 24,500 limit in the third pay run
- An employee aged 56 at the same total who stays under the 32,500 catch up limit
- An employee aged 61 at 34,500 who is accepted only because of the 60 to 63 enhanced catch up

The same answer key is checked at every layer: the in memory pipeline, the Postgres backed
pipeline, the HTTP API, and, in CI, **the service deployed on a real kind cluster**. "It
deploys" means "it gives the right answer for every record when deployed".

```text
$ uv run python scripts/load_sample_data.py --api http://localhost:8080
ok       provider_a_2026-01-09.csv                processed accepted=45 rejected=5 resubmitted=False
ok       provider_b_2026-01-09.csv                processed accepted=46 rejected=4 resubmitted=False
ok       provider_c_2026-01-09.dat                processed accepted=46 rejected=4 resubmitted=False
ok       provider_a_2026-01-23.csv                processed accepted=50 rejected=0 resubmitted=False
ok       provider_b_2026-01-23.csv                processed accepted=50 rejected=1 resubmitted=False
ok       provider_c_2026-01-23_bad_trailer.dat    rejected  accepted=0 rejected=0 resubmitted=False
ok       provider_c_2026-01-23.dat                processed accepted=50 rejected=0 resubmitted=False
ok       provider_a_2026-02-06.csv                processed accepted=49 rejected=1 resubmitted=False
ok       provider_b_2026-02-06.csv                processed accepted=50 rejected=0 resubmitted=False
ok       provider_c_2026-02-06.dat                processed accepted=50 rejected=0 resubmitted=False
0 mismatches
```

## Features

- Three payroll formats out of the box: two CSV layouts with different headers, date and money conventions, and an 80 character fixed width format with header and trailer records
- New providers are added as a YAML connector, not code
- Validation against the employee census: missing or malformed fields, unknown employees, deductions that don't match the employee's election, duplicate pay periods
- Annual deferral limit with both catch up tiers (from age 50, and the enhanced tier for ages 60 to 63), configured per plan year rather than hardcoded
- Over limit contributions are rejected, never silently capped: correcting money is a payroll decision
- Whole file rejection on trailer count or total mismatch
- Two level idempotency: file hash and record key with content hash
- Serialized processing with a Postgres advisory lock, so two files can't race past a limit together
- Reconciliation report per file, as JSON or CSV
- Prometheus metrics for files, records, rejection reasons and latency, with a Grafana dashboard
- Multi stage, non root container image; hardened pods with read only filesystems, dropped capabilities and NetworkPolicies
- One command local Kubernetes stack with Terraform; CI with Checkov, Trivy and an end to end test on kind

## Design notes

Most of the design came from problems found while building and running it. The full
reasoning behind every significant decision is in [decisions.md](decisions.md).

| Problem | How contribflow handles it |
|---|---|
| Python's `Decimal()` happily accepts `"NaN"`, `"1e5"` and `"-10"` | Each amount style has a strict pattern. For money, a value rejected beats a value read wrong |
| One bad field produces a cascade of misleading reasons (a malformed gross pay also "fails" the election check) | Every rule skips when its inputs are missing or malformed; that problem is already reported once |
| A missing CSV column would report the same `MISSING_FIELD` on every row | A mapped column absent from the header is one file level `COLUMN_MISSING` |
| Two files for the same employee processed at once could each pass the year to date check and together exceed the limit | Each file is processed in one transaction behind a Postgres advisory lock. Payroll volume makes the serialization free |
| Contributions reference a file row that is only written once the outcome is known | The foreign key is deferred to commit time |
| The dashboard showed a 0.66% rejection rate when the real figure was about 3% | Prometheus `increase()` misses the first jump of a brand new counter. Every known label combination now starts at 0 on startup |
| The first CI run failed the Trivy gate on a HIGH vulnerability in a base image library whose fix had already shipped | The image applies OS security updates at build time; the gate still fails if no fix exists |
| Terraform's Helm provider read a stale repository cache from the operator's own machine and failed at plan time | The provider's repository config and cache live inside the Terraform module |
| A local Grafana install already held port 3000 | Every host port is a Terraform variable; the cluster's Grafana defaults to 3300 |

## Tech stack

- **Language:** Python 3.12, FastAPI, pydantic, psycopg 3
- **Storage:** PostgreSQL 17 with plain SQL and an advisory lock for processing
- **Observability:** prometheus-client, kube-prometheus-stack, Grafana dashboard as code
- **Packaging:** uv, Docker (multi stage, non root), Docker Compose
- **Kubernetes:** Helm, kind, ServiceMonitor, NetworkPolicy
- **Infrastructure as code:** Terraform (kind, helm, random providers)
- **Quality:** pytest, ruff, Checkov, Trivy, GitHub Actions

## Project structure

```text
contribflow/
├── src/contribflow/
│   ├── connectors/           # one YAML mapping per payroll provider
│   ├── parsing/              # CSV and fixed width parsers, normalization, trailer checks
│   ├── validation/           # one function per rule, the engine, the in memory ledger
│   ├── db/                   # schema.sql and the Postgres ledger
│   ├── pipeline.py           # one file end to end: hash, parse, check, validate, post
│   ├── api.py                # HTTP API
│   ├── metrics.py            # every Prometheus metric in one place
│   ├── report.py             # reconciliation report formatting
│   ├── models.py             # canonical contribution and census models
│   └── cli.py                # contribflow ingest
├── config/limits.yaml        # deferral limits and catch up tiers by plan year
├── generator/                # synthetic data generator and answer key
├── sample_data/              # generated files used by tests, CI and the demo
├── tests/                    # unit and Postgres backed tests, all checked against the answer key
├── deploy/
│   ├── helm/contribflow/     # chart: API, Postgres, NetworkPolicies, ServiceMonitor, dashboard
│   ├── terraform/local/      # kind cluster, monitoring stack, the app
│   └── compose/              # local Postgres init
├── scripts/                  # up, down, and the sample data loader
├── .github/workflows/ci.yml
├── decisions.md              # why things are the way they are
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml
```

## Prerequisites

- Docker Desktop (or Docker Engine with Compose v2)
- [uv](https://docs.astral.sh/uv/)
- For the Kubernetes stack: [kind](https://kind.sigs.k8s.io/) and Terraform

No API keys or cloud accounts are needed.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | none | Postgres connection string for the API |
| `CONTRIBFLOW_LIMITS` | `config/limits.yaml` | Deferral limits by plan year |
| `TEST_DATABASE_URL` | unset | Enables the Postgres integration tests. The database is wiped, so never point it at real data |

Limits for 2026, from [config/limits.yaml](config/limits.yaml):

| Setting | Value |
|---|---|
| Elective deferral limit | 24,500 |
| Catch up, age 50 and over | 8,000 |
| Enhanced catch up, ages 60 to 63 (replaces the regular catch up) | 11,250 |
| Election tolerance | 0.01 |

## How to demo this

About 5 minutes with Docker Compose. On Windows PowerShell, use `curl.exe` instead of `curl`.

1. **Stand it up:** `docker compose up -d --build` starts Postgres and the API.
2. **Load every file and check every outcome:** `uv run python scripts/load_sample_data.py --api http://localhost:8000`. Point out the bad trailer file rejected whole and its correction accepted, the duplicate pay period, and the employee crossing the limit.
3. **Resubmit a file:** nothing changes, and the original result comes back.
   ```bash
   curl -s -X POST -F "file=@sample_data/provider_a_2026-01-09.csv" \
     "http://localhost:8000/files?connector_id=provider_a"
   ```
   ```json
   {"outcome": "processed", "resubmitted": true, "accepted": 45, "rejected": 5, "already_posted": 0, ...}
   ```
4. **Send the same records as a different file:** the bytes differ, so it's a new file, but every record is recognized.
   ```bash
   uv run python -c "import pathlib; p = pathlib.Path('sample_data/provider_a_2026-01-09.csv'); pathlib.Path('reexport.csv').write_bytes(p.read_bytes().replace(b'\n', b'\r\n'))"
   curl -s -X POST -F "file=@reexport.csv" "http://localhost:8000/files?connector_id=provider_a"
   ```
   ```json
   {"resubmitted": false, "accepted": 0, "rejected": 5, "already_posted": 45, ...}
   ```
5. **Read a reconciliation report:** `curl -s "http://localhost:8000/files/<file_id>/report?format=csv"`. Row 24 fails two rules, and both are reported.
6. **Show the receipts:** [decisions.md](decisions.md), every design decision with its reasoning and the alternatives considered.

For the full version with Prometheus and Grafana, see [Kubernetes with Terraform](#kubernetes-with-terraform).

## Quick start

```bash
git clone https://github.com/viditpawar/contribflow
cd contribflow
uv sync

# Process files with no database (the ledger lives in memory)
uv run contribflow ingest --census sample_data/census.csv \
  sample_data/provider_a_2026-01-09.csv sample_data/provider_c_2026-01-23_bad_trailer.dat

# Regenerate the synthetic data (the committed copy is identical)
uv run python generator/generate.py --seed 42 --out sample_data

# Tests, including the Postgres integration tests
docker compose up -d db
TEST_DATABASE_URL=postgresql://contribflow:contribflow@localhost:5432/contribflow_test uv run pytest
```

## Kubernetes with Terraform

One script builds the image and stands up the whole stack on a local kind cluster. No cloud
account or registry is needed:

```bash
scripts/up.sh
uv run python scripts/load_sample_data.py
terraform -chdir=deploy/terraform/local output -raw grafana_admin_password
scripts/down.sh     # removes everything
```

| Resource | What it does |
|---|---|
| `kind_cluster` | Single node cluster, with the API, Grafana and Prometheus mapped to localhost only |
| `random_password` x2 | Postgres and Grafana admin passwords |
| `helm_release.monitoring` | kube-prometheus-stack, pinned and trimmed for a laptop. Picks up ServiceMonitors from every namespace; the Grafana sidecar loads the contribflow dashboard |
| `terraform_data.load_image` | Loads the locally built image into the node. The tag is the image ID, so every rebuild rolls the deployment |
| `helm_release.contribflow` | The chart: the API, Postgres as a StatefulSet, NetworkPolicies, the ServiceMonitor and the dashboard |

| Service | URL |
|---|---|
| API | http://localhost:8080 |
| Grafana (user `admin`) | http://localhost:3300/d/contribflow |
| Prometheus | http://localhost:9090 |

Every container runs as non root with a read only root filesystem, no Linux capabilities, a
seccomp profile and no service account token. Only API pods can reach Postgres. Checkov
findings that are accepted are skipped on the resource itself, each with its reason.

## CI/CD

Every push runs three jobs:

| Job | What it checks |
|---|---|
| `lint and test` | ruff lint and format, pytest against a Postgres service container, and a check that the committed sample data still matches the generator |
| `helm, terraform and checkov` | `helm lint`, `terraform fmt` and `validate`, Checkov on the **rendered** chart, the Dockerfile and the Terraform, and a Trivy misconfiguration scan |
| `image scan and kind smoke test` | Builds the image, fails on fixable HIGH or CRITICAL vulnerabilities, installs the chart on a throwaway kind cluster, and checks every outcome from the deployed service against the answer key |

## API

| Method and path | Purpose |
|---|---|
| `PUT /census` | Replace the employee census (CSV upload) |
| `POST /files?connector_id=provider_a` | Process one payroll file (multipart upload) |
| `GET /files/{file_id}/report` | Reconciliation report; add `?format=csv` for CSV |
| `GET /healthz` | Readiness, including the database |
| `GET /metrics/` | Prometheus metrics |

## Metrics

| Metric | Labels |
|---|---|
| `contribflow_files_processed_total` | connector, status (processed, rejected, resubmitted) |
| `contribflow_files_rejected_total` | reason |
| `contribflow_records_total` | connector, outcome (accepted, rejected, already_posted) |
| `contribflow_records_rejected_total` | connector, rule |
| `contribflow_file_processing_seconds` | connector (histogram) |

A resubmitted file counts only as `status="resubmitted"`; its records are never counted
twice. Labels are fixed, small sets, so cardinality stays flat no matter how many employees
or files there are.

## Known limitations

- Negative amounts (reversals and adjustments) are rejected as malformed.
- A second check in the same pay period, such as a bonus, is treated as a duplicate.
- After tax contributions and the overall annual additions limit are not modeled yet.
- The employer match is carried through but not validated against the plan's formula.
- The API has no authentication; it is meant to run behind one.
- File processing is serialized by design: right for payroll volumes, not for high throughput.

## License

MIT
