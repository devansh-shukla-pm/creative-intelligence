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
const mono=t=>new Paragraph({spacing:{after:0,line:240},children:[new TextRun({text:t===''?' ':t,font:'Courier New',size:16})]});
const codeBlock=txt=>txt.replace(/\r/g,'').split('\n').map(mono);
const fence=(txt,startMarker)=>{ // text inside the first ``` block after marker
  let i=startMarker?txt.indexOf(startMarker):0; const a=txt.indexOf('```',i); const b=txt.indexOf('\n```',a+3); return txt.slice(txt.indexOf('\n',a)+1,b); };
const D=__dirname+'/../';
const extraction=fence(fs.readFileSync(D+'prompts/extraction_prompt.md','utf8'),'');
const clustering=fence(fs.readFileSync(D+'prompts/clustering_prompt.md','utf8'),'## Prompt');

c.push(new Paragraph({spacing:{after:60},children:[new TextRun({text:'PRD: Input Data Processing',bold:true,size:40})]}));
c.push(new Paragraph({spacing:{after:200},children:[new TextRun({text:'Companion to PRD 1 (Creative Intelligence Report). This document says how raw ad data is pulled and turned into the data the report shows.',size:20,color:'595959'})]}));

c.push(H1('1. Purpose'));
c.push(P('The report needs more than Meta metrics. It needs to know what each ad says: its product, hook, problem, claim, use case and CTA. We get this by running every ad through two prompts, in order. The output of both prompts, joined with the Meta metrics, fills the whole report.'));

c.push(H1('2. Pipeline'));
c.push(table(['Step','What happens','Output'],[
 ['1. Create report','User clicks Generate Creative Intel. Creative Intelligence creates its own report id for the ad account and date range.','Report id'],
 ['2. Pull data','Call the table-report API for that report. Read every page. This is the same API the old Creative Report uses.','List of ads with Meta metrics. Signal A.'],
 ['3. Extraction prompt','Run on every ad that is not cached. Reads the ad creative and returns fixed fields and free-text fields.','One JSON per ad.'],
 ['4. Clustering prompt','Groups the free-text values of all ads into short labels (angles). Runs only for ads not already clustered.','Cluster label per ad, per field.'],
 ['5. Clean product names','Turn the free-text Product values into one clean name per product (aggregate or cluster).','One product name per ad.'],
 ['6. Join and save','Join metrics + extraction output + cluster labels + clean product name into one record per ad.','Ad records. Signal B.'],
 ['7. Insights and Lab','Backend jobs read the ad records. Insight prompt produces the 4 cards. Lab model results are computed.','Signal C and Signal D (see PRD 1, section 4.3).'],
],[1700,5260,2400]));
c.push(gap());
c.push(P('All steps run in the backend. The front end never calls a prompt and never calculates.'));

c.push(H1('3. Step 2: Pull data'));
c.push(P('**API:** the old Creative Report API, called with the new report id from step 1.'));
c.push(Q('GET /shiprocket-ads/api/ve1/creative-audit/{report_id}/table-report?page={n}&size={n}&sortBy=roas&sortDir=dsc'));
c.push(B('Auth: Bearer token. Use a server-side token or the user\'s session token. Never store a token in the repo or the report.'));
c.push(B('Paging: the response has `current_page`, `total_pages`, `has_next`. Keep calling the next page until `has_next` is false. Only then is Signal A sent.'));
c.push(B('De-duplicate by `ad_id`. If an ad appears twice, keep one.'));
c.push(B('**Backend change needed:** add `campaign_id` and `campaign_name` to every ad in the response. Without them the Campaign filter cannot work.'));
c.push(P('**Fields we get per ad** (from the sample response):'));
c.push(table(['Field','Meaning'],[
 ['ad_id','Unique id of the ad. Used as the key everywhere, including the caches.'],
 ['status','ACTIVE or PAUSED.'],
 ['campaign_id, campaign_name','Campaign the ad belongs to. NEW: the backend must add these two fields to the table-report response. The current response does not have them. Needed for the Campaign filter in the report.'],
 ['ad_name','Ad name.'],
 ['thumbnail_url, creative_url','Image or video of the ad. creative_url is what the extraction prompt reads.'],
 ['media_type','VIDEO, IMAGE or CAROUSEL.'],
 ['total_spend, purchase_value, roas','Spend, revenue and ROAS.'],
 ['cpr, purchase_count','Cost per result and number of purchases.'],
 ['frequency','Average views per person.'],
 ['lpv_count / lpv_percentage','Landing page views.'],
 ['atc_count / atc_percentage','Add to cart.'],
 ['conversion_percentage','Conversion rate.'],
],[3000,6360]));
c.push(gap());
c.push(P('**Rules**'));
c.push(B('An ad with no usable `creative_url` cannot be extracted. Keep its metrics, mark it "unclassified", and do not send it to the prompts.'));
c.push(B('Ads that spent very little are still extracted. We decide later, in each report section, which ads are big enough to count.'));

