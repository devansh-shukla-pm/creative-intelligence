"""Meta results as aggregate blocks (per-ad totals for one exact date range), planned to use as few Meta calls as possible.

A pull of a date range is one ad-level insights request, about one call per 500 ads. A block stores that answer. For a new report:
  1. take stored blocks that lie fully inside the requested range (an aggregate cannot be cut, so partial overlaps do not count),
     choose the non-overlapping set that covers the most days;
  2. the uncovered days are the gaps; pull each gap as one aggregate and store it as a block;
  3. add the blocks up per ad.
It never costs more calls than a plain pull of the whole range: if the stored blocks would leave a fragmented or mostly uncovered
range, the whole range is pulled as one block instead.

Recent days are provisional (Meta keeps adjusting conversions for a few days). The part of a pull newer than FINAL_AFTER_DAYS is its own
small block that is only trusted for FRESH_HOURS; everything older is final once pulled. So "last 6 months" after "last 3 months"
reuses the 3 month block and pulls the earlier months plus the last few days.
"""
from __future__ import annotations
import datetime
from . import meta_client as mc

FINAL_AFTER_DAYS = 3
FRESH_HOURS = 6
MAX_GAPS = 3                    # more separate gaps than this: pull the whole range in one go (fewer calls)
MIN_COVER = 0.25                # stored blocks covering less than this share of the range are not worth the extra gaps

D = datetime.date.fromisoformat

def _valid_blocks(conn, account_id, d_from, d_to):
    return conn.execute(
        """SELECT id, date_from, date_to, pulled_at FROM insight_blocks
            WHERE account_id=%s AND date_from >= %s AND date_to <= %s
              AND (pulled_at::date >= date_to + make_interval(days => %s) OR pulled_at > now() - make_interval(hours => %s))
            ORDER BY date_to""", (account_id, d_from, d_to, FINAL_AFTER_DAYS, FRESH_HOURS)).fetchall()

def _best_disjoint(blocks):
    """Weighted interval scheduling: the non-overlapping blocks that cover the most days."""
    bl = sorted(blocks, key=lambda b: b["date_to"])
    n = len(bl); best = [0] * (n + 1); take = [None] * (n + 1)
    for i in range(1, n + 1):
        b = bl[i - 1]; days = (b["date_to"] - b["date_from"]).days + 1
        j = i - 1
        while j > 0 and bl[j - 1]["date_to"] >= b["date_from"]: j -= 1
        with_b = best[j] + days
        if with_b > best[i - 1]: best[i], take[i] = with_b, (j, b)
        else: best[i], take[i] = best[i - 1], None
    chosen, i = [], n
    while i > 0:
        if take[i]: j, b = take[i]; chosen.append(b); i = j
        else: i -= 1
    return list(reversed(chosen))

def _gaps(d_from, d_to, chosen):
    gaps, cur = [], d_from
    for b in sorted(chosen, key=lambda b: b["date_from"]):
        if b["date_from"] > cur: gaps.append((cur, b["date_from"] - datetime.timedelta(days=1)))
        cur = b["date_to"] + datetime.timedelta(days=1)
    if cur <= d_to: gaps.append((cur, d_to))
    return gaps

def plan(conn, account_id, d_from, d_to):
    """-> (blocks to reuse [ids], ranges to pull [(date, date)])"""
    a, b = D(d_from), D(d_to)
    total = (b - a).days + 1
    chosen = _best_disjoint(_valid_blocks(conn, account_id, a, b))
    covered = sum((x["date_to"] - x["date_from"]).days + 1 for x in chosen)
    gaps = _gaps(a, b, chosen)
    if chosen and (len(gaps) > MAX_GAPS or covered / total < MIN_COVER):
        chosen, gaps = [], [(a, b)]                       # fragmented: one plain pull is cheaper than several small ones
    return [x["id"] for x in chosen], _split_recent(gaps, datetime.date.today())

def _split_recent(gaps, today):
    """Cut each gap at the final/provisional line, so the recent days are a block of their own (trusted for hours, not forever)."""
    cutoff = today - datetime.timedelta(days=FINAL_AFTER_DAYS)
    out = []
    for g1, g2 in gaps:
        if g1 <= cutoff: out.append((g1, min(g2, cutoff)))
        if g2 > cutoff: out.append((max(g1, cutoff + datetime.timedelta(days=1)), g2))
    return out

def _row_tuple(block_id, r):
    m = mc.metrics_from_insight(r)
    return (block_id, r["ad_id"], m["total_spend"], m["impressions"], m["clicks"], m["link_clicks"], m["purchase_count"],
            m["purchase_value"], m["atc_count"], m["lpv_count"], m["frequency"])

