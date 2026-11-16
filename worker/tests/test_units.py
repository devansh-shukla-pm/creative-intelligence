import json, base64, os
import pytest

def test_metrics_match_the_old_table_report_api():
    """Numbers from the sample table-report row: percentages are relative to link clicks (11)."""
    from worker.meta_client import metrics_from_insight
    row = {"spend": "190", "impressions": "2000", "clicks": "20", "inline_link_clicks": "11", "frequency": "1.063028",
           "actions": [{"action_type": "purchase", "value": "3"}, {"action_type": "add_to_cart", "value": "9"}, {"action_type": "landing_page_view", "value": "7"}],
           "action_values": [{"action_type": "purchase", "value": "3603.4"}]}
    m = metrics_from_insight(row)
    assert round(m["roas"], 3) == 18.965 and round(m["cpr"], 2) == 63.33
    assert round(m["conversion_percentage"], 2) == 27.27 and round(m["atc_percentage"], 2) == 81.82 and round(m["lpv_percentage"], 2) == 63.64

def test_purchase_event_priority_and_empty_ads():
    from worker.meta_client import metrics_from_insight
    m = metrics_from_insight({"spend": "100", "actions": [{"action_type": "purchase", "value": "2"}, {"action_type": "omni_purchase", "value": "5"}],
                              "action_values": [{"action_type": "omni_purchase", "value": "900"}], "inline_link_clicks": "0"})
    assert m["purchase_count"] == 5 and m["purchase_value"] == 900 and m["conversion_percentage"] == 0
    z = metrics_from_insight({"spend": "50"})
    assert z["roas"] == 0 and z["cpr"] is None

def test_creative_info_types():
    from worker.meta_client import creative_info
    v = creative_info({"effective_status": "ACTIVE", "preview_shareable_link": "https://fb.me/x", "creative": {"id": "1", "video_id": "9", "thumbnail_url": "t"}})
    assert v["media_type"] == "VIDEO" and v["status"] == "ACTIVE" and v["preview_link"] == "https://fb.me/x"
    c = creative_info({"effective_status": "PAUSED", "creative": {"object_story_spec": {"link_data": {"child_attachments": [{"picture": "a"}, {"picture": "b"}]}}}})
    assert c["media_type"] == "CAROUSEL" and c["carousel_urls"] == ["a", "b"] and c["status"] == "PAUSED"
    i = creative_info({"creative": {"image_url": "http://img"}})
    assert i["media_type"] == "IMAGE" and i["image_url"] == "http://img"

def test_llm_json_parsing_variants():
    from worker.llm import parse_json
    assert parse_json('{"a": 1}') == {"a": 1}
    assert parse_json('```json\n{"a": [1,2]}\n```') == {"a": [1, 2]}
    assert parse_json('Sure! Here it is: {"a": 2} hope that helps') == {"a": 2}
    with pytest.raises(json.JSONDecodeError):
        parse_json('{"a": ')

def test_llm_regenerates_on_malformed_json(monkeypatch):
    from worker import llm as L
    answers = iter(['{"broken": ', '{"ok": true}'])
    client = L.LLM(api_key="k")
    monkeypatch.setattr(client, "chat", lambda *a, **k: next(answers))
    assert client.chat_json("m", "x") == {"ok": True}

def test_llm_retries_transient_errors_but_not_auth(monkeypatch):
    from worker import llm as L
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    c = L.LLM(api_key="k"); calls = []
    def flaky(body, t):
        calls.append(1)
        if len(calls) < 3: raise L.LLMError("busy", 503)
        return {"choices": [{"message": {"content": "{}"}}]}
    monkeypatch.setattr(c, "_post", flaky)
    assert c.chat("m", "x") == "{}" and len(calls) == 3
    calls.clear()
    def auth(body, t): calls.append(1); raise L.LLMError("bad key", 401)
    monkeypatch.setattr(c, "_post", auth)
    with pytest.raises(L.LLMError): c.chat("m", "x")
    assert len(calls) == 1

