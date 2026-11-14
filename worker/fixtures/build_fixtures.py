"""One-time: pull test fixtures out of the demo app so the whole pipeline can run offline (MOCK_META=1 MOCK_LLM=1).

audit_rows.json   479 ad rows in the old table-report API shape
truth.json        the known classification of 288 of those ads (stages, product names, category, approach, creator-led)
"""
import json, pathlib
root = pathlib.Path(__file__).resolve().parents[2]
html = (root / "app" / "creative-intelligence.html").read_text(encoding="utf8").split("\n")

i = next(k for k, l in enumerate(html) if l.startswith("const CREATIVE_AUDIT_DATA"))
rows, k = [], i + 1
while html[k].strip().startswith("{"):
    rows.append(json.loads(html[k].strip().rstrip(","))); k += 1

d = json.loads(next(l for l in html if l.startswith("const DATA = "))[len("const DATA = "):].rstrip(";"))
names = {s["id"]: s["name"] for s in d["skus"]}
truth = {}
for a in d["ads"]:
    truth[a["ad_id"]] = {
        "products": [names[s] for s in a["skus"] if s in names], "is_multi": a["is_multi_sku"], "category": a["category"],
        "campaign": a["campaign"], "approach": a["approach"], "is_creator_led": a["is_creator_led"], "stages": a["stages"],
    }
(root / "worker" / "fixtures" / "audit_rows.json").write_text(json.dumps(rows))
(root / "worker" / "fixtures" / "truth.json").write_text(json.dumps(truth))
print(len(rows), "rows;", len(truth), "classified")
