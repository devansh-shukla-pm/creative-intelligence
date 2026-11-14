"""Step: the 4 insight cards.

1. build_insight_inputs.js (Node) does every calculation and writes the candidate pack.
2. The unified insight prompt judges the candidates and writes the cards (it does no maths).
3. verify_insights.js checks every card against the pack; failing cards are fixed by regenerating, else dropped.
"""
from __future__ import annotations
import json, re, subprocess, tempfile
from pathlib import Path
from . import config
from .llm import LLMError
from .prompts import insight_prompt

ENGINE = config.INSIGHT_ENGINE_DIR
LINE = re.compile(r"^Insight (\d+) .*: (ok|PROBLEMS: (.*))$")

def _node(*args):
    r = subprocess.run(["node", *map(str, args)], capture_output=True, text=True, cwd=str(ENGINE))
    return r

def build_pack(data, workdir: Path):
    src = workdir / "ads.json"; out = workdir / "pack.json"
    src.write_text(json.dumps({"ads": data["ads"], "stage_defs": data["stage_defs"], "skus": data["skus"]}))
    r = _node("build_insight_inputs.js", "--data", src, "--out", out)
    if r.returncode != 0:
        raise RuntimeError(f"insight pack failed: {r.stderr[-400:]}")
    return json.loads(out.read_text()), out

def verify(cards, pack_path: Path, workdir: Path):
    """-> list of (ok, problems) per card, in order."""
    gen = workdir / "gen.json"
    gen.write_text(json.dumps({"insights": cards}))
    r = _node("verify_insights.js", gen, pack_path)
    status = {}
    for line in r.stdout.splitlines():
        m = LINE.match(line.strip())
        if m: status[int(m.group(1))] = (m.group(2) == "ok", m.group(3) or "")
    return [status.get(i + 1, (False, "not checked")) for i in range(len(cards))]

def run_insights(data, llm, progress=lambda m: None):
    with tempfile.TemporaryDirectory() as td:
        wd = Path(td)
        progress("Computing insight candidates")
        pack, pack_path = build_pack(data, wd)
        if not pack.get("candidates"):
            return []
        if config.MOCK_LLM:                                      # offline run: stored cards, no verification against a different dataset
            return llm.chat_json("mock", "", label="insights")["insights"]
        system = insight_prompt()
        user = json.dumps(pack)
        feedback = ""
        best = []
        for attempt in range(3):
            progress("Writing the insight cards" if attempt == 0 else "Fixing insight cards")
            try:
                raw = llm.chat_json(config.INSIGHT_MODEL, user + feedback, max_tokens=6000, label="insights", system=system, timeout_s=240)
            except LLMError:
                continue
            cards = [c for c in (raw.get("insights") or []) if isinstance(c, dict)]
            if not cards: continue
            res = verify(cards, pack_path, wd)
            good = [c for c, (ok, _) in zip(cards, res) if ok]
            if len(good) > len(best): best = good
            if len(good) == len(cards): return good
            probs = "; ".join(f"card {i + 1}: {p}" for i, (ok, p) in enumerate(res) if not ok)
            feedback = f"\n\nYour previous answer failed these checks, fix them and return the full corrected JSON: {probs}"
        return best                                           # fewer good cards is correct; never pad