c.push(H1('4. Step 3: Extraction prompt'));
c.push(P('Full prompt is in Appendix A.'));
c.push(B('**Runs on every ad** that is not already in the extraction cache.'));
c.push(B('**Input:** the ad creative (video or image from `creative_url`) plus the prompt.'));
c.push(B('**Output:** one JSON per ad with a fixed template. Two kinds of fields:'));
c.push(B('Fixed-choice fields, for example Product, Category, Customer life cycle, storytelling style, hook type, creator presence, offer visibility, video duration.',1));
c.push(B('Free-text fields, short and in the ad\'s own framing: problem_statement_text, hook_line_text, primary_usp_claim, offer_details, testimonial_claim, proof_points, comparison_axis, use_case_scenario, credibility_signal, cta_text, plus lifecycle_reasoning and creative_summary.',1));
c.push(B('**Validation:** output must be valid JSON in the exact template. If it is not, retry. After the retry limit, mark the ad "unclassified" and continue. One bad ad must never block the report.'));
c.push(B('**Cache:** save the result per `ad_id`. An ad that is already cached is never sent again.'));

c.push(H1('5. Step 4: Clustering prompt'));
c.push(P('Full prompt is in Appendix B.'));
c.push(B('**Why:** free text differs ad to ad ("Tired of frizz?" and "Frizzy in monsoon?"). We group similar values into one short label so we can add up spend and ROAS per angle. These labels are the angles shown in the report.'));
c.push(B('**Input:** the free-text fields of the ads (no metrics). `proof_points` is flattened into single strings first. Null and empty values are left out.'));
c.push(B('**One call for all fields.** Each field is clustered on its own. Values are never mixed across fields.'));
c.push(B('**Output:** for each field, a list of clusters (label and ad_ids), plus the updated list of all labels (the cluster memory).'));
c.push(B('**Limits:** at most 15 clusters per field. Clusters with fewer than 3 ads are merged into the closest bigger one when it makes sense.'));
c.push(B('**Cluster memory:** the full list of existing labels per field is sent with every call. The model must reuse an existing label when the value fits, and add a new one only if it does not. The updated list is saved and sent next time. This keeps angle names stable across runs.'));
c.push(B('**Only new ads:** ads that already have cluster labels are not sent again.'));
c.push(B('**Big accounts:** one call is fine for about 100 to 200 ads. Above that, split by field into batches of about 200 ads and add a second call that merges labels across batches.'));
c.push(B('**All maths happens in code, never in the prompt.** The prompt only groups. Spend, ROAS and counts are calculated by the backend, so numbers are exact.'));

