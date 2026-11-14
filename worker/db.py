"""Postgres access for the worker (psycopg 3, one connection, main thread only)."""
from __future__ import annotations
import json
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
