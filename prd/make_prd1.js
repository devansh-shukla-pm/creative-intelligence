const fs=require('fs');
const {PageBreak,Document,Packer,Paragraph,TextRun,Table,TableRow,TableCell,HeadingLevel,AlignmentType,LevelFormat,BorderStyle,WidthType,ShadingType}=require('docx');
const W=9360;
const bd={style:BorderStyle.SINGLE,size:4,color:'BFBFBF'}; const borders={top:bd,bottom:bd,left:bd,right:bd};
const H1=t=>new Paragraph({heading:HeadingLevel.HEADING_1,spacing:{before:320,after:120},children:[new TextRun({text:t,bold:true,size:30})]});
const H2=t=>new Paragraph({heading:HeadingLevel.HEADING_2,spacing:{before:220,after:80},children:[new TextRun({text:t,bold:true,size:24})]});
const H3=t=>new Paragraph({spacing:{before:160,after:60},children:[new TextRun({text:t,bold:true,size:21})]});
const runs=t=>{ // **bold** support
  const out=[]; t.split(/(\*\*[^*]+\*\*)/).forEach(p=>{ if(!p) return; if(p.startsWith('**')) out.push(new TextRun({text:p.slice(2,-2),bold:true,size:21})); else out.push(new TextRun({text:p,size:21})); }); return out; };
const P=t=>new Paragraph({spacing:{after:100,line:276},children:runs(t)});
const B=(t,l=0)=>new Paragraph({numbering:{reference:'bul',level:l},spacing:{after:50,line:264},children:runs(t)});
const N=(t)=>new Paragraph({numbering:{reference:'num',level:0},spacing:{after:50,line:264},children:runs(t)});
const Q=t=>new Paragraph({spacing:{after:80},indent:{left:360},border:{left:{style:BorderStyle.SINGLE,size:12,color:'AAAAAA',space:8}},children:[new TextRun({text:t,italics:true,size:21})]});
function table(cols,rows,widths){
  const tot=widths.reduce((a,b)=>a+b,0);
  const cell=(t,w,head)=>new TableCell({borders,width:{size:w,type:WidthType.DXA},margins:{top:70,bottom:70,left:110,right:110},shading:head?{fill:'EDEDED',type:ShadingType.CLEAR,color:'auto'}:undefined,
    children:String(t).split('\n').map(line=>new Paragraph({spacing:{after:20},children:[new TextRun({text:line,size:19,bold:!!head})]}))});
  return new Table({width:{size:tot,type:WidthType.DXA},columnWidths:widths,rows:[new TableRow({tableHeader:true,children:cols.map((c,i)=>cell(c,widths[i],true))}),...rows.map(r=>new TableRow({children:r.map((c,i)=>cell(c,widths[i],false))}))]});
}
const gap=()=>new Paragraph({spacing:{after:60},children:[]});
const c=[];
c.push(new Paragraph({spacing:{after:60},children:[new TextRun({text:'PRD: Creative Intelligence Report',bold:true,size:40})]}));
c.push(new Paragraph({spacing:{after:200},children:[new TextRun({text:'Covers: landing page, report page, Creative Overview tab, Insights & Actionables tab. The Experimentation Lab has its own PRD. How we pull and process the data is in PRD 2.',size:20,color:'595959'})]}));

c.push(H1('1. Background & Problem'));
c.push(P('Brands run hundreds of Meta ads. Meta shows spend, revenue and ROAS for each ad. It does not show which creative choices make an ad work: the problem it opens with, the hook, the main claim, the use case, the call to action.'));
c.push(P('So marketers check ads one by one and decide by instinct. Patterns across many ads stay hidden.'));
c.push(P('Creative Intelligence fixes this. The user picks an ad account and a date range. We generate a report with three things: how the account is performing, hidden insights with actions, and a suggested creative recipe.'));

