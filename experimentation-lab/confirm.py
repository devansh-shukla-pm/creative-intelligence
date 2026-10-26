import sys, json, itertools, numpy as np, pandas as pd, warnings, multiprocessing as mp
warnings.filterwarnings('ignore')
import evalh as H
from hybrid import Hybrid, STAGES
from catboost import CatBoostRegressor
E = H.E
PRODS = ['night-repair-cream', 'hair-colour-dye', 'root-touch-up-powder']

def cb_fit(tr, feats, depth=4, l2=8, iters=250, lr=0.05):
    m = CatBoostRegressor(iterations=iters, depth=depth, learning_rate=lr, l2_leaf_reg=l2, random_seed=7, verbose=0, thread_count=1, cat_features=feats)
    m.fit(tr[feats], tr['y'], sample_weight=tr['w']); return m

def oof_task(args):
    d, seed = args
    rng = np.random.RandomState(seed); idx = rng.permutation(len(d)); folds = np.array_split(idx, 5)
    ph = np.zeros(len(d)); pc = np.zeros(len(d))
    for f in range(5):
        te_i = folds[f]; te = d.iloc[te_i]; tr = d.drop(d.index[te_i])
        ph[te_i] = Hybrid(pairs=True).fit(tr).predict_y(te)
        pc[te_i] = cb_fit(tr, E.F_STAGE).predict(te[E.F_STAGE])
    return ph, pc

def tune_task(args):
    """nested: outer fold f of rep seed; choose CatBoost config on the training part only (inner 3-fold)"""
    d, seed, f = args
    rng = np.random.RandomState(seed); idx = rng.permutation(len(d)); folds = np.array_split(idx, 5)
    te_i = folds[f]; te = d.iloc[te_i]; tr = d.drop(d.index[te_i]).reset_index(drop=True)
    grid = [dict(depth=a, l2=b, iters=c) for a in (3, 4, 6) for b in (3, 8, 20) for c in (150, 300)]
    ii = np.random.RandomState(1).permutation(len(tr)); inner = np.array_split(ii, 3); best = None
    for cfg in grid:
        err = 0; wsum = 0
        for k in range(3):
            iv = tr.iloc[inner[k]]; it = tr.drop(tr.index[inner[k]])
            p = np.expm1(cb_fit(it, E.F_STAGE, **cfg).predict(iv[E.F_STAGE]))
            err += (np.abs(iv.roas.values - p) * iv.spend.values).sum(); wsum += iv.spend.sum()
        if best is None or err / wsum < best[0]: best = (err / wsum, cfg)
    pt = cb_fit(tr, E.F_STAGE, **best[1]).predict(te[E.F_STAGE])
    return te_i, pt, best[1]

def shuffled(d, seed):
    rng = np.random.RandomState(seed); out = d.copy()
    for p, g in d.groupby('product'):
        ix = g.index.values; sh = rng.permutation(ix)
        for st in STAGES: out.loc[ix, st] = d.loc[sh, st].values
    return out

def mets(d, pred):
    o = d.copy(); o['pred_y'] = pred; return H.metrics(o)

