"""Head-to-head: old Lab method vs CatBoost recipe model, on the same data and the same splits.
Run: python exp_compare.py   (needs numpy, pandas, catboost)
"""
import json, csv, itertools, sys, warnings
import numpy as np, pandas as pd
from catboost import CatBoostRegressor
warnings.filterwarnings('ignore')

LAB = json.load(open('lab-data.json'))
STAGES = ['problem-statement','hook-line','primary-usp-claim','use-case-scenario','cta-text']
META = ['storytelling_style','hook_type','visual_style','audio_type','video_duration','text_density','creator_presence','offer_visibility','sequence_pattern','aspect_ratio','Customer life cycle','media_type']

# ---------- data ----------
rows = list(csv.DictReader(open(__import__('os').environ.get('CI_SOURCE_CSV','source-data/Shesha Full Creatives Analysis.csv'), encoding='utf-8-sig')))
meta = {}
for r in rows: meta.setdefault(r['ad_id'], r)          # duplicates carry identical numbers (checked), keep first
recs = []
for a in LAB['ads']:
    m = meta.get(a['ad_id'], {})
    prod = a['skus'][0] if len(a['skus']) == 1 else ('combo' if len(a['skus']) > 1 else 'unmapped')
    d = {'ad_id': a['ad_id'], 'product': prod, 'spend': a['spend'], 'revenue': a['revenue']}
    for st in STAGES: d[st] = a['stages'].get(st) or 'MISSING'
    for k in META: d[k] = (m.get(k) or 'MISSING').split(' | ')[0].strip() or 'MISSING'
    recs.append(d)
df = pd.DataFrame(recs)
df = df[df.spend >= 10].reset_index(drop=True)
df['roas'] = df.revenue / df.spend
df['y'] = np.log1p(df.roas)
CAP = df.spend.quantile(0.90)
df['w'] = np.sqrt(np.minimum(df.spend, CAP))
print('eligible ads', len(df), '| products', df['product'].value_counts().to_dict())

# ---------- old Lab method (python port of lab-engine.v1.js) ----------
def old_lab(tr):
    """tr: train ads of ONE product. returns dict with picks per stage, lifts, B, or None."""
    B = tr.revenue.sum() / tr.spend.sum()
    groups = {}; allg = []
    for st in STAGES:
        groups[st] = {}
        for ang, g in tr[tr[st] != 'MISSING'].groupby(st):
            if len(g) < 3: continue
            raw = g.revenue.sum() / g.spend.sum(); rho = (g.revenue / g.spend).values
            o = dict(stage=st, angle=ang, n=len(g), raw=raw, mean=rho.mean(), rho=rho, spend=g.spend.sum())
            groups[st][ang] = o; allg.append(o)
    if any(not groups[st] for st in STAGES): return None
    ssw = sum(((o['rho'] - o['mean']) ** 2).sum() for o in allg); dfw = sum(o['n'] - 1 for o in allg)
    s2 = ssw / dfw if dfw else 0; k = len(allg); tau2 = 0; Kraw = np.inf
    if s2 > 0 and k > 1:
        w = np.array([o['n'] / s2 for o in allg]); sw = w.sum(); sw2 = (w ** 2).sum()
        mu = sum(wi * o['mean'] for wi, o in zip(w, allg)) / sw
        Q = sum(wi * (o['mean'] - mu) ** 2 for wi, o in zip(w, allg))
        tau2 = max(0, (Q - (k - 1)) / (sw - sw2 / sw)); Kraw = s2 / tau2 if tau2 > 0 else np.inf
    K = min(20, max(0.5, Kraw))
    for o in allg: o['shrunk'] = (o['n'] * o['raw'] + K * B) / (o['n'] + K); o['lift'] = o['shrunk'] - B
    cache = {}
    def pair(sa, aa, sb, ab):
        key = (sa, aa, sb, ab)
        if key not in cache:
            g = tr[(tr[sa] == aa) & (tr[sb] == ab)]; sp = g.spend.sum()
            ran = len(g) >= 1 and sp >= 8000
            cache[key] = dict(n=len(g), ran=ran, strong=ran and len(g) >= 3, obs=g.revenue.sum() / sp if ran else None)
        return cache[key]
    prs = list(itertools.combinations(range(5), 2))
    def score(p):
        t = sum(g['shrunk'] for g in p)
        for i, j in prs:
            q = pair(p[i]['stage'], p[i]['angle'], p[j]['stage'], p[j]['angle'])
            if q['strong']: t += q['obs'] - (B + p[i]['lift'] + p[j]['lift'])
        return t
    picks = [max(groups[st].values(), key=lambda o: o['shrunk']) for st in STAGES]
    for _ in range(2):
        ch = False
        for si, st in enumerate(STAGES):
            best, bs = picks[si], score(picks)
            for c in groups[st].values():
                if c is picks[si]: continue
                t = picks[:]; t[si] = c; sc = score(t)
                if sc > bs + 1e-9: best, bs = c, sc
            if best is not picks[si]: picks[si] = best; ch = True
        if not ch: break
    return dict(B=B, K=K, picks=[p['angle'] for p in picks], groups=groups, tau2=tau2, s2=s2)