c.push(H1('2. Goals / Non-Goals'));
c.push(P('**Goals**'));
c.push(B('One click generates a report from an ad account and a date range.'));
c.push(B('Show performance first. Then show which creative choices drive it.'));
c.push(B('Show only non-obvious insights. Before showing an insight ask: "Would an experienced marketer already believe this without our data?" If yes, do not show it.'));
c.push(B('Suggest the best angle for each stage, with the numbers behind it.'));
c.push(B('Never show an empty or wrong number. A section appears only when its data is ready.'));
c.push(B('All calculations run in the backend. The front end only displays results. Any "processing" animation is only for show.'));
c.push(P('**Non-Goals**'));
c.push(B('Creating or publishing ads. "Generate Creative" is only a placeholder button for now.'));
c.push(B('Trend or fatigue insights. Our data has no dates per row, so these are not possible yet.'));
c.push(B('Category-level analysis. We only support Account, Campaign and SKU.'));
c.push(B('Platforms other than Meta.'));
c.push(B('The Experimentation Lab. It has its own PRD.'));
c.push(B('The Take Action button on insight cards. It is not in scope for this version.'));

c.push(H1('3. Key Terms'));
c.push(table(['Term','Meaning'],[
 ['Stage','One part of an ad. There are 5 core stages: Problem Statement, Hook Line, Primary USP Claim, Use Case Scenario, CTA Text. There are 5 optional stages: Testimonial Claim, Proof Points, Credibility Signal, Offer Details, Comparison Axis.'],
 ['Angle','One specific choice inside a stage. Example: "Authenticity of Ayurveda" is an angle of Hook Line. Angles are made by grouping similar free-text values (see PRD 2). In the UI always say "angle", never "cluster".'],
 ['Approach','The overall strategy of an ad: Push Product, Push Problem, Push Differentiation, Push Brand or Push Offer.'],
 ['SKU','One product. An ad can have one SKU or several (a combo ad). Combo ads stay in their own group. Never split them or count them twice.'],
 ['Recipe','One angle picked for each of the 5 core stages.'],
 ['ROAS','Revenue divided by spend. "Average ROAS" is total revenue divided by total spend for what is on screen.'],
],[1700,7660]));

c.push(H1('4. Flow and Loading'));
c.push(H2('4.1 Landing page'));
c.push(P('The landing page is the same as the existing Creative Report generation landing page. Reuse it as it is.'));
c.push(P('When the user picks the ad account and date range and clicks the generate button, start the report job and open the report page (section 4.2).'));
c.push(H2('4.2 Report page: starting state'));
c.push(P('Open on the Creative Overview tab. Show the filter bar below with these default values. Show shimmer under the bar until data arrives.'));
c.push(table(['Filter','Default value','Notes'],[
 ['Ad Account','The account picked on the landing page','Changing it starts a new report.'],
 ['Campaign','All Campaigns','Works as soon as Meta data is ready.'],
 ['SKU / Product','Locked, shows "All Products"','Unlocks at Signal B.'],
 ['Creative','No creative selected','Lists creative IDs once data is ready.'],
 ['Creative Type','All','Options: All, Video, Image, Carousel.'],
],[2200,3400,3760]));
c.push(H2('4.3 What unlocks when'));
c.push(P('The backend sends 4 signals. Each section stays in shimmer or locked state until its signal arrives.'));
c.push(table(['Signal','What it means','What it unlocks'],[
 ['A. Meta data ready','We have pulled the ad data for the account and date range.','Filter bar (except SKU), Performance Summary, Format Split, Spend Efficiency, Creative Metric Explorer (Creative Metrics view).'],
 ['B. Classification ready','Both prompts have finished for all ads (see PRD 2). SKU data is ready.','SKU filter, Creative Stage Overview (both charts), Story Matrix view, and the Insights & Actionables tab (everything except the 4 insight cards).'],
 ['C. Insights ready','The insight prompt has finished.','The 4 insight cards. Until then they keep shimmering, even though the tab is open.'],
 ['D. Lab ready','The backend has finished all Experimentation Lab work. Separate from B and C.','The Experimentation Lab tab.'],
],[1900,3300,4160]));
c.push(gap());
c.push(P('**Copy to show while locked or loading**'));
c.push(table(['Where','Text'],[
 ['Pill at the top while anything is loading','Some sections are still loading…'],
 ['SKU filter and Story Matrix, on hover','Your reports are being stitched, you will be notified once it\'s ready.'],
 ['Experimentation Lab tab, on hover','Your data is being fetched and stitched together. You\'ll be able to access this feature in no time.'],
],[3600,5760]));
c.push(gap());
c.push(P('**Rules**'));
c.push(B('A locked tab looks dimmed, has a lock icon, ignores clicks and shows its tooltip on hover. When it unlocks the tooltip must disappear.'));
c.push(B('Never hide a locked item. The user should see it exists.'));
c.push(B('If a signal fails, show the normal error state with a Retry button. Never leave a loader on screen forever.'));
c.push(B('If the report takes very long, use the existing Creative Report pattern: a "still loading" popup with two options (Continue Viewing, Explore More), restart the polling after each timeout, and send an email when the report is done.'));

