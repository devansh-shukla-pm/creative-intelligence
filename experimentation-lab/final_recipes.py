import json, itertools, numpy as np, pandas as pd, warnings
warnings.filterwarnings('ignore')
import evalh as H
from hybrid import Hybrid, STAGES
E = H.E; df = H.df.reset_index(drop=True)
PRODS = ['night-repair-cream', 'hair-colour-dye', 'root-touch-up-powder']
NAMES = {s['id']: s['name'] for s in json.load(open('lab-data.json'))['skus']}
MINN = 2

# ---- 1. calibration from out-of-fold blend predictions (how much of a predicted lift shows up in held-out ads) ----
rng = np.random.RandomState(3); recs = []
for rep in range(2):
    idx = rng.permutation(len(df)); folds = np.array_split(idx, 5); oof = np.zeros(len(df))
    for f in range(5):
        te_i = folds[f]; te = df.iloc[te_i]; tr = df.drop(df.index[te_i])
        oof[te_i] = 0.5 * Hybrid(pairs=True).fit(tr).predict_y(te) + 0.5 * H.m_cb(tr, te)
    o = df.copy(); o['pred'] = oof; o = o[o.spend >= H.EVAL_MIN]; recs.append(o)
o = pd.concat(recs)
sl = {}
for p in PRODS:
    g = o[o['product'] == p]; pm = g.groupby('ad_id').pred.transform('mean')
    x = (g.pred - g.groupby('ad_id').pred.transform('mean')) * 0
    x = g.pred - g.pred.mean(); y = g.y - g.y.mean(); w = np.sqrt(np.minimum(g.spend, E.CAP))
    sl[p] = float((w * x * y).sum() / (w * x * x).sum()); 
allx = o.pred - o.groupby('product').pred.transform('mean'); ally = o.y - o.groupby('product').y.transform('mean'); w = np.sqrt(np.minimum(o.spend, E.CAP))
slope_all = float((w * allx * ally).sum() / (w * allx * allx).sum())
res_sd = float(np.sqrt(np.average((o.y - o.pred) ** 2, weights=w)))
print('calibration slope (all products, within-product lift)', round(slope_all, 3), 'per product', {k: round(v, 2) for k, v in sl.items()}, 'resid sd', round(res_sd, 3))

# ---- 2. final fit on all eligible ads ----
hy = Hybrid(pairs=True).fit(df); cb = E.fit_cb(df, E.F_STAGE)
out = {'meta': {'slope': slope_all, 'resid_sd': res_sd, 'n_ads': len(df), 'minn': MINN}, 'products': []}
def blend(G): return 0.5 * hy.predict_y(G) + 0.5 * cb.predict(G[E.F_STAGE])
for p in PRODS:
    g = df[df['product'] == p]
    cand = []
    for st in STAGES:
        vc = g[g[st] != 'MISSING'][st].value_counts(); cand.append(list(vc[vc >= MINN].index))
    G = pd.DataFrame(list(itertools.product(*cand)), columns=STAGES); G['product'] = p
    for k in E.META: G[k] = g[k].mode().iloc[0]
    G['spend'] = float(g.spend.median()); G['ad_id'] = 'x'
    s = blend(G); best = G.iloc[int(np.argmax(s))]
    modal = {st: g[g[st] != 'MISSING'][st].value_counts().index[0] for st in STAGES}
    M = pd.DataFrame([{**modal, 'product': p, **{k: G[k].iloc[0] for k in E.META}, 'spend': G.spend.iloc[0], 'ad_id': 'x'}])
    B = g.revenue.sum() / g.spend.sum()
    pr_best = float(np.expm1(s.max())); pr_modal = float(np.expm1(blend(M)[0]))
    raw_inc = pr_best / pr_modal - 1                          # model's raw claim vs the most-used recipe
    cal_inc = (1 + raw_inc) ** slope_all - 1                  # what held-out data says actually shows up
    lo, hi = np.exp(np.log1p(pr_best) * 0 + np.log(1 + pr_best) - 1.28 * res_sd) - 1, np.exp(np.log(1 + pr_best) + 1.28 * res_sd) - 1
    stages = []
    for st in STAGES:
        a = best[st]; sub = g[g[st] == a]
        stages.append(dict(stage=st, angle=a, n=int(len(sub)), spend=float(sub.spend.sum()), roas=float(sub.revenue.sum() / sub.spend.sum()), modal=modal[st]))
    top5 = G.assign(pred=np.expm1(s)).sort_values('pred', ascending=False).head(5)
    alts = [dict(recipe=[r[st] for st in STAGES], pred=float(r.pred)) for _, r in top5.iterrows()]
    out['products'].append(dict(id=p, name=NAMES[p], ads=int(len(g)), baseline=float(B), grid=int(len(G)), recipe=stages,
        pred_recipe=pr_best, pred_modal=pr_modal, raw_inc=float(raw_inc), cal_inc=float(cal_inc), lo=float(lo), hi=float(hi), alts=alts,
        full_runs=int((g[STAGES].eq(best[STAGES].values).all(axis=1)).sum())))
    print(p, 'grid', len(G), 'pred', round(pr_best, 2), 'modal', round(pr_modal, 2), 'raw inc %.1f%%' % (100 * raw_inc), 'calibrated %.1f%%' % (100 * cal_inc))
json.dump(out, open('final_results.json', 'w'), indent=1)
