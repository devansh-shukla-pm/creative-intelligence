"""Experimentation Lab model: spend-weighted ridge (generalised DerSimonian-Laird shrinkage) blended with CatBoost.

compute_lab(ads) takes the report's ads in DATA shape and returns the dict the Lab tab displays
(same shape as experimentation-lab/steps_data.json): per eligible product the best recipe, the predicted ROAS and the
evidence behind every step. Method and testing notes: docs/experimentation-lab-methodology.md.
"""
from __future__ import annotations
import itertools, warnings
import numpy as np, pandas as pd
from catboost import CatBoostRegressor
from .hybrid import Hybrid, STAGES

warnings.filterwarnings("ignore")
MINN = 2            # an angle needs at least 2 ads to be considered
EVAL_MIN = 10000    # accuracy and calibration are judged on ads whose ROAS is precisely measured
F_STAGE = ["product"] + STAGES

# ---------------------------------------------------------------- data
def build_df(ads):
    rows = []
    for a in ads:
        if a["spend"] < 10: continue                       # tracking glitches
        skus = a.get("skus") or []
        product = skus[0] if (len(skus) == 1 and not a.get("is_multi_sku")) else ("combo" if (a.get("is_multi_sku") or len(skus) > 1) else "unmapped")
        d = {"ad_id": a["ad_id"], "product": product, "spend": float(a["spend"]), "revenue": float(a["revenue"]),
             "creative_url": a.get("creative_url") or ""}
        for st in STAGES: d[st] = (a.get("stages") or {}).get(st) or "MISSING"
        rows.append(d)
    df = pd.DataFrame(rows)
    if df.empty: return df
    df["roas"] = df.revenue / df.spend
    df["y"] = np.log1p(df.roas)
    cap = df.spend.quantile(0.90)
    df["w"] = np.sqrt(np.minimum(df.spend, cap))
    df.attrs["cap"] = float(cap)
    return df.reset_index(drop=True)

def fit_cb(tr, seed=7):
    m = CatBoostRegressor(iterations=250, depth=4, learning_rate=0.05, l2_leaf_reg=8, loss_function="RMSE",
                          random_seed=seed, verbose=0, thread_count=4, cat_features=F_STAGE)
    m.fit(tr[F_STAGE], tr["y"], sample_weight=tr["w"])
    return m

class Blend:
    def __init__(self, train):
        self.hy = Hybrid(pairs=True).fit(train)
        self.cb = fit_cb(train)
    def predict_y(self, G):
        return 0.5 * self.hy.predict_y(G) + 0.5 * self.cb.predict(G[F_STAGE])
    def predict_roas(self, G):
        return np.expm1(self.predict_y(G))

def _base_pred(tr, te):
    p = (tr.y * tr.w).groupby(tr["product"]).sum() / tr.w.groupby(tr["product"]).sum()
    return te["product"].map(p).fillna((tr.y * tr.w).sum() / tr.w.sum()).values

# ---------------------------------------------------------------- held-out testing
def backtest(df, reps=2, seed=3):
    """5-fold cross-validation repeated `reps` times. Returns out-of-fold predictions for every ad."""
    rng = np.random.RandomState(seed); frames = []
    for rep in range(reps):
        idx = rng.permutation(len(df)); folds = np.array_split(idx, 5)
        pred = np.zeros(len(df)); base = np.zeros(len(df))
        for f in range(5):
            te_i = folds[f]; te = df.iloc[te_i]; tr = df.drop(df.index[te_i])
            pred[te_i] = Blend(tr).predict_y(te)
            base[te_i] = _base_pred(tr, te)
        o = df.copy(); o["pred"] = pred; o["base"] = base; o["rep"] = rep
        frames.append(o)
    return pd.concat(frames, ignore_index=True)

def _wmae(o, col):
    return float((np.abs(o.roas - np.expm1(o[col])) * o.spend).sum() / o.spend.sum())

def accuracy(o):
    """Spend-weighted mean absolute ROAS error on ads the model did not train on, versus the product-average guess."""
    return {"blend_wMAE": round(float(np.mean([_wmae(g, "pred") for _, g in o.groupby("rep")])), 4),
            "base_wMAE": round(float(np.mean([_wmae(g, "base") for _, g in o.groupby("rep")])), 4)}

def calibration(o, products, cap, boot=300, seed=11):
    """How much of a predicted within-product lift shows up on held-out ads (slope), with a bootstrap range."""
    rng = np.random.RandomState(seed); out = {}
    big = o[o.spend >= EVAL_MIN]
    for p in products:
        g = big[big["product"] == p]
        if len(g) < 8: out[p] = {"slope": 0.0, "lo": -1.0, "hi": 1.0, "n": int(len(g))}; continue
        x = (g.pred - g.pred.mean()).values; y = (g.y - g.y.mean()).values; w = np.sqrt(np.minimum(g.spend, cap)).values
        slope = float((w * x * y).sum() / ((w * x * x).sum() + 1e-12))
        sl = []
        for _ in range(boot):
            i = rng.randint(0, len(g), len(g)); xi, yi, wi = x[i] - x[i].mean(), y[i] - y[i].mean(), w[i]
            sl.append((wi * xi * yi).sum() / ((wi * xi * xi).sum() + 1e-12))
        lo, hi = np.percentile(sl, [10, 90])
        out[p] = {"slope": slope, "lo": float(lo), "hi": float(hi), "n": int(len(g))}
    return out