c.push(H1('5. Tab 1: Creative Overview'));
c.push(P('**Goal:** show how the account is doing and where money is working or being wasted, before any creative-level analysis.'));
c.push(table(['Section','What to show','Needs signal'],[
 ['Performance Summary','4 cards: Total Spend, Total Ads, Revenue, ROAS. Each shows the change versus the previous period of the same length. The ad count is a link that opens the list of those ads.','A'],
 ['Format Split','Donut chart of Video, Image and Carousel with ad count and share. A switch to see it by Format, Spend or ROAS. One line below comparing formats, for example "6% ROAS Image outperformance vs Video".','A'],
 ['Spend Efficiency','Two top cards: "Stuck in low-ROAS ads" (spend and number of ads under 2.0x) and "Potential upside" (extra revenue if that spend earned the top-tier ROAS). Below that, 4 ROAS tiers with spend, ad count and a short note: Excellent 4.0x+, Good 3.0 to 3.9x, Average 2.0 to 2.9x, Poor under 2.0x.','A'],
 ['Creative Metric Explorer','Table of ads: thumbnail and name, spend, CPR, ROAS, purchase value. Sortable columns. A Metrics menu to add or remove columns. Pagination with page size. "Preview" opens the creative. A switch between Creative Metrics and Story Matrix Analysis.','A (Creative Metrics), B (Story Matrix)'],
 ['Creative Stage Overview','A row of 10 stage pills (optional stages have a small dot). For the picked stage show: a Spend vs Revenue chart by angle with a ROAS line, and a ranked list of the top 10 angles by ROAS with ads and spend.','B'],
],[2300,5760,1300]));
c.push(gap());
c.push(P('**Rules**'));
c.push(B('Every section follows the filter bar and the date range.'));
c.push(B('Use one ROAS scale everywhere: Excellent, Good, Average, Poor. On this tab show the tiers as shades of one accent colour, not red, amber and green.'));
c.push(B('Combo (multi-SKU) ads show only under "Combo-ads" in the SKU filter. Never inside a single SKU\'s numbers.'));
c.push(B('Sections waiting for Signal B show shimmer. Never show placeholder numbers once real data exists.'));
c.push(H3('Acceptance criteria'));
c.push(B('Sections that need only Signal A show as soon as A arrives. They do not wait for B.'));
c.push(B('Changing any filter updates every visible section.'));
c.push(B('Totals in Performance Summary match the sum of ads in the Metric Explorer for the same filters.'));
c.push(B('Creative Stage Overview and Story Matrix stay in loading or locked state until Signal B.'));