# validate the port against the JS engine on full Night Repair data
nr = df[df['product'] == 'night-repair-cream']
o = old_lab(nr)
print('PORT CHECK Night Repair  B=%.2f K=%.2f' % (o['B'], o['K']), o['picks'])

# ---------- CatBoost model ----------
def fit_cb(tr, feats):
    m = CatBoostRegressor(iterations=250, depth=4, learning_rate=0.05, l2_leaf_reg=8, loss_function='RMSE',
                          random_seed=7, verbose=0, thread_count=4, cat_features=feats)
    m.fit(tr[feats], tr['y'], sample_weight=tr['w']); return m
F_STAGE = ['product'] + STAGES
F_META = F_STAGE + META

def wmae(y, p, w): return float((np.abs(y - p) * w).sum() / w.sum())

# ---------- EXPERIMENT A: row-level prediction (5-fold x 3 repeats) ----------
def expA(reps=3):
    res = {k: [] for k in ['product baseline','product median (fair)','product log-mean (fair)', 'old method naive sum', 'old method mean lift', 'CatBoost stages', 'CatBoost stages+meta']}
    resw = {k: [] for k in res}
    rng = np.random.RandomState(0)
    for rep in range(reps):
        idx = rng.permutation(len(df)); folds = np.array_split(idx, 5)
        for f in range(5):
            te = df.iloc[folds[f]]; tr = df.drop(df.index[folds[f]])
            pb = {p: g.revenue.sum() / g.spend.sum() for p, g in tr.groupby('product')}
            gB = tr.revenue.sum() / tr.spend.sum()
            def wmed(g):
                o = np.argsort(g.roas.values); c = np.cumsum(g.w.values[o]); return g.roas.values[o][np.searchsorted(c, c[-1] / 2)]
            pmed = {p: wmed(g) for p, g in tr.groupby('product')}; gmed = wmed(tr)
            plog = {p: float(np.expm1((g.y * g.w).sum() / g.w.sum())) for p, g in tr.groupby('product')}
            base = te['product'].map(pb).fillna(gB).values
            lifts = {}
            for p, g in tr.groupby('product'):
                ol = old_lab(g) if len(g) >= 15 else None
                lifts[p] = ol
            naive, mean_ = [], []
            for _, r in te.iterrows():
                ol = lifts.get(r['product']); b = pb.get(r['product'], gB)
                if ol is None: naive.append(b); mean_.append(b); continue
                ls = [ol['groups'][st][r[st]]['lift'] for st in STAGES if r[st] in ol['groups'][st]]
                naive.append(b + sum(ls)); mean_.append(b + (np.mean(ls) if ls else 0))
            preds = {'product baseline': base, 'product median (fair)': te['product'].map(pmed).fillna(gmed).values, 'product log-mean (fair)': te['product'].map(plog).fillna(gmed).values, 'old method naive sum': np.array(naive), 'old method mean lift': np.array(mean_)}
            m1 = fit_cb(tr, F_STAGE); preds['CatBoost stages'] = np.expm1(m1.predict(te[F_STAGE]))
            m2 = fit_cb(tr, F_META); preds['CatBoost stages+meta'] = np.expm1(m2.predict(te[F_META]))
            for k, p in preds.items():
                res[k].append(float(np.abs(te.roas.values - p).mean())); resw[k].append(wmae(te.roas.values, p, te.spend.values))
    print('\nEXPERIMENT A  row-level prediction, 5-fold x %d (lower is better)' % reps)
    print('%-26s %10s %14s' % ('model', 'MAE (ads)', 'MAE (spend-wtd)'))
    for k in res: print('%-26s %10.3f %14.3f' % (k, np.mean(res[k]), np.mean(resw[k])))
    return res, resw

