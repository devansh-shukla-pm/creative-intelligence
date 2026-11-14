"""Worker entry point: python -m worker.run --report <uuid>

Runs the whole pipeline for one report, setting each signal as soon as its piece is ready.
Safe to re-run: every step reads the caches first.
"""
from __future__ import annotations
import argparse, datetime, sys, traceback, concurrent.futures as cf
from . import config, db, cache
from .report import Report, ReportError
from .llm import get_llm
from .sources import get_source
from . import extract, cluster, naming, assemble, insights
from .lab.model import compute_lab, eligible_products

def previous_period(rep):
    """The period of equal length right before the report's range."""
    a = datetime.date.fromisoformat(rep.date_from); b = datetime.date.fromisoformat(rep.date_to)
    n = (b - a).days + 1
    pb = a - datetime.timedelta(days=1)
    return (pb - datetime.timedelta(days=n - 1)).isoformat(), pb.isoformat()

def stage_a(rep, source):
    rep.progress("pulling", "Pulling your ads from Meta")
    ads = source.fetch_ads(rep, on_progress=lambda m: rep.progress("pulling", m))
    if not ads:
        raise ReportError("No ads with spend were found for this account and date range.")
    prev = source.period_totals(rep, *previous_period(rep))
    conn = rep.conn
    for a in ads:
        cache.save_creative(conn, rep.account_id, a["ad_id"], {**a["creative"], "ad_name": a["ad_name"],
                            "campaign_id": a.get("campaign_id"), "campaign_name": a.get("campaign_name")})
    # thumbnails: only for ads that do not have one yet
    have = cache.has_thumb(conn, rep.account_id, [a["ad_id"] for a in ads])
    need = [a for a in ads if a["ad_id"] not in have]
    if need:
        rep.progress("pulling", f"Saving {len(need)} thumbnails")
        with cf.ThreadPoolExecutor(max_workers=8) as pool:
            for ad, data in zip(need, pool.map(source.thumbnail, need)):
                if data: cache.save_thumb(conn, rep.account_id, ad["ad_id"], data)
    cache.save_report_ads(conn, rep.id, ads)
    db.upsert_payload(conn, rep.id, "audit", assemble.audit_rows(ads))
    db.upsert_payload(conn, rep.id, "cmt_ads", assemble.cmt_ads(ads))
    db.upsert_payload(conn, rep.id, "data", assemble.build_data(ads, {}, prev))   # metrics only until classification is done
    rep.signal("a")
    return ads, prev

def stage_b(rep, source, llm, ads, prev=None):
    conn = rep.conn
    ids = [a["ad_id"] for a in ads]
    cached = cache.load_cache(conn, rep.account_id, ids)

    rep.progress("extracting", "Reading your ads", 0, len(ads))
    extract.run_extraction(conn, rep, llm, source, ads, cached,
                           lambda m, d=None, t=None: rep.progress("extracting", m, d, t))
    cached = cache.load_cache(conn, rep.account_id, ids)
    extracted = [{"ad_id": i, "extraction": cached[i]["extraction"]} for i in ids
                 if cached.get(i) and cached[i].get("extraction")]

    rep.progress("clustering", "Grouping similar messages", 0, len(extracted))
    cluster.run_clustering(conn, rep, llm, extracted, cached, lambda m, d=None, t=None: rep.progress("clustering", m, d, t))
    cached = cache.load_cache(conn, rep.account_id, ids)

    rep.progress("naming", "Naming your products", 0, len(extracted))
    naming.run_naming(conn, rep, llm, extracted, cached, lambda m, d=None, t=None: rep.progress("naming", m, d, t))
    cached = cache.load_cache(conn, rep.account_id, ids)

    rep.progress("assembling", "Putting your report together")
    classified = {i: {"extraction": cached[i].get("extraction"), "labels": cached[i].get("cluster_labels"), "product": cached[i].get("product")}
                  for i in ids if cached.get(i) and cached[i].get("extraction")}
    data = assemble.build_data(ads, classified, prev)
    db.upsert_payload(conn, rep.id, "cmt_dims", assemble.build_cmt_dims(ads, classified))
    db.upsert_payload(conn, rep.id, "data", data)
    rep.signal("b")
    return data

def stage_c(rep, llm, data):
    rep.progress("insights", "Finding what is worth acting on")
    cards = insights.run_insights(data, llm, lambda m: rep.progress("insights", m))
    db.upsert_payload(rep.conn, rep.id, "insights", cards)
    rep.signal("c")

def stage_d(rep, data):
    rep.progress("lab", "Building recipes")
    names = {s["id"]: s["name"] for s in data["skus"]}
    lab = compute_lab(data["ads"], names, config.LAB_MIN_ADS, config.LAB_MIN_SPEND, config.LAB_BACKTEST_REPS,
                      progress=lambda m: rep.progress("lab", m))
    db.upsert_payload(rep.conn, rep.id, "lab", lab)
    rep.signal("d")

def run(report_id):
    conn = db.connect(); db.migrate(conn)
    rep = Report.load(conn, report_id)
    rep.start()
    try:
        llm = get_llm(); source = get_source(rep)
        ads, prev = stage_a(rep, source)
        data = stage_b(rep, source, llm, ads, prev)
        # insights and the Lab are independent: run them side by side
        with cf.ThreadPoolExecutor(max_workers=2) as pool:
            fc = pool.submit(lambda: _own_conn(report_id, "c", llm, data))
            fd = pool.submit(lambda: _own_conn(report_id, "d", llm, data))
            errs = [f.exception() for f in (fc, fd) if f.exception()]
        if errs:
            raise errs[0]
        rep.finish()
    except ReportError as e:
        rep.fail(str(e)); print("FAILED:", e, file=sys.stderr); return 1
    except Exception as e:
        traceback.print_exc()
        rep.fail("Something went wrong while building the report. Try again.")
        return 1
    return 0

def _own_conn(report_id, which, llm, data):
    """Each parallel stage uses its own database connection."""
    conn = db.connect(); rep = Report.load(conn, report_id)
    if which == "c": stage_c(rep, llm, data)
    else: stage_d(rep, data)

def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--report", required=True)
    return run(ap.parse_args(argv).report)

if __name__ == "__main__":
    sys.exit(main())
