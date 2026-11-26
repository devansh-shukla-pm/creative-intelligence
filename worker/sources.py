"""Where ads come from. The pipeline only talks to this interface, so real Meta and the mock are interchangeable."""
from __future__ import annotations
from . import blocks, cache, config, crypto, db, meta_client as mc
from .report import ReportError

class MetaSource:
    def __init__(self, token, account_id=None, rep=None):
        self.token = token
        self.account_id = account_id
        self.rep = rep
        self._acct_videos = None            # video_id -> info from the ad account's own video library, fetched at most once

    @classmethod
    def for_report(cls, rep):
        blob = rep.user_token_blob()
        if not blob:
            raise ReportError("Meta login not found. Connect Meta again.")
        return cls(crypto.decrypt(blob), rep.account_id, rep)

    def fetch_metrics(self, rep, on_progress=None):
        """Phase 1: the numbers (spend, ROAS, ...) as insight-shaped rows. Only the date gaps not stored yet are asked from Meta."""
        try:
            conn = rep.conn
            if blocks.needs_pull(conn, rep.account_id, rep.date_from, rep.date_to):
                with db.MetaGate(rep):
                    block_ids, _ = blocks.ensure(conn, self.token, rep.account_id, rep.date_from, rep.date_to, on_progress)
            else:
                block_ids = blocks.plan(conn, rep.account_id, rep.date_from, rep.date_to)[0]
                if on_progress: on_progress("Loaded your ad numbers (already pulled)")
            rows = blocks.aggregate(conn, rep.account_id, block_ids)
            if not rows:
                with db.MetaGate(rep):
                    d = mc.diagnose_empty(self.token, rep.account_id, rep.date_from, rep.date_to)
                print(f"[meta] no ads with spend returned: {d}", flush=True)
                raise ReportError(mc.explain_empty(d, rep.date_from, rep.date_to))
            return rows
        except mc.TokenExpired:
            raise ReportError("Your Meta login expired. Connect Meta again and generate the report.")
        except mc.MetaError as e:
            raise ReportError(f"Meta API error: {e}")

    def provisional_ads(self, rep, rows):
        """Ads with their numbers and whatever creative info is already cached, so the page can show metrics before creative details load.
        Ads we know nothing about yet are marked PENDING."""
        known = cache.load_cache(rep.conn, rep.account_id, [r["ad_id"] for r in rows])
        ads = []
        for r in rows:
            cr = (known.get(r["ad_id"]) or {}).get("creative") or {}
            ads.append({"ad_id": r["ad_id"], "ad_name": r.get("ad_name") or cr.get("ad_name") or "",
                        "campaign_id": r.get("campaign_id"), "campaign_name": r.get("campaign_name"),
                        "metrics": mc.metrics_from_insight(r), "creative": cr if cr.get("media_type") else {"media_type": "PENDING"}})
        return ads

    def attach_creatives(self, rep, rows, on_progress=None):
        """Phase 2: creative details (format, status, preview link, ad copy). Only for ads not read in the last week.
        -> (ads, number of ads whose details were just fetched)"""
        try:
            ids = [r["ad_id"] for r in rows]
            fresh = cache.fresh_creatives(rep.conn, rep.account_id, ids, hours=168)
            need = [i for i in ids if i not in fresh]
            details = {}
            if need:
                with db.MetaGate(rep):
                    details = mc.pull_ad_details(self.token, need,
                                                 on_progress=(lambda n: on_progress(f"Reading creative details: {n} of {len(need)}")) if on_progress else None)
        except mc.TokenExpired:
            raise ReportError("Your Meta login expired. Connect Meta again and generate the report.")
        except mc.MetaError as e:
            raise ReportError(f"Meta API error: {e}")
        ads = []
        for r in rows:
            d = details.get(r["ad_id"], {})
            ads.append({
                "ad_id": r["ad_id"], "ad_name": r.get("ad_name") or d.get("name") or (fresh.get(r["ad_id"]) or {}).get("ad_name") or "",
                "campaign_id": r.get("campaign_id"), "campaign_name": r.get("campaign_name"),
                "metrics": mc.metrics_from_insight(r), "creative": fresh[r["ad_id"]] if r["ad_id"] in fresh else mc.creative_info(d),
            })
        return ads, len(need)

    def fetch_ads(self, rep, on_progress=None):
        """Both phases at once (the 60-day window uses this)."""
        return self.attach_creatives(rep, self.fetch_metrics(rep, on_progress), on_progress)[0]

    def period_totals(self, rep, since, until):
        stored = blocks.stored_totals(rep.conn, rep.account_id, since, until)       # the whole period is already stored: no Meta call
        if stored: return stored
        try:
            with db.MetaGate(rep):
                return mc.pull_period_totals(self.token, rep.account_id, since, until)
        except mc.MetaError:
            return None                      # the trend is optional: never fail the report over it

    def _account_videos(self, video_ids):
        if self._acct_videos is None and self.account_id:
            self._acct_videos = mc.pull_account_videos(self.token, self.account_id, video_ids)
        return self._acct_videos or {}

    def video_urls(self, ads):
        """ad_id -> fresh video url, only for the ads that need extraction."""
        by_video = {a["creative"]["video_id"]: a["ad_id"] for a in ads if a["creative"].get("video_id")}
        with db.MetaGate(self.rep):
            src = mc.pull_video_sources(self.token, by_video.keys())
        urls = {by_video[v]: (info or {}).get("source") for v, info in src.items() if (info or {}).get("source")}
        missing = [v for v in by_video if by_video[v] not in urls]
        if missing:                          # Page-level access refused: try the ad account's own video library
            with db.MetaGate(self.rep):
                acct = self._account_videos(missing)
            for v in missing:
                if (acct.get(v) or {}).get("source"): urls[by_video[v]] = acct[v]["source"]
        return urls

    def video_frames(self, ads):
        """ad_id -> still frames, used when the video file itself is not available."""
        by_video = {a["creative"]["video_id"]: a["ad_id"] for a in ads if a["creative"].get("video_id")}
        with db.MetaGate(self.rep):
            out = {by_video[v]: u for v, u in mc.pull_video_frames(self.token, by_video.keys()).items()}
        missing = [v for v in by_video if by_video[v] not in out]
        if missing:
            with db.MetaGate(self.rep):
                acct = self._account_videos(missing)
            for v in missing:
                uris = [t.get("uri") for t in ((acct.get(v) or {}).get("thumbnails") or {}).get("data", []) if t.get("uri")]
                if uris:
                    idx = sorted({0, len(uris) // 3, (2 * len(uris)) // 3, len(uris) - 1}) if len(uris) > 4 else range(len(uris))
                    out[by_video[v]] = [uris[i] for i in idx]
        return out

    def thumbnail(self, ad):
        c = ad["creative"]
        return mc.fetch_thumbnail(c.get("image_url") or c.get("thumbnail_url"))

def get_source(rep):
    if config.MOCK_META:
        from .mock import MockSource
        return MockSource()
    return MetaSource.for_report(rep)
