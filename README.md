# contribflow

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
