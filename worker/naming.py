"""Step: one clean name per product (PRD 2 section 6).

1. Each Product value from extraction is a "mention". Mentions already known to the account are resolved from memory.
2. Unknown mentions go to the naming prompt in one call (existing names are passed in so names stay stable).
3. Results are stored in the account's product memory, then each ad gets {products, category, is_multi}.
"""
from __future__ import annotations
import json, re
from . import cache, config
from .llm import LLMError
from .prompts import naming_prompt_template

BATCH = 150
NOT_A_PRODUCT = {"", "n a", "na", "none", "null", "unknown", "product", "products", "brand"}

def norm(s):
    s = re.sub(r"[^a-z0-9|]+", " ", str(s).lower()).strip()
    return re.sub(r"\s+", " ", s)

def slug(name):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")

def mentions_of(extraction):
    """Product may be a list or a string; each element is one product mention (synonyms inside it are separated by '|')."""
    p = extraction.get("Product")
    items = p if isinstance(p, list) else ([p] if p else [])
    return [m.strip() for m in items if isinstance(m, str) and m.strip()]

def _index(memory):
    idx = {}
    for e in memory:
        for a in e.get("aliases", []): idx[a] = e
        idx[norm(e["product"])] = e
    return idx

def _lookup(memory, mention):
    idx = _index(memory); n = norm(mention)
    if n in idx: return idx[n]
    parts = [norm(p) for p in n.split("|") if p.strip()]       # "hair color | hair dye": any synonym known is enough
    for p in parts:
        if p in idx: return idx[p]
    return None

def resolve_mentions(llm, memory, mentions):
    """Returns (updated memory, {mention: entry or None}). Unknown mentions are sent to the LLM."""
    unknown = sorted({m for m in mentions if norm(m) not in NOT_A_PRODUCT and _lookup(memory, m) is None})
    for i in range(0, len(unknown), BATCH):
        chunk = unknown[i:i + BATCH]
        prompt = (naming_prompt_template()
                  .replace("{{existing_products}}", json.dumps([{"product": e["product"], "category": e["category"]} for e in memory], indent=2))
                  .replace("{{mentions}}", json.dumps(chunk, indent=2)))
        res = llm.chat_json(config.NAMING_MODEL, prompt, max_tokens=8000, label="naming")
        for mention, m in (res.get("mappings") or {}).items():
            if mention not in chunk or not isinstance(m, dict) or not m.get("product"):
                continue
            name = str(m["product"]).strip()
            entry = next((e for e in memory if norm(e["product"]) == norm(name)), None)
            if entry is None:
                entry = {"product": name, "category": slug(str(m.get("category") or "other")), "aliases": [], "is_bundle": bool(m.get("is_bundle"))}
                memory.append(entry)
            a = norm(mention)
            if a not in entry["aliases"]: entry["aliases"].append(a)
    return memory, {m: (None if norm(m) in NOT_A_PRODUCT else _lookup(memory, m)) for m in mentions}

def run_naming(conn, rep, llm, extracted_ads, cached, progress):
    """extracted_ads: [{ad_id, extraction}]. Saves a product record for every ad that lacks one."""
    todo = [a for a in extracted_ads if (cached.get(a["ad_id"]) or {}).get("product") is None]
    if not todo:
        progress("Product names already set (cache)", len(extracted_ads), len(extracted_ads)); return
    _, memory = cache.load_memory(conn, rep.account_id)
    all_mentions = [m for a in todo for m in mentions_of(a["extraction"])]
    progress(f"Naming products ({len(set(all_mentions))} distinct values)", 0, len(todo))
    try:
        memory, resolved = resolve_mentions(llm, memory, all_mentions)
    except LLMError:
        from .report import ReportError
        raise ReportError("Naming the products failed. Try again in a few minutes.")
    cache.save_product_memory(conn, rep.account_id, memory)
    for a in todo:
        entries = [resolved.get(m) for m in mentions_of(a["extraction"])]
        entries = [e for e in entries if e]
        names = []
        for e in entries:
            if e["product"] not in names: names.append(e["product"])
        bundle = any(e.get("is_bundle") for e in entries) or len(names) >= 2
        rec = {"products": [] if (bundle and len(names) < 2) else names, "category": entries[0]["category"] if entries else None,
               "is_multi": bundle}
        cache.save_product(conn, rep.account_id, a["ad_id"], rec)
