"""Builds the two app files from app/src/app.template.html.

  app/creative-intelligence.html   DEMO build: the demo account's datasets are embedded (used by the Claude artifact, the zip, local viewing)
  app/report.html                  LIVE build: no data embedded; reads window.__BOOT (served by /api/report/boot) and polls for signals

Run: python3 scripts/build_app.py
"""
import json, pathlib, re

root = pathlib.Path(__file__).resolve().parent.parent
tpl = (root / "app" / "src" / "app.template.html").read_text(encoding="utf8")
demo = root / "app" / "demo"
D = lambda name: (demo / f"{name}.json").read_text(encoding="utf8")

stage_defs = json.loads(D("DATA"))["stage_defs"]
EMPTY_DATA = json.dumps({"meta": {"source": "Meta Marketing API", "total_ads": 0, "sku_coverage_note": "", "campaign_coverage_note": "", "partnership_proxy_note": ""},
                         "stage_defs": stage_defs, "skus": [], "ads": []})

DEMO = {
    "DATA": f"let DATA = {D('DATA')};",
    "CMT_TOTAL_ADS": f"let CMT_TOTAL_ADS = {D('CMT_TOTAL_ADS')};",
    "CMT_ADS": f"let CMT_ADS = {D('CMT_ADS')};",
    "CMT_DIMENSIONS": f"let CMT_DIMENSIONS = {D('CMT_DIMENSIONS')};",
    "CREATIVE_AUDIT_DATA": f"let CREATIVE_AUDIT_DATA = {D('CREATIVE_AUDIT_DATA')};",
    "IA_GENERATED_INSIGHTS": f"let IA_GENERATED_INSIGHTS = {D('IA_GENERATED_INSIGHTS')};",
    "CRE_SPRITE": f"let CRE_SPRITE = {D('CRE_SPRITE')};",
    "STEPS": f"window.__LAB = {D('STEPS')};",
}
LIVE = {
    "DATA": f"let DATA = (window.__BOOT && window.__BOOT.data) || {EMPTY_DATA};",
    "CMT_TOTAL_ADS": "let CMT_TOTAL_ADS = (window.__BOOT && window.__BOOT.cmtAds) ? window.__BOOT.cmtAds.length : 0;",
    "CMT_ADS": "let CMT_ADS = (window.__BOOT && window.__BOOT.cmtAds) || [];",
    "CMT_DIMENSIONS": "let CMT_DIMENSIONS = (window.__BOOT && window.__BOOT.cmtDims) || {};",
    "CREATIVE_AUDIT_DATA": "let CREATIVE_AUDIT_DATA = (window.__BOOT && window.__BOOT.audit) || [];",
    "IA_GENERATED_INSIGHTS": "let IA_GENERATED_INSIGHTS = (window.__BOOT && window.__BOOT.insights) || [];",
    "CRE_SPRITE": 'let CRE_SPRITE = {"cell":84,"sheetW":0,"sheetH":0,"file":"","map":{}};',
    "STEPS": "window.__LAB = (window.__BOOT && window.__BOOT.lab) || {\"meta\":{},\"products\":[]};",
}

# Live page: a blocking script pulls in the report data (served by the API with the user's session) before the app starts.
BOOT_LOADER = ("(function(){var id=new URLSearchParams(location.search).get('id');"
               "if(!id){location.replace('/');return;}"
               "document.write('<script src=\"/api/report/boot?id='+encodeURIComponent(id)+'\" onerror=\"location.replace(\\'/\\')\"><\\/script>');})();")

def build(table, live):
    out = tpl
    for name, text in table.items():
        marker = f"/*@@DATASET:{name}@@*/"
        assert marker in out, marker
        out = out.replace(marker, text)
    mode = "live" if live else "demo"
    out = out.replace("/*@@BOOTLOADER@@*/", BOOT_LOADER if live else "")
    out = out.replace("/*@@MODE@@*/", f"const LIVE = {'true' if live else 'false'};  // build mode: {mode}")
    return out

(root / "app" / "creative-intelligence.html").write_text(build(DEMO, False), encoding="utf8")
(root / "app" / "report.html").write_text(build(LIVE, True), encoding="utf8")
# logo for the landing page
import base64
m = re.search(r'<img class="brand-logo" src="data:image/png;base64,([^"]+)"', tpl)
(root / "app" / "assets").mkdir(exist_ok=True)
(root / "app" / "assets" / "logo.png").write_bytes(base64.b64decode(m.group(1)))
print("built demo and live")
