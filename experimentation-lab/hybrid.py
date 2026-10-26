"""Hybrid Lab engine: heteroscedastic random-effects model (generalised DerSimonian-Laird).

  y_i = log(1+ROAS_i) = product_p + sum_stage u[stage, angle] + sum_pairs v[pair] + e_i
  Var(e_i) = f(spend_i)   (fitted: high spend -> tiny variance -> that ad's ROAS is trusted)
  u, v ~ N(0, tau^2_group)  -> shrinkage lam_group = sigma^2 / tau^2_group, chosen by exact leave-one-out
"""
import itertools, numpy as np, pandas as pd

STAGES = ['problem-statement', 'hook-line', 'primary-usp-claim', 'use-case-scenario', 'cta-text']


class Design:
    def __init__(self, train, pairs=True, minpair=2, cov=False):
        self.prods = sorted(train['product'].unique())
        self.cols = []   # (group, key)
        self.cov = cov
        if cov:
            self.ls_mu = float(np.log(train['spend']).mean()); self.ls_sd = float(np.log(train['spend']).std())
            self.cols += [('cov', 'ls'), ('cov', 'ls2')]
        for p in self.prods: self.cols.append(('prod', p))
        for st in STAGES:
            for a in sorted(train[st].unique()):
                if a != 'MISSING': self.cols.append((st, a))
        self.pairs = pairs
        if pairs:
            cnt = {}
            for _, r in train.iterrows():
                for i, j in itertools.combinations(range(5), 2):
                    a, b = r[STAGES[i]], r[STAGES[j]]
                    if a != 'MISSING' and b != 'MISSING': cnt[(i, j, a, b)] = cnt.get((i, j, a, b), 0) + 1
            for k, c in sorted(cnt.items()):
                if c >= minpair: self.cols.append(('pair', k))
        self.index = {c: n for n, c in enumerate(self.cols)}
        self.groups = [c[0] for c in self.cols]

    def X(self, d, spend=None):
        M = np.zeros((len(d), len(self.cols)))
        recs = d.to_dict('records')
        if self.cov:
            sp = d['spend'].values if spend is None else np.full(len(d), spend)
            z = (np.log(sp) - self.ls_mu) / self.ls_sd
            M[:, self.index[('cov', 'ls')]] = z; M[:, self.index[('cov', 'ls2')]] = z ** 2 - 1
        for n, r in enumerate(recs):
            j = self.index.get(('prod', r['product']))
            if j is not None: M[n, j] = 1
            for st in STAGES:
                j = self.index.get((st, r[st]))
                if j is not None: M[n, j] = 1
            if self.pairs:
                for i, jj in itertools.combinations(range(5), 2):
                    j = self.index.get(('pair', (i, jj, r[STAGES[i]], r[STAGES[jj]])))
                    if j is not None: M[n, j] = 1
        return M


def fit_var(spend, res, floor=0.01):
    """Var(e) = exp(a + b*log(spend)) fitted on binned residual^2; b clipped to [-1.2, 0]."""
    ls = np.log(spend); q = np.quantile(ls, np.linspace(0, 1, 9)); xs, vs = [], []
    for lo, hi in zip(q[:-1], q[1:]):
        m = (ls >= lo) & (ls <= hi)
        if m.sum() >= 4: xs.append(ls[m].mean()); vs.append(max(np.mean(res[m] ** 2), 1e-4))
    b, a = np.polyfit(xs, np.log(vs), 1); b = min(0, max(-1.2, b))
    a = np.mean(np.log(vs) - b * np.array(xs))
    return lambda s: np.maximum(np.exp(a + b * np.log(s)), floor), (a, b)


def solve(X, y, w, lam):
    A = X.T @ (X * w[:, None]) + np.diag(lam)
    return np.linalg.solve(A + 1e-9 * np.eye(len(lam)), X.T @ (w * y))


def loo_error(X, y, w, lam, intercept):
    Xa = np.column_stack([np.ones(len(y)), X]); la = np.concatenate([[1e-8], lam])
    A = Xa.T @ (Xa * w[:, None]) + np.diag(la) + 1e-9 * np.eye(len(la))
    Ai = np.linalg.inv(A); beta = Ai @ (Xa.T @ (w * y))
    r = y - Xa @ beta; h = np.einsum('ij,jk,ik->i', Xa, Ai, Xa) * w
    loo = r / np.clip(1 - h, 1e-3, None)
    return float(np.sum(w * loo ** 2) / np.sum(w))


