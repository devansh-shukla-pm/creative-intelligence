# Ad Free-Text Clustering Prompt

This is the finalized prompt for grouping free-text values (extracted via `extraction_prompt.md`) into semantic clusters, so downstream code can aggregate ROAS/CPA/spend per theme rather than per raw string.

## Design decisions
- One combined call clusters all free-text fields together (not one call per field).
- The LLM returns groupings only (cluster label + ad_ids). All metric aggregation (ROAS, CPA, spend, n) happens downstream in code — never computed by the LLM — to keep the numbers exact and auditable.
- **Persistent cluster memory**: existing cluster labels are passed into every call. The LLM reuses existing labels where possible, only creates new ones if a value genuinely doesn't fit. Output always includes `updated_cluster_memory` — the full updated label list — which is saved to localStorage and passed to future calls.
- **Per-ad assignment cache**: once an ad is clustered, its assignments are saved to localStorage. Future clustering calls skip already-clustered ads entirely — only new ads are sent to the API.
- Cluster count cap: 15 per field (raised from 10 to allow memory growth over time). Merge clusters with fewer than 3 ad_ids into the nearest larger cluster where reasonable; don't force bad merges.
- Input excludes performance metrics entirely — clustering is purely semantic.
- `proof_points` (an array field per ad) should be flattened into individual tagged strings before being sent in.
- Open item: whether `credibility_signal` should cluster by role/title (e.g. "Dermatologist-led credibility") vs. by literal name similarity — not yet resolved.
- Batching: fine as a single call at ~100 ads. If ad volume scales into the thousands, chunk by field into batches (~200 ads per batch) and add a second-pass "merge cluster labels across batches" call.

## Prompt

The prompt is built dynamically in code (`buildClusteringPrompt(existingMemory)`). When existing cluster memory is available, it is injected at the top under "EXISTING CLUSTER LABELS". The static core of the prompt is:

```
You are a semantic clustering engine for e-commerce ad creative analysis. You will receive a JSON array of ads, each with an ad_id and several free-text fields extracted from that ad's creative.

[EXISTING CLUSTER LABELS section injected here when memory exists]

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
8. EXISTING CLUSTERS: You have been provided a set of existing cluster labels per field (above). For each new ad value, FIRST check if it fits semantically into one of the existing labels. If yes, assign it to that existing cluster. Only create a NEW cluster label if the value genuinely does not fit any existing one.
9. UPDATED CLUSTER LIST: In your output, the "clusters" array for each field must include ALL clusters — both existing ones (with their ad_ids from this run, which may be empty if no current ad fits them) AND any new clusters created. Existing clusters with zero ads in this batch should still appear with "ad_ids": []. This keeps the cluster vocabulary stable across runs.

Output format — include ALL fields that had at least one non-null value in the input, plus any field that had existing clusters passed in:

{
  "fields": {
    "problem_statement_text": {
      "clusters": [
        { "cluster_label": "Hair frizz in humidity", "ad_ids": ["12345", "12388"] },
        { "cluster_label": "Hairfall and thinning", "ad_ids": [] }
      ]
    },
    "hook_line_text": { "clusters": [...] },
    "primary_usp_claim": { "clusters": [...] },
    "offer_details": { "clusters": [...] },
    "testimonial_claim": { "clusters": [...] },
    "proof_points": { "clusters": [...] },
    "comparison_axis": { "clusters": [...] },
    "use_case_scenario": { "clusters": [...] },
    "credibility_signal": { "clusters": [...] },
    "cta_text": { "clusters": [...] }
  },
  "updated_cluster_memory": {
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
  }
}

The "updated_cluster_memory" object must contain the COMPLETE list of all cluster labels for each field — both existing ones and any new ones created in this run. This will be saved and passed to future clustering calls.

Here is the ad data to cluster:
{{ads_json}}
```

## Input structure (per ad)

```json
{
  "ads": [
    {
      "ad_id": "12345",
      "problem_statement_text": "hair frizz in humid weather",
      "hook_line_text": "Tired of frizzy hair every monsoon?",
      "primary_usp_claim": "keratin-infused formula seals moisture",
      "offer_details": "Flat 20% off, valid till Sunday",
      "testimonial_claim": "smoother hair in one wash",
      "comparison_axis": null,
      "use_case_scenario": "monsoon",
      "credibility_signal": null,
      "cta_text": "Shop Now"
    }
  ]
}
```

## Caching architecture

Three layers of localStorage cache reduce API calls on repeated runs:

1. **Extraction cache** (`gemini_extraction_cache_v1`): per-ad extraction results, keyed by `ad_id`. Skips re-extraction for already-processed ads.
2. **Cluster memory** (`gemini_cluster_memory_v1`): growing vocabulary of cluster labels per field. Passed into every clustering call so labels stay consistent across runs.
3. **Cluster assignment cache** (`gemini_cluster_assignments_v1`): per-ad cluster assignments, keyed by `ad_id`. Already-clustered ads are skipped entirely — only new ads are sent to the API.
