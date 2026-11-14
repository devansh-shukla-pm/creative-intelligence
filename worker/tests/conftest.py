import os, sys, pathlib, tempfile, uuid
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

@pytest.fixture(scope="session")
def pg_uri():
    import pgserver
    d = tempfile.mkdtemp(prefix="ci-pg-")
    srv = pgserver.get_server(pathlib.Path(d), cleanup_mode="stop")
    yield srv.get_uri()
    srv.cleanup()

@pytest.fixture()
def env(pg_uri, monkeypatch):
    import base64
    monkeypatch.setenv("DATABASE_URL", pg_uri)
    monkeypatch.setenv("ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("MOCK_META", "1"); monkeypatch.setenv("MOCK_LLM", "1")
    monkeypatch.setenv("LAB_BACKTEST_REPS", "1")
    # modules read config at import time: reload them with the test environment
    import importlib
    from worker import config
    importlib.reload(config)
    return config

@pytest.fixture()
def conn(env):
    from worker import db
    c = db.connect(); db.migrate(c)
    yield c
    c.close()

def make_report(conn, account="1000000000001", user="u1", dates=("2026-08-01", "2026-10-23")):
    conn.execute("INSERT INTO users (id,name,token_enc) VALUES (%s,'T','x') ON CONFLICT DO NOTHING", (user,))
    r = conn.execute("INSERT INTO reports (user_id,account_id,account_name,currency,date_from,date_to) VALUES (%s,%s,'Test','INR',%s,%s) RETURNING id::text",
                     (user, account, *dates)).fetchone()
    return r["id"]
