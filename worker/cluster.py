"""Step: clustering prompt. Groups the free-text values of new ads into stable labels (angles).

Ported from the creative extraction dashboard: batches of 40 processed one after another, with the cluster
memory carried from batch to batch. Ads that already have labels are never sent again.
"""
from __future__ import annotations
import json
from . import cache, config
from .llm import LLMError

FREE_TEXT_FIELDS = ["problem_statement_text", "hook_line_text", "primary_usp_claim", "offer_details", "testimonial_claim",
                    "proof_points", "comparison_axis", "use_case_scenario", "credibility_signal", "cta_text"]

def memory_size(mem):
    return sum(len(v) for v in (mem or {}).values() if isinstance(v, list))

def build_clustering_prompt(existing_memory):
    has = memory_size(existing_memory) > 0
    existing_section = ("\nEXISTING CLUSTER LABELS (from previous runs — reuse these where possible):\n"
                        + json.dumps(existing_memory, indent=2) + "\n\n") if has else ""
    reuse_rule = (
        "8. EXISTING CLUSTERS: You have been provided a set of existing cluster labels per field (above). For each new ad value, "
        "FIRST check if it fits semantically into one of the existing labels. If yes, assign it to that existing cluster. "
        "Only create a NEW cluster label if the value genuinely does not fit any existing one.\n"
        "9. UPDATED CLUSTER LIST: In your output, the \"clusters\" array for each field must include ALL clusters — both existing ones "
        "(with their ad_ids from this run, which may be empty if no current ad fits them) AND any new clusters created. "
        "Existing clusters with zero ads in this batch should still appear with \"ad_ids\": []. "
        "This keeps the cluster vocabulary stable across runs."
    ) if has else "8. Since no existing clusters exist yet, define them freely following rules 1–7."

    return f"""You are a semantic clustering engine for e-commerce ad creative analysis. You will receive a JSON array of ads, each with an ad_id and several free-text fields extracted from that ad's creative.
{existing_section}
Your task: for EACH free-text field independently, group semantically similar values into clusters — even if the wording differs — so that ads saying essentially the same thing are grouped together.

Rules:
1. Cluster ONLY within the same field. Never merge values across different fields.
2. Null or empty values must be excluded from clustering entirely — do not create a "null" or "not applicable" cluster.
3. Start with as many clusters as needed to represent genuinely distinct meanings, then merge:
   - Merge any cluster with fewer than 3 ad_ids into the closest semantically related larger cluster, if one exists with reasonable similarity.
   - If a small cluster has no reasonably similar larger cluster to merge into, keep it standalone.
   - Cap the final cluster count per field at 15 (to allow memory growth over time).
4. Give each cluster a short, human-readable label (3-6 words) that a marketer would immediately understand — not a generic name like "Cluster 1".
5. Do not alter, invent, or paraphrase the original ad_id list — every ad_id present in the input for a given field must appear in exactly one cluster for that field.
6. Do not fabricate ad_ids or values that were not present in the input.
7. Return only valid JSON. No explanations, no markdown formatting.
{reuse_rule}

Output format — include ALL fields that had at least one non-null value in the input, plus any field that had existing clusters passed in:

{{
  "fields": {{
    "problem_statement_text": {{
      "clusters": [
        {{ "cluster_label": "Hair frizz in humidity", "ad_ids": ["12345", "12388"] }},
        {{ "cluster_label": "Hairfall and thinning", "ad_ids": [] }}
      ]
    }},
    "hook_line_text": {{ "clusters": [...] }},
    "primary_usp_claim": {{ "clusters": [...] }},
    "offer_details": {{ "clusters": [...] }},
    "testimonial_claim": {{ "clusters": [...] }},
    "proof_points": {{ "clusters": [...] }},
    "comparison_axis": {{ "clusters": [...] }},
    "use_case_scenario": {{ "clusters": [...] }},
    "credibility_signal": {{ "clusters": [...] }},
    "cta_text": {{ "clusters": [...] }}
  }},
  "updated_cluster_memory": {{
    "problem_statement_text": ["Hair frizz in humidity", "Hairfall and thinning", "Skin dryness in winter"],
    "hook_line_text": ["Direct question about problem", "Shocking statistic opener"],
    "primary_usp_claim": ["Dermatologist tested formula", "24-hour long lasting claim"],
    "offer_details": ["Flat % discount", "Limited time bundle offer"],
    "testimonial_claim": ["Visible results in days", "Dermatologist recommended"],
    "proof_points": ["Sales count milestone", "Rating and review count"],
    "comparison_axis": ["Price vs competitor", "Ingredient quality comparison"],
    "use_case_scenario": ["Monsoon hair care", "Daily office commute"],
    "credibility_signal": ["Dermatologist endorsement", "Founder story credibility"],
    "cta_text": ["Shop now urgency", "DM or link in bio"]
  }}
}}

The "updated_cluster_memory" object must contain the COMPLETE list of all cluster labels for each field — both existing ones and any new ones created in this run. This will be saved and passed to future clustering calls.

Here is the ad data to cluster:"""

