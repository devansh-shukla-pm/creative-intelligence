"""ONE-TIME refactor: split the monolithic prototype into a template plus dataset files.

app/creative-intelligence.html  ->  app/src/app.template.html  (placeholders where the data was)
                                    app/demo/*.json            (the demo account's datasets)
After this, scripts/build_app.py produces both app builds from the template. Run once; kept for history.
"""
import json, pathlib, re, subprocess
root = pathlib.Path(__file__).resolve().parent.parent
src = (root / "app" / "creative-intelligence.html").read_text(encoding="utf8")
L = src.split("\n")

def idx(prefix):
    return next(i for i, l in enumerate(L) if l.startswith(prefix))

def block_end(i, closer):
    j = i + 1
    while not L[j].startswith(closer): j += 1
    return j

def js_to_json(js):
    """Evaluate a JS literal with node and return JSON text (the arrays use unquoted keys)."""
    r = subprocess.run(["node", "-e", f"process.stdout.write(JSON.stringify({js}))"], capture_output=True, text=True, check=True)
    return r.stdout

demo = root / "app" / "demo"
spans = {}   # name -> (start, end, json_text)

i = idx("const DATA = ");                          spans["DATA"] = (i, i, L[i][len("const DATA = "):].rstrip().rstrip(";"))
i = idx("const CMT_ADS = [");  j = block_end(i, "];"); spans["CMT_ADS"] = (i, j, js_to_json("\n".join(L[i:j + 1]).replace("const CMT_ADS = ", "").rstrip().rstrip(";")))
i = idx("const CMT_DIMENSIONS = {"); j = block_end(i, "};"); spans["CMT_DIMENSIONS"] = (i, j, js_to_json("\n".join(L[i:j + 1]).replace("const CMT_DIMENSIONS = ", "").rstrip().rstrip(";")))
i = idx("const CREATIVE_AUDIT_DATA = ["); j = block_end(i, "];"); spans["CREATIVE_AUDIT_DATA"] = (i, j, js_to_json("\n".join(L[i:j + 1]).replace("const CREATIVE_AUDIT_DATA = ", "").rstrip().rstrip(";")))
i = idx("const IA_GENERATED_INSIGHTS = ");     spans["IA_GENERATED_INSIGHTS"] = (i, i, L[i][len("const IA_GENERATED_INSIGHTS = "):].rstrip().rstrip(";"))
i = idx("const CRE_SPRITE = ");                spans["CRE_SPRITE"] = (i, i, L[i][len("const CRE_SPRITE = "):].rstrip().rstrip(";"))
i = next(k for k, l in enumerate(L) if l.startswith("const STEPS = ")); j = block_end(i, "};")
spans["STEPS"] = (i, j, "\n".join(L[i:j + 1])[len("const STEPS = "):].rstrip().rstrip(";"))
i = idx("const CMT_TOTAL_ADS"); spans["CMT_TOTAL_ADS"] = (i, i, L[i].split("=")[1].strip().rstrip(";"))

for name, (a, b, text) in spans.items():
    json.loads(text)                                  # must be valid JSON
    (demo / f"{name}.json").write_text(text, encoding="utf8")

out = []
skip_until = -1
by_start = {a: (name, b) for name, (a, b, _) in spans.items()}
for k, line in enumerate(L):
    if k <= skip_until: continue
    if k in by_start:
        name, b = by_start[k]
        out.append(f"/*@@DATASET:{name}@@*/")
        skip_until = b
    else:
        out.append(line)
(root / "app" / "src" / "app.template.html").write_text("\n".join(out), encoding="utf8")
print({n: (a + 1, b + 1, len(t)) for n, (a, b, t) in spans.items()})
