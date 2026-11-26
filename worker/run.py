"""Worker entry point: python -m worker.run --report <uuid>

Runs the whole pipeline for one report, setting each signal as soon as its piece is ready.
Safe to re-run: every step reads the caches first.
"""
from __future__ import annotations
import argparse, dataclasses, datetime, sys, traceback, concurrent.futures as cf
from . import config, db, cache
from .report import Report, ReportError, ReportCancelled
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

def window_range():
    """The last WINDOW_DAYS up to today: what insights and the Lab always run on."""
    today = datetime.date.today()
    return (today - datetime.timedelta(days=config.WINDOW_DAYS - 1)).isoformat(), today.isoformat()

def window_label():
    m = round(config.WINDOW_DAYS / 30)
    return f"{m} month{'s' if m != 1 else ''}" if m >= 1 else f"{config.WINDOW_DAYS} days"

def _save_creatives(rep, ads):
    cache.save_creatives_batch(rep.conn, rep.account_id, [
        (a["ad_id"], {**a["creative"], "ad_name": a["ad_name"], "campaign_id": a.get("campaign_id"), "campaign_name": a.get("campaign_name")})
        for a in ads])

_BG = []      # background jobs (thumbnails) that must finish before the report is marked done

def _thumbs_job(account_id, source, ads):
    """Downloads and stores thumbnails for ads that have none yet. Runs beside the main pipeline on its own connection, so the
    report never waits for it; the page simply shows thumbnails as they arrive."""
    try:
        conn = db.connect()
        have = cache.has_thumb(conn, account_id, [a["ad_id"] for a in ads])
        need = [a for a in ads if a["ad_id"] not in have]
        with cf.ThreadPoolExecutor(max_workers=24) as pool:
            for i in range(0, len(need), 48):
                chunk = need[i:i + 48]
                got = [(ad["ad_id"], d) for ad, d in zip(chunk, pool.map(source.thumbnail, chunk)) if d]
                if got: cache.save_thumbs_batch(conn, account_id, got)
        conn.close()
    except Exception:
        traceback.print_exc()           # thumbnails are cosmetic: never fail the report over them

def _start_thumbs(rep, source, ads):
    ex = cf.ThreadPoolExecutor(max_workers=1)
    _BG.append(ex.submit(_thumbs_job, rep.account_id, source, ads))

def stage_a(rep, source):
    rep.progress("pulling", "Pulling your ads from Meta")
    ads = source.fetch_ads(rep, on_progress=lambda m: rep.progress("pulling", m))
    if not ads:
        raise ReportError("No ads with spend were found for this account and date range.")
    prev = source.period_totals(rep, *previous_period(rep))        # one account-level call
    conn = rep.conn
    _save_creatives(rep, ads)
    cache.save_report_ads(conn, rep.id, ads)
    db.upsert_payload(conn, rep.id, "audit", assemble.audit_rows(ads))
    db.upsert_payload(conn, rep.id, "cmt_ads", assemble.cmt_ads(ads))
    db.upsert_payload(conn, rep.id, "data", assemble.build_data(ads, {}, prev))   # metrics only until classification is done
    rep.signal("a")
    _start_thumbs(rep, source, ads)
    return ads, prev

def _classify(rep, source, llm, ads, prev=None):
    """Read, group and name the ads, then assemble the datasets. Writes nothing the page shows; returns (data, classified)."""
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
    return assemble.build_data(ads, classified, prev), classified

def stage_b(rep, source, llm, ads, prev=None):
    data, classified = _classify(rep, source, llm, ads, prev)
    db.upsert_payload(rep.conn, rep.id, "cmt_dims", assemble.build_cmt_dims(ads, classified))
    db.upsert_payload(rep.conn, rep.id, "data", data)
    rep.signal("b")
    return data

def stage_window(rep, source, llm, range_ads, range_data):
    """Insights and the Lab run on the last WINDOW_DAYS up to today, whatever range the report shows. Ads already read for the
    range (or for an earlier report) come from the cache, so only newer ads cost model calls."""
    wf, wt = window_range()
    pfx = f"Processing {window_label()} of data · "
    wrep = dataclasses.replace(rep, date_from=wf, date_to=wt, prefix=pfx)
    rep.conn.execute("UPDATE reports SET window_from=%s, window_to=%s WHERE id=%s", (wf, wt, rep.id))
    if cache.reuse_window_results(rep.conn, rep, wf, wt):
        rep.signal("c"); rep.signal("d"); return
    if (rep.date_from, rep.date_to) == (wf, wt):
        data_w = range_data
    else:
        wrep.progress("pulling", "Pulling your ads from Meta")
        ads_w = source.fetch_ads(wrep, on_progress=lambda m: wrep.progress("pulling", m))
        if not ads_w:
            db.upsert_payload(rep.conn, rep.id, "insights", [])
            db.upsert_payload(rep.conn, rep.id, "lab", {"meta": {"n_ads": 0}, "products": []})
            rep.signal("c"); rep.signal("d"); return
        _save_creatives(wrep, ads_w)
        _start_thumbs(rep, source, ads_w)
        data_w, _ = _classify(wrep, source, llm, ads_w, None)
    with cf.ThreadPoolExecutor(max_workers=2) as pool:        # insights and the Lab are independent: side by side
        fc = pool.submit(lambda: _own_conn(rep.id, "c", llm, data_w, pfx))
        fd = pool.submit(lambda: _own_conn(rep.id, "d", llm, data_w, pfx))
        errs = [f.exception() for f in (fc, fd) if f.exception()]
    if errs:
        raise errs[0]

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
    try:
        rep.start()
        llm = get_llm(); source = get_source(rep)
        ads, prev = stage_a(rep, source)
        data = stage_b(rep, source, llm, ads, prev)
        stage_window(rep, source, llm, ads, data)
        for job in _BG: job.result()          # thumbnails still downloading
        _BG.clear()
        from . import meta_client
        print(f"[meta] requests made by this run: {meta_client.CALLS[0]}", flush=True)
        rep.finish()
    except ReportCancelled:
        print("Cancelled by the user.", flush=True); return 0
    except ReportError as e:
        rep.fail(str(e)); print("FAILED:", e, file=sys.stderr)
        return 0                          # the failure is shown on the report page; the job itself did its work, so no GitHub alert
    except Exception as e:
        traceback.print_exc()
        rep.fail("Something went wrong while building the report. Try again.")
        return 1
    return 0

def _own_conn(report_id, which, llm, data, prefix=""):
    """Each parallel stage uses its own database connection."""
    conn = db.connect(); rep = dataclasses.replace(Report.load(conn, report_id), prefix=prefix)
    if which == "c": stage_c(rep, llm, data)
    else: stage_d(rep, data)

def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--report", required=True)
    return run(ap.parse_args(argv).report)

if __name__ == "__main__":
    sys.exit(main())
