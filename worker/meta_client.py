"""Meta Marketing API pulls: ad-level insights for a date range + creative details.

Produces rows in the same shape as the old creative-audit table-report API
(ad_id, total_spend, roas, cpr, purchase_count, purchase_value, lpv/atc/conversion percentages ...)
plus campaign id and name. Percentages are relative to link clicks, matching the old API.
"""
from __future__ import annotations
import io, json, time
import requests
from . import config

GRAPH = f"https://graph.facebook.com/{config.META_API_VERSION}"
RATE_LIMIT_CODES = {4, 17, 32, 341, 613, 80000, 80003, 80004}
PURCHASE = ["omni_purchase", "offsite_conversion.fb_pixel_purchase", "purchase"]
ATC = ["omni_add_to_cart", "offsite_conversion.fb_pixel_add_to_cart", "add_to_cart"]
LPV = ["landing_page_view"]
INSIGHT_FIELDS = ("ad_id,ad_name,campaign_id,campaign_name,adset_id,adset_name,spend,impressions,frequency,"
                  "clicks,inline_link_clicks,actions,action_values")
CREATIVE_FIELDS = ("id,name,effective_status,preview_shareable_link,"
                   "creative.thumbnail_width(480).thumbnail_height(480){id,thumbnail_url,image_url,video_id,"
                   "object_story_spec,asset_feed_spec}")
CREATIVE_FIELDS_PLAIN = ("id,name,effective_status,preview_shareable_link,"
                         "creative{id,thumbnail_url,image_url,video_id,object_story_spec,asset_feed_spec}")

class MetaError(Exception):
    def __init__(self, msg, code=None, status=None):
        super().__init__(msg); self.code, self.status = code, status

class TokenExpired(MetaError):
    """The user's Meta token is no longer valid: they need to connect Meta again."""

def _get(url, params=None, token=None, tries=5):
    params = dict(params or {})
    if token and "access_token" not in params:
        params["access_token"] = token
    last = None
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params if not url.startswith("http") or "?" not in url else None, timeout=60)
        except requests.RequestException as e:
            last = MetaError(f"network error: {e}")
            time.sleep(2 ** attempt); continue
        body = {}
        try: body = r.json()
        except ValueError: pass
        err = body.get("error") if isinstance(body, dict) else None
        if r.status_code == 200 and not err:
            return body
        code = (err or {}).get("code")
        msg = (err or {}).get("message") or f"HTTP {r.status_code}"
        if code == 190 or r.status_code == 401:
            raise TokenExpired(msg, code, r.status_code)
        if code in RATE_LIMIT_CODES or r.status_code in (429, 500, 502, 503):
            last = MetaError(msg, code, r.status_code)
            time.sleep(min(60, 5 * (2 ** attempt))); continue
        raise MetaError(msg, code, r.status_code)
    raise last or MetaError("Meta request failed")

def _paged(path, params, token, on_page=None):
    """Follow paging.next until exhausted."""
    out = []
    body = _get(GRAPH + path, params, token)
    while True:
        out.extend(body.get("data", []))
        if on_page: on_page(len(out))
        nxt = (body.get("paging") or {}).get("next")
        if not nxt: return out
        body = _get(nxt, None, None)          # next URLs already carry the token and cursor

def _action(lst, types):
    for t in types:
        for a in lst or []:
            if a.get("action_type") == t:
                try: return float(a.get("value", 0))
                except (TypeError, ValueError): return 0.0
    return 0.0

def _f(x, d=0.0):
    try: return float(x)
    except (TypeError, ValueError): return d

def metrics_from_insight(row: dict) -> dict:
    spend = _f(row.get("spend"))
    clicks = _f(row.get("clicks")); link_clicks = _f(row.get("inline_link_clicks")); impr = _f(row.get("impressions"))
    purchases = _action(row.get("actions"), PURCHASE); value = _action(row.get("action_values"), PURCHASE)
    atc = _action(row.get("actions"), ATC); lpv = _action(row.get("actions"), LPV)
    pct = lambda n: (100.0 * n / link_clicks) if link_clicks > 0 else 0.0
    return {
        "total_spend": spend, "purchase_count": purchases, "purchase_value": value,
        "roas": (value / spend) if spend > 0 else 0.0,
        "cpr": (spend / purchases) if purchases > 0 else None,
        "frequency": _f(row.get("frequency")),
        "impressions": impr, "clicks": clicks, "link_clicks": link_clicks,
        "ctr": (100.0 * clicks / impr) if impr > 0 else 0.0,
        "cpc": (spend / clicks) if clicks > 0 else 0.0,
        "cpm": (1000.0 * spend / impr) if impr > 0 else 0.0,
        "atc_count": atc, "atc_percentage": pct(atc),
        "lpv_count": lpv, "lpv_percentage": pct(lpv),
        "conversion_percentage": pct(purchases),
    }

