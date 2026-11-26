import json
from worker.tests.conftest import make_report

def test_full_pipeline_offline_then_cache(conn, env, monkeypatch):
    from worker import run as runner, mock
    calls = {"extraction": 0, "clustering": 0, "naming": 0}
    orig = mock.MockLLM.chat_json
    def counting(self, model, content, max_tokens=4096, label="", timeout_s=None, system=None):
        if label in calls: calls[label] += 1
        return orig(self, model, content, max_tokens, label, timeout_s, system)
    monkeypatch.setattr(mock.MockLLM, "chat_json", counting)

    rid = make_report(conn)
    assert runner.run(rid) == 0
    r = conn.execute("SELECT * FROM reports WHERE id=%s", (rid,)).fetchone()
    assert r["status"] == "done" and r["error"] is None
    assert all(r[f"signal_{x}"] for x in "abcd")

    P = {row["kind"]: row["body"] for row in conn.execute("SELECT kind, body FROM report_payloads WHERE report_id=%s", (rid,)).fetchall()}
    assert set(P) == {"audit", "cmt_ads", "data", "cmt_dims", "insights", "lab"}
    assert len(P["audit"]) == 479 and len(P["data"]["ads"]) == 479
    classified = [a for a in P["data"]["ads"] if a["stages"]["hook-line"]]
    assert 250 <= len(classified) <= 288
    assert {s["name"] for s in P["data"]["skus"]}                      # clean product names exist
    names = [s["name"] for s in P["data"]["skus"]]
    assert len(names) == len(set(n.lower() for n in names))            # one name per product
    assert any(a["is_multi_sku"] for a in P["data"]["ads"])           # bundles flagged
    assert P["cmt_dims"]["STORYTELLING_STYLE"] and "LAYOUT_TYPE" not in P["cmt_dims"]
    assert len(P["insights"]) >= 1
    assert P["lab"]["products"], "at least one product should be eligible for a recipe"
    prod = P["lab"]["products"][0]
    assert len(prod["recipe_support"]) == 5 and prod["final_pred"] > 0 and prod["grid"] > 1
    assert conn.execute("SELECT count(*) AS n FROM thumbs").fetchone()["n"] > 100
    first = dict(calls)
    assert first["extraction"] >= 288 and first["clustering"] >= 1 and first["naming"] >= 1

    # second report on the same account: nothing is sent to the LLMs again
    calls.update(extraction=0, clustering=0, naming=0)
    rid2 = make_report(conn, dates=("2026-09-01", "2026-10-23"))
    assert runner.run(rid2) == 0
    assert calls == {"extraction": 0, "clustering": 0, "naming": 0}
    d2 = conn.execute("SELECT body FROM report_payloads WHERE report_id=%s AND kind='data'", (rid2,)).fetchone()["body"]
    assert [a["stages"] for a in d2["ads"]] == [a["stages"] for a in P["data"]["ads"]]   # same labels from cache

def test_failure_is_reported_not_raised(conn, env, monkeypatch):
    from worker import run as runner, mock
    monkeypatch.setattr(mock.MockSource, "fetch_ads", lambda self, rep, on_progress=None: [])
    rid = make_report(conn, account="1000000000002")
    assert runner.run(rid) == 0          # a reported failure is not a failed job (no GitHub alert)
    r = conn.execute("SELECT status, error FROM reports WHERE id=%s", (rid,)).fetchone()
    assert r["status"] == "failed" and "No ads" in r["error"]


def test_numbers_open_the_page_before_creative_details_are_fetched(conn, env):
    from worker import run as runner, mock
    from worker.report import Report
    full = mock.MockSource().fetch_ads(None)
    seen = {}
    class Src:
        def fetch_metrics(self, rep, on_progress=None): return [{"ad_id": a["ad_id"]} for a in full]
        def provisional_ads(self, rep, rows):
            return [{**a, "creative": {"media_type": "PENDING"}} for a in full]
        def attach_creatives(self, rep, rows, on_progress=None):
            r = conn.execute("SELECT signal_a, rev FROM reports WHERE id=%s", (rep.id,)).fetchone()
            d = conn.execute("SELECT body FROM report_payloads WHERE report_id=%s AND kind='data'", (rep.id,)).fetchone()
            seen.update(signal_a=bool(r["signal_a"]), rev=r["rev"], ready=d["body"]["meta"]["creative_ready"])
            return full, len(full)
        def period_totals(self, rep, since, until): return None
        def thumbnail(self, ad): return None
    rid = make_report(conn, account="1000000000003")
    rep = Report.load(conn, rid)
    runner.stage_a(rep, Src())
    assert seen == {"signal_a": True, "rev": 0, "ready": False}           # numbers were already on the page, flagged as still loading
    after = conn.execute("SELECT rev FROM reports WHERE id=%s", (rid,)).fetchone()["rev"]
    d = conn.execute("SELECT body FROM report_payloads WHERE report_id=%s AND kind='data'", (rid,)).fetchone()["body"]
    assert after == 1 and d["meta"]["creative_ready"] is True            # then refreshed, and the page is told
    for job in runner._BG: job.result()
    runner._BG.clear()
