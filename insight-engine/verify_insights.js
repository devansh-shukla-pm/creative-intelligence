#!/usr/bin/env node
/* Checks generated insights against (1) the pre-computed pack: every number quoted must be a
   *_display value from that card's own candidate, and (2) the plain-language rules. */
const fs = require('fs');
const pack = require(require('path').resolve(process.argv[3] || './insight_inputs.json'));
const gen = require(process.argv[2] || './generated_insights.json');
const byId = Object.fromEntries(pack.candidates.map(c => [c.id, c]));
const strip = t => t.replace(/<[^>]+>/g, '');
const words = t => strip(t).trim().split(/\s+/).filter(Boolean).length;
const sentences = t => strip(t).split(/(?<=[.!?])\s+/).filter(Boolean);
const collect = (o, acc) => { if (o == null) return acc; if (typeof o === 'string') acc.push(o); else if (typeof o === 'object') Object.values(o).forEach(v => collect(v, acc)); return acc; };
const BAN = [/the (weaker|stronger|better|other) (product|one)\b/i,/\bthis (product|choice|idea)\b/i,/push (product|problem|offer|brand|differentiation)/i,/lead(s|ing)? with the product/i,/\bCTA\b|call to action|closing line|how it closes|shop now/i,/deal-led|brand-first|offer-led|product-first|pitch style/i,/roas/i,/frequency/i,/funnel/i,/\bLPV\b/,/\bATC\b/,/baseline/i,/\bSKU\b/i,/pooled/i,/portfolio/i,/uplift/i,/outperform/i,/\bangle\b/i,/\bstage\b/i,/approach/i,/\bbrief\b/i,/\bfund\b/i,/materiality|mechanism|cohort|leverage|optimi[sz]e|net-new|lever\b/i,/—|–|--/];
let bad = 0;
gen.insights.forEach((c, i) => {
  const cand = byId[c.candidate_id]; const probs = [];
  if (!cand) { probs.push('unknown candidate_id ' + c.candidate_id); }
  else {
    const TOK = /₹\d[\d,]*(?:\.\d+)?[LCr]*|\d+(?:\.\d+)?%|\d+(?:\.\d+)?/g;
    const norm = t => t.replace(/[.,]+$/, '');
    const allowed = new Set();
    [...collect(cand.display, []), ...collect(cand.possible_targets, []), ...collect(cand.per_product, []), ...collect(pack.dataset, [])].forEach(str => (str.match(TOK) || []).forEach(t => allowed.add(norm(t))));
    // "about 3" style values are quoted from the pack; instruction counts in the action ("3 more ads") are the writer's own ask, not data
    // a count of new ads to make is the writer's recommendation, not data: 1 to 5 before 'ads'/'versions' in the action is allowed
    const actionClean = strip(c.action).replace(/\b\d+ more\b/g, 'N more').replace(/\b[1-5]\b(?=(?: [\w-]+){0,3} (?:ads|versions|creatives)\b)/g, 'N');
    const text = strip(c.headline + ' ' + c.body) + ' ' + actionClean;
    (text.match(TOK) || []).map(norm).forEach(n => { if (!allowed.has(n)) probs.push('number "' + n + '" is not in the pack for ' + c.candidate_id); });
    if (JSON.stringify(c.ad_ids) !== JSON.stringify(cand.ad_ids)) probs.push('ad_ids differ from the pack');
  }

  if (cand && cand.type === 'product_split' && cand.case === 'budget_mismatch' && !/budget/i.test(strip(c.headline))) probs.push('budget_mismatch headline must say where the budget sits');
  if (cand && cand.type === 'product_split') {
    const need = [cand.display.better_product, cand.display.weaker_product].map(n => n.toLowerCase().replace(/ \/ hair dye| up powder$/,'').replace('touch up','touch-up'));
    const h = strip(c.headline).toLowerCase();
    need.forEach((n, k) => { const key = n.split(' ')[0]; if (!h.includes(key)) probs.push('headline does not name both products (missing "' + n + '")'); });
  }
  if (words(c.headline) > 14) probs.push('headline ' + words(c.headline) + ' words');
  const ss = sentences(c.body); if (ss.length > 2) probs.push('body has ' + ss.length + ' sentences');
  ss.forEach(x => { if (words(x) > 20) probs.push('body sentence ' + words(x) + ' words'); });
  if (words(c.action) > 25) probs.push('action ' + words(c.action) + ' words');
  if ((c.body.match(/<b>/g) || []).length > 1) probs.push('more than one bold');
  if (!/^(Make|Move|Stop|Keep|Test|Replace|Swap|Ask|Try|Change|Fix|Cut|Add|Show|Use|Pause|Shift|Split|Drop|Reduce|Raise|Build|Write|Create|Run|Put|Judge|Stop|Keep)\b/.test(c.action)) probs.push('action not verb-first');
  ['headline','body','action'].forEach(f => BAN.forEach(r => { if (r.test(strip(c[f]))) probs.push(f + ' contains ' + r); }));
  console.log('Insight', i + 1, c.source_type, '(' + c.candidate_id + ') :', probs.length ? 'PROBLEMS: ' + probs.join('; ') : 'ok'); bad += probs.length;
});
console.log(bad ? 'FAILED with ' + bad + ' problem(s)' : 'ALL CHECKS PASSED');
process.exit(bad ? 1 : 0);
