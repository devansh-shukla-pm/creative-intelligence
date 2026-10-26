import json, itertools, numpy as np, pandas as pd, warnings
warnings.filterwarnings('ignore')
import evalh as H
from hybrid import Hybrid, STAGES
E = H.E; df = H.df.reset_index(drop=True)
LD = json.load(open('lab-data.json')); URL = {a['ad_id']: a.get('creative_url') for a in LD['ads']}
NAMES = {s['id']: s['name'] for s in LD['skus']}
FR = {p['id']: p for p in json.load(open('final_results.json'))['products']}
CF = json.load(open('confirm_results.json'))
PRODS = ['night-repair-cream', 'hair-colour-dye', 'root-touch-up-powder']
MINN = 2
hy = Hybrid(pairs=True).fit(df); cb = E.fit_cb(df, E.F_STAGE)
def pred(G): return np.expm1(0.5 * hy.predict_y(G) + 0.5 * cb.predict(G[E.F_STAGE]))
def tier(sp): return 'Thin' if sp < 10000 else 'Some' if sp < 50000 else 'Solid' if sp < 200000 else 'Strong'
def frame(p, g, recs):
    G = pd.DataFrame(recs); G['product'] = p
    for k in E.META: G[k] = g[k].mode().iloc[0]
    G['spend'] = float(g.spend.median()); G['ad_id'] = 'x'; return G
out = {'meta': {'blend_wMAE': 0.328, 'base_wMAE': 0.375, 'old_wMAE': 0.378, 'n_ads': len(df),
                'shuffle_note': '0 of 12 shuffled-label runs matched the real error and ranking'}, 'products': []}
for p in PRODS:
    g = df[df['product'] == p]; fr = FR[p]; B = fr['baseline']
    modal = {st: g[g[st] != 'MISSING'][st].value_counts().index[0] for st in STAGES}
    final = {r['stage']: r['angle'] for r in fr['recipe']}
    # step 1: spend-trust bands
    bands = []
    for lo, hi, lab in [(10, 1000, 'Rs10 to 1K'), (1000, 10000, 'Rs1K to 10K'), (10000, 50000, 'Rs10K to 50K'), (50000, 1e12, 'Rs50K and above')]:
        s = g[(g.spend >= lo) & (g.spend < hi)]
        if len(s) >= 2: bands.append(dict(label=lab, n=int(len(s)), spread=float(s.y.std()), spend=float(s.spend.sum())))
    # step 2: angle effects
    stages = []; solo = {}
    for st in STAGES:
        vc = g[g[st] != 'MISSING'][st].value_counts(); angs = [a for a in vc.index if vc[a] >= MINN]
        G = frame(p, g, [{**modal, st: a} for a in angs]); adj = pred(G)
        rows = []
        for a, ad in zip(angs, adj):
            sub = g[g[st] == a]; sp = float(sub.spend.sum())
            rows.append(dict(angle=a, n=int(len(sub)), spend=sp, raw=float(sub.revenue.sum() / sp), adj=float(ad), tier=tier(sp)))
        rows.sort(key=lambda r: -r['adj']); solo[st] = rows[0]['angle']
        stages.append(dict(stage=st, rows=rows[:8], total_angles=len(rows), picked=rows[0]['angle'], final=final[st]))
    adjmap = {(s['stage'], r['angle']): r['adj'] for s in stages for r in s['rows']}
    # step 3: pair synergy (observed vs expected from adjusted effects)
    syn = []
    for i, j in itertools.combinations(range(5), 2):
        a, b = STAGES[i], STAGES[j]
        for (x, y), sub in g[(g[a] != 'MISSING') & (g[b] != 'MISSING')].groupby([a, b]):
            if len(sub) < 3 or sub.spend.sum() < 8000: continue
            if (a, x) not in adjmap or (b, y) not in adjmap: continue
            obs = float(sub.revenue.sum() / sub.spend.sum()); exp = B + (adjmap[(a, x)] - B) + (adjmap[(b, y)] - B)
            syn.append(dict(sA=a, aA=x, sB=b, aB=y, n=int(len(sub)), spend=float(sub.spend.sum()), obs=obs, exp=exp, syn=obs - exp))
    syn.sort(key=lambda r: -r['syn'])
    # step 4: search
    solo_rec = {**solo}; solo_p = float(pred(frame(p, g, [solo_rec]))[0]); fin_p = fr['pred_recipe']
    steps4 = []
    for st in STAGES:
        rev = {**final, st: solo[st]}; pr = float(pred(frame(p, g, [rev]))[0])
        steps4.append(dict(stage=st, solo=solo[st], final=final[st], changed=solo[st] != final[st], gain=fin_p - pr if solo[st] != final[st] else 0.0))
    # step 5: evidence
    ev = []
    for i, j in itertools.combinations(range(5), 2):
        a, b = STAGES[i], STAGES[j]; sub = g[(g[a] == final[a]) & (g[b] == final[b])]
        if len(sub):
            obs = float(sub.revenue.sum() / sub.spend.sum()); exp = B + (adjmap.get((a, final[a]), B) - B) + (adjmap.get((b, final[b]), B) - B)
            ev.append(dict(sA=a, aA=final[a], sB=b, aB=final[b], n=int(len(sub)), spend=float(sub.spend.sum()), obs=obs, exp=exp, syn=obs - exp))
        else: ev.append(dict(sA=a, aA=final[a], sB=b, aB=final[b], n=0, spend=0.0, obs=None, exp=None, syn=None))
    m = g[STAGES].eq(pd.Series(final)[STAGES].values).sum(axis=1)
    def pool(mask):
        s = g[mask]; return dict(n=int(len(s)), spend=float(s.spend.sum()), roas=float(s.revenue.sum() / s.spend.sum()) if len(s) and s.spend.sum() else None)
    near = g[m >= 3].assign(match=m[m >= 3]).sort_values(['match', 'spend'], ascending=False).head(4)
    closest = [dict(ad_id=r.ad_id, match=int(r.match), spend=float(r.spend), roas=float(r.revenue / r.spend), url=URL.get(r.ad_id)) for r in near.itertuples()]
    # step 6: contrasts (old-style naive additive)
    naive = B + sum((g[g[st] == final[st]].revenue.sum() / g[g[st] == final[st]].spend.sum()) - B for st in STAGES)
    out['products'].append(dict(id=p, name=NAMES[p], ads=int(len(g)), spend=float(g.spend.sum()), baseline=B, grid=fr['grid'],
        bands=bands, stages=stages, syn_top=syn[:4], syn_bot=syn[::-1][:3], steps4=steps4, solo_pred=solo_p, final_pred=fin_p, alts=fr['alts'],
        evidence=ev, tested=sum(1 for e in ev if e['n']), full_runs=int((m == 5).sum()), m4=pool(m >= 4), m3=pool(m >= 3), closest=closest,
        pred_modal=fr['pred_modal'], lo=fr['lo'], hi=fr['hi'], naive=float(naive),
        recipe_support=[dict(stage=r['stage'], angle=r['angle'], n=r['n'], spend=r['spend'], tier=tier(r['spend'])) for r in fr['recipe']],
        calib=CF['calibration'][p]))
    print(p, 'ok', round(solo_p, 2), round(fin_p, 2))
json.dump(out, open('steps_data.json', 'w'), indent=1)
