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


def test_fresh_creatives_and_batch_writes(conn):
    from worker import cache
    cache.save_creatives_batch(conn, "acct-x", [("a1", {"media_type": "VIDEO", "ad_name": "one"}), ("a2", {"media_type": "IMAGE"})])
    cache.save_creatives_batch(conn, "acct-x", [("a3", {"ad_name": "no media type yet"})])
    fresh = cache.fresh_creatives(conn, "acct-x", ["a1", "a2", "a3", "a4"])
    assert set(fresh) == {"a1", "a2"} and fresh["a1"]["ad_name"] == "one"
    conn.execute("UPDATE ad_cache SET updated_at = now() - interval '2 days' WHERE account_id='acct-x' AND ad_id='a1'")
    assert set(cache.fresh_creatives(conn, "acct-x", ["a1", "a2"])) == {"a2"}
    cache.save_thumbs_batch(conn, "acct-x", [("a1", b"x"), ("a2", b"y")])
    assert cache.has_thumb(conn, "acct-x", ["a1", "a2", "a9"]) == {"a1", "a2"}


def test_video_access_probe_stops_after_three_refusals(monkeypatch):
    from worker import meta_client as mc
    calls = []
    def fake_get(url, params=None, token=None, tries=5):
        calls.append(url)
        raise mc.MetaError("(#10) Application does not have permission", 10, 400)
    monkeypatch.setattr(mc, "_get", fake_get)
    monkeypatch.setitem(mc._video_blocked, "code", None)
    assert mc.pull_video_sources("t", [str(i) for i in range(500)]) == {}
    assert len(calls) == 4                      # one batch call + three single probes, not 500+ calls
    assert mc.pull_video_frames("t", ["1", "2"]) == {} and len(calls) == 4      # and nothing more once blocked
    monkeypatch.setitem(mc._video_blocked, "code", None)


def test_insights_cache_roundtrip(conn):
    from worker import cache
    assert cache.get_insights(conn, "acct-i", "2026-01-01", "2026-01-31") is None
    cache.put_insights(conn, "acct-i", "2026-01-01", "2026-01-31", [{"ad_id": "1", "spend": "5"}])
    assert cache.get_insights(conn, "acct-i", "2026-01-01", "2026-01-31") == [{"ad_id": "1", "spend": "5"}]
    conn.execute("UPDATE insights_cache SET fetched_at = now() - interval '7 hours' WHERE account_id='acct-i'")
    assert cache.get_insights(conn, "acct-i", "2026-01-01", "2026-01-31") is None


def test_usage_header_throttle(monkeypatch):
    from worker import meta_client as mc
    slept = []
    monkeypatch.setattr(mc.time, "sleep", lambda s: slept.append(s))
    mc._watch_usage({"x-app-usage": '{"call_count": 40}'}); assert slept == []
    mc._watch_usage({"x-app-usage": '{"call_count": 80}'}); assert slept == [5]
    mc._watch_usage({"x-business-use-case-usage": '{"1":[{"call_count": 50, "estimated_time_to_regain_access": 2}]}'}); assert slept[-1] == 120


def test_meta_gate_lets_one_report_through(conn, env):
    from worker import db
    class Rep:
        def __init__(self): self.msgs = []
        def progress(self, stage, message, *a, **k): self.msgs.append(message)
    first = db.MetaGate(Rep()); first.__enter__()
    second_rep = Rep(); second = db.MetaGate(second_rep, poll_s=0.05)
    import threading
    got = []
    t = threading.Thread(target=lambda: (second.__enter__(), got.append(1), second.__exit__()))
    t.start(); import time; time.sleep(0.4)
    assert got == [] and any("Waiting for another report" in m for m in second_rep.msgs)     # waits, and says so
    first.__exit__()
    t.join(timeout=5); assert got == [1]


def test_cancelled_report_stops_at_next_progress(conn):
    import pytest
    from worker.tests.conftest import make_report
    from worker.report import Report, ReportCancelled
    rid = make_report(conn)
    rep = Report.load(conn, rid); rep.start(); rep.progress("pulling", "x")
    conn.execute("UPDATE reports SET status='cancelled' WHERE id=%s", (rid,))
    with pytest.raises(ReportCancelled): rep.progress("pulling", "y")
    rep.finish(); rep.fail("boom")                                  # neither may overwrite 'cancelled'
    assert conn.execute("SELECT status FROM reports WHERE id=%s", (rid,)).fetchone()["status"] == "cancelled"