c.push(H1('6. Tab 2: Insights & Actionables'));
c.push(P('**Goal:** show hidden creative signals that Meta reporting does not show, and say what to do about them. This is an insight feed, not a dashboard. Keep the section order below.'));
c.push(table(['#','Section','What to show'],[
 ['1','Insight cards','4 insights worth acting on. Left side: a list of the 4. Right side: details of the picked one. Details are: a type tag (for example Opportunity), a headline, "What we found" with numbers, "What to do" with a Take Action button (placeholder only, see Insight rules), and a link to the ads behind the insight. Needs Signal C.'],
 ['2','Creative Ranking Engine','Ranks every creative with a score out of 100. The score uses more than ROAS, and it accounts for how much spend backs each result. The "Run Ranking" button starts a loader with 3 steps (Studying ad-level data, Normalizing outliers, Finalizing statistical ranking), then shows the ranked list. A "What am I looking at?" hover explains the score.'],
 ['3','Filters','Campaign and SKU dropdowns. Everything below follows them.'],
 ['4','Recipe Suggestion','Best angle for each of the 5 core stages with its return. A "Generate Creative" button (placeholder). A "Want Advanced Suggestions?" button that opens the Experimentation Lab tab. A hover explains why the top performer per stage can be luck.'],
 ['5','Winning & Losing Angles','Left: "Increase spend" lists angles that earn above average but get a small share of budget. Right: "Cut spend" lists angles that earn below average but take a big share of budget. Each row shows stage, angle, share of spend, return versus average, and ROAS.'],
 ['6','2D heatmap','User picks any two stages. Show a grid of angle by angle with ROAS, coloured on a smooth scale. Two sliders: minimum ads per cell and minimum spend per cell. Cells below the limits are shown empty.'],
 ['7','3D Combination Lab','User picks three stages. Show the combinations in a 3D view the user can rotate. Also a Table view of the same data. Same two sliders. A Reset view button.'],
],[500,2400,6460]));
c.push(gap());
c.push(P('**Insight rules**'));
c.push(B('Show 4 insights. Each one must be: hidden from the marketer, big enough to matter, something they can act on, and explained by the data. If fewer than 4 qualify, show fewer. Never make one up.'));
c.push(B('Insight types we support: two angles that work better together than alone, a proven angle never tried on a sibling product, a pattern that is true overall but only comes from one SKU, spend and results that disagree, and a stage that is rarely used but performs well. Insights about staleness are not supported.'));
c.push(B('**Take Action button: not in scope for this version.** The button stays on the card as a placeholder. Do not build anything behind it. What it does will be defined in a later version.'));
c.push(B('The prompt that writes the insight cards is attached in full as Appendix A. It does no maths. A backend step first computes a candidate pack (all numbers, rankings and thresholds), and the prompt only judges the candidates and writes the cards. Developers must build that step as well. The prompt describes the pack it expects.'));
c.push(P('**Scope rules**'));
c.push(B('The tab opens at Signal B. The 4 insight cards keep shimmering until Signal C.'));
c.push(B('The Campaign and SKU dropdowns list real campaigns and SKUs with ad counts. Sections 4 to 7 must not have their own separate SKU filter. One filter controls them all.'));
c.push(B('An angle or combination shows in rankings and tables only if it has enough ads and spend. Otherwise show an empty cell, not a score.'));
c.push(H3('Acceptance criteria'));
c.push(B('The tab opens at Signal B with the 4 insight cards in shimmer.'));
c.push(B('When Signal C arrives the cards replace the shimmer without the layout jumping.'));
c.push(B('Changing Campaign or SKU updates sections 4 to 7 together.'));
c.push(B('"Want Advanced Suggestions?" opens the Experimentation Lab only if it is unlocked. If locked, it does nothing.'));
c.push(B('Every "view ads" link opens the creative of the highest-spend ad behind that number.'));

c.push(H1('7. Tab 3: Experimentation Lab (separate PRD)'));
c.push(P('The Lab is a big feature and has its own PRD. This document only says how the tab fits in the report.'));
c.push(B('It is the third tab, after Creative Overview and Insights & Actionables.'));
c.push(B('It unlocks on its own signal (Signal D, section 4.3). This is separate from B and C. Until then it is locked and uses the copy from section 4.3.'));
c.push(B('The "Want Advanced Suggestions?" button on Insights & Actionables opens this tab. While the tab is locked the button does nothing.'));
c.push(B('Everything inside the tab is out of scope here.'));

c.push(H1('8. Rules for the Whole Report'));
c.push(B('**Theme:** support dark and light. Light uses the warm design-system colours (cream background, coral accent). A toggle at the top right saves the choice. The default follows the system setting.'));
c.push(B('**Tooltips:** hide a tooltip when the element it belongs to is replaced or unlocked.'));
c.push(B('**Number format:** INR with L and Cr (for example Rs38.65L). ROAS with two decimals and an x.'));
c.push(B('**Animation:** turn animations off if the user has reduced motion on.'));
c.push(B('**Copy:** only say what the data supports. Insight and ranking text uses the account\'s own numbers.'));

