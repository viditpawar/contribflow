# contribflow

[![ci](https://github.com/viditpawar/contribflow/actions/workflows/ci.yml/badge.svg)](https://github.com/viditpawar/contribflow/actions/workflows/ci.yml)

Payroll contribution ingestion pipeline that normalizes multi provider payroll files, validates them against employee census data, and reconciles retirement plan deferrals. Built with Python, Terraform, Kubernetes, and Grafana.

Every design choice and its tradeoffs is recorded in [decisions.md](decisions.md). All data is synthetic.

## What it does

Employers send payroll contribution files through different payroll providers, each in its own format. contribflow:

1. **Ingests** three formats: two CSV layouts with different headers, date and money conventions, and an 80 character fixed width format with header and trailer records.
2. **Normalizes** each row into one canonical contribution record, using a YAML connector per provider rather than code per provider.
3. **Validates** each record against the employee census: missing or malformed fields, employees not in the census, deductions that do not match the employee's election, duplicate pay periods, and the annual deferral limit with both catch up tiers (from age 50, and the enhanced tier for ages 60 to 63). The limits are config, keyed by plan year.
4. **Rejects whole files** when the fixed width trailer's record count or deferral total does not match the detail records.
5. **Is idempotent:** resubmitting the same file changes nothing, and a file exported again with different bytes is recognized record by record as `already_posted`.
6. **Reports** every record's outcome and reasons as JSON or CSV.
7. **Exposes Prometheus metrics** with a Grafana dashboard, and runs on a local kind cluster built by Terraform and Helm.

```
 payroll file ─► POST /files?connector_id=...
                     │
                     ▼
   sha256 seen before? ── yes ─► return the original result (no change)
                     │ no
   parse (csv or fixed width, from connector YAML)
   normalize to canonical records
   file checks (trailer count and total) ── fail ─► reject whole file
   validate each record (census, election, duplicate, annual limit)
   post accepted records ─► Postgres (one transaction, serialized)
                     │
   GET /files/{id}/report        /metrics ─► Prometheus ─► Grafana
```

## Demo in 3 minutes

Requires Docker and [uv](https://docs.astral.sh/uv/). On Windows PowerShell, use `curl.exe` instead of `curl`.

**1. Start Postgres and the API**

```bash
docker compose up -d --build
```

**2. Upload the census and all ten sample files.** The script checks every result against [expected_outcomes.json](sample_data/expected_outcomes.json), the answer key written by the data generator.

```bash
uv run python scripts/load_sample_data.py --api http://localhost:8000
```

```
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

What to notice: the bad trailer file is rejected whole, and its corrected version right after it is accepted. In run 2, provider_b repeats a pay period that was already posted, with different amounts, and that row is rejected. In run 3, one employee crosses the annual deferral limit.

**3. Send the first file again.** Nothing is posted twice; the original result comes back.

```bash
curl -s -X POST -F "file=@sample_data/provider_a_2026-01-09.csv" \
  "http://localhost:8000/files?connector_id=provider_a"
```

```json
{"file_id": "2558d680-...", "outcome": "processed", "resubmitted": true,
 "accepted": 45, "rejected": 5, "already_posted": 0, ...}
```

**4. Send the same records as a different file.** Here the same rows are saved with Windows line endings, so the bytes and the file hash differ. Each record is still recognized as already posted.

```bash
uv run python -c "import pathlib; p = pathlib.Path('sample_data/provider_a_2026-01-09.csv'); pathlib.Path('reexport.csv').write_bytes(p.read_bytes().replace(b'\n', b'\r\n'))"
curl -s -X POST -F "file=@reexport.csv" "http://localhost:8000/files?connector_id=provider_a"
```

```json
{"resubmitted": false, "accepted": 0, "rejected": 5, "already_posted": 45, ...}
```

**5. Read the reconciliation report** for any `file_id` (JSON by default, or CSV). The first file, filtered here to its rejected rows:

```bash
curl -s "http://localhost:8000/files/<file_id>/report?format=csv"
```

```
source_row,employee_id,outcome,reasons
16,EMP000015,rejected,MALFORMED_FIELD
19,EMP000018,rejected,ELECTION_MISMATCH
24,EMP000023,rejected,ELECTION_MISMATCH;MALFORMED_FIELD
25,EMP900001,rejected,EMPLOYEE_NOT_IN_CENSUS
34,EMP000033,rejected,MISSING_FIELD
...
```

Row 24 fails two rules, and both are reported.

**6. The full version** on a local Kubernetes cluster, with Prometheus and Grafana, is one command: `scripts/up.sh` (see [Full stack on kind](#full-stack-on-kind-no-cloud-no-cost)).

![Grafana dashboard](docs/dashboard.png)

## Quick start

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/) and Docker.

```bash
uv sync

# Regenerate the synthetic sample data (already committed in sample_data/)
uv run python generator/generate.py --seed 42 --out sample_data

# Process sample files with no database (the ledger lives in memory)
uv run contribflow ingest --census sample_data/census.csv \
  sample_data/provider_a_2026-01-09.csv sample_data/provider_c_2026-01-23_bad_trailer.dat

# Unit tests
uv run pytest

# Integration tests against Postgres
docker compose up -d db
TEST_DATABASE_URL=postgresql://contribflow:contribflow@localhost:5432/contribflow_test uv run pytest
```

### API with Docker Compose

```bash
docker compose up -d --build
uv run python scripts/load_sample_data.py --api http://localhost:8000
```

### Full stack on kind (no cloud, no cost)

Additionally requires kind and Terraform.

```bash
scripts/up.sh      # builds the image, creates the cluster, installs monitoring and the app
uv run python scripts/load_sample_data.py   # uploads every sample file and checks each outcome
terraform -chdir=deploy/terraform/local output -raw grafana_admin_password
scripts/down.sh    # deletes the cluster
```

| Service | URL |
|---|---|
| API | http://localhost:8080 |
| Grafana dashboard (user `admin`) | http://localhost:3300/d/contribflow |
| Prometheus | http://localhost:9090 |

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

## Repository layout

```
src/contribflow/        pipeline, parsing, validation, API, metrics, Postgres access
src/contribflow/connectors/   one YAML mapping per payroll provider
config/limits.yaml      deferral limits by plan year
generator/              synthetic data generator with an expected outcomes manifest
sample_data/            generated data used by tests, CI and the demo
tests/                  unit and integration tests, all checked against the manifest
deploy/helm/            Helm chart: API, Postgres, NetworkPolicies, ServiceMonitor, dashboard
deploy/terraform/local/ kind cluster, kube-prometheus-stack and the app
scripts/                up, down, and the sample data loader
```

## Known limitations (v1)

- Negative amounts (reversals and adjustments) are rejected as malformed.
- A second check in the same pay period, such as a bonus, is treated as a duplicate.
- File processing is serialized by design; fine for payroll volumes, not for high throughput.
