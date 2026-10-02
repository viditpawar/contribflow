# Decisions log

Each entry records what was decided, why, and what was rejected. Entries are never deleted. A reversed decision gets a new entry that supersedes the old one.

> D1 to D9 were recorded before this file was added to the repo. Merge them in above D10.

## D10. Single synchronous Python service with a CLI over a shared core

**Decision:** One FastAPI service accepts a file, processes it in the request, and returns the result. A CLI calls the same core functions in `pipeline.py`.

**Reasoning:** Payroll files are small, so processing takes well under a second. A long running process is what Prometheus scrapes cleanly. The code stays short and explainable.

**Alternatives considered:** A Kubernetes Job per file with Pushgateway for metrics (poor fit, Pushgateway is meant for batch jobs whose metrics outlive them). A queue with workers (unneeded at this volume).

## D11. Connectors are declarative YAML mapping specs read by two generic parsers

**Decision:** Each payroll provider is described by a connector YAML file that maps its columns (CSV) or byte ranges (fixed width) to canonical fields. Two generic parsers, one for CSV and one for fixed width, read these specs.

**Reasoning:** Adding a provider means adding config, not code. The later AI mapper produces a connector file, so the core never changes for it.

**Alternatives considered:** One hand coded parser per provider (simpler at first, but every new provider means new code and new tests).

## D12. Canonical contribution schema and money handling

**Decision:** The canonical record has these fields: record_id, source_file_id, source_row, connector_id, employer_id, employee_id, pay_period_start, pay_period_end, pay_date, gross_pay, pretax_deferral, roth_deferral, employer_match, plan_year, content_hash. Money is `Decimal` in Python and `NUMERIC(12,2)` in Postgres. plan_year is derived from pay_date.

**Reasoning:** Float rounding errors are unacceptable for money. The annual deferral limit applies by the calendar year a contribution is paid, so pay_date drives plan_year.

**Alternatives considered:** Integer cents (also correct, but less readable in reports and SQL). Float (rejected).

## D13. PostgreSQL with psycopg 3 and plain SQL

**Decision:** Store files, contributions, rejections and census in Postgres. Access it with psycopg 3 and plain SQL. The schema lives in `schema.sql` and is applied at startup with `CREATE TABLE IF NOT EXISTS`.

**Reasoning:** Unique constraints and transactions do the idempotency work. Plain SQL is easy to explain line by line.

**Alternatives considered:** SQLite (weaker for concurrent writers and a Kubernetes deployment). SQLAlchemy ORM with Alembic migrations (more machinery than a handful of tables need).

## D14. Two level idempotency

**Decision:** Level one: the sha256 of the file. An identical file returns the original report and changes nothing. Level two: the record key (employer_id, employee_id, pay_period_end) has a unique constraint. If the key matches and content_hash matches, the record outcome is `already_posted`. If the key matches but content differs, it is rejected as `DUPLICATE_PAY_PERIOD`. Record outcomes are accepted, rejected or already_posted.

**Reasoning:** Separates a harmless resubmission (including a file exported again with different bytes) from a real conflict.

**Alternatives considered:** File hash only (misses a file exported again). Record key only (cannot tell a replay from a conflict).

**Known limitation:** An off cycle check (for example a bonus) in the same pay period is flagged as a duplicate. Documented, not solved in v1.

## D15. Validation collects all failing rules; limits live in config

**Decision:** Every rule runs on every record and all failures are recorded. Reason codes are stable: MISSING_FIELD, MALFORMED_FIELD, EMPLOYEE_NOT_IN_CENSUS, ELECTION_MISMATCH, DUPLICATE_PAY_PERIOD, OVER_ANNUAL_LIMIT. The annual deferral limit, catch up amount, catch up age and election tolerance live in `config/limits.yaml`, keyed by plan year.

**Reasoning:** Complete rejection reasons save operations a round trip. Limits change every year and must not be hardcoded.

**Alternatives considered:** Stop at the first failing rule (hides problems that occur together).

