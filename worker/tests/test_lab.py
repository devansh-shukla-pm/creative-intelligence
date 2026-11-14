import json, pathlib
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

@pytest.fixture(scope="module")
def lab_result():
    from worker.lab.model import compute_lab
    d = json.loads((ROOT / "experimentation-lab" / "lab-data.json").read_text())
    names = {s["id"]: s["name"] for s in d["skus"]}
    return compute_lab(d["ads"], names, min_ads=15, min_spend=300000, reps=1)

def test_matches_validated_results(lab_result):
    """The refactored worker reproduces the numbers published with the research scripts (steps_data.json)."""
    ref = {p["id"]: p for p in json.loads((ROOT / "experimentation-lab" / "steps_data.json").read_text())["products"]}
    got = {p["id"]: p for p in lab_result["products"]}
    assert set(got) == set(ref)
    for pid, p in got.items():
        assert abs(p["final_pred"] - ref[pid]["final_pred"]) < 1e-6
        assert [r["angle"] for r in p["recipe_support"]] == [r["angle"] for r in ref[pid]["recipe_support"]]
        assert abs(p["baseline"] - ref[pid]["baseline"]) < 1e-9
        assert p["grid"] == ref[pid]["grid"]

def test_accuracy_beats_product_average(lab_result):
    m = lab_result["meta"]
    assert m["blend_wMAE"] < m["base_wMAE"]
    assert 0.2 < m["blend_wMAE"] < 0.5

def test_structure_has_everything_the_ui_reads(lab_result):
    p = lab_result["products"][0]
    for k in ["id", "name", "ads", "spend", "baseline", "grid", "bands", "stages", "syn_top", "syn_bot", "steps4", "solo_pred",
              "final_pred", "alts", "evidence", "tested", "full_runs", "m4", "m3", "closest", "pred_modal", "lo", "hi", "naive",
              "recipe_support", "calib"]:
        assert k in p, k
    assert len(p["stages"]) == 5 and len(p["evidence"]) == 10 and len(p["steps4"]) == 5
    assert p["lo"] < p["final_pred"] < p["hi"]

def test_ineligible_products_get_no_recipe():
    from worker.lab.model import compute_lab
    d = json.loads((ROOT / "experimentation-lab" / "lab-data.json").read_text())
    r = compute_lab(d["ads"][:12], {}, min_ads=15, min_spend=300000, reps=1)
    assert r["products"] == []
