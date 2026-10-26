import re
ci=open('../app/creative-intelligence.html',encoding='utf-8').read()
i_style=ci.index('</style>')
head=ci[:i_style].replace('<title>Creative Intelligence</title>','<title>Experimentation Lab</title>')+open('lab-steps.css').read()+open('lab-lean.css').read()+'\n</style>\n'
shell=ci[ci.index('<div class="shell">'):ci.index('<script>')]
data_line=[l for l in ci.split('\n') if l.startswith('const DATA = ')][0]
icons=ci[ci.index('const ICON_PATHS'):ci.index('/* ================= constants')]
nav=re.search(r"const NAV = \[.*?\n\];",ci,re.S).group(0).replace("ico:'bars'},\n  ]},\n  {section:'META","ico:'bars', live:true},\n  ]},\n  {section:'META")
helpers=ci[ci.index('function fmtINR(n){'):ci.index('function fmtPct')]+ci[ci.index('function esc(s)'):ci.index('function esc(s)')+400].split('\n')[0]
logo=re.search(r'<img class="brand-logo" src="data:image/png;base64,[^"]+"[^>]*>',ci).group(0)
theme=ci[ci.index('/* ---- theme (light / dark)'):]; theme=theme[:theme.index('})();')+5]
import json
steps='const STEPS = '+open('steps_data.json').read()+';'
sidebar='''
const state={sidebarCollapsed:false,page:'experimentation-lab'};
function renderSidebar(){
  const sb=document.getElementById('sidebar');
  sb.classList.toggle('collapsed',state.sidebarCollapsed);
  document.querySelector('.shell').classList.toggle('collapsed',state.sidebarCollapsed);
  sb.innerHTML=`<div class="brand-row"><div class="brand">'''+logo+'''</div><div class="collapse-btn" id="sidebarToggle">${ic('panelLeft',14)}</div></div><div class="nav-scroll">${NAV.map(sec=>`<div class="nav-section">${sec.section}</div>${sec.items.map(it=>`<div class="nav-item ${it.key===state.page?'active':'disabled'}" title="${esc(it.label)}">${ic(it.ico,16)}<span>${esc(it.label)}</span></div>`).join('')}`).join('')}</div>`;
  document.getElementById('sidebarToggle').onclick=()=>{state.sidebarCollapsed=!state.sidebarCollapsed;renderSidebar();};
}
'''
out=head+shell+'<script>\n'+data_line+'\n</script>\n<script>\n(function(){\n"use strict";\n'+icons+'\n'+nav+'\n'+helpers+'\n'+steps+'\n'+sidebar+open('lab-ui-steps.js').read()+open('lab-ui-lean.js').read()+'''
document.getElementById('breadcrumb').innerHTML='Fastrr Ads / Creative Intelligence / <b>Experimentation Lab</b>';
renderSidebar(); renderLean();
'''+'})();\n'+theme.replace('/* ---- theme','/* ---- theme',1)+'\n</script>\n'
open('experimentation-lab-standalone.html','w',encoding='utf-8').write(out)
print(len(out))