## D16. Seeded synthetic data generator with an expected outcomes manifest

**Decision:** A generator produces the census and provider files from a fixed seed, injects known defects, and writes `expected_outcomes.json` listing what each record should produce. Tests use it as their oracle.

**Reasoning:** Data is reproducible, contains no real identifiers, and tests prove every injected defect is caught with the right reason code.

**Alternatives considered:** Hand written fixtures (drift from the real file formats, cover less).

## D17. Everything runs locally on kind; no cloud resources

**Decision:** The project runs on a local kind cluster. Terraform manages the kind cluster and the Helm releases. No cloud provider is used.

**Reasoning:** Zero cost is a hard requirement. kind runs the same cluster in local development and in CI. Infrastructure is still defined in code.

**Alternatives considered:** k3d (faster start, less CI parity). minikube. A managed cloud cluster such as AKS or EKS (rejected for cost).

## D18. Observability with kube-prometheus-stack and a dashboard defined in code

**Decision:** Install kube-prometheus-stack via Helm. The app exposes `/metrics`, a ServiceMonitor wires it to Prometheus, and the Grafana dashboard JSON lives in the repo and is loaded through the Grafana sidecar ConfigMap.

**Reasoning:** Industry standard stack, and the dashboard is versioned with the code.

**Alternatives considered:** Separate Prometheus and Grafana charts (more wiring). A hosted Grafana free tier (external dependency, conflicts with D17).

## D19. In cluster Postgres as a plain StatefulSet

**Decision:** Postgres runs as a small StatefulSet using the official image, templated in the contribflow Helm chart.

**Reasoning:** Few moving parts and fully explainable.

**Alternatives considered:** A popular community Postgres chart (its image distribution changed recently, less dependable). The CloudNativePG operator (more realistic, more to explain). A managed database (costs money, conflicts with D17).

## D20. CI on GitHub Actions

**Decision:** GitHub Actions runs ruff, pytest (with a Postgres service container), Trivy (image and config), Checkov (Terraform and Helm), helm lint, terraform validate, and a smoke test on kind.

**Reasoning:** Free for public repos, visible to reviewers, and kind runs natively on Actions runners.

**Alternatives considered:** Azure DevOps (equally capable, less visible to reviewers).

## D21. AI column mapper deferred, local model only

**Decision:** The AI column mapper is built only after v1 works. It uses a local model through Ollama, and its only output is a connector YAML (D11) that a human approves.

**Reasoning:** Protects the two week scope. Costs nothing. Payroll data never leaves the machine.

**Alternatives considered:** A hosted LLM API (cost and data exposure). Building it alongside the core (risks an unfinished v1).

## D22. Public GitHub repo

**Decision:** The repo is public.

**Reasoning:** Actions minutes are free for public repos, and the code is visible to the founders.

**Alternatives considered:** A private repo (limited free CI minutes, reviewers need an invite).

## D23. Python 3.12 managed with uv; no Makefile

**Decision:** Target Python 3.12, pinned in `.python-version`. Use uv for the virtual environment, dependencies and the lockfile (`uv.lock`). Use ruff for linting and formatting, pytest for tests. Common commands are documented in the README instead of a Makefile.

**Reasoning:** 3.12 is mature and well supported by every library we need. uv gives a reproducible lockfile and the same commands locally and in CI. `make` is not installed on the Windows dev machine, and plain commands are clearer than a wrapper.

**Alternatives considered:** pip with requirements.txt (no lockfile by default). Poetry (slower, more config). Python 3.14 (newest, but some libraries may lag). A Makefile or a task runner (extra tool for little gain).

## D24. File level controls reject the whole file