c.push(H1('6. Step 5: One Clean Name Per Product'));
c.push(P('**Problem.** The extraction prompt returns Product as free text. The same product comes back in many spellings. In the Shesha account, 288 ads gave 178 different Product values. Examples: "Hair color | Hair dye", "Hair color", "Hair Colour | Hair Dye" and "hair color | hair dye" are all one product. "Root touch-up powder", "Root Touch Up Powder" and "Hair root touch-up powder" are one product. 12 ads had no Product.'));
c.push(P('**Why it matters.** The SKU filter, every product-level number and the Experimentation Lab need one name per product. With raw values the same product is split into many small groups, each too small to analyse.'));
c.push(P('**Requirement.** Developers must add a step after extraction that gives every ad one clean product name. Use aggregation or clustering of the Product values. The method is up to developers. For example, cluster the Product values with the same approach and memory as the clustering prompt, or match them to a list of known products. Whatever is used, it must meet the rules below.'));
c.push(P('**Rules**'));
c.push(B('Every product has exactly one name in the whole account. "Hair color" and "Hair Colour | Hair Dye" must end up as the same name.'));
c.push(B('Names are short and human-readable, for example "Hair Colour / Hair Dye", "Night Repair Cream", "Root Touch-Up Powder".'));
c.push(B('Names are stable. A product keeps its name on every refresh. Keep a saved list of product names (like the cluster memory) and reuse a name whenever a new value fits it.'));
c.push(B('An ad that shows more than one product is a combo ad. Set `is_multi_sku` to true and keep it in its own group. Never split it across products and never count it twice.'));
c.push(B('An ad with no Product value gets the name "Unclassified". It is shown under "Unclassified" in the SKU filter.'));
c.push(B('Do not hard-code product names for one account. The step must work for any account.'));
c.push(B('Maths still happens in code. Counts and spend per product are calculated by the backend after names are fixed.'));
c.push(B('Save the product name per `ad_id` in the same cache as the other steps. Only ads without a product name are processed on a refresh.'));
c.push(P('**Output per ad:** `skus` (a list with the clean product name or names) and `is_multi_sku` (true or false).'));
c.push(H3('Acceptance criteria'));
c.push(B('No two product names in the SKU filter refer to the same product.'));
c.push(B('Each product appears once in the SKU filter, with the right ad count.'));
c.push(B('The ad counts of all products, plus combo ads and Unclassified, add up to the total number of ads.'));
c.push(B('Running the report twice on the same data gives the same product names.'));

c.push(H1('7. Step 6: Join and save'));
c.push(P('One record per ad. The whole report reads only these records.'));
c.push(table(['Report field','Comes from'],[
 ['ad_id, status, media_type, creative_url, thumbnail','API'],
 ['spend, revenue, roas, cpr, frequency, lpv, atc, conversion','API (total_spend, purchase_value and so on)'],
 ['skus, is_multi_sku','Step 5: clean product name (section 6).'],
 ['approach','Extraction: Customer life cycle.'],
 ['is_creator_led','Extraction: creator_presence (anything other than "no person").'],
 ['Stage angles (Problem Statement, Hook Line, Primary USP Claim, Use Case Scenario, CTA Text, and the 5 optional stages)','Clustering: cluster label for each free-text field.'],
 ['campaign_id, campaign_name','API (new fields, see section 3).'],
 ['classified (true or false)','False for ads that failed extraction or had no creative.'],
],[4300,5060]));

c.push(H1('8. Caching and refresh'));
c.push(B('**What is cached:** extraction output per `ad_id`, cluster labels per `ad_id`, clean product name per `ad_id`, the cluster memory per field, and the saved list of product names.'));
c.push(B('**Where:** developers choose (for example Redis). The prompt files mention browser storage. That was for the prototype. Production uses backend storage.'));
c.push(B('**On refresh or on a new report:** pull the data again. Run extraction only for ads not in the cache. Run clustering only for ads without labels, using the saved cluster memory. Then join and save.'));
c.push(B('**Result:** an unchanged ad is never processed twice. A refresh of an old account is fast. Signal B is sent when the last new ad is done.'));

c.push(H1('9. Signals'));
c.push(table(['Signal','Sent when'],[
 ['A','Step 2 finished. All pages pulled.'],
 ['B','Steps 3 to 6 finished for all ads.'],
 ['C','The insight prompt has finished (PRD 1, Appendix A).'],
 ['D','The Lab computations are finished (separate PRD).'],
],[1500,7860]));

