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

def save_extraction(conn, account_id, ad_id, extraction, status, attempts):
    conn.execute(
        """UPDATE ad_cache SET extraction=%s, extraction_status=%s, extraction_attempts=%s, updated_at=now()
            WHERE account_id=%s AND ad_id=%s""",
        (db.J(extraction) if extraction is not None else None, status, attempts, account_id, ad_id))

def bump_attempt(conn, account_id, ad_id, attempts, status=None):
    conn.execute("UPDATE ad_cache SET extraction_attempts=%s, extraction_status=COALESCE(%s, extraction_status), updated_at=now() WHERE account_id=%s AND ad_id=%s",
                 (attempts, status, account_id, ad_id))

def save_cluster_labels(conn, account_id, ad_id, labels):
    conn.execute("UPDATE ad_cache SET cluster_labels=%s, updated_at=now() WHERE account_id=%s AND ad_id=%s",
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

def save_report_ads(conn, report_id, ads):
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO report_ads (report_id, ad_id, metrics) VALUES (%s,%s,%s)
               ON CONFLICT (report_id, ad_id) DO UPDATE SET metrics=EXCLUDED.metrics""",
            [(report_id, a["ad_id"], db.J(a["metrics"])) for a in ads])
