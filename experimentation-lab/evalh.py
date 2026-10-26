import sys, warnings, numpy as np, pandas as pd
warnings.filterwarnings('ignore')
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    import exp_compare as E
from hybrid import Hybrid, STAGES
from cred import CredModel
df = E.df.copy()

def wcorr(a, b, w):
    a = a - np.average(a, weights=w); b = b - np.average(b, weights=w)
    return float((w * a * b).sum() / np.sqrt((w * a * a).sum() * (w * b * b).sum() + 1e-12))

EVAL_MIN = 10000   # ranking is judged on ads where ROAS is precisely measured (the 'at scale' objective)

def metrics(o):
    """o: OOF frame with product, spend, roas, y, pred_y"""
    m = {}
    m['wMAE'] = float((np.abs(o.roas - np.expm1(o.pred_y)) * o.spend).sum() / o.spend.sum())
    d = o[o.spend >= EVAL_MIN].copy(); gp = d.groupby('product')
    d['py'] = d.pred_y - gp.pred_y.transform('mean'); d['ay'] = d.y - gp.y.transform('mean')
    d = d[gp['y'].transform('size') >= 8]
    w = np.sqrt(np.minimum(d.spend, E.CAP)).values
    m['lift r'] = wcorr(d.py.values, d.ay.values, w)
    top, bot = [], []
    for p, g in d.groupby('product'):
        base = g.revenue.sum() / g.spend.sum(); k = max(2, len(g) // 4)
        gs = g.sort_values('py')
        t = gs.tail(k); b = gs.head(k)
        top.append((t.revenue.sum() / t.spend.sum() / base, g.spend.sum())); bot.append((b.revenue.sum() / b.spend.sum() / base, g.spend.sum()))
    sw = np.array([x[1] for x in top])
    m['top25%'] = float(np.average([x[0] for x in top], weights=sw)); m['bot25%'] = float(np.average([x[0] for x in bot], weights=sw))
    return m

def run(models, reps=4, seed=0):
    rng = np.random.RandomState(seed); agg = {k: [] for k in models}
    for rep in range(reps):
        idx = rng.permutation(len(df)); folds = np.array_split(idx, 5)
        oof = {k: np.zeros(len(df)) for k in models}
        for f in range(5):
            te_i = folds[f]; te = df.iloc[te_i]; tr = df.drop(df.index[te_i])
            for k, fn in models.items(): oof[k][te_i] = fn(tr, te)
        for k in models:
            o = df.copy(); o['pred_y'] = oof[k]; agg[k].append(metrics(o))
    out = pd.DataFrame({k: pd.DataFrame(v).mean() for k, v in agg.items()}).T
    sd = pd.DataFrame({k: pd.DataFrame(v).std() for k, v in agg.items()}).T
    return out, sd

# ---- model zoo: each returns predicted y = log1p(ROAS) for test rows ----
def m_base(tr, te):
    p = (tr.y * tr.w).groupby(tr['product']).sum() / tr.w.groupby(tr['product']).sum()
    return te['product'].map(p).fillna((tr.y * tr.w).sum() / tr.w.sum()).values

def m_oldlab(tr, te):
    base = m_base(tr, te); res = base.copy(); lifts = {}
    for p, g in tr.groupby('product'):
        lifts[p] = E.old_lab(g) if len(g) >= 15 else None
    for n, (_, r) in enumerate(te.iterrows()):
        ol = lifts.get(r['product'])
        if ol is None: continue
        ls = [ol['groups'][st][r[st]]['lift'] for st in STAGES if r[st] in ol['groups'][st]]
        res[n] = np.log1p(max(1e-3, np.expm1(base[n]) + sum(ls)))
    return res

def m_cb(tr, te):
    m = E.fit_cb(tr, E.F_STAGE); return m.predict(te[E.F_STAGE])

def mk_c(**kw):
    def f(tr, te): return CredModel(**kw).fit(tr).predict_y(te)
    return f

def mk_h(at_ref=False, **kw):
    def f(tr, te): return Hybrid(**kw).fit(tr).predict_y(te, at_ref=at_ref)
    return f

def m_ens(tr, te):
    return 0.5 * mk_h(pairs=True)(tr, te) + 0.5 * m_cb(tr, te)

def m_ens_cov(tr, te):
    return 0.5 * mk_h(pairs=True, cov=True)(tr, te) + 0.5 * m_cb(tr, te)

if __name__ == '__main__':
    def m_ens_scale(tr, te): return 0.5 * mk_h(pairs=True, cov=True, at_ref=True)(tr, te) + 0.5 * m_cb(tr, te)
    models = {'CatBoost': m_cb,
              'H main': mk_h(pairs=False),
              'H +pairs': mk_h(pairs=True),
              'H +pairs +cov @scale': mk_h(pairs=True, cov=True, at_ref=True),
              'ENS H+pairs & CatBoost': m_ens,
              'ENS H(cov@scale) & CatBoost': m_ens_scale}
    o, sd = run(models, reps=int(sys.argv[1]) if len(sys.argv) > 1 else 3)
    pd.set_option('display.width', 200); print(o.round(3)); print('\nsd across repeats'); print(sd.round(3))
