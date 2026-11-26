"""Builds the datasets the UI reads, from metrics + extraction + cluster labels + product names.

 audit    ranking-engine rows (same shape as the old table-report API, plus campaign)
 cmt_ads  rows for the Creative Metric Explorer
 data     {meta, stage_defs, skus, ads[]} used by Overview filters, Insights and the Lab
 cmt_dims dimension aggregates for Story Matrix Analysis
"""
from __future__ import annotations
import re
from collections import OrderedDict

STAGE_DEFS = [
    {"key": "problem-statement", "label": "Problem Statement", "mandatory": True, "question": "What problem does the ad open with?"},
    {"key": "hook-line", "label": "Hook Line", "mandatory": True, "question": "How does the first 3 seconds land?"},
    {"key": "primary-usp-claim", "label": "Primary USP Claim", "mandatory": True, "question": "What is the creative proving?"},
    {"key": "use-case-scenario", "label": "Use Case Scenario", "mandatory": True, "question": "What context does the creative live in?"},
    {"key": "cta-text", "label": "CTA Text", "mandatory": True, "question": "How does the creative close?"},
    {"key": "testimonial-claim", "label": "Testimonial Claim", "mandatory": False, "question": "Activate for UGC / testimonial formats"},
    {"key": "proof-points", "label": "Proof Points", "mandatory": False, "question": "Activate for credibility-led creatives"},
    {"key": "credibility-signal", "label": "Credibility Signal", "mandatory": False, "question": "Activate when brand asset is featured"},
    {"key": "offer-details", "label": "Offer Details", "mandatory": False, "question": "Activate only when a promotion is live"},
    {"key": "comparison-axis", "label": "Comparison Axis", "mandatory": False, "question": "Activate for myth-busting / comparison formats"},
]
# stage key -> free-text field the clustering prompt produced
STAGE_FIELD = {
    "problem-statement": "problem_statement_text", "hook-line": "hook_line_text", "primary-usp-claim": "primary_usp_claim",
    "use-case-scenario": "use_case_scenario", "cta-text": "cta_text", "testimonial-claim": "testimonial_claim",
    "proof-points": "proof_points", "credibility-signal": "credibility_signal", "offer-details": "offer_details",
    "comparison-axis": "comparison_axis",
}
# Story Matrix dimensions -> extraction field (LAYOUT_TYPE has no source in the extraction schema, so it is not produced)
DIMENSIONS = OrderedDict([
    ("STORYTELLING_STYLE", "storytelling_style"), ("HOOK_TYPE", "hook_type"), ("VISUAL_TYPE", "visual_style"),
    ("PRODUCT_INTERACTION", "Product Interaction Type"), ("PRODUCT_PLACEMENT_TIMING", "Product_Placement_Timing"),
    ("TARGET_AGE", "target_demographic.age"), ("TARGET_GENDER", "target_demographic.gender"), ("AUDIO", "audio_type"),
    ("PRODUCT_POSITION", "Product Position on Frame"),
])

