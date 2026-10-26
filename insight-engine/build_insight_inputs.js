#!/usr/bin/env node
/*
  CREATIVE INTEL: INSIGHT PRE-COMPUTE
  ====================================================================
  Does EVERY calculation the insight prompt used to do, so the prompt
  never has to. Reads the raw ad-level data, writes insight_inputs.json:
  a finished "candidate pack" in which

    - all baselines, rollups, pair tables, percentiles and thresholds are
      already computed,
    - every numeric guardrail (G1 zero-spend, G2 absolute spend floor) is
      already applied,
    - the 7 candidate types are already ranked and assembled into a
      suggested feed order (+ reserves),
    - every number the model is allowed to quote is also pre-rounded and
      pre-formatted as a *_display string.

  The model's job is then ONLY: judgment (G3 product/angle fit, the
  Obviousness Filter) and plain-language writing.

  Usage:
    node build_insight_inputs.js                      # reads ./build/ci/creative-intelligence.html
    node build_insight_inputs.js --html path/to.html
    node build_insight_inputs.js --data ads.json      # {ads, stage_defs, skus} or a bare ads array
    node build_insight_inputs.js --out custom.json
*/
const fs = require('fs');
const path = require('path');

/* ------------------------------ config ------------------------------ */
const CFG = {
  FIXED_FLOOR: 5000,            // G2 fixed currency floor (never scope-relative)
  FLOOR_PCT: 0.003,             // G2 percentage floor (0.3% of total spend)
  DO:   { minN:5, roasMult:1.2, maxShare:3, widenN:3, widenRoasMult:1.3 },
  STOP: { minShare:15, freqPeerShare:10, dragMult:0.85, brokenHi:0.98, brokenLo:0.85 },
  CHEM: { minN:4, strongMult:1.25, widenMult:1.15 },
  WS:   { minSourceN:4, roasMult:1.2, maxTargetN:1, coldStartBelow:8 },
  PT:   { topK:3, minShare:5, minSkuAds:3, minPatternAds:3, holdsMult:1.1, confirmFrac:0.7, debunkFrac:0.3, minTestable:3 },
  AA:   { minDominantShare:40, minBestN:4, gapMult:1.3 },
  US:   { maxPresencePct:15, minN:2, roasMult:1.3 },
  // fatigue only counts when people really have seen it more than elsewhere
  FATIGUE: { minTimesSeen:2.5, vsPeersMult:1.25 },
  // funnel leak: people click through fine, then do not add to cart / buy, on a choice with real money behind it
  FL:   { minSpend:300000, minN:4, lpvMult:1.05, leakMult:0.85, convLeakMult:0.75 },
  // product split: the same creative choice, different results in different single products
  QC:   { minN:5, minShare:3, lpvMax:0.9, convMin:1.25, roasMin:1.1 },
  CL:   { minN:4, dragMult:0.8 },
  PS:   { minN:3, minSpend:25000, betterMult:1.2, budgetTimes:3, bothMinSpend:100000, worksMult:1.25 },
  RESERVE: 3,                   // how many extra ranked candidates to hand over as substitutes
  // EDITORIAL EXCLUSIONS: things a marketer already knows or can decide without data.
  // Never the subject of an insight, never one half of a pairing, never counted as a candidate.
  EXCLUDE_STAGES: ['cta-text'],        // choosing how an ad closes is intuitive
  EXCLUDE_APPROACH_TYPES: true,        // Push Product / Problem / Differentiation / Brand / Offer: broad pitch styles are intuitive
};
const STAGE_GLOSS = {
  'problem-statement':'the problem it opens with', 'hook-line':'the opening hook',
  'primary-usp-claim':"the core claim it's proving", 'use-case-scenario':'the context it is shown in',
  'cta-text':'how it closes', 'testimonial-claim':'the testimonial it uses', 'proof-points':'the proof it cites',
  'credibility-signal':'the credibility signal it leans on', 'offer-details':'the offer or promo it is running',
  'comparison-axis':'what it is comparing itself against',
};
const APPROACH_GLOSS = {
  'Push Product':'leads with the product itself', 'Push Problem':'leads with the problem it solves',
  'Push Differentiation':'leads with what makes it different', 'Push Brand':'leads with brand trust and credibility',
  'Push Offer':'leads with a deal or promotion',
};


/* ------------------------- semantic sanity layer -------------------------
   Keeps the feed from suggesting nonsense such as "the grey-hair hook works on
   hair oil, so use it on face wash". Two parts:
   1. PRODUCT_PROFILES: what each product is, what body area and what concern it serves.
   2. concernsOf(): which area / concern a piece of creative text speaks to.
   A creative choice that speaks to an area or concern is only ever suggested for, or
   compared across, products that serve it. Anything else is dropped here and listed
   under rejected_by_guardrail (G7) so it is never brought back.
   The profiles are plain descriptions maintained by the team: fix them here if a product
   is described wrongly. */
