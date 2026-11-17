"""The report being processed: loads it, reports progress, sets signals."""
from __future__ import annotations
from dataclasses import dataclass
from . import db

class ReportError(Exception):
    """A failure the user should see (shown in the report's error state)."""

class ReportCancelled(Exception):
    """The user pressed Cancel. Raised from progress() so every long step stops at its next update."""

@dataclass
class Report:
    conn: object
    id: str
    user_id: str
    account_id: str
    account_name: str
    currency: str
    date_from: str
    date_to: str
    prefix: str = ""                 # added to every progress message ("Processing 2 months of data · ")

    @classmethod
    def load(cls, conn, report_id):
        r = db.one(conn, """SELECT id::text, user_id, account_id, account_name, currency,
                                   to_char(date_from,'YYYY-MM-DD') AS date_from, to_char(date_to,'YYYY-MM-DD') AS date_to
                              FROM reports WHERE id = %s""", (report_id,))
        if not r:
            raise ReportError(f"Report {report_id} not found")
        return cls(conn, **r)

    def start(self):
        r = self.conn.execute("UPDATE reports SET status='running', error=NULL, heartbeat_at=now(), updated_at=now() WHERE id=%s AND status<>'cancelled' RETURNING 1", (self.id,)).fetchone()
        if not r: raise ReportCancelled()

    def progress(self, stage, message, done=None, total=None):
        p = {"message": self.prefix + message}
        if done is not None: p["done"] = done
        if total is not None: p["total"] = total
        r = self.conn.execute(
            "UPDATE reports SET stage=%s, progress=%s, heartbeat_at=now(), updated_at=now() WHERE id=%s AND status<>'cancelled' RETURNING 1",
            (stage, db.J(p), self.id)).fetchone()
        if not r: raise ReportCancelled()

    def signal(self, letter):
        assert letter in "abcd"
        self.conn.execute(f"UPDATE reports SET signal_{letter}=now(), updated_at=now() WHERE id=%s AND status<>'cancelled'", (self.id,))

    def finish(self):
        self.conn.execute("UPDATE reports SET status='done', stage=NULL, progress='{}'::jsonb, updated_at=now() WHERE id=%s AND status<>'cancelled'", (self.id,))

    def fail(self, message):
        self.conn.execute("UPDATE reports SET status='failed', error=%s, updated_at=now() WHERE id=%s AND status<>'cancelled'", (message[:500], self.id))

    def user_token_blob(self):
        r = db.one(self.conn, "SELECT token_enc FROM users WHERE id=%s", (self.user_id,))
        return r["token_enc"] if r else None
