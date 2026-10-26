import sys, itertools, numpy as np, pandas as pd, warnings
warnings.filterwarnings('ignore')
import evalh as H
from hybrid import Hybrid, STAGES
E = H.E
df = H.df

def grid_for(train, prod, minn):
    g = train[train['product'] == prod]; cand = []
    for st in STAGES:
        vc = g[g[st] != 'MISSING'][st].value_counts(); cand.append(list(vc[vc >= minn].index))
    if any(not c for c in cand): return None
    G = pd.DataFrame(list(itertools.product(*cand)), columns=STAGES); G['product'] = prod
    for k in E.META: G[k] = g[k].mode().iloc[0]
    G['spend'] = float(g.spend.quantile(0.75)); G['ad_id'] = 'x'
    return G

def h_scores(m, G, kappa):
    mu = m.predict_y(G, at_ref=True) if m.cov else m.predict_y(G)
    if kappa == 0: return mu
    top = np.argsort(-mu)[:300]; sd = np.zeros(len(G))
    A = np.column_stack([np.ones(len(top)), m.D.X(G.iloc[top], spend=m.ref_spend if m.cov else None)])
    sd[top] = np.sqrt(np.einsum('ij,jk,ik->i', A, m.cov_mat, A)); out = mu - kappa * sd
    out[sd == 0] = -9; return out

def recipes(train, prod, minn_h=1, kappas=(0, 0.5, 1.0), cov=True, pairs=True):
    out = {}
    m = Hybrid(pairs=pairs, cov=cov).fit(train); m.cov_mat = m.cov_post if hasattr(m, 'cov_post') else None
    return m

def best_by(G, s): return [G.iloc[int(np.argmax(s))][st] for st in STAGES]

def run(prods, reps=30, cov=True):
    rows = []
    for prod in prods:
        d = df[df['product'] == prod]; rng = np.random.RandomState(21)
        R = {}; stated = []
        for r in range(reps):
            msk = rng.rand(len(d)) < 0.6; tr_p, te_p = d[msk], d[~msk]
            train = pd.concat([df[df['product'] != prod], tr_p])
            G1 = grid_for(train, prod, 1); G3 = grid_for(train, prod, 3)
            rec = {}
            m = Hybrid(pairs=True, cov=cov).fit(train)
            m.cov_mat = m.cov
            m_cov_post = m.cov
            for name, G in [('n>=1', G1), ('n>=3', G3)]:
                if G is None: continue
                mu = m.predict_y(G, at_ref=True) if cov else m.predict_y(G)
                rec['H ' + name] = best_by(G, mu)
                if name == 'n>=1':
                    top = np.argsort(-mu)[:300]; A = np.column_stack([np.ones(len(top)), m.D.X(G.iloc[top], spend=m.ref_spend if cov else None)])
                    sd = np.sqrt(np.einsum('ij,jk,ik->i', A, m_cov_post, A))
                    rec['H n>=1 lowerbound'] = [G.iloc[top[int(np.argmax(mu[top] - 1.0 * sd))]][st] for st in STAGES]
                    stated.append(float(np.expm1(mu.max())))
            if G3 is not None:
                cb = E.fit_cb(train, E.F_STAGE); pc = cb.predict(G3[E.F_STAGE]); rec['CatBoost n>=3'] = best_by(G3, pc)
                mu3 = m.predict_y(G3, at_ref=True) if cov else m.predict_y(G3)
                rec['ENS n>=3'] = best_by(G3, 0.5 * mu3 + 0.5 * pc)
            ol = E.old_lab(tr_p); rec['old Lab'] = ol['picks'] if ol else None
            rec['modal'] = E.modal_recipe(tr_p, prod)
            for k, rr in rec.items():
                for mm in (3, 2):
                    e = E.eval_recipe(te_p, prod, rr, mm)
                    if e: R.setdefault((k, mm), []).append(e[0])
        for (k, mm), v in sorted(R.items(), key=lambda x: (x[0][1], x[0][0])):
            rows.append(dict(product=prod, method=k, match=mm, usable=len(v), ratio=np.mean(v), beat=np.mean(np.array(v) > 1)))
    out = pd.DataFrame(rows)
    pd.set_option('display.width', 200)
    for mm in (3, 2):
        print('\nheld-out ads matching >=%d of 5 angles: mean ratio vs product average (1.00 = no better), %% of splits beating it' % mm)
        t = out[out.match == mm].pivot(index='method', columns='product', values='ratio').round(3)
        b = out[out.match == mm].pivot(index='method', columns='product', values='beat').mul(100).round(0)
        print(t.join(b, rsuffix=' %beat'))
    return out

if __name__ == '__main__':
    run(['night-repair-cream', 'hair-colour-dye', 'root-touch-up-powder'], reps=int(sys.argv[1]) if len(sys.argv) > 1 else 20, cov=(sys.argv[2] != 'nocov') if len(sys.argv) > 2 else True)
