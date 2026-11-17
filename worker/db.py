"""Postgres access for the worker (psycopg 3, one connection, main thread only)."""
from __future__ import annotations
import json, time
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from . import config

def connect() -> psycopg.Connection:
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(config.DATABASE_URL, autocommit=True, row_factory=dict_row)

def migrate(conn) -> None:
    conn.execute((config.ROOT / "db" / "schema.sql").read_text())

def J(obj):
    return Jsonb(obj)

def one(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()

def all_(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()

def upsert_payload(conn, report_id, kind, body):
    conn.execute(
        """INSERT INTO report_payloads (report_id, kind, body) VALUES (%s,%s,%s)
           ON CONFLICT (report_id, kind) DO UPDATE SET body = EXCLUDED.body, updated_at = now()""",
        (report_id, kind, J(body)))


class MetaGate:
    """Only one report at a time talks to the Meta API. Meta's call budget belongs to the whole app, so two big reports pulling
    together would spend it twice as fast. The others wait here (and show that on the report page) instead of hitting the limit.
    Uses a Postgres advisory lock on its own connection, released when the block ends or the worker dies."""
    KEY = 727001

    def __init__(self, rep, poll_s=5):
        self.rep, self.poll_s, self.conn = rep, poll_s, None

    def __enter__(self):
        self.conn = connect()
        try:
            while not self.conn.execute("SELECT pg_try_advisory_lock(%s) AS ok", (self.KEY,)).fetchone()["ok"]:
                self.rep.progress("pulling", "Waiting for another report to finish pulling from Meta")   # also stops here if cancelled
                time.sleep(self.poll_s)
        except BaseException:
            self.conn.close(); raise
        return self

    def __exit__(self, *exc):
        try:
            self.conn.execute("SELECT pg_advisory_unlock(%s)", (self.KEY,))
        finally:
            self.conn.close()
        return False