def test_empty_meta_answer_is_explained(conn, env, monkeypatch):
    import pytest
    from worker import meta_client as mc
    from worker.sources import MetaSource
    from worker.report import Report, ReportError
    from worker.tests.conftest import make_report
    monkeypatch.setattr(mc, "pull_insights", lambda *a, **k: [])
    monkeypatch.setattr(mc, "account_spend", lambda *a, **k: 0.0)
    monkeypatch.setattr(mc, "diagnose_empty", lambda *a, **k: {"account_status": 1, "range_spend": 0.0, "lifetime_spent": 5000.0, "has_ads": True})
    rid = make_report(conn, account="1000000000009", dates=("2026-01-01", "2026-01-10"))
    rep = Report.load(conn, rid)
    with pytest.raises(ReportError) as e:
        MetaSource("tok", rep.account_id, rep).fetch_ads(rep)
    assert "no spend" in str(e.value) and "earlier range" in str(e.value)


def test_explain_empty_cases():
    from worker.meta_client import explain_empty
    f, t = "2026-01-01", "2026-01-31"
    assert "read this ad account" in explain_empty({"account_error": "x"}, f, t)
    assert "not active" in explain_empty({"account_status": 2}, f, t)
    assert "account level" in explain_empty({"account_status": 1, "range_spend": 120.0}, f, t)
    assert "no ads yet" in explain_empty({"account_status": 1, "range_spend": 0, "has_ads": False}, f, t)
    assert "never spent" in explain_empty({"account_status": 1, "range_spend": 0, "lifetime_spent": 0.0, "has_ads": True}, f, t)
    assert "temporary" not in explain_empty({"account_status": 1, "range_spend": 0, "has_ads": True}, f, t)


def test_connection_survives_the_database_hanging_up(conn, env):
    """Neon closes idle connections on long runs; the worker must reconnect and carry on instead of crashing."""
    import psycopg
    from worker import db
    pid = conn.execute("SELECT pg_backend_pid() AS p").fetchone()["p"]
    killer = psycopg.connect(env["DATABASE_URL"] if isinstance(env, dict) and "DATABASE_URL" in env else __import__("worker.config", fromlist=["x"]).DATABASE_URL, autocommit=True)
    killer.execute("SELECT pg_terminate_backend(%s)", (pid,)); killer.close()
    assert conn.execute("SELECT 1 AS ok").fetchone()["ok"] == 1                 # reconnected transparently
    assert conn.execute("SELECT pg_backend_pid() AS p").fetchone()["p"] != pid
    with conn.cursor() as cur:                                                   # batch writes work after reconnect too
        cur.execute("SELECT 2 AS two"); assert cur.fetchone()["two"] == 2


def test_ads_with_the_same_creative_share_results(conn):
    from worker import cache
    acct = "acct-share"
    cache.save_creatives_batch(conn, acct, [("a1", {"creative_id": "C1", "media_type": "VIDEO"}), ("a2", {"creative_id": "C1", "media_type": "VIDEO"}),
                                            ("a3", {"creative_id": "C2", "media_type": "IMAGE"}), ("a4", {"media_type": "IMAGE"})])
    cache.save_extraction(conn, acct, "a1", {"hook_line_text": "Grey hair gone"}, "ok", 1)
    cache.save_cluster_labels(conn, acct, "a1", {"hook_line_text": "Hair problem hook"})
    cache.save_product(conn, acct, "a1", {"products": ["Root Touch Up"], "category": "Hair", "is_multi": False})
    cache.share_results(conn, acct, ["a1", "a2", "a3", "a4"])
    rows = cache.load_cache(conn, acct, ["a1", "a2", "a3", "a4"])
    assert rows["a2"]["extraction"] == {"hook_line_text": "Grey hair gone"} and rows["a2"]["extraction_status"] == "ok"
    assert rows["a2"]["cluster_labels"] == {"hook_line_text": "Hair problem hook"} and rows["a2"]["product"]["products"] == ["Root Touch Up"]
    assert rows["a3"]["extraction"] is None and rows["a4"]["extraction"] is None          # other creatives are untouched
    uniq = cache.unique_by_creative([{"ad_id": i, "creative": {"creative_id": c}} for i, c in [("a1", "C1"), ("a2", "C1"), ("a3", "C2"), ("a4", None)]])
    assert [a["ad_id"] for a in uniq] == ["a1", "a3", "a4"]                                # one per creative; no id means its own


def test_nothing_already_done_is_sent_to_the_models_again():
    from worker.extract import needs_extraction
    from worker.cluster import run_clustering
    for st in ("ok", "fallback", "skipped", "failed"):
        assert needs_extraction({"extraction_status": st, "extraction_attempts": 1}) is False      # a thumbnail-only read is final too
    assert needs_extraction(None) is True and needs_extraction({"extraction_status": None, "extraction_attempts": 1}) is True
    ad = {"ad_id": "x", "extraction": {"hook_line_text": "h", "cta_text": "Buy now"}}
    cached = {"x": {"cluster_labels": {"hook_line_text": "H"}, "cluster_attempts": 2}}              # model skipped cta_text twice already
    msgs = []
    assert run_clustering(None, type("R", (), {"account_id": "a"})(), None, [ad], cached, lambda *a, **k: msgs.append(a))["new"] == 0
