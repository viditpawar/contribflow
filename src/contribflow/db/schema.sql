-- Applied at startup (D13). Every statement is safe to run repeatedly.

CREATE TABLE IF NOT EXISTS census (
    employee_id         TEXT PRIMARY KEY,
    employer_id         TEXT NOT NULL,
    date_of_birth       DATE NOT NULL,
    pretax_election_pct NUMERIC(5, 2) NOT NULL,
    roth_election_pct   NUMERIC(5, 2) NOT NULL
);

-- One row per distinct file received, including rejected files (D24).
CREATE TABLE IF NOT EXISTS files (
    file_id      UUID PRIMARY KEY,
    file_hash    TEXT NOT NULL UNIQUE,
    file_name    TEXT NOT NULL,
    connector_id TEXT NOT NULL,
    outcome      TEXT NOT NULL CHECK (outcome IN ('processed', 'rejected')),
    record_count INTEGER NOT NULL,
    file_reasons TEXT[] NOT NULL,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Posted contributions: accepted records only.
CREATE TABLE IF NOT EXISTS contributions (
    record_id        UUID PRIMARY KEY,
    -- Checked at commit: the files row is written after the file's records are posted.
    source_file_id   UUID NOT NULL REFERENCES files (file_id) DEFERRABLE INITIALLY DEFERRED,
    source_row       INTEGER NOT NULL,
    connector_id     TEXT NOT NULL,
    employer_id      TEXT NOT NULL,
    employee_id      TEXT NOT NULL,
    pay_period_start DATE NOT NULL,
    pay_period_end   DATE NOT NULL,
    pay_date         DATE NOT NULL,
    plan_year        INTEGER NOT NULL,
    gross_pay        NUMERIC(12, 2) NOT NULL,
    pretax_deferral  NUMERIC(12, 2) NOT NULL,
    roth_deferral    NUMERIC(12, 2) NOT NULL,
    employer_match   NUMERIC(12, 2) NOT NULL,
    content_hash     TEXT NOT NULL,
    -- The idempotency key (D14). The pipeline checks it first; this is the safety net.
    UNIQUE (employer_id, employee_id, pay_period_end)
);

CREATE INDEX IF NOT EXISTS contributions_year_to_date
    ON contributions (employer_id, employee_id, plan_year);

-- The outcome of every record in every processed file, for the reconciliation report.
CREATE TABLE IF NOT EXISTS record_results (
    file_id     UUID NOT NULL REFERENCES files (file_id),
    source_row  INTEGER NOT NULL,
    employee_id TEXT,
    outcome     TEXT NOT NULL CHECK (outcome IN ('accepted', 'rejected', 'already_posted')),
    reasons     TEXT[] NOT NULL,
    PRIMARY KEY (file_id, source_row)
);
