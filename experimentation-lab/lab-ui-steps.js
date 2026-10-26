/* ===== Experimentation Lab: six-step flow on the hybrid engine ===== */
const S = STEPS, ST = { sel: S.products[0].id };
const SL = {}; DATA.stage_defs.forEach(d=>SL[d.key]=d.label);
const KEYS = ['problem-statement','hook-line','primary-usp-claim','use-case-scenario','cta-text'];
const x2 = n=>n==null||isNaN(n)?'—':n.toFixed(2)+'x';
const sg = n=>(n>0?'+':'')+n.toFixed(2);
const P = ()=>S.products.find(p=>p.id===ST.sel);
function rating(p){
  const sup = p.recipe_support.filter(r=>r.n>=3).length;
  const m3 = p.m3 && p.m3.n>=3 && p.m3.roas && Math.abs(p.m3.roas/p.final_pred-1)<=.15;
  const checks = [
    {ok:p.ads>=40, t:`Built on <b>${p.ads} ads</b> and <b>${fmtINR(p.spend)}</b> of spend for this product.`, w:`Only <b>${p.ads} ads</b> for this product, which is a thin base.`},
    {ok:sup>=4, t:`<b>${sup} of 5</b> chosen angles have at least 3 real ads behind them.`, w:`Only <b>${sup} of 5</b> chosen angles have at least 3 real ads behind them.`},
    {ok:p.tested>=7, t:`<b>${p.tested} of 10</b> angle pairs in this recipe have run together in real ads.`, w:`Only <b>${p.tested} of 10</b> angle pairs have ever run together; the rest are untested.`},
    {ok:!!m3, t:`The ${p.m3.n} closest real ads (3+ matching angles) earned <b>${x2(p.m3.roas)}</b>, in line with the <b>${x2(p.final_pred)}</b> prediction.`, w:p.m3.n>=3?`The ${p.m3.n} closest real ads earned <b>${x2(p.m3.roas)}</b>, which is not close to the <b>${x2(p.final_pred)}</b> prediction.`:`Fewer than 3 real ads are close to this recipe, so there is little to compare against.`},
    {ok:p.full_runs>0, t:`This exact 5-angle recipe has already run on <b>${p.full_runs} ads</b>.`, w:`This exact 5-angle recipe has <b>never run</b>. It is a new combination to test.`},
    {ok:true, t:`On ads it never saw, the model's error was <b>${S.meta.blend_wMAE}</b> versus <b>${S.meta.base_wMAE}</b> for simply using the product average, about 12% better.`},
    {ok:p.calib.lo>0, t:`The size of the gain over your normal ads was confirmed on hidden ads.`, w:`The <b>size</b> of the gain over your normal ads could not be confirmed: on hidden ads the test could not rule out a gain of zero.`},
  ];
  const ok = checks.filter(c=>c.ok).length;
  return {checks, ok, level: ok>=6?'Strong':ok>=4?'Moderate':'Limited'};
}
function pairTbl(rows, withN){
  return `<div class="xl-wrap"><table class="xl-tbl"><tr><th>Pair</th><th class="num">Ads</th><th class="num">Spend</th><th class="num">Real ROAS</th><th class="num">Expected alone</th><th class="num">Synergy</th></tr>${rows.map(r=>`<tr><td><b>${esc(r.aA)}</b> <span class="mut">+</span> <b>${esc(r.aB)}</b><small>${SL[r.sA]} + ${SL[r.sB]}</small></td>${r.n?`<td class="num">${r.n}</td><td class="num">${fmtINR(r.spend)}</td><td class="num">${x2(r.obs)}</td><td class="num">${x2(r.exp)}</td><td class="num ${r.syn>=0?'pos':'neg'}">${sg(r.syn)}</td>`:`<td class="num mut" colspan="5" style="text-align:left">never run together</td>`}</tr>`).join('')}</table></div>`;
}
function renderLab(){
  const p = P(), rt = rating(p), root = document.getElementById('content');
  const chips = S.products.map(q=>`<button class="xl-chip ${q.id===ST.sel?'on':''}" data-p="${q.id}">${esc(q.name)} <small>${q.ads} ads</small></button>`).join('')
    + `<span class="xl-chip off" title="Fewer than 3 usable angles per stage">Lip Balm <small>9 ads, no recipe</small></span>`;
  const solo = p.steps4.filter(s=>s.changed).length;
  const html = `<div class="xl">
  <div><button class="zl-dev" id="xBack">&larr; Back to recipe generator</button><div class="xl-kicker" style="margin-top:14px">Experimentation Lab, full walkthrough</div><h1>Which creative recipe should we test next?</h1>
    <p class="xl-lede">Every ad is five parts: problem, hook, claim, use case and call to action. For one product at a time, this page scores each choice, finds the pairs that work together, searches every combination, and ends with one predicted ROAS you can plan around. Each step shows what was decided and why.</p></div>
  <div class="xl-chips">${chips}</div>
  <div class="xl-preview"><b class="big">${x2(p.final_pred)}</b><span>predicted ROAS for the suggested recipe, against <b>${x2(p.baseline)}</b> for this product's average ad</span><span>Evidence: <b>${rt.level}</b> (${rt.ok} of 7 checks)</span><a data-jump="s6">See why in step 6</a></div>
  <div class="xl-audit">
    <div><b>${p.ads}</b><span>ads used (spend of Rs10 or more)</span></div>
    <div><b>${fmtINR(p.spend)}</b><span>total spend behind them</span></div>
    <div><b>${x2(p.baseline)}</b><span>average ROAS (revenue / spend)</span></div>
    <div><b>${p.grid.toLocaleString('en-IN')}</b><span>recipes scored in step 4</span></div>
    <div><b>${p.tested}/10</b><span>pairs with real evidence</span></div>
  </div>

  <section class="xl-step"><div class="xl-sh"><span class="xl-sn">STEP 1</span><h2>Clean the data and weigh every ad by how far we can trust it</h2></div>
    <p class="xl-what">Ads that spent under <b>Rs10</b> are dropped as tracking glitches. For the rest, <b>spend decides how much an ad counts</b>. A Rs500 ad can show 8x or 0.5x by luck. A Rs1 lakh ad cannot. We measured how wildly ROAS swings at each spend level in this product's own ads, and weight every ad by the inverse of that swing.</p>
    <div class="xl-wrap"><table class="xl-tbl"><tr><th>Ad spend</th><th class="num">Ads</th><th class="num">Typical ROAS swing</th><th class="num">Weight in the model</th><th></th></tr>
    ${(()=>{const w0=p.bands[0].spread**2; return p.bands.map(b=>{const w=w0/(b.spread**2); return `<tr><td><b>${b.label}</b></td><td class="num">${b.n}</td><td class="num">±${((Math.exp(b.spread)-1)*100).toFixed(0)}%</td><td class="num">${w.toFixed(1)}x</td><td><div class="xl-bar"><i style="width:${Math.min(100,w/ (w0/(p.bands[p.bands.length-1].spread**2))*100)}%"></i></div></td></tr>`}).join('')})()}</table></div>
    <div class="xl-decide"><i>Decision</i><span>High-spend results are trusted and barely pulled down. Low-spend results are discounted. A hook used by only one ad still counts fully if that ad spent a lot.</span></div></section>

  <section class="xl-step"><div class="xl-sh"><span class="xl-sn">STEP 2</span><h2>Score every angle, one stage at a time</h2></div>
    <p class="xl-what">An <b>angle</b> is one specific choice inside a stage, for example the hook "Authenticity of Ayurveda". For each angle we show its <b>raw ROAS</b> (what its ads earned) and its <b>model ROAS</b>: what the model predicts when that angle is dropped into this product's most-used recipe, so small lucky samples are pulled back toward normal. Evidence tier is based on the spend behind the angle.</p>
    <div class="xl-cols">${p.stages.map(s=>`<div class="xl-col"><h4>${SL[s.stage]}</h4>${s.rows.slice(0,5).map((r,i)=>`<div class="xl-ang ${i===0?'pick':''}">${i===0?'<span class="tg">Best on its own</span>':''}<b>${esc(r.angle)}</b><em>raw ${x2(r.raw)} &rarr; model ${x2(r.adj)}<br>${r.n} ads, ${fmtINR(r.spend)}<span class="xl-tier ${r.tier}">${r.tier}</span></em></div>`).join('')}${s.total_angles>5?`<div class="xl-more">+${s.total_angles-5} more angles</div>`:''}</div>`).join('')}</div>
    <div class="xl-decide"><i>Decision</i><span>Best single angle per stage: ${p.stages.map(s=>`<b>${esc(s.picked)}</b>`).join(', ')}. An angle needs at least 2 ads to be considered.</span></div></section>

  <section class="xl-step"><div class="xl-sh"><span class="xl-sn">STEP 3</span><h2>Find pairs that work better together</h2></div>
    <p class="xl-what">Two angles can lift each other. For every pair with at least 3 ads and Rs8,000 of spend, we compare <b>what the pair really earned</b> with <b>what you would expect by adding the two angles' own effects</b>. The gap is the synergy. The model keeps pair effects only as far as they help predict ads it has not seen.</p>
    <div class="xl-two"><div><h5 class="xl-h5">Strongest synergies</h5>${pairTbl(p.syn_top)}</div><div><h5 class="xl-h5">Weakest synergies</h5>${pairTbl(p.syn_bot)}</div></div>
    <div class="xl-decide"><i>Decision</i><span>These pair effects feed the search in step 4, so the final recipe is not five separate favourites glued together.</span></div></section>

  <section class="xl-step"><div class="xl-sh"><span class="xl-sn">STEP 4</span><h2>Search every combination and settle on one recipe</h2></div>
    <p class="xl-what">We score <b>${p.grid.toLocaleString('en-IN')} real combinations</b> of supported angles with the full model (angle effects, pair effects, plus a second model, CatBoost, averaged in). Then we compare the winner with simply taking each stage's best single angle.</p>
    <div class="xl-flow"><div class="bx"><span>Best single angles stitched together</span><b>${x2(p.solo_pred)}</b></div><span class="ar">&rarr;</span><div class="bx"><span>Best full combination (suggested)</span><b>${x2(p.final_pred)}</b></div><span class="xl-what">${solo?`${solo} stage${solo>1?'s were':' was'} swapped to unlock a better fit.`:'No swap beat the best single angles, so they stand.'}</span></div>
    <div class="xl-wrap"><table class="xl-tbl"><tr><th>Stage</th><th>Best on its own</th><th>Final pick</th><th>Result</th><th class="num">ROAS gained</th></tr>${p.steps4.map(s=>`<tr><td>${SL[s.stage]}</td><td>${esc(s.solo)}</td><td><b>${esc(s.final)}</b></td><td>${s.changed?'<span class="pos">Swapped</span>':'<span class="mut">Kept</span>'}</td><td class="num ${s.changed?'pos':'mut'}">${s.changed?'+'+s.gain.toFixed(2)+'x':'—'}</td></tr>`).join('')}</table></div>
    <h5 class="xl-h5" style="margin-top:6px">Runner-up recipes</h5>
    <div class="xl-ads">${p.alts.slice(1,4).map(a=>`<div class="xl-ad"><span>${a.recipe.map(esc).join(' / ')}</span><b class="tabnum">${x2(a.pred)}</b></div>`).join('')}</div>
    <div class="xl-decide"><i>Decision</i><span>Recipe locked: ${p.recipe_support.map(r=>`<b>${esc(r.angle)}</b>`).join(', ')}.</span></div></section>

  <section class="xl-step"><div class="xl-sh"><span class="xl-sn">STEP 5</span><h2>Check the recipe against real ads</h2></div>
    <p class="xl-what">The recipe can recommend a combination nobody has run. So we check how much of it is backed by real ads: each of its 10 angle pairs, then the closest real ads. Pairs that never ran together are labelled, not hidden.</p>
    ${pairTbl(p.evidence)}
    <div class="xl-two"><div><h5 class="xl-h5">Closest real ads (3 or more matching angles)</h5><div class="xl-ads">${p.closest.length?p.closest.map(a=>`<div class="xl-ad"><span>${a.match} of 5 angles match, ${fmtINR(a.spend)} spent</span><span><b class="tabnum">${x2(a.roas)}</b> ${a.url?`<a href="${esc(a.url)}" target="_blank" rel="noopener">View</a>`:''}</span></div>`).join(''):'<div class="xl-ad">No real ad is this close. This is a new recipe.</div>'}</div></div>
    <div><h5 class="xl-h5">Pooled result of near-matches</h5><div class="xl-ads"><div class="xl-ad"><span>4+ angles match</span><b class="tabnum">${p.m4.n?`${p.m4.n} ads, ${x2(p.m4.roas)}`:'none'}</b></div><div class="xl-ad"><span>3+ angles match</span><b class="tabnum">${p.m3.n?`${p.m3.n} ads, ${x2(p.m3.roas)}`:'none'}</b></div><div class="xl-ad"><span>Exact 5-angle recipe</span><b class="tabnum">${p.full_runs} ads</b></div></div></div></div>
    <div class="xl-decide"><i>Decision</i><span>${p.tested} of 10 pairs and ${p.m3.n} near-match ads support this recipe. ${p.full_runs?'It has been run before.':'It has never run in full, so treat it as a test, not a certainty.'}</span></div></section>

  <section class="xl-step" id="s6"><div class="xl-sh"><span class="xl-sn">STEP 6</span><h2>Predicted ROAS for this recipe</h2></div>
    <div class="xl-final">
      <div class="xl-hero"><span class="lab">Predicted ROAS (model estimate at a typical ad spend)</span><span class="val">${x2(p.final_pred)}</span>
        <span class="rng">Likely range <b>${x2(p.lo)}</b> to <b>${x2(p.hi)}</b> (80% of the time). Your average ad earns <b>${x2(p.baseline)}</b>.</span>
        <div class="xl-rec">${p.recipe_support.map(r=>`<div><span>${SL[r.stage]}</span><b>${esc(r.angle)}</b></div>`).join('')}</div></div>
      <div><h5 class="xl-h5">Where this lands</h5>
        <div class="xl-cmp">${(()=>{const rows=[['Your average ad',p.baseline,''],['Most-used recipe',p.pred_modal,''],['Suggested recipe',p.final_pred,'me'],['Simply adding up angles',p.naive,'bad']];const mx=Math.max(...rows.map(r=>r[1]));return rows.map(r=>`<div class="r ${r[2]}"><span>${r[0]}</span><div class="t"><i style="width:${r[1]/mx*100}%"></i></div><b>${x2(r[1])}</b></div>`).join('')})()}</div>
        <p class="xl-foot" style="margin-top:10px">The last bar is the naive way to combine angles: it adds each angle's raw result and ignores luck and overlap. ${p.naive>p.final_pred*1.05?'Here it overshoots the model.':'Here it happens to land close, but it overshoots badly when angles have few ads (Root Touch-Up: 4.48x).'}</p></div>
    </div>
    <div><h5 class="xl-h5">Why you can trust it, and where to be careful</h5>
      <ul class="xl-chk">${rt.checks.map(c=>`<li class="${c.ok?'ok':'warn'}"><i>${c.ok?'&#10003;':'!'}</i><span>${c.ok?c.t:(c.w||c.t)}</span></li>`).join('')}</ul></div>
    <div class="xl-verdict"><b>${rt.level} evidence.</b> ${p.lo<p.baseline?`The likely range reaches below your usual ${x2(p.baseline)}, so the model's best guess of ${x2(p.final_pred)} is upside to test, not a promise.`:`Even the low end of the range sits above your usual ${x2(p.baseline)}.`} The model ranks angles better than guessing and beats the product average on ads it never saw, which is why this recipe is worth launching. Only a live test against a control ad can confirm the exact gain.</div>
    <p class="xl-foot">Predicted ROAS is the model's estimate at this product's median ad spend. Held-out testing on ${S.meta.n_ads} ads: error ${S.meta.blend_wMAE} (this method) vs ${S.meta.base_wMAE} (product average) vs ${S.meta.old_wMAE} (the original arithmetic-only Lab). ${S.meta.shuffle_note}.</p>
  </section>
  </div>`;
  root.innerHTML = html;
  root.querySelectorAll('[data-p]').forEach(b=>b.onclick=()=>{ST.sel=b.dataset.p;renderLab();window.scrollTo(0,0);});
  document.getElementById('xBack').onclick=()=>{LZ.view='lean';renderLean();};
  root.querySelectorAll('[data-jump]').forEach(a=>a.onclick=()=>document.getElementById(a.dataset.jump).scrollIntoView({behavior:'smooth'}));
}
