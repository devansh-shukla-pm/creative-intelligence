import re
import os
HERE=os.path.dirname(os.path.abspath(__file__))
p=os.path.join(HERE,'..','app','creative-intelligence.html')
ci=open(p,encoding='utf-8').read()
assert 'LAB_MERGED' not in ci
L=HERE+'/'
css=open(L+'lab-steps.css').read()+open(L+'lab-lean.css').read()
i=ci.index('</style>'); ci=ci[:i]+'\n/* ===== LAB_MERGED: Experimentation Lab tab ===== */\n'+css+ci[i:]
ci=ci.replace("{key:'experimentation-lab', label:'Experimentation Lab', ico:'bars'},","{key:'experimentation-lab', label:'Experimentation Lab', ico:'bars', live:true},",1)
steps=open(L+'steps_data.json').read()
body=open(L+'lab-ui-steps.js').read()+'\n'+open(L+'lab-ui-lean.js').read()
body=body.replace("const S = STEPS, ST","const S = STEPS, ST",1)
# safe scramble + loader guards
body=body.replace("sc.forEach(e=>{ if(!e.isConnected) return;","if(!sc.some(e=>e.isConnected)){clearInterval(LZ.tm);LZ.tm=null;return;} sc.forEach(e=>{ if(!e.isConnected) return;",1)
body=body.replace("    if(stop||LZ.view!=='loading') return;","    if(stop||LZ.view!=='loading'||!q('zPct')) return;",1)
block='''/* ===== LAB_MERGED: Experimentation Lab (statistical recipe generator + full walkthrough) ===== */
const EXPLAB = (function(){
const STEPS = '''+steps+''';
'''+body+'''
return {
  enter(){ if(LZ.view==='loading') LZ.view='lean'; },
  render(){ if(LZ.view==='dev') renderLab(); else renderLean(); },
  leave(){ if(LZ.tm){clearInterval(LZ.tm);LZ.tm=null;} }
};
})();
let __prevPage = null;

'''
k=ci.index('function render(){')
ci=ci[:k]+block+ci[k:]
a="""  const bc = document.getElementById('breadcrumb');
  if(bc){
    bc.innerHTML = state.page==='insights-actionables'
      ? 'Fastrr Ads / Creative Intelligence / <b>Insights &amp; Actionables</b>'
      : 'Fastrr Ads / Creative Intelligence / <b>Creative Overview</b>';
  }
  if(state.page==='insights-actionables') renderInsightsActionables();
  else renderCreativeOverview();
"""
assert a in ci
b="""  const bc = document.getElementById('breadcrumb');
  if(bc){
    bc.innerHTML = state.page==='insights-actionables'
      ? 'Fastrr Ads / Creative Intelligence / <b>Insights &amp; Actionables</b>'
      : state.page==='experimentation-lab'
        ? 'Fastrr Ads / Creative Intelligence / <b>Experimentation Lab</b>'
        : 'Fastrr Ads / Creative Intelligence / <b>Creative Overview</b>';
  }
  if(__prevPage==='experimentation-lab' && state.page!=='experimentation-lab') EXPLAB.leave();
  if(state.page==='insights-actionables') renderInsightsActionables();
  else if(state.page==='experimentation-lab'){ if(__prevPage!=='experimentation-lab') EXPLAB.enter(); EXPLAB.render(); }
  else renderCreativeOverview();
  __prevPage = state.page;
"""
ci=ci.replace(a,b,1)
open(p,'w',encoding='utf-8').write(ci)
print(len(ci))