def pull_insights(token, account_id, since, until, on_page=None):
    params = {
        "level": "ad", "fields": INSIGHT_FIELDS, "limit": 200,
        "time_range": json.dumps({"since": since, "until": until}),
        "filtering": json.dumps([{"field": "spend", "operator": "GREATER_THAN", "value": "0"}]),
    }
    try:
        return _paged(f"/act_{account_id}/insights", params, token, on_page)
    except MetaError as e:
        if "reduce the amount of data" in str(e).lower() or e.code == 1:
            return _async_insights(token, account_id, params)
        raise

def _async_insights(token, account_id, params):
    """Large accounts: run the report as a background job on Meta's side and poll it."""
    r = requests.post(f"{GRAPH}/act_{account_id}/insights", data={**params, "access_token": token}, timeout=60).json()
    rid = r.get("report_run_id")
    if not rid: raise MetaError(f"Could not start async insights job: {r}")
    for _ in range(180):                                   # up to ~15 minutes
        st = _get(f"{GRAPH}/{rid}", {"fields": "async_status,async_percent_completion"}, token)
        if st.get("async_status") == "Job Completed": break
        if st.get("async_status") in ("Job Failed", "Job Skipped"): raise MetaError(f"Async insights job {st.get('async_status')}")
        time.sleep(5)
    else:
        raise MetaError("Async insights job timed out")
    return _paged(f"/{rid}/insights", {"limit": 500}, token)

def _chunks(seq, n):
    for i in range(0, len(seq), n): yield seq[i:i + n]

def pull_ad_details(token, ad_ids):
    """Creative info per ad (multi-id read, 50 at a time)."""
    out = {}
    for chunk in _chunks(list(ad_ids), 50):
        try:
            body = _get(GRAPH + "/", {"ids": ",".join(chunk), "fields": CREATIVE_FIELDS}, token)
        except MetaError as e:
            if e.code != 100: raise
            body = _get(GRAPH + "/", {"ids": ",".join(chunk), "fields": CREATIVE_FIELDS_PLAIN}, token)   # modifier syntax not accepted
        out.update(body)
    return out

def pull_video_sources(token, video_ids):
    """Short-lived mp4 URLs the extraction model can fetch right now. Never stored long term."""
    out = {}
    for chunk in _chunks(sorted(set(video_ids)), 50):
        try:
            body = _get(GRAPH + "/", {"ids": ",".join(chunk), "fields": "source,picture,length"}, token)
        except MetaError:
            continue                                            # no permission for some videos: extraction falls back to the thumbnail
        out.update(body)
    return out

def creative_info(detail: dict) -> dict:
    """Flatten Meta's creative object into what we keep per ad."""
    cr = detail.get("creative") or {}
    oss = cr.get("object_story_spec") or {}
    afs = cr.get("asset_feed_spec") or {}
    link = oss.get("link_data") or {}
    children = link.get("child_attachments") or []
    video_id = cr.get("video_id") or (oss.get("video_data") or {}).get("video_id") or next(
        (v.get("video_id") for v in (afs.get("videos") or []) if v.get("video_id")), None)
    slides = [c.get("picture") or c.get("image_url") for c in children if (c.get("picture") or c.get("image_url"))]
    if video_id: media = "VIDEO"
    elif len(children) > 1: media = "CAROUSEL"
    else: media = "IMAGE"
    image_url = cr.get("image_url") or link.get("picture") or (oss.get("photo_data") or {}).get("url") or \
        next((i.get("url") for i in (afs.get("images") or []) if i.get("url")), None)
    return {
        "creative_id": cr.get("id"), "media_type": media, "video_id": video_id,
        "image_url": image_url, "thumbnail_url": cr.get("thumbnail_url"),
        "carousel_urls": slides if media == "CAROUSEL" else [],
        "preview_link": detail.get("preview_shareable_link"),
        "status": "ACTIVE" if detail.get("effective_status") == "ACTIVE" else "PAUSED",
    }

def fetch_thumbnail(url, max_px=480):
    """Download an image and shrink it to a small JPEG (about 20-40 KB). Returns bytes or None."""
    if not url: return None
    try:
        from PIL import Image
        r = requests.get(url, timeout=30)
        if r.status_code != 200: return None
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
        im.thumbnail((max_px, max_px))
        buf = io.BytesIO(); im.save(buf, "JPEG", quality=82, optimize=True)
        return buf.getvalue()
    except Exception:
        return None