**Decision:** Before any record is validated, the file passes file level checks. For fixed width files the trailer must exist, its record count must equal the number of detail records, and its deferral total (pretax plus Roth across all detail records) must equal the sum of those records. Any failure rejects the whole file: no records are posted, and the report lists every failing check (TRAILER_MISSING, TRAILER_COUNT_MISMATCH, TRAILER_TOTAL_MISMATCH), collected as in D15. The rejected file is still recorded with its hash, so resubmitting the same bytes returns the same rejection, while a corrected file has a new hash and is processed normally. A metric `contribflow_files_rejected_total` labeled by `reason` counts these separately from record rejections. A file with two failing checks increments two reasons, so the count of rejected files comes from `contribflow_files_processed_total{status="rejected"}`, not from summing reasons.

**Reasoning:** A trailer mismatch means the file was truncated or altered. Posting part of a file known to be incomplete creates partial payroll contributions that are hard to unwind. File rejections and record rejections have different causes and owners: a file failure is a provider or transfer problem, a record failure is a data problem. They deserve separate dashboard panels and alerts.

**Alternatives considered:** Post the valid records and flag the trailer as a warning (risks partial posting). Count file failures in the record rejection metric (mixes units and hides that a whole file failed).

## D25. Synthetic provider formats and pay schedule

**Decision:** Three employers, 50 employees each, each employer using one provider. All pay biweekly, with three pay runs starting 2026-01-09. Provider formats:
- **provider_a (CSV):** snake_case headers matching canonical names, ISO dates, plain decimal amounts.
- **provider_b (CSV):** different header names and column order, MM/DD/YYYY dates, amounts like `$1,234.56`. One row per employee per pay run.
- **provider_c (fixed width, 80 characters):** header, detail and trailer records, YYYYMMDD dates, amounts as zero padded cents with an implied decimal point.

source_row is the physical line number in the file, so the first data row is line 2 in every format.

**Reasoning:** Three runs are enough to show year to date logic (duplicates across files, an employee crossing the annual limit) while keeping sample data small. The formats differ in the ways real payroll files differ: names, order, date and money conventions, and fixed width layout.

**Alternatives considered:** provider_b with separate pretax and Roth rows per employee (realistic, but requires a grouping step in the generic connector; can be added later as a new connector feature). A full year of 26 runs (more files with no new test coverage).

## D26. Connector spec format

**Decision:** A connector YAML maps each canonical field to its source: a column header for CSV, or a `[start, end)` character range for fixed width, read exactly like a Python slice `line[start:end]`. The spec also names the date format (a `strptime` pattern), the amount style (`plain`, `currency` or `implied_cents`) and, for fixed width, the header, detail and trailer record type codes and the trailer field ranges. The mapping direction is canonical field to source, and a connector must map exactly the nine input fields from D12 or it fails to load. Connector files ship inside the package under `src/contribflow/connectors/`.

**Reasoning:** Mapping from canonical field to source makes "is every required field mapped" a one line check, and it is the shape the AI mapper (D21) will produce. Python slice positions mean the YAML and the code read the same way, with no off by one conversion.

**Alternatives considered:** 1 based column positions as printed in many payroll specs (familiar to payroll teams, but needs a conversion in code that is easy to get wrong). Mapping from source column to canonical field (makes missing mappings harder to detect). Free form regex per field (powerful, hard to review and to generate safely).

## D27. Strict parsing and file structure checks

**Decision:** All nine input fields are required. Blank after trimming whitespace is MISSING_FIELD. Amounts must match their style exactly: two decimal places for `plain` and `currency`, digits only for `implied_cents`. Negative amounts are MALFORMED_FIELD, so reversals and adjustments are out of scope for v1. Dates must parse with the connector's date format. Three file level reasons join D24's list: COLUMN_MISSING (a mapped CSV column is absent from the header), UNKNOWN_RECORD_TYPE (a fixed width line whose type is not header, detail or trailer), and TRAILER_MALFORMED (more than one trailer, or unreadable trailer values). The trailer total is checked after normalization, because it needs parsed amounts. If any deferral in the file is unreadable, the total cannot be verified and the file fails with TRAILER_TOTAL_MISMATCH. The header record's content is not validated in v1.

