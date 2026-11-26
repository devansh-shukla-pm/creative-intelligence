"""All reads and writes of the per-ad cache, account memory and thumbnails."""
from __future__ import annotations
from . import db

def load_cache(conn, account_id, ad_ids):
    rows = db.all_(conn, "SELECT * FROM ad_cache WHERE account_id=%s AND ad_id = ANY(%s)", (account_id, list(ad_ids)))
    return {r["ad_id"]: r for r in rows}

def save_creative(conn, account_id, ad_id, creative):
    conn.execute(
        """INSERT INTO ad_cache (account_id, ad_id, creative) VALUES (%s,%s,%s)
           ON CONFLICT (account_id, ad_id) DO UPDATE SET creative = ad_cache.creative || EXCLUDED.creative, updated_at = now()""",
        (account_id, ad_id, db.J(creative)))

def save_creatives_batch(conn, account_id, items):
    """items: [(ad_id, creative dict)]. One round trip per chunk instead of one per ad."""
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO ad_cache (account_id, ad_id, creative) VALUES (%s,%s,%s)
               ON CONFLICT (account_id, ad_id) DO UPDATE SET creative = ad_cache.creative || EXCLUDED.creative, updated_at = now()""",
            [(account_id, ad_id, db.J(c)) for ad_id, c in items])

def fresh_creatives(conn, account_id, ad_ids, hours=24):
    """Creative info saved in the last `hours` hours, so Meta need not be asked about those ads again."""
    rows = db.all_(conn, """SELECT ad_id, creative FROM ad_cache WHERE account_id=%s AND ad_id = ANY(%s)
                              AND updated_at > now() - make_interval(hours => %s) AND creative ? 'media_type'""",
                   (account_id, list(ad_ids), hours))
    return {r["ad_id"]: r["creative"] for r in rows}

def save_extraction(conn, account_id, ad_id, extraction, status, attempts):
    conn.execute(
        """UPDATE ad_cache SET extraction=%s, extraction_status=%s, extraction_attempts=%s, updated_at=now()
            WHERE account_id=%s AND ad_id=%s""",
        (db.J(extraction) if extraction is not None else None, status, attempts, account_id, ad_id))

def bump_attempt(conn, account_id, ad_id, attempts, status=None):
    conn.execute("UPDATE ad_cache SET extraction_attempts=%s, extraction_status=COALESCE(%s, extraction_status), updated_at=now() WHERE account_id=%s AND ad_id=%s",
                 (attempts, status, account_id, ad_id))

def save_cluster_labels(conn, account_id, ad_id, labels):
    conn.execute("UPDATE ad_cache SET cluster_labels=%s, cluster_attempts=cluster_attempts+1, updated_at=now() WHERE account_id=%s AND ad_id=%s",
                 (db.J(labels), account_id, ad_id))

def save_product(conn, account_id, ad_id, product):
    conn.execute("UPDATE ad_cache SET product=%s, updated_at=now() WHERE account_id=%s AND ad_id=%s",
                 (db.J(product), account_id, ad_id))

def load_memory(conn, account_id):
    r = db.one(conn, "SELECT cluster_memory, product_memory FROM account_memory WHERE account_id=%s", (account_id,))
    return (r["cluster_memory"], r["product_memory"]) if r else ({}, [])

def save_cluster_memory(conn, account_id, memory):
    conn.execute(
        """INSERT INTO account_memory (account_id, cluster_memory) VALUES (%s,%s)
           ON CONFLICT (account_id) DO UPDATE SET cluster_memory=EXCLUDED.cluster_memory, updated_at=now()""",
        (account_id, db.J(memory)))

def save_product_memory(conn, account_id, memory):
    conn.execute(
        """INSERT INTO account_memory (account_id, product_memory) VALUES (%s,%s)
           ON CONFLICT (account_id) DO UPDATE SET product_memory=EXCLUDED.product_memory, updated_at=now()""",
        (account_id, db.J(memory)))

def has_thumb(conn, account_id, ad_ids):
    rows = db.all_(conn, "SELECT ad_id FROM thumbs WHERE account_id=%s AND ad_id = ANY(%s)", (account_id, list(ad_ids)))
    return {r["ad_id"] for r in rows}

def save_thumb(conn, account_id, ad_id, data, content_type="image/jpeg"):
    conn.execute(
        """INSERT INTO thumbs (account_id, ad_id, content_type, bytes) VALUES (%s,%s,%s,%s)
           ON CONFLICT (account_id, ad_id) DO UPDATE SET bytes=EXCLUDED.bytes, content_type=EXCLUDED.content_type, updated_at=now()""",
        (account_id, ad_id, content_type, data))

def save_thumbs_batch(conn, account_id, items, content_type="image/jpeg"):
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO thumbs (account_id, ad_id, content_type, bytes) VALUES (%s,%s,%s,%s)
               ON CONFLICT (account_id, ad_id) DO UPDATE SET bytes=EXCLUDED.bytes, content_type=EXCLUDED.content_type, updated_at=now()""",
            [(account_id, ad_id, content_type, data) for ad_id, data in items])

