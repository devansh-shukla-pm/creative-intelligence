"""Postgres access for the worker (psycopg 3, one connection, main thread only)."""
from __future__ import annotations
import json, time
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from . import config

_KEEPALIVE = dict(keepalives=1, keepalives_idle=20, keepalives_interval=10, keepalives_count=3, connect_timeout=20)

def _raw_connect() -> psycopg.Connection:
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(config.DATABASE_URL, autocommit=True, row_factory=dict_row, **_KEEPALIVE)

class Conn:
    """A connection that survives the database hanging up. A report can run for hours and the model calls between database writes
    leave the connection idle for minutes; Neon (or anything in between) then closes it ('SSL connection has been closed
    unexpectedly'). On such an error this reconnects and repeats the statement. Safe because autocommit is on and every statement
    the worker runs is an upsert or an update that can be repeated."""
    RETRIES = 4
    PING_AFTER_S = 20

    def __init__(self):
        self._c = _raw_connect(); self._last = time.time()

    def _reconnect(self):
        try: self._c.close()
        except Exception: pass
        self._c = _raw_connect()

    def _run(self, fn):
        for attempt in range(self.RETRIES):
            try:
                r = fn(self._c); self._last = time.time(); return r
            except (psycopg.OperationalError, psycopg.InterfaceError):
                if attempt == self.RETRIES - 1: raise
                print(f"[db] connection lost, reconnecting (attempt {attempt + 1})", flush=True)
                time.sleep(2 ** attempt)
                try: self._reconnect()
                except (psycopg.OperationalError, psycopg.InterfaceError): pass     # try again on the next loop

    def execute(self, *a, **k):
        return self._run(lambda c: c.execute(*a, **k))

    def cursor(self, *a, **k):
        if time.time() - self._last > self.PING_AFTER_S:          # a cursor is used for batch writes: make sure the line is alive first
            self._run(lambda c: c.execute("SELECT 1"))
        return self._c.cursor(*a, **k)

    def close(self):
        try: self._c.close()
        except Exception: pass

    def __enter__(self): return self
    def __exit__(self, *exc): self.close(); return False

    def __getattr__(self, name):
        return getattr(self._c, name)

def connect(resilient: bool = True):
    """The worker's database connection. `resilient=False` gives a plain connection (the Meta gate needs one: its advisory lock
    lives and dies with the session, so silently reconnecting would drop the lock)."""
    return Conn() if resilient else _raw_connect()

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
        self.conn = connect(resilient=False)
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
        except Exception:
            pass                       # the connection died: the lock went with it
        finally:
            try: self.conn.close()
            except Exception: pass
        return False
