"""Empirical-credibility Lab engine ("Hybrid-C").

Idea: instead of assuming how much to trust an angle's historical ROAS (a fixed K), MEASURE it.
For every training ad i and every stage j we ask: "the OTHER ads of this product that used the same angle
had lift x (log-ROAS vs product baseline) on total spend S over n ads -- how much of x showed up in ad i?"
The slope of that relationship is the credibility c(S, n). It is fitted, not assumed:

    c(S, n) = cmax * S/(S+S0) * n/(n+n0)          (rises with spend S and with ad count n)
    predicted lift(ad) = sum_stage c(S_j, n_j) * x_j  [+ sum_pairs c2 * x_pair]
"""
import itertools, numpy as np, pandas as pd
from scipy.optimize import least_squares

STAGES = ['problem-statement', 'hook-line', 'primary-usp-claim', 'use-case-scenario', 'cta-text']
CLIP = 1.5


def lg(r): return np.log1p(np.maximum(r, 0))


class CredModel:
    def __init__(self, pairs=False, minpair=2, floor_S=0.0, w_pow=0.5, cap=None):
        self.pairs = pairs; self.minpair = minpair; self.w_pow = w_pow; self.cap = cap

    # ---------- statistics ----------
    @staticmethod
    def _stats(g, mask):
        s = g[mask]; n = len(s)
        if n == 0: return 0, 0.0, 0.0
        S = s.spend.sum(); return n, S, s.revenue.sum() / S

    def _prep(self, train):
        self.tr = train.reset_index(drop=True)
        self.prod_base = {}
        for p, g in self.tr.groupby('product'): self.prod_base[p] = (g.revenue.sum(), g.spend.sum())
        self.gb = self.tr.revenue.sum() / self.tr.spend.sum()

    def base(self, p, excl=None):
        if p in self.prod_base:
            R, S = self.prod_base[p]
            if excl is not None: R -= excl.revenue; S -= excl.spend
            if S > 0: return R / S
        return self.gb

    def features(self, d, loo):
        """returns arrays N(rows,5), S, X for stages and (optionally) pair features"""
        tr = self.tr; nrows = len(d); recs = d.to_dict('records')
        N = np.zeros((nrows, 5)); S = np.zeros((nrows, 5)); X = np.zeros((nrows, 5))
        NP = np.zeros((nrows, 10)); SP = np.zeros((nrows, 10)); XP = np.zeros((nrows, 10))
        byprod = {p: g for p, g in tr.groupby('product')}
        for n_, r in enumerate(recs):
            g = byprod.get(r['product'])
            if g is None: continue
            if loo: g = g[g['ad_id'] != r['ad_id']]
            if len(g) == 0: continue
            B = g.revenue.sum() / g.spend.sum(); lb = lg(B)
            for j, st in enumerate(STAGES):
                a = r[st]
                if a == 'MISSING': continue
                n, Ssum, R = self._stats(g, g[st] == a)
                if n: N[n_, j] = n; S[n_, j] = Ssum; X[n_, j] = np.clip(lg(R) - lb, -CLIP, CLIP)
            if self.pairs:
                for k, (i, j) in enumerate(itertools.combinations(range(5), 2)):
                    a, b = r[STAGES[i]], r[STAGES[j]]
                    if a == 'MISSING' or b == 'MISSING': continue
                    n, Ssum, R = self._stats(g, (g[STAGES[i]] == a) & (g[STAGES[j]] == b))
                    if n >= self.minpair: NP[n_, k] = n; SP[n_, k] = Ssum; XP[n_, k] = np.clip(lg(R) - lb, -CLIP, CLIP)
        return N, S, X, NP, SP, XP

    # ---------- credibility curve ----------
    @staticmethod
    def cred(S, N, cmax, S0, n0):
        return cmax * S / (S + S0) * N / (N + n0) * (N > 0)

    def _pred(self, th, F):
        N, S, X, NP, SP, XP = F
        p = (self.cred(S, N, *th[:3]) * X).sum(1)
        if self.pairs: p = p + (self.cred(SP, NP, *th[3:6]) * XP).sum(1)
        return p

    def fit(self, train):
        self._prep(train)
        tr = self.tr
        F = self.features(tr, loo=True)
        y = np.array([lg(r.roas) - lg(self.base(r['product'], excl=r)) for _, r in tr.iterrows()])
        w = np.minimum(tr.spend.values, self.cap or np.inf) ** self.w_pow; w = w / w.mean()
        k = 6 if self.pairs else 3
        x0 = np.array([0.4, 5000, 1.0, 0.2, 5000, 1.0][:k])
        lo = np.array([0, 100, 0.01, 0, 100, 0.01][:k]); hi = np.array([1.5, 5e5, 20, 1.5, 5e5, 20][:k])
        res = least_squares(lambda th: np.sqrt(w) * (y - self._pred(th, F)), x0, bounds=(lo, hi))
        self.th = res.x; self.y_loo = y; self.res_loo = y - self._pred(self.th, F); self.w_tr = w
        self.sd_res = float(np.sqrt(np.average(self.res_loo ** 2, weights=w)))
        return self

    # ---------- predictions ----------
    def lift(self, d):
        F = self.features(d, loo=False); return self._pred(self.th, F)

    def predict_y(self, d):
        b = np.array([lg(self.base(p)) for p in d['product']])
        return b + self.lift(d)

    def predict_roas(self, d): return np.expm1(self.predict_y(d))

    def curve(self, S, n): return self.cred(np.array(S, float), np.array(n, float), *self.th[:3])


def recipe_candidates(train, prod, minn=1):
    g = train[train['product'] == prod]
    return [list(g[g[st] != 'MISSING'][st].value_counts().loc[lambda v: v >= minn].index) for st in STAGES]