const PRODUCT_PROFILES = {
  'lip-balm':             { what:'a lip balm for dry or dark lips',                       areas:['lips'], concerns:['lips'] },
  'root-touch-up-powder': { what:'an instant powder that covers grey roots between colourings', areas:['hair'], concerns:['grey-hair','hair-colouring'] },
  'hair-colour-dye':      { what:'a hair colour that covers grey hair',                   areas:['hair'], concerns:['grey-hair','hair-colouring'] },
  'tan-removal':          { what:'a de-tan product for sun-tanned skin',                  areas:['skin'], concerns:['tan','pigmentation','glow'] },
  'kumkumadi-oil':        { what:'an Ayurvedic face oil for glow and pigmentation',       areas:['skin'], concerns:['glow','pigmentation','night-care'] },
  'night-repair-cream':   { what:'a night-time skin repair cream',                        areas:['skin'], concerns:['night-care','pigmentation','acne','glow'] },
  'hair-oil':             { what:'an oil for hair health and growth',                     areas:['hair'], concerns:['hair-growth'] },
  'day-cream':            { what:'a daytime face cream',                                  areas:['skin'], concerns:['glow','tan'] },
  'face-wash':            { what:'a daily face cleanser',                                 areas:['skin'], concerns:['acne','glow','pigmentation'] },
  'face-serum':           { what:'a face serum for glow and pigmentation',                areas:['skin'], concerns:['glow','pigmentation','acne'] },
};
const AREA_RULES = [
  ['hair',  /\bhair\b|grey|gray|\broot\b|\bdye\b|scalp/i],
  ['lips',  /\blips?\b/i],
  ['skin',  /\bskin|glow|pigment|acne|\bscar|\btan\b|post-sun|dullness|brighten|exfoliat|night repair|nighttime|skincare|complexion|skin tone/i],
];
const CONCERN_RULES = [
  ['grey-hair',       /grey|gray|\broot\b/i],
  ['hair-colouring',  /\bdye\b|hair colou?r|colou?r/i],
  ['hair-growth',     /growth|strength|hair health|hair-fall|hairfall/i],
  ['tan',             /\btan\b|post-sun|\bsun\b/i],
  ['lips',            /\blips?\b/i],
  ['acne',            /acne|\bscar/i],
  ['night-care',      /night/i],
  ['pigmentation',    /pigment|dullness/i],
];
// text from the data that is not about these products at all (mis-tagged ads); never used anywhere
const OFF_TOPIC = /digital|security|privacy|disaster|environment|weight|health risk|health warning|general health|health awareness|authentic health|fragrance|odou?r|freshness/i;
const tagsOf = text => ({
  areas: AREA_RULES.filter(([, re]) => re.test(text)).map(([k]) => k),
  concerns: CONCERN_RULES.filter(([, re]) => re.test(text)).map(([k]) => k),
});
// does a piece of creative text make sense for this product? (text with no area/concern is treated as general)
const fitsProduct = (text, skuId) => {
  const prof = PRODUCT_PROFILES[skuId]; if (!prof) return true;
  const t = tagsOf(text);
  if (t.areas.length && !t.areas.some(a => prof.areas.includes(a))) return false;
  if (t.concerns.length && !t.concerns.every(c => prof.concerns.includes(c))) return false;
  return true;
};

/* ------------------------------ helpers ----------------------------- */
const sum = (a, f) => a.reduce((s, x) => s + f(x), 0);
const median = arr => { if (!arr.length) return 0; const s = arr.slice().sort((a,b)=>a-b); const m = Math.floor(s.length/2); return s.length%2 ? s[m] : (s[m-1]+s[m])/2; };
// nearest-rank percentile, exactly as the prompt specifies: s[round(p*(n-1))]
const pctile = (arr, p) => { if (!arr.length) return 0; const s = arr.slice().sort((a,b)=>a-b); return s[Math.min(s.length-1, Math.max(0, Math.round(p*(s.length-1))))]; };
const roasOf = list => { const sp = sum(list, a=>a.spend); return sp ? sum(list, a=>a.revenue)/sp : 0; };
const rupees = n => { // plain, readable
  if (n >= 1e7) return '₹' + (n/1e7).toFixed(2) + 'Cr';
  if (n >= 1e5) return '₹' + (n/1e5).toFixed(1) + 'L';
  return '₹' + Math.round(n).toLocaleString('en-IN');
};
const back = n => '₹' + n.toFixed(2);                         // "₹3.35" = rupees back per ₹1 spent
const pct = n => (n > 0 && n < 1 ? n.toFixed(1) : String(Math.round(n))) + '%';
const timesSeen = n => 'about ' + Math.round(n);
const ids = list => list.map(a => a.ad_id);

/* ------------------------------ load data --------------------------- */
function loadData() {
  const argv = process.argv.slice(2);
  const get = k => { const i = argv.indexOf(k); return i >= 0 ? argv[i+1] : null; };
  let data;
  if (get('--data')) {
    data = JSON.parse(fs.readFileSync(get('--data'), 'utf8'));
    if (Array.isArray(data)) data = { ads: data };
  } else {
    const htmlPath = get('--html') || path.join(__dirname, 'build/ci/creative-intelligence.html');
    const html = fs.readFileSync(htmlPath, 'utf8');
    const first = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1])[0];
    data = new Function(first + '\n;return DATA;')();
  }
  return { data, out: get('--out') || path.join(__dirname, 'insight_inputs.json') };
}

/* ------------------------------ rollups ----------------------------- */
function stageAngleRows(ads, stageDefs, totalSpend) {
  const rows = [];
  stageDefs.forEach(sd => {
    const groups = {};
    ads.forEach(ad => {
      const angle = ad.stages && ad.stages[sd.key];
      if (!angle) return;
      (groups[angle] = groups[angle] || []).push(ad);
    });
    Object.entries(groups).forEach(([angle, list]) => {
      const spend = sum(list, a=>a.spend); if (spend <= 0) return;
      const w = f => sum(list, a => a.spend * a[f]) / spend;
      rows.push({
        stage: sd.key, stageLabel: sd.label, angle, n: list.length, spend,
        spend_share_pct: totalSpend ? spend/totalSpend*100 : 0,
        revenue: sum(list, a=>a.revenue), roas: sum(list, a=>a.revenue)/spend,
        lpv_pct: w('lpv_pct'), atc_pct: w('atc_pct'), conv_pct: w('conv_pct'), frequency: w('frequency'), ads: list,
      });
    });
  });
  return rows;
}
const baselineOf = ads => ({
  n: ads.length, spend: sum(ads, a=>a.spend), revenue: sum(ads, a=>a.revenue), roas: roasOf(ads),
  medLpv: median(ads.map(a=>a.lpv_pct)), medAtc: median(ads.map(a=>a.atc_pct)), medConv: median(ads.map(a=>a.conv_pct)),
});

