"""The per-day store: any range is a sum of stored days, and only missing days are asked from Meta."""
import datetime
import pytest
from worker import daily, meta_client as mc

ACCT = "acct-daily"

def make_rows(d_from, d_to):
    """Fake Meta: ads 1 and 2 spend 100 (ad 1 earns 300, ad 2 earns 100) every day in the window; ad 3 only on the first day."""
    out = []
    d = datetime.date.fromisoformat(d_from); end = datetime.date.fromisoformat(d_to)
    while d <= end:
        for ad, rev in (("1", 300), ("2", 100)):
            out.append({"ad_id": ad, "ad_name": f"ad {ad}", "campaign_id": "c1", "campaign_name": "camp", "date_start": d.isoformat(),
                        "spend": "100", "impressions": "1000", "clicks": "50", "inline_link_clicks": "40", "frequency": "1.5",
                        "actions": [{"action_type": "omni_purchase", "value": "3"}, {"action_type": "landing_page_view", "value": "20"},
                                    {"action_type": "omni_add_to_cart", "value": "10"}],
                        "action_values": [{"action_type": "omni_purchase", "value": str(rev)}]})
        d += datetime.timedelta(days=1)
    return out

@pytest.fixture()
def meta(monkeypatch):
    calls = []
    monkeypatch.setattr(mc, "pull_insights_daily", lambda token, acct, since, until, on_page=None: (calls.append((since, until)), make_rows(since, until))[1])
    monkeypatch.setattr(mc, "account_spend", lambda *a, **k: 0.0)
    return calls

def pull(conn, d_from, d_to):
    missing = daily.missing_days(conn, ACCT, d_from, d_to)
    if missing: daily.pull_missing(conn, "tok", ACCT, missing)
    return daily.aggregate(conn, ACCT, d_from, d_to)

def test_a_range_is_the_sum_of_stored_days(conn, meta):
    rows = {r["ad_id"]: r for r in pull(conn, "2026-01-01", "2026-01-10")}
    m = mc.metrics_from_insight(rows["1"])
    assert m["total_spend"] == 1000 and m["purchase_value"] == 3000 and m["roas"] == 3.0       # 10 days x (100 spend, 300 revenue)
    assert m["purchase_count"] == 30 and m["lpv_count"] == 200 and m["atc_count"] == 100
    assert round(m["lpv_percentage"], 1) == 50.0 and round(m["frequency"], 2) == 1.5            # 200 / 400 link clicks
    assert rows["1"]["ad_name"] == "ad 1" and rows["1"]["campaign_name"] == "camp"

def test_a_longer_range_pulls_only_the_days_it_does_not_have(conn, meta):
    pull(conn, "2026-02-01", "2026-02-28")                       # "the last 3 months" report
    first = list(meta); assert first[0][0] == "2026-02-01" and first[-1][1] == "2026-02-28"
    meta.clear()
    rows = pull(conn, "2025-12-01", "2026-02-28")                # "the last 6 months" report: only the earlier part is new
    asked = [(a, b) for a, b in meta]
    assert asked and min(a for a, _ in asked) == "2025-12-01" and max(b for _, b in asked) == "2026-01-31"
    assert all(b <= "2026-01-31" for _, b in asked)             # not a single day from the first report is asked again
    m = mc.metrics_from_insight({r["ad_id"]: r for r in rows}["1"])
    assert m["total_spend"] == 100 * 90                          # Dec 1 to Feb 28 = 90 days, all of them counted
    meta.clear(); pull(conn, "2026-01-05", "2026-02-10")         # a range inside what is stored: no Meta call at all
    assert meta == []

def test_gaps_are_cut_into_windows(conn):
    days = [datetime.date(2026, 3, d) for d in range(1, 31)] + [datetime.date(2026, 4, 5)]
    w = daily.chunks(days)
    assert w[0] == ("2026-03-01", "2026-03-14") and w[2] == ("2026-03-29", "2026-03-30") and w[-1] == ("2026-04-05", "2026-04-05")
    assert len(w) == 4

def test_recent_days_are_refreshed_and_old_days_become_final(conn, meta):
    today = datetime.date.today()
    d1 = (today - datetime.timedelta(days=1)).isoformat()
    pull(conn, d1, d1); assert len(meta) == 1
    meta.clear(); pull(conn, d1, d1); assert meta == []                                            # pulled minutes ago: still fresh
    conn.execute("UPDATE insight_days SET pulled_at = now() - interval '7 hours' WHERE account_id=%s", (ACCT,))
    pull(conn, d1, d1); assert len(meta) == 1                                                      # provisional day, older than 6 h: refreshed
    old = (today - datetime.timedelta(days=30)).isoformat()
    pull(conn, old, old); meta.clear()
    conn.execute("UPDATE insight_days SET pulled_at = now() - interval '2 days' WHERE account_id=%s AND day=%s", (ACCT, old))
    assert daily.missing_days(conn, ACCT, old, old) == []                                          # pulled long after the day: final
    conn.execute("UPDATE insight_days SET pulled_at = %s::date + interval '1 day' WHERE account_id=%s AND day=%s", (old, ACCT, old))
    assert [d.isoformat() for d in daily.missing_days(conn, ACCT, old, old)] == [old]               # pulled while provisional: pulled once more

def test_an_empty_answer_for_a_window_that_has_spend_is_not_stored(conn, monkeypatch):
    monkeypatch.setattr(mc, "pull_insights_daily", lambda *a, **k: [])
    monkeypatch.setattr(mc, "account_spend", lambda *a, **k: 5000.0)
    with pytest.raises(mc.MetaError):
        daily.pull_missing(conn, "tok", ACCT, [datetime.date(2026, 5, 1)])
    assert daily.missing_days(conn, ACCT, "2026-05-01", "2026-05-01")                              # still missing: the next report asks again

def test_totals_come_from_the_store_when_the_period_is_stored(conn, meta):
    assert daily.totals(conn, ACCT, "2026-06-01", "2026-06-05") is None
    pull(conn, "2026-06-01", "2026-06-05")
    t = daily.totals(conn, ACCT, "2026-06-01", "2026-06-05")
    assert t["spend"] == 1000 and t["revenue"] == 2000 and t["roas"] == 2.0 and t["ads"] == 2
