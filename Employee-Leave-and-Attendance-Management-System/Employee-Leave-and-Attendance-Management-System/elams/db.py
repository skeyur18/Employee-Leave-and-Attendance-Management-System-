import os
import sqlite3

DB_PATH = os.environ.get("ELAMS_DB", "elams.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    department    TEXT NOT NULL,
    designation   TEXT NOT NULL DEFAULT 'Staff',
    role          TEXT NOT NULL DEFAULT 'employee' CHECK (role IN ('employee','manager')),
    leave_balance INTEGER NOT NULL DEFAULT 20,
    joined        TEXT NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS attendance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    date        TEXT NOT NULL,
    check_in    TEXT NOT NULL,
    check_out   TEXT,
    UNIQUE (employee_id, date)
);
CREATE TABLE IF NOT EXISTS leaves (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    leave_type  TEXT NOT NULL,
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    days        INTEGER NOT NULL,
    reason      TEXT,
    status      TEXT NOT NULL DEFAULT 'PENDING',     -- PENDING / APPROVED / REJECTED
    decided_by  INTEGER REFERENCES employees(id),
    decided_on  TEXT,
    comment     TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    created     TEXT NOT NULL
);
"""


def get_conn(path=None):
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