/* ------------------------------ main -------------------------------- */
function main() {
  const { data, out } = loadData();
  const stageDefs = data.stage_defs.filter(sd => !CFG.EXCLUDE_STAGES.includes(sd.key));
  const skuName = id => ((data.skus || []).find(s => s.id === id) || {}).name || id;
  const skuIdByName = nm => ((data.skus || []).find(s => s.name === nm) || {}).id;
  const referenced = new Set();     // product ids named by any candidate, for the pack's product_profiles

  // G1: zero / near-zero spend out of every pool and baseline
  const allAds = data.ads.map(a => ({ ...a, stages: Object.fromEntries(Object.entries(a.stages || {}).map(([k, v]) => [k, v && OFF_TOPIC.test(v) ? '' : v])) }));
  const ads = allAds.filter(a => a.spend >= 1);
  const base = baselineOf(ads);
  base.lpvW = sum(ads,a=>a.spend*a.lpv_pct)/base.spend; base.atcW = sum(ads,a=>a.spend*a.atc_pct)/base.spend; base.convW = sum(ads,a=>a.spend*a.conv_pct)/base.spend;
  const floor = Math.max(base.spend * CFG.FLOOR_PCT, CFG.FIXED_FLOOR);   // G2 (percentage AND fixed currency)
  const rows = stageAngleRows(ads, stageDefs, base.spend);

  const candidates = [];      // every candidate that passed numeric guardrails
  const unavailable = [];     // types that came back empty, with the plain reason
  const rejected = [];        // things that cleared ratio bars but failed an arithmetic guardrail

  /* ---------- TYPE 1: DO ---------- */
  {
    const c = CFG.DO;
    const ratioPool = (n, m) => rows.filter(r => r.n>=n && r.roas>=m*base.roas && r.spend_share_pct<c.maxShare);
    let pool = ratioPool(c.minN, c.roasMult), widened = false;
    // report what the fixed floor knocked out (so the model never resurrects it)
    ratioPool(c.minN, c.roasMult).filter(r => r.spend < floor).forEach(r => rejected.push({
      type:'do', guardrail:'G2 spend floor', label: `${r.stageLabel}: ${r.angle}`, n_ads:r.n,
      spend_display: rupees(r.spend), floor_display: rupees(floor),
      note:'Cleared the ratio bars but total spend is below the absolute floor. Do not use.' }));
    pool = pool.filter(r => r.spend >= floor);
    if (!pool.length) { pool = ratioPool(c.widenN, c.widenRoasMult).filter(r => r.spend >= floor); widened = true; }
    if (!pool.length) unavailable.push({ type:'do', reason:'No creative choice is both clearly above average and under-funded with enough real spend.' });
    else {
      pool.forEach(r => r._score = ((r.roas/base.roas)-1) * r.n);
      pool.sort((a,b) => b._score - a._score);
      pool.slice(0, 3).forEach((t, idx) => candidates.push({
        type:'do', fixed_slot: idx ? undefined : 1, score: +(((t.roas/base.roas)-1)*100*t.n).toFixed(1),
        stage_key: t.stage, stage_plain: STAGE_GLOSS[t.stage], angle_text: t.angle,
        display: {
          n_ads: String(t.n), return_per_rupee: back(t.roas), account_return_per_rupee: back(base.roas),
          better_than_account: Math.round((t.roas/base.roas-1)*100) + '%', budget_share: pct(t.spend_share_pct),
          spend: rupees(t.spend), other_qualifying_choices: String(pool.length-1),
        },
        evidence: { n_ads:t.n, spend:Math.round(t.spend), roas:+t.roas.toFixed(3), spend_share_pct:+t.spend_share_pct.toFixed(2), widened },
        choice_keys: [t.stage+'|'+t.angle],
        ad_ids: ids(t.ads),
        needs_judgment: ['obviousness_filter'],
      }));
    }
  }

  /* ---------- TYPE 2: STOP ---------- */
  {
    const c = CFG.STOP;
    const pool = rows.filter(r => r.spend_share_pct >= c.minShare);
    if (!pool.length) unavailable.push({ type:'stop', reason:'No creative choice takes 15% or more of spend, so nothing is big enough to flag.' });
    else {
      const peers = rows.filter(r => r.spend_share_pct >= c.freqPeerShare);
      const p75 = pctile(peers.map(r => r.frequency), 0.75);
      const peerMedFreq = median(peers.map(r => r.frequency));
      // wearing out only counts if, across the account, ads people have seen more often really do earn less than the rest
      const heavy = ads.filter(a => a.frequency >= CFG.FATIGUE.minTimesSeen), light = ads.filter(a => a.frequency < CFG.FATIGUE.minTimesSeen);
      const fatigueIsReal = heavy.length >= 5 && light.length >= 5 && roasOf(heavy) <= 0.95 * roasOf(light);
      let hit = (peers.length > 1 && fatigueIsReal) ? pool.filter(r => r.frequency >= p75 && r.roas >= base.roas && r.frequency >= CFG.FATIGUE.minTimesSeen && r.frequency >= CFG.FATIGUE.vsPeersMult*peerMedFreq).map(r => ({ r, kind:'fatigue' })) : [];
      if (!hit.length) {
        hit = pool.map(r => {
          if (r.lpv_pct >= base.medLpv*c.brokenHi && (r.atc_pct < base.medAtc*c.brokenLo || r.conv_pct < base.medConv*c.brokenLo))
            return { r, kind:'broken_stage', broken: r.atc_pct < base.medAtc*c.brokenLo ? 'people_click_but_do_not_add_to_cart' : 'people_add_to_cart_but_do_not_buy' };
          if (r.atc_pct >= base.medAtc*c.brokenHi && r.lpv_pct < base.medLpv*c.brokenLo)
            return { r, kind:'broken_stage', broken:'almost_nobody_clicks_through' };
          return null;
        }).filter(Boolean);
      }
      if (!hit.length) hit = pool.filter(r => r.roas <= c.dragMult*base.roas).map(r => ({ r, kind:'drag' }));
      if (!hit.length) unavailable.push({ type:'stop', reason:'Big-spend creative choices show no fatigue, no broken step and no drag.' });
      else {
        hit.sort((a,b) => b.r.spend_share_pct - a.r.spend_share_pct);
        const { r:t, kind, broken } = hit[0];
        const peerOthers = peers.filter(p => !(p.stage===t.stage && p.angle===t.angle));
        candidates.push({
          type:'stop', fixed_slot: 2, score: null, case: kind, broken_step: broken || null,
          stage_key: t.stage, stage_plain: STAGE_GLOSS[t.stage], angle_text: t.angle,
          display: {
            n_ads: String(t.n), budget_share: pct(t.spend_share_pct), return_per_rupee: back(t.roas),
            account_return_per_rupee: back(base.roas), times_seen_per_person: timesSeen(t.frequency),
            typical_times_seen_elsewhere: timesSeen(median(peerOthers.map(p=>p.frequency))), spend: rupees(t.spend),
          },
          evidence: { n_ads:t.n, spend:Math.round(t.spend), spend_share_pct:+t.spend_share_pct.toFixed(2), frequency:+t.frequency.toFixed(2), frequency_p75_of_peers:+p75.toFixed(2), roas:+t.roas.toFixed(3) },
          ad_ids: ids(t.ads),
          needs_judgment: ['obviousness_filter'],
        });
      }
    }
  }

  /* ---------- TYPE 3: CHEMISTRY ---------- */
  {
    const c = CFG.CHEM;
    const solo = {}; rows.forEach(r => { solo[r.stage+'|'+r.angle] = r.roas; });
    const groups = {};
    for (let i = 0; i < stageDefs.length; i++) for (let j = i+1; j < stageDefs.length; j++) {
      const a = stageDefs[i], b = stageDefs[j];
      ads.forEach(ad => {
        const va = ad.stages[a.key], vb = ad.stages[b.key]; if (!va || !vb) return;
        const k = a.key+'='+va+'|'+b.key+'='+vb;
        (groups[k] = groups[k] || { sa:a, va, sb:b, vb, list:[] }).list.push(ad);
      });
    }
    let pairs = Object.values(groups).map(g => {
      const spend = sum(g.list, x=>x.spend); const soloA = solo[g.sa.key+'|'+g.va]||0, soloB = solo[g.sb.key+'|'+g.vb]||0;
      return { ...g, spend, n:g.list.length, pairRoas: spend ? sum(g.list,x=>x.revenue)/spend : 0, soloA, soloB, expected: Math.max(soloA, soloB) };
    }).filter(g => g.n >= c.minN && g.spend >= floor && g.expected > 0);
    let q = pairs.filter(g => g.pairRoas >= c.strongMult*g.expected), widened = false;
    if (!q.length) { q = pairs.filter(g => g.pairRoas >= c.widenMult*g.expected); widened = true; }
    if (!q.length) unavailable.push({ type:'chemistry', reason:'No two creative choices that appear together beat the stronger of the two on their own by enough.' });
    else {
      q.forEach(g => g._s = (g.pairRoas/g.expected-1)*g.n);
      q.sort((a,b) => b._s - a._s);
      q.slice(0, 3).forEach(t => {
      const uplift = Math.round((t.pairRoas/t.expected-1)*100);
      candidates.push({
        type:'chemistry', score: +(uplift*t.n).toFixed(1),
        part_a: { stage_key:t.sa.key, stage_plain:STAGE_GLOSS[t.sa.key], angle_text:t.va },
        part_b: { stage_key:t.sb.key, stage_plain:STAGE_GLOSS[t.sb.key], angle_text:t.vb },
        display: {
          n_ads: String(t.n), pair_return_per_rupee: back(t.pairRoas), part_a_alone_return_per_rupee: back(t.soloA),
          part_b_alone_return_per_rupee: back(t.soloB), better_than_stronger_part: uplift + '%', spend: rupees(t.spend),
        },
        evidence: { n_ads:t.n, spend:Math.round(t.spend), pair_roas:+t.pairRoas.toFixed(3), solo_a:+t.soloA.toFixed(3), solo_b:+t.soloB.toFixed(3), widened },
        ad_ids: ids(t.list),
        needs_judgment: ['obviousness_filter'],
      });
      });
    }
  }

  /* ---------- non-combo base for cross-product types (4, 5) ---------- */
  const single = ads.filter(a => !a.is_multi_sku && a.skus.length === 1);
  const bySku = {}; single.forEach(a => (bySku[a.skus[0]] = bySku[a.skus[0]] || []).push(a));
  const catOf = {};
  Object.entries(bySku).forEach(([sku, list]) => {
    const c = {}; list.forEach(a => { if (a.category) c[a.category] = (c[a.category]||0)+1; });
    const k = Object.keys(c); catOf[sku] = k.length ? k.sort((x,y)=>c[y]-c[x])[0] : null;
  });

  /* ---------- TYPE 4: WHITESPACE ---------- */
  {
    const c = CFG.WS; const pairs = [];
    Object.entries(bySku).forEach(([src, srcAds]) => {
      const sb = baselineOf(srcAds), sRows = stageAngleRows(srcAds, stageDefs, sb.spend);
      sRows.filter(r => r.n >= c.minSourceN && r.roas >= c.roasMult*sb.roas && r.spend >= floor).forEach(r => {
        Object.entries(bySku).forEach(([tgt, tgtAds]) => {
          if (tgt === src || !catOf[tgt] || catOf[tgt] !== catOf[src]) return;
          if (!fitsProduct(r.angle, tgt)) { rejected.push({ type:'whitespace', guardrail:'G7 semantic mismatch', label:`${r.stageLabel}: ${r.angle}`, from_product: skuName(src), to_product: skuName(tgt),
            note:`This creative choice speaks to something ${skuName(tgt)} (${PRODUCT_PROFILES[tgt] ? PRODUCT_PROFILES[tgt].what : 'this product'}) does not address. Never suggest it for that product.` }); return; }
          const onAngle = tgtAds.filter(a => a.stages[r.stage] === r.angle).length;
          if (onAngle > c.maxTargetN) return;
          const up = (r.roas/sb.roas-1)*100;
          pairs.push({ src, tgt, r, up, onAngle, tgtTotal: tgtAds.length, category: catOf[src], _s: up*r.n - onAngle*1000 });
        });
      });
    });
    if (!pairs.length) unavailable.push({ type:'whitespace', reason:'No proven creative choice is untested on a sibling product in the same category.' });
    else {
      // one candidate per (source product, creative choice); every possible target product listed inside it,
      // so the model can reject individual targets on G3 without any recompute
      const grp = {};
      pairs.forEach(p => { const k = p.src+'|'+p.r.stage+'|'+p.r.angle; (grp[k] = grp[k] || { head:p, targets:[] }).targets.push(p); });
      Object.values(grp).sort((a,b) => b.head.up*b.head.r.n - a.head.up*a.head.r.n).slice(0, 4).forEach(g => {
        const p = g.head;
        g.targets.sort((x,y) => x.onAngle - y.onAngle || y.tgtTotal - x.tgtTotal);
        candidates.push({
          type:'whitespace', score: +(p.up*p.r.n).toFixed(1),
          stage_key: p.r.stage, stage_plain: STAGE_GLOSS[p.r.stage], angle_text: p.r.angle,
          source_product: skuName(p.src), category: p.category,
          display: {
            n_ads: String(p.r.n), return_per_rupee: back(p.r.roas),
            better_than_that_products_own_average: Math.round(p.up) + '%', spend: rupees(p.r.spend),
          },
          possible_targets: g.targets.slice(0, 4).map(t => ({
            target_product: skuName(t.tgt),
            framing: t.tgtTotal < c.coldStartBelow ? 'cold_start' : 'whitespace',
            target_product_total_ads: String(t.tgtTotal), target_product_ads_using_it: String(t.onAngle),
          })),
          evidence: { n_ads:p.r.n, spend:Math.round(p.r.spend), roas:+p.r.roas.toFixed(3) },
          ad_ids: ids(p.r.ads),
          needs_judgment: ['G3_product_fit: for EACH possible target, read angle_text against that target product. Drop any target whose real use-case the angle does not fit. If every target is dropped, drop the whole candidate and move to the next.', 'obviousness_filter'],
        });
      });
    }
  }

  /* ---------- TYPE 5: PORTFOLIO TRUTH ---------- */
  {
    const c = CFG.PT;
    const pooled = stageAngleRows(single, stageDefs, sum(single, a=>a.spend));
    const topAngles = pooled.filter(r => r.spend_share_pct >= c.minShare).sort((a,b)=>b.roas-a.roas).slice(0, c.topK)
      .map(r => ({ type:'angle', stage:r.stage, label:r.angle, roas:r.roas, share:r.spend_share_pct, n:r.n, test: list => list.filter(a => a.stages[r.stage] === r.angle) }));
    let topApproach = [];
    if (!CFG.EXCLUDE_APPROACH_TYPES) {
      const ag = {}; single.forEach(a => { if (a.approach) (ag[a.approach] = ag[a.approach] || []).push(a); });
      const singleSpend = sum(single, a=>a.spend) || 1;
      topApproach = Object.entries(ag).map(([name, list]) => ({ name, n:list.length, roas:roasOf(list), share:sum(list,a=>a.spend)/singleSpend*100 }))
        .filter(g => g.share >= c.minShare).sort((a,b)=>b.roas-a.roas).slice(0, c.topK)
        .map(g => ({ type:'approach', stage:null, label:g.name, roas:g.roas, share:g.share, n:g.n, test: list => list.filter(a => a.approach === g.name) }));
    }
    const confirmed = [], debunked = [];
    topAngles.concat(topApproach).forEach(cand => {
      const res = Object.entries(bySku).map(([sku, skuAds]) => {
        if (skuAds.length < c.minSkuAds) return null;
        const m = cand.test(skuAds); if (m.length < c.minPatternAds) return null;
        const roas = roasOf(m), own = roasOf(skuAds);
        return { product: skuName(sku), roas, own, holds: roas >= c.holdsMult*own, spend: sum(m, a=>a.spend) };
      }).filter(Boolean);
      if (!res.length) return;
      const holds = res.filter(r => r.holds).length, testable = res.length;
      if (holds >= c.confirmFrac*testable && testable >= c.minTestable) confirmed.push({ ...cand, res, holds, testable });
      else if (holds <= c.debunkFrac*testable && testable >= c.minTestable) debunked.push({ ...cand, res, holds, testable });
    });
    const pick = debunked.length ? ['debunked', debunked] : confirmed.length ? ['confirmed', confirmed] : null;
    if (!pick) unavailable.push({ type:'portfolio_truth', reason:'Top pooled patterns give a mixed picture across products, so no clear confirm or debunk.' });
    else {
      const [verdict, list] = pick; list.sort((a,b)=>b.share-a.share); const t = list[0];
      const carrying = t.res.filter(r=>r.holds).sort((a,b)=>b.spend-a.spend).slice(0,2).map(r=>r.product);
      candidates.push({
        type:'portfolio_truth', verdict, score: +(t.share*(verdict==='debunked'?25:10)).toFixed(1),
        subject_kind: t.type,
        stage_key: t.stage, stage_plain: t.stage ? STAGE_GLOSS[t.stage] : null,
        angle_text: t.type==='angle' ? t.label : null,
        approach_name: t.type==='approach' ? t.label : null,
        approach_plain: t.type==='approach' ? (APPROACH_GLOSS[t.label] || null) : null,
        display: {
          overall_return_per_rupee: back(t.roas), overall_budget_share: pct(t.share),
          holds_in: `${t.holds} of ${t.testable}`, products_tested: String(t.testable), products_where_it_holds: String(t.holds),
          products_carrying_it: carrying,
        },
        per_product: t.res.map(r => ({ product:r.product, return_per_rupee:back(r.roas), own_average_return_per_rupee:back(r.own), holds:r.holds })),
        evidence: { pooled_roas:+t.roas.toFixed(3), pooled_share_pct:+t.share.toFixed(2), holds:t.holds, testable:t.testable },
        ad_ids: ids(t.type==='approach' ? single.filter(a => a.approach===t.label) : single.filter(a => a.stages[t.stage]===t.label)),
        needs_judgment: ['obviousness_filter'],
      });
    }
  }

  /* ---------- TYPE 6: APPROACH ALIGNMENT (excluded by editorial rule) ---------- */
  if (CFG.EXCLUDE_APPROACH_TYPES) {
    unavailable.push({ type:'approach_alignment', reason:'Excluded by rule: broad pitch styles (lead with product, offer, brand) are things a marketer already knows. Never write about them.' });
  } else {
    const c = CFG.AA;
    const g = {}; ads.forEach(a => { if (a.approach) (g[a.approach] = g[a.approach] || []).push(a); });
    const tbl = Object.entries(g).map(([name, list]) => ({ name, n:list.length, spend:sum(list,a=>a.spend), share:sum(list,a=>a.spend)/base.spend*100, roas:roasOf(list), ads:list }));
    const dom = tbl.slice().sort((a,b)=>b.share-a.share)[0];
    const best = tbl.filter(r=>r.n>=c.minBestN).sort((a,b)=>b.roas-a.roas)[0];
    if (!dom || !best) unavailable.push({ type:'approach_alignment', reason:'Not enough ads per pitch style to compare.' });
    else if (best.name === dom.name) unavailable.push({ type:'approach_alignment', reason:'Your biggest pitch style by spend is also your best performer.' });
    else if (!(dom.share >= c.minDominantShare && best.roas >= c.gapMult*dom.roas)) unavailable.push({ type:'approach_alignment', reason:`Dominant pitch style takes ${pct(dom.share)} of budget at ${back(dom.roas)} back per ₹1; best performer gets ${back(best.roas)}. Gap is too small to act on.` });
    else candidates.push({
      type:'approach_alignment', score: +(((best.roas/dom.roas)-1)*100*best.n).toFixed(1),
      dominant: { approach_name:dom.name, approach_plain:APPROACH_GLOSS[dom.name], budget_share:pct(dom.share), return_per_rupee:back(dom.roas), n_ads:String(dom.n) },
      best_performing: { approach_name:best.name, approach_plain:APPROACH_GLOSS[best.name], budget_share:pct(best.share), return_per_rupee:back(best.roas), n_ads:String(best.n) },
      display: { better_by: Math.round((best.roas/dom.roas-1)*100)+'%' },
      evidence: { dominant_share_pct:+dom.share.toFixed(2), dominant_roas:+dom.roas.toFixed(3), best_roas:+best.roas.toFixed(3) },
      ad_ids: ids(best.ads), needs_judgment: ['obviousness_filter'],
    });
  }

  /* ---------- TYPE 7: UNDERUSED STAGE ---------- */
  {
    const c = CFG.US;
    const hits = stageDefs.map(sd => {
      const list = ads.filter(a => a.stages[sd.key]); const presence = list.length/ads.length*100;
      if (presence > c.maxPresencePct || list.length < c.minN) return null;
      const roas = roasOf(list); if (roas < c.roasMult*base.roas) return null;
      return { sd, list, presence, roas, up: (roas/base.roas-1)*100 };
    }).filter(Boolean).sort((a,b) => b.up - a.up || a.list.length - b.list.length);
    if (!hits.length) unavailable.push({ type:'underused_stage', reason:'No rarely-used part of an ad clearly beats the account average.' });
    else {
      const t = hits[0];
      candidates.push({
        type:'underused_stage', score: +(t.up*t.list.length).toFixed(1),
        stage_key: t.sd.key, stage_plain: STAGE_GLOSS[t.sd.key],
        display: { n_ads_using_it: String(t.list.length), total_ads: String(ads.length), return_per_rupee: back(t.roas), account_return_per_rupee: back(base.roas), better_than_account: Math.round(t.up)+'%' },
        evidence: { presence_pct:+t.presence.toFixed(2), roas:+t.roas.toFixed(3) },
        ad_ids: ids(t.list), needs_judgment: ['obviousness_filter'],
      });
    }
  }


  /* ---------- TYPE 8: FUNNEL LEAK (hook gets the click, then people do not buy) ---------- */
  {
    const c = CFG.FL;
    const hits = rows.filter(r => r.spend >= c.minSpend && r.n >= c.minN && r.roas < base.roas
        && r.lpv_pct >= c.lpvMult*base.lpvW && (r.atc_pct < c.leakMult*base.atcW || r.conv_pct < c.convLeakMult*base.convW))
      .sort((a,b) => b.spend - a.spend);
    if (!hits.length) unavailable.push({ type:'funnel_leak', reason:'No big-spend creative choice gets clicks but loses people before they add to cart or buy.' });
    else {
      hits.slice(0, 3).forEach((t, idx) => {
      const leakAtCart = t.atc_pct < c.leakMult*base.atcW;
      candidates.push({
        type:'funnel_leak', fixed_slot: idx ? undefined : 2, score: +(t.spend/1000).toFixed(1), case: leakAtCart ? 'people_click_but_do_not_add_to_cart' : 'people_add_to_cart_but_do_not_buy',
        stage_key: t.stage, stage_plain: STAGE_GLOSS[t.stage], angle_text: t.angle,
        display: {
          n_ads: String(t.n), spend: rupees(t.spend), budget_share: pct(t.spend_share_pct),
          return_per_rupee: back(t.roas), account_return_per_rupee: back(base.roas),
          clicks_vs_account: Math.round((t.lpv_pct/base.lpvW-1)*100) + '% more people click through than average',
          cart_vs_account: Math.round((1-t.atc_pct/base.atcW)*100) + '% fewer people add to cart than average',
          buy_vs_account: Math.round((1-t.conv_pct/base.convW)*100) + '% fewer people go on to buy than average',
        },
        evidence: { n_ads:t.n, spend:Math.round(t.spend), roas:+t.roas.toFixed(3), lpv_ratio:+(t.lpv_pct/base.lpvW).toFixed(3), atc_ratio:+(t.atc_pct/base.atcW).toFixed(3), conv_ratio:+(t.conv_pct/base.convW).toFixed(3) },
        leak_step_plain: leakAtCart ? 'add to cart' : 'buy',
        action_hint: leakAtCart
          ? 'Test a clearer product page for these ads, one that shows the product, its benefit and the price sooner, and keep the opening.'
          : 'Test a simpler checkout for these ads, with price, delivery and payment options clear sooner, and keep the opening.',
        choice_keys: [t.stage+'|'+t.angle],
        ad_ids: ids(t.ads),
        needs_judgment: ['obviousness_filter'],
      });
      });
    }
  }

  /* ---------- TYPE 9: PRODUCT SPLIT (same creative choice, different result by product) ---------- */
  {
    const c = CFG.PS;
    const found = [];
    stageDefs.forEach(sd => {
      const groups = {};
      single.forEach(a => { const v = a.stages[sd.key]; if (v) (groups[v] = groups[v] || []).push(a); });
      Object.entries(groups).forEach(([angle, list]) => {
        const by = {};
        list.forEach(a => { const nm = skuName(a.skus[0]); (by[nm] = by[nm] || []).push(a); });
        const parts = Object.entries(by).map(([name, l]) => ({ name, id: l[0].skus[0], l, n:l.length, spend:sum(l,a=>a.spend), roas:roasOf(l), own: roasOf(single.filter(a => skuName(a.skus[0]) === name)) }))
          .filter(p => p.n >= c.minN && p.spend >= c.minSpend)
          .filter(p => { const ok = fitsProduct(angle, p.id); if (!ok) rejected.push({ type:'product_split', guardrail:'G7 semantic mismatch', label:`${sd.label}: ${angle}`, product: p.name, note:`This creative choice speaks to something ${p.name} does not address, so it is never compared on that product.` }); return ok; });
        parts.forEach(hi => parts.forEach(lo => {
          if (hi === lo || hi.roas < c.betterMult*lo.roas) return;
          found.push({ sd, angle, hi, lo, ratio: hi.roas/lo.roas, times: lo.spend/hi.spend });
        }));
      });
    });
    // case A: the better product is starved while the weaker one soaks up the budget
    // moving budget between two products only makes sense when they serve the same need (they share a concern)
    // comparing a hair product with a skin product is explained by the products themselves, so both cases need the same body area
    const sameArea = (a, b) => { const pa = PRODUCT_PROFILES[a.id], pb = PRODUCT_PROFILES[b.id]; return !!(pa && pb && pa.areas.some(x => pb.areas.includes(x))); };
    const sameNeed = (a, b) => { const pa = PRODUCT_PROFILES[a.id], pb = PRODUCT_PROFILES[b.id]; return !!(pa && pb && pa.concerns.some(x => pb.concerns.includes(x))); };
    const starved = found.filter(f => sameArea(f.hi, f.lo) && sameNeed(f.hi, f.lo)).filter(f => f.times >= c.budgetTimes).sort((a,b) => (b.ratio-1)*b.hi.n - (a.ratio-1)*a.hi.n);
    // case B: it clearly works in one product and clearly drags in another, both with real money behind them
    const works = found.filter(f => sameArea(f.hi, f.lo) && f.hi.spend >= c.bothMinSpend && f.lo.spend >= c.bothMinSpend && f.ratio >= c.worksMult && f.lo.roas < f.lo.own).sort((a,b) => (b.ratio-1)*b.lo.n - (a.ratio-1)*a.lo.n);
    const mk = (f, kind) => ({
      type:'product_split', case: kind, score: +(((f.ratio-1)*100)*(kind==='budget_mismatch' ? f.hi.n : f.lo.n)).toFixed(1),
      stage_key: f.sd.key, stage_plain: STAGE_GLOSS[f.sd.key], angle_text: f.angle,
      display: {
        better_product: f.hi.name, better_product_return_per_rupee: back(f.hi.roas), better_product_n_ads: String(f.hi.n), better_product_spend: rupees(f.hi.spend),
        weaker_product: f.lo.name, weaker_product_return_per_rupee: back(f.lo.roas), weaker_product_n_ads: String(f.lo.n), weaker_product_spend: rupees(f.lo.spend),
        weaker_product_own_average_return_per_rupee: back(f.lo.own),
        weaker_gets_times_the_budget: 'about ' + Math.round(f.times) + ' times',
      },
      evidence: { hi_roas:+f.hi.roas.toFixed(3), lo_roas:+f.lo.roas.toFixed(3), hi_spend:Math.round(f.hi.spend), lo_spend:Math.round(f.lo.spend), hi_n:f.hi.n, lo_n:f.lo.n },
      choice_keys: [f.sd.key+'|'+f.angle],
      products_involved: [f.hi.id, f.lo.id],
      ad_ids: ids(f.hi.l.concat(f.lo.l)),
      needs_judgment: ['obviousness_filter', 'product_logic: would a marketer already expect this choice to suit one of the two products better than the other? If the difference is plainly explained by what the products are, drop it.'],
    });
    const seen = new Set();
    [['budget_mismatch', starved], ['works_here_not_there', works]].forEach(([kind, list]) => {
      list.forEach(f => { const k = kind+f.sd.key+f.angle; if (seen.has(k)) return; seen.add(k); if (candidates.filter(x => x.type==='product_split' && x.case===kind).length < 2) candidates.push(mk(f, kind)); });
    });
    if (!starved.length && !works.length) unavailable.push({ type:'product_split', reason:'No creative choice shows a clear, well-funded difference between products.' });
  }


  /* ---------- TYPE 10: QUIET CONVERTER (fewer clicks, but the people who click buy more) ---------- */
  {
    const c = CFG.QC;
    const hits = rows.filter(r => r.n >= c.minN && r.spend >= floor && r.spend_share_pct >= c.minShare
        && r.lpv_pct <= c.lpvMax*base.lpvW && r.conv_pct >= c.convMin*base.convW && r.roas >= c.roasMin*base.roas)
      .sort((a,b) => (b.conv_pct/base.convW-1)*b.n - (a.conv_pct/base.convW-1)*a.n);
    if (!hits.length) unavailable.push({ type:'quiet_converter', reason:'No creative choice gets noticeably fewer clicks but clearly more buyers per click.' });
    else hits.slice(0, 2).forEach(t => candidates.push({
      type:'quiet_converter', score: +(((t.conv_pct/base.convW)-1)*100*t.n).toFixed(1),
      stage_key: t.stage, stage_plain: STAGE_GLOSS[t.stage], angle_text: t.angle,
      display: {
        n_ads: String(t.n), spend: rupees(t.spend), budget_share: pct(t.spend_share_pct),
        return_per_rupee: back(t.roas), account_return_per_rupee: back(base.roas),
        clicks_vs_account: Math.round((1-t.lpv_pct/base.lpvW)*100) + '% fewer people click through than average',
        buy_vs_account: Math.round((t.conv_pct/base.convW-1)*100) + '% more people go on to buy than average',
      },
      evidence: { n_ads:t.n, spend:Math.round(t.spend), roas:+t.roas.toFixed(3), lpv_ratio:+(t.lpv_pct/base.lpvW).toFixed(3), conv_ratio:+(t.conv_pct/base.convW).toFixed(3) },
      action_hint: 'Keep these ads running and judge them on sales, not clicks. Test a more eye-catching opening that keeps the same claim.',
      choice_keys: [t.stage+'|'+t.angle],
      ad_ids: ids(t.ads),
      needs_judgment: ['obviousness_filter'],
    }));
  }

  /* ---------- TYPE 11: CLASH (two choices that do worse together than the weaker one alone) ---------- */
  {
    const c = CFG.CL;
    const solo2 = {}; rows.forEach(r => { solo2[r.stage+'|'+r.angle] = r.roas; });
    const grp = {};
    for (let i = 0; i < stageDefs.length; i++) for (let j = i+1; j < stageDefs.length; j++) {
      const a = stageDefs[i], b = stageDefs[j];
      ads.forEach(ad => { const va = ad.stages[a.key], vb = ad.stages[b.key]; if (!va || !vb) return;
        const k = a.key+'='+va+'|'+b.key+'='+vb; (grp[k] = grp[k] || { sa:a, va, sb:b, vb, list:[] }).list.push(ad); });
    }
    const bad = Object.values(grp).map(g => { const spend = sum(g.list,x=>x.spend); const soloA = solo2[g.sa.key+'|'+g.va]||0, soloB = solo2[g.sb.key+'|'+g.vb]||0;
        return { ...g, spend, n:g.list.length, pairRoas: spend ? sum(g.list,x=>x.revenue)/spend : 0, soloA, soloB, worst: Math.min(soloA, soloB) }; })
      .filter(g => g.n >= c.minN && g.spend >= floor && g.worst > 0 && g.pairRoas <= c.dragMult*g.worst)
      .sort((a,b) => (b.worst/b.pairRoas-1)*b.n - (a.worst/a.pairRoas-1)*a.n);
    if (!bad.length) unavailable.push({ type:'clash', reason:'No two creative choices do clearly worse together than the weaker one does alone.' });
    else bad.slice(0, 2).forEach(t => candidates.push({
      type:'clash', score: +(((t.worst/t.pairRoas)-1)*100*t.n).toFixed(1),
      part_a: { stage_key:t.sa.key, stage_plain:STAGE_GLOSS[t.sa.key], angle_text:t.va },
      part_b: { stage_key:t.sb.key, stage_plain:STAGE_GLOSS[t.sb.key], angle_text:t.vb },
      display: { n_ads:String(t.n), pair_return_per_rupee: back(t.pairRoas), part_a_alone_return_per_rupee: back(t.soloA), part_b_alone_return_per_rupee: back(t.soloB), spend: rupees(t.spend) },
      evidence: { n_ads:t.n, spend:Math.round(t.spend), pair_roas:+t.pairRoas.toFixed(3), solo_a:+t.soloA.toFixed(3), solo_b:+t.soloB.toFixed(3) },
      ad_ids: ids(t.list),
      needs_judgment: ['obviousness_filter', 'sense: do the two choices contradict each other in the ad (for example one says the product is gentle, the other says it is strong)? If the clash is just two unrelated ideas, drop it.'],
    }));
  }

  /* ---------- assembly: DO, then the leak/stop findings, then the strongest of the rest ---------- */
  // every candidate carries the creative choices it rests on, so two cards never lean on the same choice
  candidates.forEach(c => {
    if (c.choice_keys) return;
    const keys = [];
    if (c.stage_key && c.angle_text) keys.push(c.stage_key + '|' + c.angle_text);
    if (c.part_a) keys.push(c.part_a.stage_key + '|' + c.part_a.angle_text);
    if (c.part_b) keys.push(c.part_b.stage_key + '|' + c.part_b.angle_text);
    c.choice_keys = keys;
  });
  // TIER 1 = the basic, most direct findings. They fill the feed first and are tried first as substitutes.
  // TIER 2 = the more specialised ones. They only appear when tier 1 cannot fill the feed.
  const TIER = { do:1, funnel_leak:1, stop:1, product_split:1, chemistry:1, quiet_converter:2, clash:2, whitespace:2, portfolio_truth:2, underused_stage:2, approach_alignment:9 };
  candidates.forEach(c => { c.tier = TIER[c.type] || 2; });
  const fixed = ['do','funnel_leak','stop'].map(t => candidates.find(c => c.type === t)).filter(Boolean);
  const used = new Set(); fixed.forEach(c => c.choice_keys.forEach(k => used.add(k)));
  const rest = [], overlapping = [];
  candidates.filter(c => !fixed.includes(c)).sort((a,b) => (a.tier - b.tier) || (b.score - a.score)).forEach(c => {
    if (c.choice_keys.some(k => used.has(k))) { overlapping.push(c); return; }   // would repeat a creative choice a stronger card already uses
    c.choice_keys.forEach(k => used.add(k)); rest.push(c);
  });
  rest.forEach((c, i) => { c.rank_among_rest = i + 1; });
  const TOTAL = 4;
  // variety: the main feed shows at most one card per type (two for product splits), so one kind of finding never crowds out the rest;
  // the extra candidates of a type become the first substitutes
  const slotsLeft = Math.max(0, TOTAL - fixed.length), perType = {}; fixed.forEach(c => { perType[c.type] = (perType[c.type] || 0) + 1; });
  const picked = [], leftovers = [];
  rest.forEach(c => { const cap = c.type === 'product_split' ? 2 : 1; if (picked.length < slotsLeft && (perType[c.type] || 0) < cap) { picked.push(c); perType[c.type] = (perType[c.type] || 0) + 1; } else leftovers.push(c); });
  while (picked.length < slotsLeft && leftovers.length) picked.push(leftovers.shift());   // not enough variety available: fill with the strongest extras
  picked.sort((a, b) => (a.tier - b.tier) || (b.score - a.score));
  const suggested = fixed.concat(picked);
  let reserve = leftovers.slice(0, CFG.RESERVE + 2);
  // candidates that overlap a chosen card stay available, but only as a substitute for the card they overlap
  overlapping.forEach(c => { c.use_only_if_dropped = suggested.concat(reserve).filter(x => x.choice_keys.some(k => c.choice_keys.includes(k))).map(x => x.type + '|' + x.choice_keys.join(',')); });
  reserve = reserve.concat(overlapping.slice(0, CFG.RESERVE));
  const label = (c, i) => { c.id = c.type + '_' + (i + 1); return c; };
  suggested.concat(reserve).forEach(label);
  // express use_only_if_dropped with real candidate ids
  overlapping.forEach(c => { if (!c.use_only_if_dropped) return; const hit = suggested.concat(reserve).filter(x => x !== c && x.choice_keys.some(k => c.choice_keys.includes(k)) && suggested.includes(x)); c.use_only_if_dropped = hit.map(x => x.id); });
  const slots = suggested.length;

  const profiles = {};
  suggested.concat(reserve).forEach(c => {
    (c.products_involved || []).concat((c.possible_targets || []).map(t => skuIdByName(t.target_product))).concat(c.source_product ? [skuIdByName(c.source_product)] : []).filter(Boolean).forEach(id => { if (PRODUCT_PROFILES[id]) profiles[skuName(id)] = { what_it_is: PRODUCT_PROFILES[id].what, serves_area: PRODUCT_PROFILES[id].areas, serves_concerns: PRODUCT_PROFILES[id].concerns }; });
  });
  const pack = {
    _readme: 'Everything in here is already computed. Do not calculate, round, convert or re-derive any number. Quote only the *_display strings, exactly as written. Run only the judgment checks listed in needs_judgment, then write.',
    dataset: {
      ads_with_spend: String(ads.length), total_spend: rupees(base.spend),
      account_return_per_rupee: back(base.roas), account_return_meaning: 'For every ₹1 spent across the whole account, this many rupees came back.',
      spend_floor_applied: rupees(floor), currency: '₹',
    },
    product_profiles: profiles,
    suggested_order: suggested.map(c => c.id),
    reserve_order: reserve.map(c => c.id),
    candidates: suggested.concat(reserve),
    unavailable_types: unavailable,
    rejected_by_guardrail: rejected,
    _meta: { slots_target: 4, slots_possible: Math.min(4, slots), generated_by: 'build_insight_inputs.js' },
  };
  fs.writeFileSync(out, JSON.stringify(pack, null, 2));
  console.log('wrote', out);
  console.log('suggested order:', pack.suggested_order.join(', '));
  console.log('reserve:', pack.reserve_order.join(', ') || '(none)');
  console.log('unavailable:', unavailable.map(u => u.type).join(', ') || '(none)');
  console.log('rejected by guardrail:', rejected.length);
}
main();