if __name__ == '__main__':
    d = H.df.reset_index(drop=True); ctx = mp.get_context('fork'); pool = ctx.Pool(8)
    REPS, PERMS = 10, 12
    print('step 1a: 10 repeated 5-fold runs of the blend', flush=True)
    res = pool.map(oof_task, [(d, s) for s in range(REPS)])
    rows = {'blend': [], 'random-effects only': [], 'CatBoost only': []}; oofs = []
    for ph, pc in res:
        rows['blend'].append(mets(d, 0.5 * ph + 0.5 * pc)); rows['random-effects only'].append(mets(d, ph)); rows['CatBoost only'].append(mets(d, pc)); oofs.append(0.5 * ph + 0.5 * pc)
    tab = pd.DataFrame({k: pd.DataFrame(v).mean() for k, v in rows.items()}).T; sdt = pd.DataFrame({k: pd.DataFrame(v).std() for k, v in rows.items()}).T
    print(tab.round(3)); print('sd across repeats'); print(sdt.round(3), flush=True)
    print('\nstep 1b: shuffle test on the blend (%d shuffles)' % PERMS, flush=True)
    pr = pool.map(oof_task, [(shuffled(d, 1000 + s), 500 + s) for s in range(PERMS)])
    pm = [mets(shuffled(d, 1000 + s), 0.5 * a + 0.5 * b) for s, (a, b) in enumerate(pr)]
    P = pd.DataFrame(pm); real = tab.loc['blend']
    print('real blend', real.round(3).to_dict()); print('shuffled mean', P.mean().round(3).to_dict(), 'sd', P.std().round(3).to_dict())
    for m, hi in [('lift r', True), ('top25%', True), ('wMAE', False)]:
        cnt = (P[m] >= real[m]).sum() if hi else (P[m] <= real[m]).sum(); print('  p(%s) = %.3f   (%d of %d shuffles as good)' % (m, (cnt + 1) / (PERMS + 1), cnt, PERMS))
    print('\nstep 1c: per-product calibration slope, 10 repeats pooled + bootstrap CI', flush=True)
    cal = {}
    for p in PRODS:
        m = (d['product'] == p) & (d.spend >= H.EVAL_MIN); sub = d[m]; w = np.sqrt(np.minimum(sub.spend, E.CAP)).values
        xs = [o[m.values] - o[m.values].mean() for o in oofs]; y = sub.y.values - sub.y.mean()
        def slope(ix): 
            xx = np.concatenate([x[ix] for x in xs]); yy = np.concatenate([y[ix]] * len(xs)); ww = np.concatenate([w[ix]] * len(xs)); return (ww * xx * yy).sum() / ((ww * xx * xx).sum() + 1e-12)
        n = len(sub); s0 = slope(np.arange(n)); rng = np.random.RandomState(0); bs = [slope(rng.randint(0, n, n)) for _ in range(400)]
        cal[p] = dict(slope=float(s0), lo=float(np.percentile(bs, 10)), hi=float(np.percentile(bs, 90)), n=n)
        print('  %-22s slope %.2f   80%% CI [%.2f, %.2f]   (%d ads >= 10K)' % (p, s0, cal[p]['lo'], cal[p]['hi'], n))
    allm = d.spend >= H.EVAL_MIN
    print('\nstep 2: nested CatBoost tuning (3 reps x 5 outer folds)', flush=True)
    tasks = [(d, s, f) for s in range(3) for f in range(5)]; tr_ = pool.map(tune_task, tasks)
    tuned = []; cfgs = []
    for s in range(3):
        pt = np.zeros(len(d))
        for (_, ss, f), (ti, p, cfg) in zip(tasks, tr_):
            if ss == s: pt[ti] = p; cfgs.append(tuple(sorted(cfg.items())))
        tuned.append(pt)
    from collections import Counter
    print('configs chosen:', Counter(cfgs).most_common(4))
    dm = [mets(d, t) for t in tuned]; dd = [mets(d, res[s][1]) for s in range(3)]
    db = [mets(d, 0.5 * res[s][0] + 0.5 * tuned[s]) for s in range(3)]
    print('CatBoost default  ', pd.DataFrame(dd).mean().round(3).to_dict()); print('CatBoost tuned    ', pd.DataFrame(dm).mean().round(3).to_dict())
    print('blend (tuned CB)  ', pd.DataFrame(db).mean().round(3).to_dict()); print('blend (default CB)', tab.loc['blend'].round(3).to_dict())
    json.dump(dict(calibration=cal, blend=tab.loc['blend'].to_dict(), shuffled_mean=P.mean().to_dict()), open('confirm_results.json', 'w'), indent=1)
    print('DONE', flush=True)
