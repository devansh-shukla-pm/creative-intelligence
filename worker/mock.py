"""Offline stand-ins for Meta and the LLMs (MOCK_META=1, MOCK_LLM=1).

They replay the demo account (479 ads, 288 with known classification) through the REAL pipeline code,
so the database, caching, assembly, insight pack builder and Lab model all run for real.
"""
from __future__ import annotations
import hashlib, json, re
from pathlib import Path
from . import config
from .llm import LLMError

FIX = Path(__file__).resolve().parent / "fixtures"
_rows = _truth = None

def _load():
    global _rows, _truth
    if _rows is None:
        _rows = json.loads((FIX / "audit_rows.json").read_text())
        _truth = json.loads((FIX / "truth.json").read_text())
    return _rows, _truth

class MockSource:
    def fetch_ads(self, rep, on_progress=None):
        rows, truth = _load()
        ads = []
        for r in rows:
            spend = r["total_spend"]
            impressions = spend / 150 * 1000
            clicks = impressions * 0.012
            link_clicks = (r["lpv_count"] / (r["lpv_percentage"] / 100)) if r["lpv_percentage"] else clicks * 0.7
            m = {"total_spend": spend, "purchase_count": r["purchase_count"], "purchase_value": r["purchase_value"], "roas": r["roas"],
                 "cpr": r["cpr"] or None, "frequency": r["frequency"], "impressions": impressions, "clicks": clicks,
                 "link_clicks": link_clicks, "ctr": 1.2, "cpc": spend / clicks if clicks else 0, "cpm": 150.0,
                 "atc_count": r["atc_count"], "atc_percentage": r["atc_percentage"], "lpv_count": r["lpv_count"],
                 "lpv_percentage": r["lpv_percentage"], "conversion_percentage": r["conversion_percentage"]}
            video = r["media_type"] == "VIDEO"
            t = truth.get(r["ad_id"], {})
            ads.append({"ad_id": r["ad_id"], "ad_name": r["ad_name"], "campaign_id": t.get("campaign"), "campaign_name": t.get("campaign"),
                        "metrics": m,
                        "creative": {"creative_id": r["ad_id"], "media_type": r["media_type"], "video_id": f"v{r['ad_id']}" if video else None,
                                     "image_url": None if video else r["creative_url"], "thumbnail_url": r["thumbnail_url"], "carousel_urls": [],
                                     "preview_link": r["creative_url"], "status": r["status"]}})
        if on_progress: on_progress(f"Pulled {len(ads)} ads from Meta (mock)")
        return ads

    def period_totals(self, rep, since, until):
        return None

    def video_urls(self, ads):
        return {a["ad_id"]: a["creative"]["preview_link"] for a in ads if a["creative"].get("video_id")}

    def thumbnail(self, ad):
        base = Path(__file__).resolve().parent.parent / "app"
        i = ad["ad_id"]
        for rel in (f"thumbs/{i}.jpg", f"shesha-thumbs/{i}_thumb.jpg", f"cre-thumbs/{i}_thumb.jpg", f"cmt-thumbs/{i}_thumb.jpg"):
            p = base / rel
            if p.exists(): return p.read_bytes()
        return None

def _pick(seed, options, k=1):
    h = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    return [options[(h >> (8 * j)) % len(options)] for j in range(k)]