def store_block(conn, account_id, d_from, d_to, rows):
    b = conn.execute(
        """INSERT INTO insight_blocks (account_id, date_from, date_to, ads) VALUES (%s,%s,%s,%s)
           ON CONFLICT (account_id, date_from, date_to) DO UPDATE SET pulled_at = now(), ads = EXCLUDED.ads RETURNING id""",
        (account_id, d_from, d_to, len(rows))).fetchone()
    conn.execute("DELETE FROM block_ads WHERE block_id=%s", (b["id"],))
    with conn.cursor() as cur:
        if rows:
            cur.executemany(
                """INSERT INTO block_ads (block_id, ad_id, spend, impressions, clicks, link_clicks, purchases, value, atc, lpv, frequency)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", [_row_tuple(b["id"], r) for r in rows])
            names = {r["ad_id"]: (account_id, r["ad_id"], r.get("ad_name"), r.get("campaign_id"), r.get("campaign_name")) for r in rows}
            cur.executemany(
                """INSERT INTO ad_names (account_id, ad_id, ad_name, campaign_id, campaign_name) VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (account_id, ad_id) DO UPDATE SET ad_name=EXCLUDED.ad_name, campaign_id=EXCLUDED.campaign_id,
                     campaign_name=EXCLUDED.campaign_name, updated_at=now()""", list(names.values()))
    return b["id"]

def ensure(conn, token, account_id, d_from, d_to, on_progress=None):
    """Make sure the whole range is stored. Returns (block ids to sum, number of Meta pulls made)."""
    reuse, gaps = plan(conn, account_id, d_from, d_to)
    ids = list(reuse)
    for i, (g1, g2) in enumerate(gaps, 1):
        label = f" ({i} of {len(gaps)})" if len(gaps) > 1 else ""
        rows = mc.pull_insights(token, account_id, g1.isoformat(), g2.isoformat(),
                                on_page=(lambda n, l=label: on_progress(f"Pulled {n} ads from Meta{l}")) if on_progress else None)
        if not rows and mc.account_spend(token, account_id, g1.isoformat(), g2.isoformat()) > 0:
            raise mc.MetaError("Meta returned no ad rows for a period that has spend")      # an empty answer, not an idle period: not stored
        ids.append(store_block(conn, account_id, g1, g2, rows))
    return ids, len(gaps)

def needs_pull(conn, account_id, d_from, d_to):
    return bool(plan(conn, account_id, d_from, d_to)[1])

def aggregate(conn, account_id, block_ids):
    """Stored blocks summed per ad, shaped like the insight rows Meta sends (so metrics_from_insight works unchanged)."""
    rows = conn.execute(
        """SELECT d.ad_id, n.ad_name, n.campaign_id, n.campaign_name,
                  sum(d.spend) AS spend, sum(d.impressions) AS impressions, sum(d.clicks) AS clicks, sum(d.link_clicks) AS link_clicks,
                  sum(d.purchases) AS purchases, sum(d.value) AS value, sum(d.atc) AS atc, sum(d.lpv) AS lpv,
                  COALESCE(sum(d.frequency * d.impressions) / NULLIF(sum(d.impressions), 0), 0) AS frequency
             FROM block_ads d JOIN insight_blocks b ON b.id = d.block_id
             LEFT JOIN ad_names n ON n.account_id = b.account_id AND n.ad_id = d.ad_id
            WHERE d.block_id = ANY(%s)
            GROUP BY d.ad_id, n.ad_name, n.campaign_id, n.campaign_name
           HAVING sum(d.spend) > 0
            ORDER BY sum(d.spend) DESC""", (list(block_ids),)).fetchall()
    return [{
        "ad_id": r["ad_id"], "ad_name": r["ad_name"], "campaign_id": r["campaign_id"], "campaign_name": r["campaign_name"],
        "spend": str(r["spend"]), "impressions": str(r["impressions"]), "clicks": str(r["clicks"]),
        "inline_link_clicks": str(r["link_clicks"]), "frequency": str(r["frequency"]),
        "actions": [{"action_type": "omni_purchase", "value": str(r["purchases"])},
                    {"action_type": "omni_add_to_cart", "value": str(r["atc"])},
                    {"action_type": "landing_page_view", "value": str(r["lpv"])}],
        "action_values": [{"action_type": "omni_purchase", "value": str(r["value"])}],
    } for r in rows]

def stored_totals(conn, account_id, d_from, d_to):
    """Period totals for the trend arrows straight from stored blocks when the whole period is stored; None otherwise (no Meta call)."""
    reuse, gaps = plan(conn, account_id, d_from, d_to)
    if gaps or not reuse: return None
    r = conn.execute("""SELECT count(DISTINCT ad_id) FILTER (WHERE spend > 0) AS ads, COALESCE(sum(spend), 0) AS spend, COALESCE(sum(value), 0) AS value
                          FROM block_ads WHERE block_id = ANY(%s)""", (reuse,)).fetchone()
    spend, value = float(r["spend"]), float(r["value"])
    return {"from": d_from, "to": d_to, "ads": int(r["ads"]), "spend": spend, "revenue": value, "roas": (value / spend) if spend > 0 else 0.0}