c.push(H1('9. Edge Cases'));
c.push(table(['Case','What should happen'],[
 ['No ad account or date range picked','"Generate Creative Intel" stays disabled.'],
 ['No ads in the date range','Show an empty state asking the user to change the range. No tabs unlock.'],
 ['Meta data is ready but classification fails','Sections that need only Signal A keep working. Sections that need B show an error with Retry. SKU filter, Insights and Lab stay locked.'],
 ['Insight prompt returns fewer than 4 insights','Show only the valid ones. Do not fill the gap.'],
 ['User leaves while loading','The report keeps processing. When the user returns, show whatever signals have arrived.'],
 ['User changes the account or date range','Start a new report. Do not mix in old results.'],
],[3600,5760]));

c.push(H1('10. Open Questions'));
c.push(N('Date range: what is the maximum range and which presets do we offer?'));
c.push(N('Should this report support multiple ad accounts (up to 3, see the Multi-Account Audit PRD) in v1?'));
c.push(N('Where does "Generate Creative" lead, and who builds it?'));
c.push(N('How do we notify the user when each signal is done: email only, or also in the app?'));

c.push(H1('11. Success Metrics'));
c.push(B('Report start rate: landing page visits that click Generate Creative Intel.'));
c.push(B('Time to first data (Signal A) and time to full report (all 4 signals).'));
c.push(B('Report completion rate: reports that reach all 4 signals.'));
c.push(B('Insight use: ad-link opens per insight.'));
c.push(P('**Negative metrics to watch**'));
c.push(B('How many users leave during loading, and at which stage.'));
c.push(B('Hover rate on locked items versus later use, to see if waiting frustrates users.'));
c.push(B('Insights that users ignore versus insights they act on.'));

c.push(H1('12. Moonshot Ideas'));
c.push(B('Show an insight\'s result later: when a user acts on an insight, track what happened to those ads and show it on the card.'));
c.push(B('Weekly email with the top insight and the biggest spend leak for each connected account.'));

const mono=t=>new Paragraph({spacing:{after:0,line:240},children:[new TextRun({text:t===''?' ':t,font:'Courier New',size:16})]});
const codeBlock=txt=>txt.replace(/\r/g,'').split('\n').map(mono);
c.push(new Paragraph({children:[new PageBreak()]}));
c.push(H1('Appendix A: Insight Prompt (system prompt for the 4 insight cards)'));
c.push(P('This is the unified insight prompt currently used. The user turn carries the candidate pack (insight_inputs.json). Text below is copied as it is.'));
c.push(...codeBlock(fs.readFileSync(__dirname+'/../prompts/insight_unified_prompt.txt','utf8')));

const doc=new Document({
  styles:{default:{document:{run:{font:'Arial',size:21}}},paragraphStyles:[
    {id:'Heading1',name:'Heading 1',basedOn:'Normal',next:'Normal',quickFormat:true,run:{size:30,bold:true,font:'Arial'},paragraph:{spacing:{before:320,after:120},outlineLevel:0}},
    {id:'Heading2',name:'Heading 2',basedOn:'Normal',next:'Normal',quickFormat:true,run:{size:24,bold:true,font:'Arial'},paragraph:{spacing:{before:220,after:80},outlineLevel:1}}]},
  numbering:{config:[
    {reference:'bul',levels:[{level:0,format:LevelFormat.BULLET,text:'•',alignment:AlignmentType.LEFT,style:{paragraph:{indent:{left:540,hanging:270}}}},{level:1,format:LevelFormat.BULLET,text:'–',alignment:AlignmentType.LEFT,style:{paragraph:{indent:{left:1000,hanging:270}}}}]},
    {reference:'num',levels:[{level:0,format:LevelFormat.DECIMAL,text:'%1.',alignment:AlignmentType.LEFT,style:{paragraph:{indent:{left:540,hanging:360}}}}]}]},
  sections:[{properties:{page:{size:{width:12240,height:15840},margin:{top:1296,right:1440,bottom:1296,left:1440}}},children:c}]
});
Packer.toBuffer(doc).then(b=>{fs.writeFileSync('PRD_1_Creative_Intelligence_Report.docx',b);console.log('ok')});