def ad_free_text(ad_id, extraction, only=None):
    obj = {"ad_id": ad_id}
    for f in FREE_TEXT_FIELDS:
        if only is not None and f not in only:
            obj[f] = None; continue
        v = extraction.get(f)
        if f == "proof_points":
            arr = v if isinstance(v, list) else ([v] if v else [])
            obj[f] = " | ".join(f"{ad_id}::{pt}" for pt in arr if pt) or None
        else:
            obj[f] = v if (isinstance(v, str) and v.strip()) else None
    return obj

def _validate(batch, result):
    """Every input ad_id with a value for a field must come back exactly once in that field. Returns problems."""
    problems = []
    fields = result.get("fields")
    if not isinstance(fields, dict): return ["no 'fields' object"]
    for f in FREE_TEXT_FIELDS:
        want = {a["ad_id"] for a in batch if a.get(f)}
        if not want: continue
        got = []
        for c in (fields.get(f) or {}).get("clusters", []):
            got.extend(str(i) for i in c.get("ad_ids", []))
        missing = want - set(got)
        dup = len(got) - len(set(got))
        if missing: problems.append(f"{f}: {len(missing)} ad_ids missing")
        if dup: problems.append(f"{f}: {dup} duplicated ad_ids")
    return problems

def _merge_memory(old, new):
    out = {k: list(v) for k, v in (old or {}).items()}
    for k, labels in (new or {}).items():
        if not isinstance(labels, list): continue
        cur = out.setdefault(k, [])
        for l in labels:
            if isinstance(l, str) and l and l not in cur: cur.append(l)
    return out

def _collect(result, ids, assign, only=None, tag=""):
    """Copy labels from a clustering result into assign {ad_id: {field: label}}. Proof point ids look like 'ad_id::point'."""
    seen = {}
    for f, fd in (result.get("fields") or {}).items():
        if only is not None and f not in only: continue
        n_ids = n_hit = 0
        for c in (fd or {}).get("clusters", []) if isinstance(fd, dict) else []:
            label = c.get("cluster_label")
            for i in c.get("ad_ids", []) or []:
                n_ids += 1
                i = str(i).split("::")[0]
                if label and i in ids:
                    n_hit += 1
                    assign.setdefault(i, {}).setdefault(f, label)
        seen[f] = (n_ids, n_hit)
    print(f"[cluster]{tag} fields returned (ids, matched): {seen}", flush=True)