GRID = [0.3, 1, 3, 10, 30, 100, 1e3]


def tune_lambdas(X, groups, y, w, fixed=None, rounds=2, init=None):
    """coordinate search on log grid of one lambda per group, minimising exact weighted LOO error"""
    gs = sorted(set(groups)); lam_g = dict(init or {g: 10.0 for g in gs})
    if fixed: lam_g.update(fixed)
    gi = np.array(groups)
    def vec(): return np.array([lam_g[g] for g in groups])
    best = loo_error(X, y, w, vec(), True)
    for _ in range(rounds):
        for g in gs:
            if fixed and g in fixed: continue
            for v in GRID:
                old = lam_g[g]; lam_g[g] = v; e = loo_error(X, y, w, vec(), True)
                if e < best - 1e-9: best = e
                else: lam_g[g] = old
    return lam_g, best


class Hybrid:
    """weights: 'spend' (fitted heteroscedastic), 'flat', or ('pow', gamma)."""
    def __init__(self, pairs=True, weights='spend', cap_q=None, winsor=None, fixed=None, cov=False, ref_q=0.75):
        self.cov = cov; self.ref_q = ref_q; self.pairs = pairs; self.weights = weights; self.cap_q = cap_q; self.winsor = winsor; self.fixed = fixed or {}

    def fit(self, train):
        tr = train.copy()
        y = tr['y'].values.copy()
        if self.winsor:
            lo, hi = np.quantile(y, [self.winsor, 1 - self.winsor]); y = np.clip(y, lo, hi)
        self.D = Design(tr, pairs=False)                       # stage 1 : main effects only, to estimate noise curve
        X1 = self.D.X(tr); lam0 = np.array([1e-3 if g == 'prod' else 10.0 for g in self.D.groups])
        w0 = np.ones(len(y))
        if self.weights == 'flat': self.vf = lambda s: np.full(np.shape(s), 1.0)
        else:
            pm = pd.Series(y).groupby(tr['product'].values).transform('mean').values
            self.vf, self.vpar = fit_var(tr['spend'].values, y - pm)
        s = tr['spend'].values
        if self.cap_q: s = np.minimum(s, np.quantile(s, self.cap_q))
        w = 1.0 / self.vf(s)
        w = w / w.mean()
        self.D = Design(tr, pairs=self.pairs, cov=self.cov)
        self.ref_spend = float(np.quantile(tr['spend'], self.ref_q))
        X = self.D.X(tr)
        self.mean_y = np.average(y, weights=w)
        fixed = dict(self.fixed); fixed.setdefault('cov', 1e-3)
        self.lam, self.loo = tune_lambdas(X, self.D.groups, y - self.mean_y, w, fixed=fixed)
        lamv = np.array([self.lam[g] for g in self.D.groups])
        beta = solve(np.column_stack([np.ones(len(y)), X]), y - self.mean_y, w, np.concatenate([[1e-8], lamv]))
        self.b0 = beta[0]; self.beta = beta[1:]; self.X_tr = X; self.w = w; self.lamv = lamv
        # posterior covariance for uncertainty
        A = np.column_stack([np.ones(len(y)), X]); sig2 = np.average((y - self.mean_y - A @ beta) ** 2, weights=w)
        self.cov = sig2 * np.linalg.inv(A.T @ (A * w[:, None]) + np.diag(np.concatenate([[1e-8], lamv])) + 1e-9 * np.eye(A.shape[1]))
        return self

    def predict_y(self, d, at_ref=False):
        return self.mean_y + self.b0 + self.D.X(d, spend=(self.ref_spend if at_ref else None)) @ self.beta

    def predict_roas(self, d): return np.expm1(self.predict_y(d))

    def predict_sd(self, d):
        A = np.column_stack([np.ones(len(d)), self.D.X(d)])
        return np.sqrt(np.einsum('ij,jk,ik->i', A, self.cov, A))
