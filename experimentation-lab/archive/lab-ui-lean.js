/* ===== Experimentation Lab: lean generator ===== */
const READY = S.products.filter(p=>p.ads>=15 && p.spend>=300000);
const LZ = { view:'lean', sel:null, open:false, run:null };
const ELIG = DATA.ads.filter(a=>a.spend>=10);
const ELIG_SPEND = ELIG.reduce((a,b)=>a+b.spend,0);
const LOADER = [
  {t:'Reading your ads', d:2000, s:p=>`${p.ads} ${p.name} ads loaded`},
  {t:'Dropping glitches and weighing every ad by spend', d:2400, s:p=>`${fmtINR(p.spend)} of spend, big spenders count most`},
  {t:'Scoring every angle across the 5 stages', d:2800, s:p=>`${p.stages.reduce((a,s)=>a+s.total_angles,0)} angles scored`},
  {t:'Pulling lucky flukes back toward normal', d:2400, s:p=>`one-ad wonders shrunk toward ${x2(p.baseline)}`},
  {t:'Hunting for angle pairs that lift each other', d:2600, s:p=>`${p.syn_top.length+p.syn_bot.length}+ real pairs compared`},
  {t:'Scoring every possible recipe', d:3600, s:p=>`${p.grid.toLocaleString('en-IN')} combinations`},
  {t:'Cross-checking against your real ads', d:2200, s:p=>`${p.tested} of 10 pairs seen in real ads`},
  {t:'Predicting ROAS and locking the recipe', d:2000, s:p=>`predicted ROAS locked in`},
];
const NOV_ICO='<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 16l.7 1.8L21.5 18.5l-1.8.7L19 21l-.7-1.8-1.8-.7 1.8-.7z"/></svg>';
const TRUST_ICO='<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 4 6v6c0 4.5 3.3 7.6 8 9 4.7-1.4 8-4.5 8-9V6z"/><path d="m9 12 2 2 4-4"/></svg>';
const LZ_TOTAL = LOADER.reduce((a,b)=>a+b.d,0);   // 20,000 ms
function lzHero(){
  const p = READY.find(q=>q.id===LZ.sel);
  const opts = READY.map(q=>`<div class="xselect-opt ${q.id===LZ.sel?'sel':''}" data-z="${q.id}"><span><b>${esc(q.name)}</b><small>${q.ads} ads, ${fmtINR(q.spend)} spend, ${q.grid.toLocaleString('en-IN')} recipes to score</small></span></div>`).join('');
  const W=[24,19,27,21,16];
  const LOCKSVG='<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>';
  const rows = KEYS.map((k,i)=>`<div class="rc-row"><span class="zl-ic">${LOCKSVG}</span><span class="nm"><i>${SL[k]}</i><em class="scr" data-w="${W[i]}">${'▒'.repeat(W[i])}</em></span></div>`).join('');
  return `<section class="rc-hero zl-hero">
    <div class="rc-left">
      <span class="rc-tag"><i></i>Recipe engine</span>
      <h2 class="rc-title">Your best ad hasn't been made yet. <span>Your data already knows how.</span></h2>
      <p class="rc-copy">We have read ${ELIG.length} of your ads and ${fmtINR(ELIG_SPEND)} of spend. Pick a product and we will score every supported angle combination to build the one ad recipe your data says should beat your average.</p>
      <div class="zl-pick">
        <div class="zl-sel xselect ${LZ.open?'open':''}" id="zSel"><div class="xselect-trigger ${p?'':'empty'}" id="zTrig"><span class="tlabel">${p?esc(p.name):'Choose a product'}</span>${ic('sortDesc',13)}</div>
          <div class="xselect-panel"><div class="xselect-list">${opts}</div><div class="xselect-foot">${READY.length} of ${DATA.skus.length} products are ready. A product needs 15+ ads, Rs3L+ spend and angles tested in every stage to get a recipe.</div></div></div>
        <button class="zl-go ${p?'ready':''}" id="zGo" aria-disabled="${p?'false':'true'}">Generate Creative Recipe ${ic('chevronRight',14)}</button>
      </div>
      <div class="zl-hint">${p?`${p.grid.toLocaleString('en-IN')} recipes are ready to be scored for ${esc(p.name)}.`:'Choose a product to unlock your recipe.'}</div>
      <div class="rc-stats"><div><b>${ELIG.length}</b><span>Ads studied</span></div><div><b>${fmtINR(ELIG_SPEND)}</b><span>Spend analysed</span></div><div><b>${READY.length}</b><span>Products ready</span></div></div>
      <div class="zl-trust">${TRUST_ICO}<span>Statistical model on your own ad data. No generative AI, no guesswork.</span></div>
    </div>
    <div class="rc-card zl-lock ${p?'armed':''}"><div class="zl-scan"></div>
      <div class="rc-cardhead"><span>Sealed recipe</span><span class="zl-st"><i></i>${p?'Ready to unseal':'Locked'}</span></div>
      <div class="zl-teaser"><div><span>Predicted ROAS</span><b>?.??x</b></div><div><span>vs your average ad</span><b class="g">+??%</b></div></div>
      ${rows}
      <div class="zl-veil">${p?`<b>${p.grid.toLocaleString('en-IN')} recipes</b> are waiting to be scored for ${esc(p.name)}. Break the seal.`:'<b>Something is hiding in your data.</b> Pick a product to break the seal.'}</div></div>
  </section>`;
}
function lzLoader(p){
  return `<section class="zl-load"><div>
    <h2>Building your <span>${esc(p.name)}</span> recipe</h2>
    <div class="zl-pct"><span id="zPct">0</span><small>%</small></div><div class="zl-prog"><i id="zBar"></i></div>
    <ul class="zl-steps">${LOADER.map((s,i)=>`<li data-i="${i}"><i></i><span>${s.t}<small id="zs${i}"></small></span></li>`).join('')}</ul><div class="zl-trust" style="margin-top:18px">${TRUST_ICO}<span>Every number is calculated from your ads. Nothing here is written by AI.</span></div></div>
    <div class="zl-viz">
      <div class="zl-vz"><h5>Stages being scored</h5><div class="zl-stg">${KEYS.map(k=>`<div data-k="${k}">${SL[k]}</div>`).join('')}</div></div>
      <div class="zl-vz"><h5>Live count</h5><div class="zl-cnt"><div><b id="zC1">0</b><span>ads read</span></div><div><b id="zC2">0</b><span>recipes scored</span></div><div><b id="zC3">0</b><span>pairs checked</span></div></div></div>
      <div class="zl-vz"><h5>Recipe search</h5><div class="zl-grid" id="zGrid">${Array.from({length:120},()=>'<i></i>').join('')}</div></div>
    </div></section>`;
}
function lzResult(p){
  const up = p.final_pred/p.baseline-1;
  return `<section class="zl-out"><div>
    <span class="lab">Predicted ROAS for this recipe</span><div class="hd"><div class="roas">${x2(p.final_pred)}</div>
    ${up>0.005?`<span class="chip up"><svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>${(up*100).toFixed(0)}% above average</span>`:`<span class="chip">In line with average</span>`}</div>
    <div class="vs">Your average ${esc(p.name)} ad earns <b>${x2(p.baseline)}</b>.</div>
    <div class="zl-facts"><div><span>Ads analysed</span><b>${p.ads} ads, ${fmtINR(p.spend)}</b></div><div><span>Creative combinations scored</span><b>${p.grid.toLocaleString('en-IN')}</b></div><div><span>Angle pairs seen in real ads</span><b>${p.tested} of 10</b></div><div><span>Accuracy</span><b>${Math.round((1-S.meta.blend_wMAE/S.meta.base_wMAE)*100)}% better than the mean/median baseline</b></div></div>
    <div class="zl-new">${NOV_ICO}<span>${p.full_runs===0?'<b>Never tried before.</b> This exact combination has not run in your account yet. Testing it is a fresh experiment, and every result adds new evidence to your data.':`<b>Run before on ${p.full_runs} ads.</b> Running it again at a bigger budget gives you a clearer read on what it can do.`}</span></div>
    <div class="zl-acts"><button class="zl-go" id="zGen">Generate Creative ${ic('chevronRight',14)}</button><button class="zl-ghost" id="zAgain">Build another recipe</button><button class="zl-ghost" id="zWalk">See how it was built</button></div>
    <div class="zl-trust" style="margin-top:16px">${TRUST_ICO}<span>Calculated from your own ad data with statistical models, not generated by AI.</span></div></div>
    <div class="rc-card zl-rec focus"><div class="rc-cardhead"><span>Your creative recipe</span><span class="zl-tag">${p.full_runs===0?'New combination':'Proven combination'}</span></div>
    ${p.recipe_support.map(r=>`<div class="rc-row"><span class="rc-rn"><i>${SL[r.stage]}</i><b>${esc(r.angle)}</b><small>${r.n} ads, ${fmtINR(r.spend)} spend</small></span></div>`).join('')}</div>
  </section>`;
}
function lzRun(p){
  const t0 = performance.now(), q = id=>document.getElementById(id);
  const trig = [0,1,2,3,4,5,6,7].map(i=>LOADER.slice(0,i).reduce((a,b)=>a+b.d,0));
  const done = new Set(); let stop=false;
  function tick(){
    if(stop||LZ.view!=='loading') return;
    const el = Math.min(performance.now()-t0, LZ_TOTAL), f = el/LZ_TOTAL;
    q('zPct').textContent = Math.floor(f*100); q('zBar').style.width = (f*100)+'%';
    LOADER.forEach((s,i)=>{
      const li = document.querySelector(`.zl-steps li[data-i="${i}"]`); if(!li) return;
      const end = trig[i]+s.d, started = el>=trig[i], fin = el>=end;
      li.classList.toggle('on', started&&!fin); li.classList.toggle('done', fin);
      if(started){ const sm=q('zs'+i); if(sm && !sm.textContent) sm.textContent = s.s(p); }
    });
    q('zC1').textContent = Math.round(Math.min(1,el/trig[1]||0)*p.ads); q('zC2').textContent = Math.round(Math.max(0,Math.min(1,(el-trig[5])/LOADER[5].d))*p.grid).toLocaleString('en-IN');
    q('zC3').textContent = Math.round(Math.max(0,Math.min(1,(el-trig[4])/(LOADER[4].d+LOADER[5].d+LOADER[6].d)))*45);
    const stg = Math.min(5, Math.floor(Math.max(0,(el-trig[2]))/(LOADER[2].d/5))); document.querySelectorAll('.zl-stg div').forEach((d,i)=>d.classList.toggle('lit', i<stg || el>=trig[3]));
    const cells = document.querySelectorAll('#zGrid i'), nf = Math.floor(Math.max(0,Math.min(1,(el-trig[5])/LOADER[5].d))*cells.length);
    cells.forEach((c,i)=>{ c.className = i<nf?'f':''; }); if(el>=trig[7]) cells[(p.id.length*7)%cells.length].className='w';
    if(el>=LZ_TOTAL){ setTimeout(()=>{ if(LZ.view==='loading'){ LZ.view='result'; renderLean(); } },450); return; }
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}
function renderLean(){
  if(LZ.tm){clearInterval(LZ.tm);LZ.tm=null;}
  const root = document.getElementById('content'), p = READY.find(q=>q.id===LZ.sel);
  const body = LZ.view==='loading'?lzLoader(p):LZ.view==='result'?lzResult(p):lzHero();
  root.innerHTML = `<div class="zl"><div class="zl-head"><div class="page-head"><div><h1>Experimentation Lab</h1><p>Test smarter. Let your own ad history build the next creative recipe.</p></div></div></div>${body}</div>`;
  if(LZ.view==='lean'){
    if(!(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches)){ const CH='ABCDEFGHJKLMNPQRSTUVWXYZ0123456789#%&*'; const sc=[...root.querySelectorAll('.scr')]; LZ.tm=setInterval(()=>{ sc.forEach(e=>{ if(!e.isConnected) return; let t='',n=+e.dataset.w; for(let i=0;i<n;i++) t+=CH[Math.floor(Math.random()*CH.length)]; e.textContent=t; }); },LZ.sel?70:140); }
    const trig = document.getElementById('zTrig'), sel = document.getElementById('zSel');
    trig.onclick = e=>{ e.stopPropagation(); LZ.open=!LZ.open; sel.classList.toggle('open',LZ.open); };
    root.querySelectorAll('[data-z]').forEach(o=>o.onclick=()=>{ LZ.sel=o.dataset.z; LZ.open=false; renderLean(); });
    document.getElementById('zGo').onclick = ()=>{ if(!LZ.sel){ LZ.open=true; sel.classList.add('open'); return; } LZ.view='loading'; renderLean(); lzRun(P2()); };
  }
  if(LZ.view==='result'){
    document.getElementById('zAgain').onclick = ()=>{ LZ.view='lean'; LZ.sel=null; renderLean(); };
    document.getElementById('zWalk').onclick = ()=>{ LZ.view='dev'; ST.sel=LZ.sel; renderLab(); };
  }
}
function P2(){ return READY.find(q=>q.id===LZ.sel); }
document.addEventListener('click',()=>{ if(LZ.view==='lean' && LZ.open){ LZ.open=false; const s=document.getElementById('zSel'); if(s) s.classList.remove('open'); } });