def cluster_batch(llm, batch, memory):
    """-> (assignments {ad_id: {field: label}}, updated memory). Retries when the output drops or duplicates ad_ids."""
    last_problems = []
    for _ in range(3):
        prompt = build_clustering_prompt(memory) + "\n" + json.dumps(batch, indent=2)
        result = llm.chat_json(config.CLUSTER_MODEL, prompt, max_tokens=16000, label="clustering")
        last_problems = _validate(batch, result)
        if not last_problems: break
    assign = {}
    ids = {a["ad_id"] for a in batch}
    _collect(result, ids, assign)
    mem = _merge_memory(memory, result.get("updated_cluster_memory"))
    for f, fd in (result.get("fields") or {}).items():       # labels used but missing from memory still get remembered
        mem = _merge_memory(mem, {f: [c.get("cluster_label") for c in (fd or {}).get("clusters", [])]})

    # The model sometimes skips a whole field. Ask again for just those fields, once.
    def _coverage(f):
        want = [a for a in batch if a.get(f)]
        return (sum(1 for a in want if f in assign.get(a["ad_id"], {})) / len(want)) if want else 1.0
    skipped = [f for f in FREE_TEXT_FIELDS if _coverage(f) < 0.6]     # a few dropped ids are fine; a mostly skipped field is retried
    if skipped:
        sub = [{**{k: a.get(k) if (k == "ad_id" or k in skipped) else None for k in a}} for a in batch]
        try:
            res2 = llm.chat_json(config.CLUSTER_MODEL, build_clustering_prompt(mem) + "\n" + json.dumps(sub, indent=2),
                                 max_tokens=16000, label="clustering-retry")
            _collect(res2, ids, assign, only=set(skipped), tag="[retry]")
            for f, fd in (res2.get("fields") or {}).items():
                if f in skipped and isinstance(fd, dict):
                    mem = _merge_memory(mem, {f: [c.get("cluster_label") for c in fd.get("clusters", [])]})
            mem = _merge_memory(mem, res2.get("updated_cluster_memory"))
        except LLMError as e:
            print(f"[cluster] retry failed: {e}", flush=True)
        print(f"[cluster] retried skipped fields {skipped}; still unlabeled: "
              f"{[f for f in skipped if any(a.get(f) and f not in assign.get(a['ad_id'], {}) for a in batch)]}", flush=True)
    return assign, mem, last_problems

def run_clustering(conn, rep, llm, extracted_ads, cached, progress):
    """extracted_ads: [{ad_id, extraction}] for ads that have an extraction. Only those without cached labels are sent."""
    def _missing(a):
        lab = (cached.get(a["ad_id"]) or {}).get("cluster_labels")
        if lab is None: return list(FREE_TEXT_FIELDS)
        return [f for f in FREE_TEXT_FIELDS if ad_free_text(a["ad_id"], a["extraction"]).get(f) and f not in lab]
    need = {a["ad_id"]: _missing(a) for a in extracted_ads}
    new = [a for a in extracted_ads if need[a["ad_id"]]]
    total = len(extracted_ads)
    if not new:
        progress(f"All {total} ads already grouped (cache)", total, total)
        return {"new": 0, "failed_batches": 0}
    memory, _ = cache.load_memory(conn, rep.account_id)
    objs = [ad_free_text(a["ad_id"], a["extraction"], only=need[a["ad_id"]]) for a in new]
    empty = [o["ad_id"] for o in objs if not any(o.get(f) for f in FREE_TEXT_FIELDS)]
    for ad_id in empty:                                       # nothing to group: mark as processed
        cache.save_cluster_labels(conn, rep.account_id, ad_id, {})
    objs = [o for o in objs if o["ad_id"] not in set(empty)]

    batches = [objs[i:i + config.CLUSTER_BATCH] for i in range(0, len(objs), config.CLUSTER_BATCH)]
    done = total - len(new) + len(empty); failed = 0
    for n, batch in enumerate(batches, 1):
        progress(f"Grouping similar messages: batch {n} of {len(batches)}", done, total)
        try:
            assign, memory, _problems = cluster_batch(llm, batch, memory)
        except LLMError:
            failed += 1                                       # these ads stay unlabeled and are retried on the next run
            continue
        for o in batch:
            merged = {**((cached.get(o["ad_id"]) or {}).get("cluster_labels") or {}), **assign.get(o["ad_id"], {})}
            cache.save_cluster_labels(conn, rep.account_id, o["ad_id"], merged)
        cache.save_cluster_memory(conn, rep.account_id, memory)
        done += len(batch)
    if batches and failed == len(batches):
        from .report import ReportError
        raise ReportError("Grouping the ad messages failed. Try again in a few minutes.")
    return {"new": len(new), "failed_batches": failed}
