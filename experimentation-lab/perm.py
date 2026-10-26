import sys, numpy as np, pandas as pd
import evalh as H
from hybrid import STAGES
real = H.df.copy()
models = {'CatBoost': H.m_cb, 'H +pairs': H.mk_h(pairs=True), 'C stages': H.mk_c(pairs=False)}
res = {k: [] for k in models}
rng = np.random.RandomState(5)
for t in range(int(sys.argv[1])):
    d = real.copy()
    perm = {}
    for p, g in d.groupby('product'):
        ix = g.index.values; sh = rng.permutation(ix)       # shuffle ALL five angles jointly between ads of the same product
        for st in STAGES: d.loc[ix, st] = real.loc[sh, st].values
    H.df = d
    o, _ = H.run(models, reps=1, seed=t)
    for k in models: res[k].append(o.loc[k])
H.df = real
real_o, _ = H.run(models, reps=3, seed=99)
for k in models:
    a = pd.DataFrame(res[k])
    print(k); print('  real   ', real_o.loc[k].round(3).to_dict())
    print('  permuted mean', a.mean().round(3).to_dict(), 'sd', a.std().round(3).to_dict())
    for m in ['lift r', 'top25%']: print('  p-value (perm >= real) %s: %.2f' % (m, (a[m] >= real_o.loc[k][m]).mean()))