**Reasoning:** For money, a value read wrong is worse than a value rejected. Python's `Decimal` alone accepts "NaN", "1e5" and negatives, so patterns guard it. A missing column is one structural problem, so it is reported once at file level rather than as the same MISSING_FIELD on every row.

**Alternatives considered:** Lenient parsing with `Decimal()` (silently accepts values no payroll system should send). Reporting a missing column as MISSING_FIELD on every record (floods the report with one root cause). Supporting negative adjustments now (real need, but it changes the limit and duplicate rules; better as its own phase).

## D28. Validation rule details

**Decision:**
- Rules skip when their inputs are missing or malformed, so one bad field never produces extra, misleading reasons.
- An employee found in the census under a different employer is EMPLOYEE_NOT_IN_CENSUS.
- Election check: expected deduction is gross pay times the election percentage, rounded half up to cents, checked separately for pretax and Roth against `election_tolerance`.
- Annual limit: year to date is tracked per (employer, employee, plan year), counting pretax plus Roth from posted contributions only. Catch up applies if the employee reaches `catch_up_age` by December 31 of the plan year. A record that would cross the limit is rejected whole, not capped.
- A plan year missing from `limits.yaml` rejects the record as PLAN_YEAR_NOT_CONFIGURED.
- 2026 values: 24,500 base, 8,000 catch up, age 50. The enhanced catch up for ages 60 to 63 is not modeled in v1.
- Records are validated and posted in file order, so a later record sees earlier records from the same file.
- The CLI picks the connector from the file name prefix (`<connector_id>_...`) unless `--connector` is given, and keeps its ledger in memory. The API requires `connector_id` explicitly.

**Reasoning:** Each choice keeps a rejection reason accurate and explainable. Rejecting rather than capping keeps the pipeline from changing payroll amounts on its own; correcting an over limit deferral is a payroll decision. Missing plan year config fails safe instead of skipping the check.