def test_token_encryption_is_compatible_with_node(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
    import importlib
    from worker import config, crypto
    importlib.reload(config); importlib.reload(crypto)
    assert crypto.decrypt(crypto.encrypt("EAAB-token")) == "EAAB-token"

def test_prompts_load_verbatim():
    from worker.prompts import extraction_prompt, naming_prompt_template, insight_prompt
    assert extraction_prompt().startswith("You are an ad-classification engine.")
    assert "FINAL OUTPUT FORMAT" in extraction_prompt()
    assert "{{mentions}}" in naming_prompt_template() and "{{existing_products}}" in naming_prompt_template()
    assert insight_prompt().startswith("CREATIVE INTEL: UNIFIED INSIGHT PROMPT")

def test_clustering_prompt_has_memory_variants():
    from worker.cluster import build_clustering_prompt
    fresh = build_clustering_prompt({})
    assert "EXISTING CLUSTER LABELS" not in fresh and "8. Since no existing clusters exist yet" in fresh
    with_mem = build_clustering_prompt({"hook_line_text": ["Direct question"]})
    assert "EXISTING CLUSTER LABELS" in with_mem and "Direct question" in with_mem and "9. UPDATED CLUSTER LIST" in with_mem
    assert fresh.rstrip().endswith("Here is the ad data to cluster:")

def test_clustering_validation_catches_dropped_and_duplicated_ads():
    from worker.cluster import _validate
    batch = [{"ad_id": "1", "hook_line_text": "a"}, {"ad_id": "2", "hook_line_text": "b"}]
    ok = {"fields": {"hook_line_text": {"clusters": [{"cluster_label": "X", "ad_ids": ["1", "2"]}]}}}
    assert _validate(batch, ok) == []
    dropped = {"fields": {"hook_line_text": {"clusters": [{"cluster_label": "X", "ad_ids": ["1"]}]}}}
    assert any("missing" in p for p in _validate(batch, dropped))
    dup = {"fields": {"hook_line_text": {"clusters": [{"cluster_label": "X", "ad_ids": ["1", "2"]}, {"cluster_label": "Y", "ad_ids": ["2"]}]}}}
    assert any("duplicated" in p for p in _validate(batch, dup))

def test_proof_points_are_flattened_like_the_dashboard():
    from worker.cluster import ad_free_text
    o = ad_free_text("77", {"proof_points": ["10k sold", "4.5 rating"], "cta_text": "Shop now", "hook_line_text": "  "})
    assert o["proof_points"] == "77::10k sold | 77::4.5 rating" and o["cta_text"] == "Shop now" and o["hook_line_text"] is None

def test_product_naming_merges_spellings(monkeypatch):
    from worker import naming
    class Fake:
        def chat_json(self, model, prompt, max_tokens=0, label="", **k):
            ms = json.loads(prompt.split("Mentions to map:", 1)[1])
            return {"mappings": {m: {"product": "Hair Colour", "category": "hair-care", "is_bundle": False} for m in ms}}
    mem, res = naming.resolve_mentions(Fake(), [], ["Hair color | Hair dye", "hair colour", "Hair Colour"])
    assert len(mem) == 1 and mem[0]["product"] == "Hair Colour"
    assert all(v is mem[0] for v in res.values())
    # known aliases are resolved without another call
    class Boom:
        def chat_json(self, *a, **k): raise AssertionError("LLM must not be called")
    mem, res = naming.resolve_mentions(Boom(), mem, ["hair colour", "Hair color | Hair dye"])
    assert all(v["product"] == "Hair Colour" for v in res.values())
    assert naming.resolve_mentions(Boom(), mem, ["N/A", ""])[1] == {"N/A": None, "": None}

def test_assemble_data_shape_matches_what_the_ui_reads():
    from worker.assemble import build_data, audit_rows, cmt_ads, build_cmt_dims
    ad = {"ad_id": "1", "ad_name": "n", "campaign_id": "c1", "campaign_name": "Camp",
          "metrics": {"total_spend": 100, "purchase_value": 300, "roas": 3, "cpr": 50, "frequency": 1.2, "purchase_count": 2, "impressions": 1000, "clicks": 20,
                      "link_clicks": 10, "atc_count": 3, "lpv_count": 6, "atc_percentage": 30, "lpv_percentage": 60, "conversion_percentage": 20,
                      "ctr": 2, "cpc": 5, "cpm": 100},
          "creative": {"creative_id": "cr", "media_type": "VIDEO", "preview_link": "https://p", "status": "ACTIVE"}}
    cl = {"1": {"extraction": {"Customer life cycle": "Push Brand Push", "creator_presence": ["no person"], "storytelling_style": ["Product demo"]},
                "labels": {"hook_line_text": "Authentic hook"}, "product": {"products": ["Night Repair Cream"], "category": "skin-care", "is_multi": False}}}
    d = build_data([ad], cl)
    a = d["ads"][0]
    assert a["skus"] == ["night-repair-cream"] and a["stages"]["hook-line"] == "Authentic hook" and a["approach"] == "Push Brand"
    assert a["is_creator_led"] is False and a["campaign"] == "Camp" and a["revenue"] == 300 and a["thumb_url"] == "/api/thumb?ad=1"
    assert d["skus"] == [{"id": "night-repair-cream", "name": "Night Repair Cream"}] and len(d["stage_defs"]) == 10
    assert audit_rows([ad])[0]["total_spend"] == 100 and cmt_ads([ad])[0]["roas"] == 3
    assert build_cmt_dims([ad], cl)["STORYTELLING_STYLE"][0]["label"] == "Product demo"
    # unclassified ads stay in the data so totals never change between signals
    assert len(build_data([ad], {})["ads"]) == 1 and build_data([ad], {})["ads"][0]["skus"] == []


def test_ad_copy_from_creative():
    from worker.meta_client import ad_copy
    cr = {"call_to_action_type": "SHOP_NOW",
          "object_story_spec": {"video_data": {"message": "Grey hair gone in 5 min", "title": "Root Touch Up"}}}
    assert ad_copy(cr) == {"primary_text": "Grey hair gone in 5 min", "headline": "Root Touch Up", "cta_button": "Shop Now"}
    feed = {"asset_feed_spec": {"bodies": [{"text": "B1"}], "titles": [{"text": "T1"}], "call_to_action_types": ["LEARN_MORE"]}}
    assert ad_copy(feed) == {"primary_text": "B1", "headline": "T1", "cta_button": "Learn More"}
    assert ad_copy({}) == {}