class MockLLM:
    def chat_json(self, model, content, max_tokens=4096, label="", timeout_s=None, system=None):
        return getattr(self, "_" + label)(content)

    # ---- extraction: answers from the known truth, in the real output template
    def _extraction(self, content):
        _, truth = _load()
        url = next((p["video_url"]["url"] if p["type"] == "video_url" else p["image_url"]["url"]
                    for p in content if p["type"] in ("video_url", "image_url")), "")
        m = re.search(r"creatives/(\d+)_creative", url)
        t = truth.get(m.group(1)) if m else None
        if not t: raise LLMError("No creative image or video available")
        ad = m.group(1)
        st = t["stages"]; names = t["products"]
        def mention(n): return n.replace(" / ", " | ")           # "Hair Colour | Hair Dye" style, like the real model
        return {
            "Product": [mention(n) for n in names] or [], "Category": [t["category"].replace("-", " ").title()] if t["category"] else [],
            "Customer life cycle": t["approach"], "creator_presence": ["upper body"] if t["is_creator_led"] else ["no person"],
            "storytelling_style": _pick(ad + "s", ["Problem-solution", "Product demo", "Testimonial or social proof", "Offer-driven", "Feature showcase"], 1),
            "hook_type": _pick(ad + "h", ["Question hook", "Creator talking to camera", "Problem statement hook", "Offer-first hook"], 1),
            "visual_style": _pick(ad + "v", ["Lifestyle cinematic", "Raw UGC hand-held", "Minimalistic", "Bold or high contrast"], 1),
            "Product Interaction Type": _pick(ad + "p", ["shown being applied or used", "product in hand", "packaging-only shots"], 1),
            "Product_Placement_Timing": _pick(ad + "t", ["appears in first 3 seconds", "appears throughout", "end-only placement"], 1),
            "target_demographic.age": _pick(ad + "a", ["adults", "youth"], 1), "target_demographic.gender": ["female"],
            "audio_type": _pick(ad + "u", ["voiceover narration", "trending music", "conversational dialogue"], 1),
            "Product Position on Frame": _pick(ad + "f", ["center dominant", "side-by-side with person"], 1),
            "problem_statement_text": st.get("problem-statement") or None, "hook_line_text": st.get("hook-line") or None,
            "primary_usp_claim": st.get("primary-usp-claim") or None, "offer_details": st.get("offer-details") or None,
            "testimonial_claim": st.get("testimonial-claim") or None, "proof_points": [st["proof-points"]] if st.get("proof-points") else [],
            "comparison_axis": st.get("comparison-axis") or None, "use_case_scenario": st.get("use-case-scenario") or None,
            "credibility_signal": st.get("credibility-signal") or None, "cta_text": st.get("cta-text") or None,
        }

    # ---- clustering: groups identical wording (the real model groups similar wording)
    def _clustering(self, content):
        text = content if isinstance(content, str) else content[0]["text"]
        ads = json.loads(text.split("Here is the ad data to cluster:", 1)[1])
        mem = {}
        m = re.search(r"EXISTING CLUSTER LABELS[^\n]*\n(\{.*?\n\})\n", text, re.S)
        if m: mem = json.loads(m.group(1))
        fields, memory = {}, {k: list(v) for k, v in mem.items()}
        for f in ["problem_statement_text", "hook_line_text", "primary_usp_claim", "offer_details", "testimonial_claim", "proof_points",
                  "comparison_axis", "use_case_scenario", "credibility_signal", "cta_text"]:
            groups = {}
            for a in ads:
                v = a.get(f)
                if not v: continue
                label = v.split("::", 1)[1].split(" | ")[0] if f == "proof_points" and "::" in v else v
                groups.setdefault(label, []).append(a["ad_id"])
            if groups or f in memory:
                for l in groups: memory.setdefault(f, [])
                for l in groups:
                    if l not in memory[f]: memory[f].append(l)
                fields[f] = {"clusters": [{"cluster_label": l, "ad_ids": ids} for l, ids in groups.items()]}
        return {"fields": fields, "updated_cluster_memory": memory}

    # ---- product naming
    def _naming(self, content):
        mentions = json.loads(content.split("Mentions to map:", 1)[1])
        out = {}
        for mt in mentions:
            first = mt.split("|")[0].strip()
            low = mt.lower()
            if any(w in low for w in ("combo", "duo", "kit", "collection", "all products", "bundle")):
                name, bundle = re.sub(r"\s+", " ", first).title(), True
            else:
                name, bundle = ("Hair Colour" if "hair colo" in low or "hair dye" in low else re.sub(r"\s+", " ", first).title()), False
            cat = "hair-care" if "hair" in low else "lip-care" if "lip" in low else "skin-care"
            out[mt] = {"product": name, "category": cat, "is_bundle": bundle}
        return {"mappings": out}

    def _insights(self, content):
        return json.loads((config.INSIGHT_ENGINE_DIR / "generated_insights.json").read_text())