**Alternatives considered:** Capping the deferral at the remaining limit (silently changes money). Tracking year to date per employee across all employers (the plan enforces per plan; across unrelated employers it is the individual's responsibility). Modeling the 60 to 63 catch up now (adds an age band rule for no new architecture).

## D29. Transactions, concurrency and storage details

**Decision:**
- Each file is processed in one database transaction that first takes a transaction level advisory lock (`pg_advisory_xact_lock`) shared by all processing and census replacement. File processing is therefore serialized.
- The pipeline takes file bytes, not a path. A file that is not valid UTF 8 is rejected as UNREADABLE_FILE. A leading byte order mark is ignored.
- A `record_results` table stores every record outcome for the report; `contributions` holds accepted records only. The contributions foreign key to `files` is deferred to commit, so the files row can be written once the outcome is known.
- `file_id` is a UUID generated per new file. A resubmitted file returns the original `file_id`.
- The API opens one connection per request, with no pool. Uploads are capped at 10 MB.
- The ledger has two implementations with the same methods: `MemoryLedger` for the CLI and unit tests, `PostgresLedger` for the API.
- Integration tests use a separate `contribflow_test` database because they wipe it.

**Reasoning:** Without serialization, two files for the same employee processed at once could each pass the year to date check and together exceed the limit. Payroll volume is a handful of files per pay run, so serializing costs nothing measurable, and the advisory lock works across any number of API replicas. The unique constraint on the record key stays as a safety net. Per request connections are the simplest correct option at this volume.

**Alternatives considered:** SERIALIZABLE isolation with retries (correct, but retry logic is harder to explain). Row locks per employee (finer grained, but the set of employees is only known after parsing). A connection pool (needed at higher request rates; easy to add later). Storing rejections only (the report needs accepted and already_posted rows too).

## D30. Metric design

**Decision:** Five metrics: `contribflow_files_processed_total{connector,status}` with status processed, rejected or resubmitted; `contribflow_files_rejected_total{reason}`; `contribflow_records_total{connector,outcome}`; `contribflow_records_rejected_total{connector,rule}`; and the histogram `contribflow_file_processing_seconds{connector}`. Metrics are recorded only after the transaction commits. A resubmission counts only as `status="resubmitted"` and never counts its records again. The `_created` series are disabled.

**Reasoning:** Labels stay low cardinality: connectors and reason codes are small fixed sets, and no employee or file identifiers become labels. Recording after commit means a rolled back transaction never inflates counts. Counting resubmitted records again would make dashboards show work that did not happen.

**Alternatives considered:** Labeling by employer (useful, but cardinality grows with customers; better as a report filter). Recording metrics inside the transaction (counts work that may roll back).

## D31. Container image

**Decision:** A two stage build on `python:3.12-slim`. The build stage installs uv with pip at a pinned version and runs `uv sync --locked --no-dev`. The runtime stage copies only the virtualenv and `config/`, runs as uid 10001, and has a HEALTHCHECK against `/healthz`. Docker Compose runs Postgres 17 and the API for local development.

**Reasoning:** The runtime image has no build tools, source tree or uv, which shrinks what Trivy has to report. Installing uv from PyPI avoids pulling a second registry image during the build. A non root user and a health check are baseline hardening, and Checkov checks both.

**Alternatives considered:** Copying uv from its official container image (one more registry to pull from; that pull failed on the dev machine because of stale registry credentials). Distroless or Alpine runtime (smaller, but Alpine's musl breaks some binary wheels and distroless makes debugging harder). A single stage image (ships build tooling).

## D32. Kubernetes deployment details

**Decision:**
- **Access:** kind maps NodePorts to localhost only: API on 8080, Grafana on 3300, Prometheus on 9090. All three are Terraform variables, and Grafana avoids 3000, which a local Grafana install often holds.
- **Image loading:** the image tag is the Docker image ID, so every rebuild gets a new tag. A `terraform_data` resource runs `kind load docker-image` whenever the tag changes, and the new tag rolls the deployment.
- **Helm provider state:** the provider keeps its repository config and cache inside the module (`.helm/`, gitignored), isolated from the operator's own Helm setup.
- **Monitoring footprint:** kube-prometheus-stack is pinned to 91.8.2, with Alertmanager and the control plane scrapers kind does not expose turned off.
- **Pod hardening:** every pod runs non root with a read only root filesystem, all capabilities dropped, the RuntimeDefault seccomp profile and no service account token. NetworkPolicies allow only API pods to reach Postgres. Postgres reads its password from a mounted file.
- **Probes and startup:** readiness checks the database through `/healthz`; liveness is a TCP check, so a database outage never restarts the API. An init container waits for Postgres.
- **Accepted Checkov findings:** these are skipped by annotation on the resource, each with its reason: pull policy Always and image digests (incompatible with images loaded into kind), the Postgres uid of 70 (the image's own user), and the API's password in an env var (Kubernetes builds DATABASE_URL from the Secret).
- **Terraform state:** local and gitignored, since it holds generated passwords. Passwords come from `random_password`.

**Reasoning:** Each item either keeps the stack free and reproducible on one laptop, or is baseline hardening a reviewer expects to see. Skipping a finding in the manifest, with a written reason, is honest and reviewable, unlike a blanket skip list in CI.

**Alternatives considered:** `kubectl port-forward` for access (dies with the terminal). Pushing to a local registry (one more moving part). Pointing the Helm provider at the operator's Helm config (a stale local cache broke the first apply). Fixing the API password finding by reading a password file in code (more code for a local stack; the right move for production).

## D33. CI design

**Decision:** Three GitHub Actions jobs.
- **test:** ruff, the format check, and pytest with a Postgres service container, plus a check that the committed sample data equals the generator's output.
- **iac:** helm lint, `terraform fmt` and `validate`, Checkov on the rendered chart, the Dockerfile and Terraform, and a Trivy misconfiguration scan.
- **e2e:** builds the image; Trivy fails the build on HIGH or CRITICAL vulnerabilities that have a fix available; then the chart is installed on kind, and `scripts/load_sample_data.py` checks every outcome from the deployed service against expected_outcomes.json. The monitoring stack is not installed in CI.

Actions are pinned to major version tags.

**Reasoning:** The same oracle that drives the unit tests also checks the deployed service, so "it deploys" means "it produces the right answers when deployed", not just "the pods are ready". Failing only on fixable vulnerabilities keeps the build actionable. Skipping the monitoring stack in CI keeps the smoke test fast and within runner memory.

**Alternatives considered:** Pinning actions to commit SHAs (stronger supply chain protection, but harder to read and update; a reasonable next step). Failing on every vulnerability, including those without a fix (blocks builds on things nobody can act on). Running the full monitoring stack in CI (slow, and it tests a third party chart rather than this code).

## D34. Metric series are initialized at startup

**Decision:** On startup the API creates every known label combination at 0 (each connector with each status, outcome and rule, and each file reason). The lists of reason codes live in `metrics.py`, and a test checks they cover every reason in the sample data.

**Reasoning:** Prometheus `increase()` cannot count the first jump of a series that did not exist before. Before this change, the dashboard showed a record rejection rate of 0.66% when the real figure was about 3%, because rejection counters were born with their first values. Initializing known series is standard Prometheus practice, and the label sets here are small and fixed.

**Alternatives considered:** Querying raw counter values instead of `increase()` (wrong after any pod restart). Accepting the undercount (a dashboard that understates rejections is worse than none).

## D35. Enhanced catch up for ages 60 to 63 (supersedes the "not modeled" part of D28)

**Decision:** Each plan year in `limits.yaml` now has `enhanced_catch_up_limit`, `enhanced_catch_up_min_age` and `enhanced_catch_up_max_age`. For 2026: 11,250 for ages 60 to 63 inclusive, so their limit is 35,750. An employee in that band gets the enhanced amount instead of the regular 8,000, not in addition to it. Age is still the age reached by December 31 of the plan year. The generator adds an employee aged 61 deferring 34,500 by run 3, who is accepted only because of this tier, and a unit test covers the age boundaries 49, 50, 59, 60, 63 and 64.

**Reasoning:** The tier is part of the 2026 rules and was a known gap in D28. Keeping the age band in config, not code, means the band or amount can change by year without a release.

**Alternatives considered:** A general list of age bands per year (more flexible, but more config than two tiers need). Hardcoding ages 60 to 63 (the band could change).

**Still not modeled:** the requirement that catch up contributions for higher earners be made as Roth. It needs prior year wage data the census does not carry.

## D36. AI mapper scope: CSV files only

**Decision:** The AI column mapper proposes connectors for CSV files only. Fixed width connectors stay hand written from the provider's layout spec.

**Reasoning:** A CSV has headers and delimited values, so mapping is a semantic question the model is good at. A fixed width file has neither headers nor delimiters, so the model would be guessing byte positions from samples, and fixed width providers always publish a layout spec anyway.

**Alternatives considered:** Supporting fixed width by having the model infer positions (low accuracy, hard to verify, little real demand).

## D37. Hybrid mapping: the model maps columns, code detects formats and verifies

**Decision:** The model's only job is choosing which source column feeds each canonical field. Code then does the rest. It detects `date_format` and `amount_style` by trying each known format against the chosen column's values. It builds a draft connector and runs it through the real parser and normalizer on the sample rows (a dry run), reporting each field's parse success rate. Model output is treated as untrusted data: it must match a JSON schema, every column it names must exist in the file, and a source column may feed only one field. Nothing the model returns is executed.

**Reasoning:** Matching headers like "Chk Dt" to pay_date is semantic and suits a model. Detecting a date format is deterministic and code does it reliably. The dry run means a wrong mapping shows up as failed parses before a human approves anything.

**Alternatives considered:** Letting the model also choose formats (it can hallucinate a plausible but wrong pattern). Mapping by fuzzy header matching only (fails on abbreviations and provider jargon). Trusting the model output after schema validation alone (a valid looking mapping can still be wrong).

## D38. Model interface

**Decision:** The mapper calls a local model through Ollama's HTTP API with structured output (a JSON schema generated from a pydantic model) and temperature 0. The prompt lives in the repo with a version number. The model sees only the header row and at most 10 sample rows. The model name and Ollama URL come from environment variables. Tests use a fake client returning recorded responses, so CI never needs Ollama.

**Reasoning:** Structured output removes free text parsing. Temperature 0 and a versioned prompt make proposals repeatable and auditable. Sending a few rows is enough context and keeps exposure minimal, even locally. A fake client keeps tests fast and deterministic.

**Alternatives considered:** An LLM framework library (an abstraction the mapper does not need). Sending the whole file (more tokens, more exposure, no accuracy gain).

## D39. Approval UI: server rendered HTML

**Decision:** A small set of pages served by the existing FastAPI app, using Jinja2 templates and plain HTML forms, with no JavaScript framework. The review page lists each canonical field with the proposed column (editable dropdown), sample values, the detected format, the parse success rate and the model's confidence. It also shows dry run outcome counts on the uploaded file. Approving requires an approver name and a connector id.

**Reasoning:** One form is all the workflow needs. Server rendering keeps everything in Python and avoids a frontend build.

**Alternatives considered:** A single page app (a build pipeline and a second language for one form). A CLI approval flow (works, but the spec asks for a UI, and a reviewer in operations is not on a terminal).

**Known limitation:** no authentication in v1. The approver name is typed and recorded, not verified.

## D40. Approved connectors live in Postgres with a full audit trail

**Decision:** A `connectors` table stores each approved connector's YAML and id. A `mapping_proposals` table records every proposal: the model name, prompt version, raw model response, the human's edits, the approver, the timestamps and the final decision. The connector loader checks the packaged YAML files first, then the database. Approved connectors are immutable: a change is saved as a new id (for example `provider_d_v2`), and packaged connector ids cannot be taken. An approved connector can also be downloaded as YAML, to commit to the repo after review.

**Reasoning:** Connectors must survive pod restarts in Kubernetes, and Postgres is already there. For a financial data pipeline, who approved which mapping, and what the model proposed, matters as much as the mapping itself. Immutability means a file that was processed can always be traced to the exact mapping used.

**Alternatives considered:** Writing YAML files to a persistent volume (no audit trail, awkward with replicas). Editable connectors (history of processed files becomes ambiguous).

## D41. Measuring the mapper

**Decision:** The generator gains three unfamiliar CSV layouts, with abbreviated or jargon headers, shuffled order, and extra irrelevant columns such as department and hours, each with a ground truth mapping. `scripts/eval_mapper.py` runs the mapper on them and reports field level accuracy per model, so the model choice is made from measurements. New metrics: `contribflow_mapping_proposals_total{outcome}` (approved, rejected) and `contribflow_mapping_fields_overridden_total`, which counts fields a human changed before approving.

**Reasoning:** An AI feature without a measurement cannot be compared, tuned or trusted. The override count is the honest production signal of how often the model is wrong.

**Alternatives considered:** Choosing a model by reputation (no evidence for this task). Measuring only end to end approvals (hides which fields the model gets wrong).

## D42. The model runs outside the cluster

**Decision:** Ollama runs on the host machine, or as an optional Docker Compose service. It is not deployed to kind. The API reaches it through `OLLAMA_URL`. If that variable is unset, the mapper pages explain that the mapper is disabled and everything else works normally.

**Reasoning:** A 7B class model needs about 5 GB of memory, which the laptop cluster cannot spare next to the monitoring stack. Keeping the model optional means the core pipeline never depends on it.

**Alternatives considered:** Running Ollama in kind (exceeds the memory budget). A hosted model API (rejected in D21 for cost and data exposure).