def residual_sd(o, cap):
    big = o[o.spend >= EVAL_MIN]
    if big.empty: big = o
    w = np.sqrt(np.minimum(big.spend, cap))
    return float(np.sqrt(np.average((big.y - big.pred) ** 2, weights=w)))

# ---------------------------------------------------------------- per-product recipe and evidence
def _tier(sp):
    return "Thin" if sp < 10000 else "Some" if sp < 50000 else "Solid" if sp < 200000 else "Strong"

def _frame(prod, g, recs):
    G = pd.DataFrame(recs); G["product"] = prod
    G["spend"] = float(g.spend.median()); G["ad_id"] = "x"
    return G

def eligible_products(df, min_ads, min_spend):
    out = []
    for p, g in df[~df["product"].isin(["combo", "unmapped"])].groupby("product"):
        if len(g) < min_ads or g.spend.sum() < min_spend: continue
        if all(((g[g[st] != "MISSING"][st].value_counts()) >= MINN).any() for st in STAGES):
            out.append(p)
    return out

def product_result(prod, name, df, blend, o_res, calib, ads_by_id):
    g = df[df["product"] == prod]
    B = float(g.revenue.sum() / g.spend.sum())
    cand = [list((lambda vc: vc[vc >= MINN].index)(g[g[st] != "MISSING"][st].value_counts())) for st in STAGES]
    grid = pd.DataFrame(list(itertools.product(*cand)), columns=STAGES)
    G = _frame(prod, g, grid.to_dict("records"))
    s = blend.predict_y(G); best_i = int(np.argmax(s)); best = grid.iloc[best_i]
    modal = {st: g[g[st] != "MISSING"][st].value_counts().index[0] for st in STAGES}
    pred = lambda recs: np.expm1(blend.predict_y(_frame(prod, g, recs)))
    pr_best = float(np.expm1(s.max())); pr_modal = float(pred([modal])[0])
    final = {st: best[st] for st in STAGES}

    recipe, recipe_support = [], []
    for st in STAGES:
        sub = g[g[st] == final[st]]
        sp = float(sub.spend.sum())
        recipe_support.append(dict(stage=st, angle=final[st], n=int(len(sub)), spend=sp, tier=_tier(sp)))
    top5 = grid.assign(pred=np.expm1(s)).sort_values("pred", ascending=False).head(5)
    alts = [dict(recipe=[r[st] for st in STAGES], pred=float(r["pred"])) for _, r in top5.iterrows()]

    # step 1: spend bands
    bands = []
    for lo, hi, lab in [(10, 1000, "Rs10 to 1K"), (1000, 10000, "Rs1K to 10K"), (10000, 50000, "Rs10K to 50K"), (50000, 1e12, "Rs50K and above")]:
        sub = g[(g.spend >= lo) & (g.spend < hi)]
        if len(sub) >= 2: bands.append(dict(label=lab, n=int(len(sub)), spread=float(sub.y.std()), spend=float(sub.spend.sum())))

    # step 2: every angle's raw ROAS and model ROAS (angle dropped into the most-used recipe)
    stages, solo = [], {}
    for st in STAGES:
        vc = g[g[st] != "MISSING"][st].value_counts(); angs = [a for a in vc.index if vc[a] >= MINN]
        adj = pred([{**modal, st: a} for a in angs])
        rows = []
        for a, ad in zip(angs, adj):
            sub = g[g[st] == a]; sp = float(sub.spend.sum())
            rows.append(dict(angle=a, n=int(len(sub)), spend=sp, raw=float(sub.revenue.sum() / sp), adj=float(ad), tier=_tier(sp)))
        rows.sort(key=lambda r: -r["adj"]); solo[st] = rows[0]["angle"]
        stages.append(dict(stage=st, rows=rows[:8], total_angles=len(rows), picked=rows[0]["angle"], final=final[st]))
    adjmap = {(s_["stage"], r["angle"]): r["adj"] for s_ in stages for r in s_["rows"]}

    # step 3: pair synergy (real ROAS vs the ROAS expected from the two angles alone)
    syn = []
    for i, j in itertools.combinations(range(5), 2):
        a, b = STAGES[i], STAGES[j]
        for (x, y), sub in g[(g[a] != "MISSING") & (g[b] != "MISSING")].groupby([a, b]):
            if len(sub) < 3 or sub.spend.sum() < 8000: continue
            if (a, x) not in adjmap or (b, y) not in adjmap: continue
            obs = float(sub.revenue.sum() / sub.spend.sum()); exp = B + (adjmap[(a, x)] - B) + (adjmap[(b, y)] - B)
            syn.append(dict(sA=a, aA=x, sB=b, aB=y, n=int(len(sub)), spend=float(sub.spend.sum()), obs=obs, exp=exp, syn=obs - exp))
    syn.sort(key=lambda r: -r["syn"])

    # step 4: best single angles versus the best full combination
    solo_p = float(pred([dict(solo)])[0])
    steps4 = []
    for st in STAGES:
        pr = float(pred([{**final, st: solo[st]}])[0])
        steps4.append(dict(stage=st, solo=solo[st], final=final[st], changed=solo[st] != final[st],
                           gain=(pr_best - pr) if solo[st] != final[st] else 0.0))

    # step 5: evidence in real ads
    ev = []
    for i, j in itertools.combinations(range(5), 2):
        a, b = STAGES[i], STAGES[j]; sub = g[(g[a] == final[a]) & (g[b] == final[b])]
        if len(sub):
            obs = float(sub.revenue.sum() / sub.spend.sum()); exp = B + (adjmap.get((a, final[a]), B) - B) + (adjmap.get((b, final[b]), B) - B)
            ev.append(dict(sA=a, aA=final[a], sB=b, aB=final[b], n=int(len(sub)), spend=float(sub.spend.sum()), obs=obs, exp=exp, syn=obs - exp))
        else:
            ev.append(dict(sA=a, aA=final[a], sB=b, aB=final[b], n=0, spend=0.0, obs=None, exp=None, syn=None))
    m = g[STAGES].eq(pd.Series(final)[STAGES].values).sum(axis=1)
    def pool(mask):
        sub = g[mask]; sp = float(sub.spend.sum())
        return dict(n=int(len(sub)), spend=sp, roas=float(sub.revenue.sum() / sp) if len(sub) and sp else None)
    near = g[m >= 3].assign(match=m[m >= 3]).sort_values(["match", "spend"], ascending=False).head(4)
    closest = [dict(ad_id=r.ad_id, match=int(r.match), spend=float(r.spend), roas=float(r.revenue / r.spend),
                    url=(ads_by_id.get(r.ad_id) or {}).get("creative_url") or None) for r in near.itertuples()]
    naive = B + sum((g[g[st] == final[st]].revenue.sum() / g[g[st] == final[st]].spend.sum()) - B for st in STAGES)

    sd = o_res
    lo = float(np.exp(np.log1p(pr_best) - 1.28 * sd) - 1); hi = float(np.exp(np.log1p(pr_best) + 1.28 * sd) - 1)
    return dict(id=prod, name=name, ads=int(len(g)), spend=float(g.spend.sum()), baseline=B, grid=int(len(grid)),
                bands=bands, stages=stages, syn_top=syn[:4], syn_bot=syn[::-1][:3], steps4=steps4,
                solo_pred=solo_p, final_pred=pr_best, alts=alts, evidence=ev, tested=sum(1 for e in ev if e["n"]),
                full_runs=int((m == 5).sum()), m4=pool(m >= 4), m3=pool(m >= 3), closest=closest,
                pred_modal=pr_modal, lo=lo, hi=hi, naive=float(naive), recipe_support=recipe_support,
                calib=calib.get(prod, {"slope": 0.0, "lo": -1.0, "hi": 1.0, "n": 0}))

