"""Where ads come from. The pipeline only talks to this interface, so real Meta and the mock are interchangeable."""
from __future__ import annotations
from . import config, crypto, meta_client as mc
from .report import ReportError

class MetaSource:
    def __init__(self, token):
        self.token = token

    @classmethod
    def for_report(cls, rep):
        blob = rep.user_token_blob()
        if not blob:
            raise ReportError("Meta login not found. Connect Meta again.")
        return cls(crypto.decrypt(blob))

    def fetch_ads(self, rep, on_progress=None):
        """-> [{ad_id, ad_name, campaign_id, campaign_name, metrics, creative}]"""
        try:
            rows = mc.pull_insights(self.token, rep.account_id, rep.date_from, rep.date_to,
                                    on_page=(lambda n: on_progress(f"Pulled {n} ads from Meta")) if on_progress else None)
            ids = [r["ad_id"] for r in rows]
            details = mc.pull_ad_details(self.token, ids) if ids else {}
        except mc.TokenExpired:
            raise ReportError("Your Meta login expired. Connect Meta again and generate the report.")
        except mc.MetaError as e:
            raise ReportError(f"Meta API error: {e}")
        ads = []
        for r in rows:
            d = details.get(r["ad_id"], {})
            ads.append({
                "ad_id": r["ad_id"], "ad_name": r.get("ad_name") or d.get("name") or "",
                "campaign_id": r.get("campaign_id"), "campaign_name": r.get("campaign_name"),
                "metrics": mc.metrics_from_insight(r), "creative": mc.creative_info(d),
            })
        return ads

    def video_urls(self, ads):
        """ad_id -> fresh video url, only for the ads that need extraction."""
        by_video = {a["creative"]["video_id"]: a["ad_id"] for a in ads if a["creative"].get("video_id")}
        src = mc.pull_video_sources(self.token, by_video.keys())
        return {by_video[v]: (info or {}).get("source") for v, info in src.items() if (info or {}).get("source")}

    def thumbnail(self, ad):
        c = ad["creative"]
        return mc.fetch_thumbnail(c.get("image_url") or c.get("thumbnail_url"))

def get_source(rep):
    if config.MOCK_META:
        from .mock import MockSource
        return MockSource()
    return MetaSource.for_report(rep)