c.push(H1('10. Failure Handling'));
c.push(table(['Case','What should happen'],[
 ['API call fails or times out','Retry. If it still fails, mark the report failed and show the error state with Retry. Nothing else runs.'],
 ['No ads returned','Show the empty state from PRD 1. Do not run any prompt.'],
 ['Extraction returns invalid JSON for an ad','Retry. Then mark that ad "unclassified" and continue.'],
 ['Clustering call fails','Retry. If it still fails, do not send Signal B. Signal A sections stay usable.'],
 ['Product naming step fails','Retry. If it still fails, do not send Signal B. Signal A sections stay usable.'],
 ['Clustering drops or invents an ad_id','Reject the output and retry. Every input ad_id must appear exactly once per field.'],
 ['Process stops half way','Next run continues from the caches. Already processed ads are not repeated.'],
],[3600,5760]));

c.push(H1('11. Open Questions'));
c.push(N('Product naming: which method will developers use (clustering with saved memory, or matching to a known product list)? Either must meet the rules in section 6.'));
c.push(N('Credibility signal: should it cluster by role (for example "Dermatologist") or by name? Still open in the clustering notes.'));
c.push(N('Which model runs each prompt, and what is the cost limit per ad?'));
c.push(N('Should a cached extraction be redone when the creative on an ad changes? If yes, what detects a change?'));
c.push(N('Cache lifetime: keep forever or expire after some days?'));

c.push(new Paragraph({children:[new PageBreak()]}));
c.push(H1('Appendix A: Extraction Prompt'));
c.push(P('Used in step 3. Copied as it is.'));
c.push(...codeBlock(extraction));
c.push(new Paragraph({children:[new PageBreak()]}));
c.push(H1('Appendix B: Clustering Prompt'));
c.push(P('Used in step 4. The prompt is built in code. The section "EXISTING CLUSTER LABELS" is inserted near the top when cluster memory exists. {{ads_json}} is replaced with the ads to cluster. Copied as it is.'));
c.push(...codeBlock(clustering));
c.push(gap());
c.push(H1('Appendix C: Sample API Response'));
c.push(P('One ad from the sample response.'));
c.push(...codeBlock(JSON.stringify(JSON.parse(fs.readFileSync(D+'docs/samples/api_sample_8_ads.json','utf8')).data.data[0],null,2)));
c.push(...codeBlock('...pagination: { "current_page": 1, "total_pages": 1, "total_elements": 8, "size": 8, "has_next": false }'));


const doc=new Document({
  styles:{default:{document:{run:{font:'Arial',size:21}}},paragraphStyles:[
    {id:'Heading1',name:'Heading 1',basedOn:'Normal',next:'Normal',quickFormat:true,run:{size:30,bold:true,font:'Arial'},paragraph:{spacing:{before:320,after:120},outlineLevel:0}},
    {id:'Heading2',name:'Heading 2',basedOn:'Normal',next:'Normal',quickFormat:true,run:{size:24,bold:true,font:'Arial'},paragraph:{spacing:{before:220,after:80},outlineLevel:1}}]},
  numbering:{config:[
    {reference:'bul',levels:[{level:0,format:LevelFormat.BULLET,text:'•',alignment:AlignmentType.LEFT,style:{paragraph:{indent:{left:540,hanging:270}}}},{level:1,format:LevelFormat.BULLET,text:'–',alignment:AlignmentType.LEFT,style:{paragraph:{indent:{left:1000,hanging:270}}}}]},
    {reference:'num',levels:[{level:0,format:LevelFormat.DECIMAL,text:'%1.',alignment:AlignmentType.LEFT,style:{paragraph:{indent:{left:540,hanging:360}}}}]}]},
  sections:[{properties:{page:{size:{width:12240,height:15840},margin:{top:1296,right:1440,bottom:1296,left:1440}}},children:c}]
});
Packer.toBuffer(doc).then(b=>{fs.writeFileSync('PRD_2_Input_Data_Processing.docx',b);console.log('ok')});
