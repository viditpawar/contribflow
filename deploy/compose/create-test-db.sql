-- Runs once when the local Postgres volume is first created.
-- Integration tests wipe their database, so they get their own.
CREATE DATABASE contribflow_test;
