"""Stored aggregate blocks: reuse what is stored, pull only the gaps, never more calls than one plain pull."""
import datetime
import pytest
from worker import blocks, meta_client as mc

ACCT = "acct-blocks"
D = datetime.date.fromisoformat

def agg_rows(since, until):
    """Fake Meta: ads 1 and 2 spend 100 a day (ad 1 earns 300, ad 2 earns 100). One aggregate row per ad for the range."""
    days = (D(until) - D(since)).days + 1
    out = []
    for ad, rev in (("1", 300), ("2", 100)):
        out.append({"ad_id": ad, "ad_name": f"ad {ad}", "campaign_id": "c1", "campaign_name": "camp",
                    "spend": str(100 * days), "impressions": str(1000 * days), "clicks": str(50 * days), "inline_link_clicks": str(40 * days),
                    "frequency": "1.5",
                    "actions": [{"action_type": "omni_purchase", "value": str(3 * days)}, {"action_type": "landing_page_view", "value": str(20 * days)},
                                {"action_type": "omni_add_to_cart", "value": str(10 * days)}],
                    "action_values": [{"action_type": "omni_purchase", "value": str(rev * days)}]})
    return out

@pytest.fixture(autouse=True)
def clean(conn):
    conn.execute("DELETE FROM insight_blocks WHERE account_id=%s", (ACCT,))

@pytest.fixture()
def meta(monkeypatch):
    calls = []
    monkeypatch.setattr(mc, "pull_insights", lambda token, acct, since, until, on_page=None: (calls.append((since, until)), agg_rows(since, until))[1])
    monkeypatch.setattr(mc, "account_spend", lambda *a, **k: 0.0)
    return calls

def report(conn, d_from, d_to):
    ids, _ = blocks.ensure(conn, "tok", ACCT, d_from, d_to)
    return {r["ad_id"]: r for r in blocks.aggregate(conn, ACCT, ids)}

def test_a_range_is_the_sum_of_its_blocks(conn, meta):
    rows = report(conn, "2025-01-01", "2025-01-10")
    m = mc.metrics_from_insight(rows["1"])
    assert m["total_spend"] == 1000 and m["purchase_value"] == 3000 and m["roas"] == 3.0
    assert m["purchase_count"] == 30 and m["lpv_count"] == 200 and round(m["lpv_percentage"], 1) == 50.0
    assert rows["1"]["ad_name"] == "ad 1" and len(meta) == 1                                     # one pull for a plain range

def test_six_months_after_three_pulls_only_the_earlier_months(conn, meta):
    report(conn, "2025-04-01", "2025-06-30")                    # "last 3 months"
    assert meta == [("2025-04-01", "2025-06-30")]
    meta.clear()
    rows = report(conn, "2025-01-01", "2025-06-30")             # "last 6 months": the stored block is reused, only Jan to Mar is new
    assert meta == [("2025-01-01", "2025-03-31")]
    assert mc.metrics_from_insight(rows["1"])["total_spend"] == 100 * 181                          # all 181 days are counted, none twice
    meta.clear(); report(conn, "2025-01-01", "2025-06-30"); assert meta == []                    # same again: nothing is asked

def test_a_partial_overlap_is_cheaper_as_one_plain_pull(conn, meta):
    report(conn, "2025-01-01", "2025-01-31")
    meta.clear()
    rows = report(conn, "2025-01-20", "2025-03-10")             # the January block is not fully inside: it cannot be used
    assert meta == [("2025-01-20", "2025-03-10")]
    assert mc.metrics_from_insight(rows["1"])["total_spend"] == 100 * 50

def test_fragmented_gaps_fall_back_to_a_single_pull(conn, meta):
    for a, b in [("2025-02-01", "2025-02-03"), ("2025-02-08", "2025-02-10"), ("2025-02-15", "2025-02-17"), ("2025-02-22", "2025-02-24")]:
        report(conn, a, b)
    meta.clear()
    report(conn, "2025-02-01", "2025-02-28")                    # four tiny blocks would leave five gaps: one pull instead
    assert meta == [("2025-02-01", "2025-02-28")]

def test_recent_days_are_a_small_block_of_their_own(conn, meta):
    today = datetime.date.today()
    start = today - datetime.timedelta(days=40)
    report(conn, start.isoformat(), today.isoformat())
    cutoff = today - datetime.timedelta(days=3)
    assert meta == [(start.isoformat(), cutoff.isoformat()), ((cutoff + datetime.timedelta(days=1)).isoformat(), today.isoformat())]
    meta.clear(); report(conn, start.isoformat(), today.isoformat()); assert meta == []              # fresh: trusted for 6 hours
    conn.execute("UPDATE insight_blocks SET pulled_at = now() - interval '7 hours' WHERE account_id=%s", (ACCT,))
    report(conn, start.isoformat(), today.isoformat())
    assert meta == [((cutoff + datetime.timedelta(days=1)).isoformat(), today.isoformat())]       # next report: only the last few days again

def test_a_block_pulled_while_still_provisional_is_not_trusted_forever(conn, meta):
    old = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    report(conn, old, old); meta.clear()
    conn.execute("UPDATE insight_blocks SET pulled_at = date_to + interval '1 day' WHERE account_id=%s", (ACCT,))     # pulled the day after
    report(conn, old, old); assert meta == [(old, old)]                                                              # pulled once more now it is final
    meta.clear(); report(conn, old, old); assert meta == []

def test_an_empty_answer_for_a_period_with_spend_is_not_stored(conn, monkeypatch):
    monkeypatch.setattr(mc, "pull_insights", lambda *a, **k: [])
    monkeypatch.setattr(mc, "account_spend", lambda *a, **k: 5000.0)
    with pytest.raises(mc.MetaError):
        blocks.ensure(conn, "tok", ACCT, "2025-05-01", "2025-05-10")
    assert blocks.needs_pull(conn, ACCT, "2025-05-01", "2025-05-10")

def test_totals_come_from_stored_blocks_when_the_period_is_stored(conn, meta):
    assert blocks.stored_totals(conn, ACCT, "2025-06-01", "2025-06-05") is None
    report(conn, "2025-06-01", "2025-06-05")
    t = blocks.stored_totals(conn, ACCT, "2025-06-01", "2025-06-05")
    assert t["spend"] == 1000 and t["revenue"] == 2000 and t["roas"] == 2.0 and t["ads"] == 2