# ---------- EXPERIMENT B: whole-pipeline recipe selection ----------
def cb_recipe(tr, prod, feats):
    """exhaustive search over supported angles (n>=3 in this product's train ads) scored by CatBoost"""
    g = tr[tr['product'] == prod]
    cand = []
    for st in STAGES:
        vc = g[g[st] != 'MISSING'][st].value_counts(); cand.append(list(vc[vc >= 3].index))
    if any(not c for c in cand): return None
    grid = pd.DataFrame(list(itertools.product(*cand)), columns=STAGES)
    grid['product'] = prod
    for k in feats:
        if k not in grid:                    # metadata: modal value for the product (context held fixed)
            grid[k] = g[k].mode().iloc[0]
    m = fit_cb(tr, feats)
    grid['pred'] = np.expm1(m.predict(grid[feats]))
    best = grid.sort_values('pred', ascending=False).iloc[0]
    return [best[st] for st in STAGES], float(best['pred']), len(grid)

def modal_recipe(tr, prod):
    g = tr[tr['product'] == prod]; out = []
    for st in STAGES:
        vc = g[g[st] != 'MISSING'][st].value_counts(); out.append(vc.index[0] if len(vc) else None)
    return out

def raw_top(tr, prod):
    ol = old_lab(tr[tr['product'] == prod])
    if ol is None: return None
    return [max(ol['groups'][st].values(), key=lambda o: o['raw'])['angle'] for st in STAGES]

def eval_recipe(te, prod, rec, minmatch=3):
    t = te[te['product'] == prod]
    if rec is None or len(t) == 0: return None
    m = t[[sum(r[st] == a for st, a in zip(STAGES, rec)) >= minmatch for _, r in t.iterrows()]]
    if len(m) < 2: return None
    return (m.revenue.sum() / m.spend.sum()) / (t.revenue.sum() / t.spend.sum()), len(m), m.spend.sum()

def expB(prods, reps=40, minmatch=3):
    out = {}
    for prod in prods:
        d = df[df['product'] == prod]; rng = np.random.RandomState(11)
        R = {k: [] for k in ['old Lab', 'CatBoost stages', 'CatBoost stages+meta', 'raw top angles', 'modal recipe']}
        pr = []; sc = 0
        for r in range(reps):
            msk = rng.rand(len(d)) < 0.6
            tr_p, te_p = d[msk], d[~msk]
            trainfull = pd.concat([df[df['product'] != prod], tr_p])     # other products stay in training (pooled model)
            ol = old_lab(tr_p)
            recs_ = {'old Lab': ol['picks'] if ol else None, 'raw top angles': raw_top(tr_p, prod), 'modal recipe': modal_recipe(tr_p, prod)}
            c1 = cb_recipe(trainfull, prod, F_STAGE); c2 = cb_recipe(trainfull, prod, F_META)
            recs_['CatBoost stages'] = c1[0] if c1 else None; recs_['CatBoost stages+meta'] = c2[0] if c2 else None
            for k, rec in recs_.items():
                e = eval_recipe(te_p, prod, rec, minmatch)
                if e: R[k].append(e[0])
            if c1:
                e = eval_recipe(te_p, prod, c1[0], minmatch)
                if e: pr.append((c1[1], (te_p[[sum(rr[st] == a for st, a in zip(STAGES, c1[0])) >= minmatch for _, rr in te_p.iterrows()]]).pipe(lambda m: m.revenue.sum() / m.spend.sum()), te_p.revenue.sum() / te_p.spend.sum()))
        out[prod] = (R, pr)
        print('\nEXPERIMENT B  %s (%d eligible ads), %d random 60/40 splits, held-out ads matching >=%d of 5 angles' % (prod, len(d), reps, minmatch))
        print('%-24s %6s %10s %12s' % ('method', 'usable', 'mean vs base', '% beat base'))
        for k, v in R.items():
            if v: print('%-24s %6d %10.3f %12.0f%%' % (k, len(v), np.mean(v), 100 * np.mean(np.array(v) > 1)))
            else: print('%-24s %6d' % (k, 0))
        if pr:
            a = np.array(pr); print('CatBoost stated ROAS %.2f vs held-out actual for that recipe %.2f (product held-out avg %.2f)' % (a[:, 0].mean(), a[:, 1].mean(), a[:, 2].mean()))
    return out

if __name__ == '__main__':
    which = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if which in ('A', 'all'): expA()
    if which in ('B', 'all'): expB(['night-repair-cream', 'hair-colour-dye', 'root-touch-up-powder'])