def _slug(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", str(s).lower())).strip("-")

def thumb_url(ad_id):
    return f"/api/thumb?ad={ad_id}"

APPROACH = {"push brand push": "Push Brand", "push brand": "Push Brand", "push problem": "Push Problem", "push product": "Push Product",
            "push differentiation": "Push Differentiation", "push offer": "Push Offer", "retarget": "Retarget"}

def _as_list(v):
    return v if isinstance(v, list) else ([v] if v else [])

# ---------- ranking rows and explorer rows (metrics only) ----------
def audit_rows(ads):
    rows = []
    for a in ads:
        m, c = a["metrics"], a["creative"]
        rows.append({
            "ad_id": a["ad_id"], "status": c.get("status", "ACTIVE"), "ad_name": a["ad_name"], "media_type": c.get("media_type", "IMAGE"),
            "thumbnail_url": thumb_url(a["ad_id"]), "creative_url": c.get("preview_link") or "",
            "cpr": m["cpr"] or 0, "total_spend": m["total_spend"], "roas": m["roas"], "frequency": m["frequency"],
            "purchase_count": m["purchase_count"], "purchase_value": m["purchase_value"],
            "conversion_percentage": m["conversion_percentage"], "atc_count": m["atc_count"], "atc_percentage": m["atc_percentage"],
            "lpv_count": m["lpv_count"], "lpv_percentage": m["lpv_percentage"],
            "campaign_id": a.get("campaign_id"), "campaign_name": a.get("campaign_name"),
        })
    return rows

def cmt_ads(ads, limit=500):
    rows = []
    for a in sorted(ads, key=lambda x: -x["metrics"]["roas"])[:limit]:
        m, c = a["metrics"], a["creative"]
        rows.append({"n": a["ad_name"], "th": thumb_url(a["ad_id"]), "cu": c.get("preview_link") or "", "mt": c.get("media_type", "IMAGE"),
                     "cpr": round(m["cpr"] or 0, 2), "spend": round(m["total_spend"], 2), "roas": round(m["roas"], 2),
                     "frequency": round(m["frequency"], 2), "purchase_count": m["purchase_count"], "purchase_value": round(m["purchase_value"], 2),
                     "conversion_percentage": round(m["conversion_percentage"], 2), "atc_percentage": round(m["atc_percentage"], 2),
                     "lpv_percentage": round(m["lpv_percentage"], 2)})
    return rows

# ---------- DATA ----------
def build_data(ads, classified, prev=None):
    """classified: {ad_id: {extraction, labels, product}}. Unclassified ads stay in the data (so totals are stable)."""
    sku_names = OrderedDict()
    out_ads = []
    creative_counts = {}
    for a in ads:
        cid = a["creative"].get("creative_id") or a["ad_id"]
        creative_counts[cid] = creative_counts.get(cid, 0) + 1
    for a in ads:
        m, c = a["metrics"], a["creative"]
        k = classified.get(a["ad_id"]) or {}
        ext, labels, prod = k.get("extraction") or {}, k.get("labels") or {}, k.get("product") or {}
        names = prod.get("products") or []
        for n in names: sku_names.setdefault(_slug(n), n)
        stages = {s["key"]: labels.get(STAGE_FIELD[s["key"]]) or "" for s in STAGE_DEFS}
        life = ext.get("Customer life cycle")
        presence = [str(p).lower() for p in _as_list(ext.get("creator_presence"))]
        out_ads.append({
            "ad_id": a["ad_id"], "creative_id": c.get("creative_id") or a["ad_id"],
            "creative_url": c.get("preview_link") or "", "thumb_url": thumb_url(a["ad_id"]),
            "media_type": c.get("media_type", "IMAGE"), "status": c.get("status", "ACTIVE"),
            "skus": [_slug(n) for n in names], "is_multi_sku": bool(prod.get("is_multi")),
            "category": _slug(prod["category"]) if prod.get("category") else "",
            "campaign": a.get("campaign_name") or None, "campaign_id": a.get("campaign_id"),
            "approach": APPROACH.get(str(life or "").lower().strip(), life or ""),
            "is_creator_led": bool(presence) and presence != ["no person"],
            "spend": m["total_spend"], "revenue": m["purchase_value"], "roas": m["roas"],
            "ads_count": creative_counts[c.get("creative_id") or a["ad_id"]],
            "frequency": m["frequency"], "lpv_pct": m["lpv_percentage"], "atc_pct": m["atc_percentage"], "conv_pct": m["conversion_percentage"],
            "stages": stages,
        })
    n_single = sum(1 for x in out_ads if len(x["skus"]) == 1 and not x["is_multi_sku"])
    n_multi = sum(1 for x in out_ads if x["is_multi_sku"])
    n_camp = sum(1 for x in out_ads if x["campaign"])
    return {
        "meta": {"source": "Meta Marketing API", "total_ads": len(out_ads),
                 "creative_ready": not any(a["media_type"] == "PENDING" for a in out_ads),
                 "sku_coverage_note": f"{n_single} of {len(out_ads)} ads mapped to a single clean SKU; {n_multi} flagged multi-SKU/bundle; {len(out_ads) - n_single - n_multi} unclassified.",
                 "campaign_coverage_note": f"{n_camp} of {len(out_ads)} ads carry a campaign.",
                 "partnership_proxy_note": 'No Partnership Ad field is pulled. "Partnership / Non-Partnership" is approximated from creator_presence (a person on camera vs none).',
                 "prev": prev},
        "stage_defs": STAGE_DEFS,
        "skus": [{"id": k, "name": v} for k, v in sku_names.items()],
        "ads": out_ads,
    }

# ---------- Story Matrix aggregates ----------
def build_cmt_dims(ads, classified):
    dims = OrderedDict()
    for dim, field in DIMENSIONS.items():
        buckets = {}
        for a in ads:
            ext = (classified.get(a["ad_id"]) or {}).get("extraction") or {}
            for label in {str(v).strip() for v in _as_list(ext.get(field)) if v and str(v).strip()}:
                b = buckets.setdefault(label, {"ads_count": 0, "spend": 0.0, "purchase_value": 0.0, "purchase_count": 0.0,
                                               "impressions": 0.0, "clicks": 0.0, "link_clicks": 0.0, "atc": 0.0, "lpv": 0.0, "freq_w": 0.0})
                m = a["metrics"]
                b["ads_count"] += 1; b["spend"] += m["total_spend"]; b["purchase_value"] += m["purchase_value"]
                b["purchase_count"] += m["purchase_count"]; b["impressions"] += m["impressions"]; b["clicks"] += m["clicks"]
                b["link_clicks"] += m["link_clicks"]; b["atc"] += m["atc_count"]; b["lpv"] += m["lpv_count"]
        rows = []
        for label, b in buckets.items():
            sp, lc = b["spend"], b["link_clicks"]
            pct = lambda n: round(100.0 * n / lc, 2) if lc > 0 else 0.0
            rows.append({"label": label, "ads_count": b["ads_count"], "spend": round(sp, 2),
                         "cpr": round(sp / b["purchase_count"], 2) if b["purchase_count"] > 0 else 0.0,
                         "roas": round(b["purchase_value"] / sp, 2) if sp > 0 else 0.0,
                         "purchase_value": round(b["purchase_value"], 2), "purchase_count": int(b["purchase_count"]),
                         "conversion_percentage": pct(b["purchase_count"]), "atc_percentage": pct(b["atc"]), "lpv_percentage": pct(b["lpv"]),
                         "impressions": int(b["impressions"]), "clicks": int(b["clicks"]),
                         "ctr": round(100.0 * b["clicks"] / b["impressions"], 2) if b["impressions"] > 0 else 0.0,
                         "cpc": round(sp / b["clicks"], 2) if b["clicks"] > 0 else 0.0,
                         "cpm": round(1000.0 * sp / b["impressions"], 2) if b["impressions"] > 0 else 0.0})
        rows.sort(key=lambda r: -r["roas"])
        if rows: dims[dim] = rows
    return dims
