"""Meta results per ad per day.

A report for any date range is the sum of stored days. Only days that are missing (or that were pulled while still provisional)
are asked from Meta, so a 6 month report after a 3 month report pulls just the earlier 3 months, and a report that overlaps an
earlier one pulls only its new days. A day is final once it is FINAL_AFTER_DAYS old; recent days are refreshed after FRESH_HOURS
because Meta keeps adjusting conversions for a few days.
"""
from __future__ import annotations
import datetime
from . import meta_client as mc

CHUNK_DAYS = 14          # days per Meta request window: keeps each answer small and a failure cheap to redo
FINAL_AFTER_DAYS = 3
FRESH_HOURS = 6

def missing_days(conn, account_id, d_from, d_to):
    rows = conn.execute(
        """SELECT g::date AS day FROM generate_series(%s::date, %s::date, interval '1 day') g
             LEFT JOIN insight_days d ON d.account_id = %s AND d.day = g::date
            WHERE d.day IS NULL
               OR NOT (d.pulled_at >= g::date + make_interval(days => %s) OR d.pulled_at > now() - make_interval(hours => %s))
            ORDER BY 1""", (d_from, d_to, account_id, FINAL_AFTER_DAYS, FRESH_HOURS)).fetchall()
    return [r["day"] for r in rows]

def chunks(days):
    """Contiguous runs of missing days, cut into windows of at most CHUNK_DAYS: [(since, until)] as ISO strings."""
    out, run = [], []
    for d in sorted(days):
        if run and (d - run[-1]).days != 1:
            out.append(run); run = []
        run.append(d)
    if run: out.append(run)
    res = []
    for r in out:
        for i in range(0, len(r), CHUNK_DAYS):
            part = r[i:i + CHUNK_DAYS]
            res.append((part[0].isoformat(), part[-1].isoformat()))
    return res

def _daily_tuple(account_id, r):
    m = mc.metrics_from_insight(r)
    return (account_id, r["ad_id"], r["date_start"], m["total_spend"], m["impressions"], m["clicks"], m["link_clicks"],
            m["purchase_count"], m["purchase_value"], m["atc_count"], m["lpv_count"], m["frequency"])

def save_chunk(conn, account_id, since, until, rows):
    """Replace the stored days in [since, until] with Meta's answer and mark every day in the window as pulled."""
    conn.execute("DELETE FROM ad_daily WHERE account_id=%s AND day BETWEEN %s AND %s", (account_id, since, until))
    with conn.cursor() as cur:
        if rows:
            cur.executemany(
                """INSERT INTO ad_daily (account_id, ad_id, day, spend, impressions, clicks, link_clicks, purchases, value, atc, lpv, frequency)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (account_id, ad_id, day) DO UPDATE SET spend=EXCLUDED.spend, impressions=EXCLUDED.impressions,
                     clicks=EXCLUDED.clicks, link_clicks=EXCLUDED.link_clicks, purchases=EXCLUDED.purchases, value=EXCLUDED.value,
                     atc=EXCLUDED.atc, lpv=EXCLUDED.lpv, frequency=EXCLUDED.frequency""",
                [_daily_tuple(account_id, r) for r in rows])
            names = {r["ad_id"]: (account_id, r["ad_id"], r.get("ad_name"), r.get("campaign_id"), r.get("campaign_name")) for r in rows}
            cur.executemany(
                """INSERT INTO ad_names (account_id, ad_id, ad_name, campaign_id, campaign_name) VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (account_id, ad_id) DO UPDATE SET ad_name=EXCLUDED.ad_name, campaign_id=EXCLUDED.campaign_id,
                     campaign_name=EXCLUDED.campaign_name, updated_at=now()""", list(names.values()))
    conn.execute("""INSERT INTO insight_days (account_id, day) SELECT %s, g::date FROM generate_series(%s::date, %s::date, interval '1 day') g
                    ON CONFLICT (account_id, day) DO UPDATE SET pulled_at = now()""", (account_id, since, until))

def pull_missing(conn, token, account_id, days, on_progress=None):
    """Ask Meta for the missing days only. Returns how many windows were pulled."""
    wins = chunks(days)
    for i, (since, until) in enumerate(wins, 1):
        prefix = f"window {i} of {len(wins)}" if len(wins) > 1 else ""
        rows = mc.pull_insights_daily(token, account_id, since, until,
                                      on_page=(lambda n, p=prefix: on_progress(f"Pulled {n} ad-days from Meta {p}".strip())) if on_progress else None)
        if not rows and mc.account_spend(token, account_id, since, until) > 0:
            # the account spent in this window but Meta returned no ads: an empty answer, not an idle period. Do not store it as done.
            raise mc.MetaError("Meta returned no ad rows for a period that has spend")
        save_chunk(conn, account_id, since, until, rows)
    return len(wins)

def aggregate(conn, account_id, d_from, d_to):
    """Stored days for the range, summed per ad, shaped like the insight rows Meta sends (so metrics_from_insight works unchanged)."""
    rows = conn.execute(
        """SELECT d.ad_id, n.ad_name, n.campaign_id, n.campaign_name,
                  sum(d.spend) AS spend, sum(d.impressions) AS impressions, sum(d.clicks) AS clicks, sum(d.link_clicks) AS link_clicks,
                  sum(d.purchases) AS purchases, sum(d.value) AS value, sum(d.atc) AS atc, sum(d.lpv) AS lpv,
                  COALESCE(sum(d.frequency * d.impressions) / NULLIF(sum(d.impressions), 0), 0) AS frequency
             FROM ad_daily d LEFT JOIN ad_names n ON n.account_id = d.account_id AND n.ad_id = d.ad_id
            WHERE d.account_id = %s AND d.day BETWEEN %s AND %s
            GROUP BY d.ad_id, n.ad_name, n.campaign_id, n.campaign_name
           HAVING sum(d.spend) > 0
            ORDER BY sum(d.spend) DESC""", (account_id, d_from, d_to)).fetchall()
    out = []
    for r in rows:
        out.append({
            "ad_id": r["ad_id"], "ad_name": r["ad_name"], "campaign_id": r["campaign_id"], "campaign_name": r["campaign_name"],
            "spend": str(r["spend"]), "impressions": str(r["impressions"]), "clicks": str(r["clicks"]),
            "inline_link_clicks": str(r["link_clicks"]), "frequency": str(r["frequency"]),
            "actions": [{"action_type": "omni_purchase", "value": str(r["purchases"])},
                        {"action_type": "omni_add_to_cart", "value": str(r["atc"])},
                        {"action_type": "landing_page_view", "value": str(r["lpv"])}],
            "action_values": [{"action_type": "omni_purchase", "value": str(r["value"])}],
        })
    return out

def totals(conn, account_id, d_from, d_to):
    """Period totals for the trend arrows, straight from stored days when the whole period is stored. None otherwise."""
    if missing_days(conn, account_id, d_from, d_to): return None
    r = conn.execute("""SELECT count(DISTINCT ad_id) FILTER (WHERE spend > 0) AS ads, COALESCE(sum(spend), 0) AS spend, COALESCE(sum(value), 0) AS value
                          FROM ad_daily WHERE account_id=%s AND day BETWEEN %s AND %s""", (account_id, d_from, d_to)).fetchone()
    spend, value = float(r["spend"]), float(r["value"])
    return {"from": d_from, "to": d_to, "ads": int(r["ads"]), "spend": spend, "revenue": value, "roas": (value / spend) if spend > 0 else 0.0}