def save_report_ads(conn, report_id, ads):
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO report_ads (report_id, ad_id, metrics) VALUES (%s,%s,%s)
               ON CONFLICT (report_id, ad_id) DO UPDATE SET metrics=EXCLUDED.metrics""",
            [(report_id, a["ad_id"], db.J(a["metrics"])) for a in ads])


def reuse_window_results(conn, rep, wfrom, wto):
    """Insights and Lab for the same user, account and window already built today: copy them instead of recomputing."""
    r = conn.execute("""SELECT id FROM reports WHERE user_id=%s AND account_id=%s AND window_from=%s AND window_to=%s
                          AND signal_c IS NOT NULL AND signal_d IS NOT NULL AND id <> %s::uuid
                        ORDER BY created_at DESC LIMIT 1""", (rep.user_id, rep.account_id, wfrom, wto, rep.id)).fetchone()
    if not r: return False
    conn.execute("""INSERT INTO report_payloads (report_id, kind, body)
                    SELECT %s::uuid, kind, body FROM report_payloads WHERE report_id=%s AND kind IN ('insights','lab')
                    ON CONFLICT (report_id, kind) DO UPDATE SET body = EXCLUDED.body, updated_at = now()""", (rep.id, r["id"]))
    return True


INSIGHTS_TTL_HOURS = 6

def get_insights(conn, account_id, date_from, date_to, hours=INSIGHTS_TTL_HOURS):
    r = conn.execute("""SELECT rows FROM insights_cache WHERE account_id=%s AND date_from=%s AND date_to=%s
                          AND fetched_at > now() - make_interval(hours => %s)""", (account_id, date_from, date_to, hours)).fetchone()
    return r["rows"] if r else None

def put_insights(conn, account_id, date_from, date_to, rows):
    conn.execute("""INSERT INTO insights_cache (account_id, date_from, date_to, rows) VALUES (%s,%s,%s,%s)
                    ON CONFLICT (account_id, date_from, date_to) DO UPDATE SET rows=EXCLUDED.rows, fetched_at=now()""",
                 (account_id, date_from, date_to, db.J(rows)))


def creative_key(ad):
    """Ads that run the same Meta creative (copies in other ad sets) read, say and look the same: one key for all of them."""
    return (ad.get("creative") or {}).get("creative_id") or ("ad", ad["ad_id"])

def unique_by_creative(ads):
    """First ad of each creative. Only these go to the models; the rest get the same result by copying (share_results)."""
    seen, out = set(), []
    for a in ads:
        k = creative_key(a)
        if k in seen: continue
        seen.add(k); out.append(a)
    return out

def share_results(conn, account_id, ad_ids):
    """Copy what has already been worked out (the model's reading, angle labels, product) onto ads that run the same creative but
    have not got it yet. The best finished sibling is used. No model call, one statement."""
    conn.execute("""
        UPDATE ad_cache t SET
          extraction = COALESCE(t.extraction, s.extraction),
          extraction_status = CASE WHEN t.extraction IS NULL THEN s.extraction_status ELSE t.extraction_status END,
          extraction_attempts = CASE WHEN t.extraction IS NULL THEN GREATEST(t.extraction_attempts, 1) ELSE t.extraction_attempts END,
          cluster_labels = COALESCE(t.cluster_labels, s.cluster_labels),
          product = COALESCE(t.product, s.product),
          updated_at = now()
        FROM (SELECT DISTINCT ON (creative->>'creative_id')
                     creative->>'creative_id' AS cid, extraction, extraction_status, cluster_labels, product
                FROM ad_cache
               WHERE account_id = %s AND extraction IS NOT NULL AND extraction_status IN ('ok', 'fallback')
                 AND creative->>'creative_id' IS NOT NULL
               ORDER BY creative->>'creative_id', (extraction_status = 'ok') DESC, (cluster_labels IS NOT NULL) DESC,
                        (product IS NOT NULL) DESC, updated_at DESC) s
        WHERE t.account_id = %s AND t.ad_id = ANY(%s) AND t.creative->>'creative_id' = s.cid
          AND (t.extraction IS NULL OR t.cluster_labels IS NULL OR t.product IS NULL)
    """, (account_id, account_id, list(ad_ids)))