# ---------------------------------------------------------------- entry point
def compute_lab(ads, sku_names=None, min_ads=15, min_spend=300000.0, reps=2, progress=None):
    """ads: report ads in DATA shape. Returns {'meta': {...}, 'products': [...]} (products empty if none is eligible)."""
    say = progress or (lambda msg: None)
    df = build_df(ads)
    meta = {"n_ads": int(len(df)), "reps": reps}
    if df.empty:
        return {"meta": meta, "products": []}
    prods = eligible_products(df, min_ads, min_spend)
    if not prods:
        return {"meta": meta, "products": []}
    if len(df) > 600: reps = 1                                  # keep big accounts tractable
    say("Testing the model on ads it has not seen")
    o = backtest(df, reps=reps)
    cap = df.attrs["cap"]
    meta.update(accuracy(o)); meta["reps"] = reps
    calib = calibration(o, prods, cap)
    sd = residual_sd(o, cap)
    say("Fitting the final model")
    blend = Blend(df)
    ads_by_id = {a["ad_id"]: a for a in ads}
    names = sku_names or {}
    out = []
    for p in prods:
        say(f"Scoring every combination for {names.get(p, p)}")
        out.append(product_result(p, names.get(p, p), df, blend, sd, calib, ads_by_id))
    return {"meta": meta, "products": out}
