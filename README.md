# Creative Intelligence

A report that turns Meta ad data into creative insight. The user picks an ad account and a date range. The report then shows how the account performs, which creative choices are behind that performance, and a data-backed creative recipe.

The app is one self-contained HTML file with three tabs:

| Tab | What it does |
|---|---|
| **Creative Overview** | Performance summary, format split, spend efficiency, creative metric explorer, creative stage overview. |
| **Insights & Actionables** | Four insight cards, creative ranking engine, recipe suggestion, winning and losing angles, 2D heatmap, 3D combination lab. |
| **Experimentation Lab** | Pick a product, click one button, get a creative recipe with a predicted ROAS and a full six-step walkthrough. |

Status: front-end prototype. All data is embedded in the HTML. In production every calculation runs in the backend and the front end only displays results (see the PRDs).

## Run it

```bash
open app/creative-intelligence.html
# or serve it
cd app && python3 -m http.server 8934     # http://localhost:8934/creative-intelligence.html
```

No build step and no install. Fonts load from Google Fonts and the "View" links open ad creatives hosted on S3, so those need internet.

Ad thumbnails are not stored in this repo (they are client creatives). Without the `thumbs/`, `cre-thumbs/`, `cmt-thumbs/`, `shesha-thumbs/` folders next to the HTML, thumbnail images show as empty. Everything else works.

Dark and light themes are built in (toggle at top right). The light theme follows the warm design-system tokens.

## How it works

```
Meta API  ->  extraction prompt  ->  clustering prompt  ->  product naming  ->  ad records
 (ads +        (reads each ad          (groups free text        (one clean name      |
  metrics)      creative)               into angles)             per product)        v
                                                                    insight prompt -> 4 insight cards
                                                                    Lab model      -> recipes + predicted ROAS
```

Four backend signals decide what unlocks and when (A: Meta data, B: classification, C: insights, D: Lab). Details are in PRD 1, section 4.3.

## Repository layout

```
app/                         The product: creative-intelligence.html (all three tabs, data embedded)
prompts/                     Every prompt used
    extraction_prompt.md         Step 1: classify each ad (fixed fields + free text)
    clustering_prompt.md         Step 2: group free text into angles, with cluster memory
    insight_unified_prompt.txt   Writes the 4 insight cards from a pre-computed candidate pack
    archive/                     Older per-level insight prompts (Account, Campaign, SKU). Not used now.
insight-engine/              Builds the candidate pack the insight prompt reads, plus checks
    build_insight_inputs.js      Computes all numbers, rankings and thresholds (the prompt does no maths)
    verify_insights.js           Checks generated insights against the numbers
    test_semantic_guard.js       Regression test for product and angle sanity rules
    insight_inputs.json          Current candidate pack
    generated_insights.json      The 4 insights shown in the app
experimentation-lab/         The recipe model and the Lab UI source
    hybrid.py                    Spend-weighted ridge model (generalised DerSimonian-Laird shrinkage)
    exp_compare.py, evalh.py     Data loading, CatBoost model, cross-validation harness
    cred.py, perm.py             Credibility model and label-shuffle test
    evalrecipe.py, confirm.py    Recipe-level hidden-ad test and the full confirmation run
    final_recipes.py             Fits on all data and writes final_results.json
    export_steps.py              Writes steps_data.json, the data the Lab tab displays
    lab-ui-*.js, lab-*.css       Lab UI source (start screen, loader, result, walkthrough)
    build_steps.py               Builds a standalone Lab page
    merge_lab_into_ci.py         One-time script that merged the Lab into the app (already applied)
    *.json                       Lab data and results
prd/                         PRD 1 (Creative Intelligence Report) and PRD 2 (Input Data Processing), .docx, plus the scripts that generate them
docs/                        Project skill/context, Lab methodology, plain-language Lab explainer, API sample response
```

## Prompts

| Prompt | Input | Output |
|---|---|---|
| `extraction_prompt.md` | One ad creative (video or image) | JSON with product, category, life cycle, style fields and free-text fields (problem, hook, USP, use case, CTA and more). Runs on every ad that is not cached. |
| `clustering_prompt.md` | Free-text values of all ads, plus saved cluster labels | Clusters (angles) per field and the updated label list. Labels are reused across runs. |
| `insight_unified_prompt.txt` | Candidate pack from `build_insight_inputs.js` | Up to 4 insight cards. Quotes numbers only from the pack and never calculates. |

All metric maths (ROAS, counts, spend) happens in code, never in a prompt.

## Experimentation Lab

For one product, the Lab scores every supported combination of angles (one per stage) and returns the best recipe with a predicted ROAS.

- **Method:** ads are weighted by spend, angle effects are shrunk toward the product average, and a regularised statistical model is averaged with CatBoost.
- **Testing:** on ads held out of training, the blend has an error of 0.328 against 0.375 for the product average. A label-shuffle test confirmed the signal is real. The size of the gain per product could not be confirmed with 251 ads, so the UI says "predicted" and recommends testing against a control.
- **Eligibility:** a product needs 15+ ads, Rs3 lakh+ spend, and angles with 2+ ads in every stage.
- **Rebuild the results:**

```bash
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
mkdir -p source-data   # put 'Shesha Full Creatives Analysis.csv' here, or set CI_SOURCE_CSV
cd experimentation-lab
python3 final_recipes.py      # fits on all data, writes final_results.json
python3 export_steps.py       # writes steps_data.json
```

The Lab tab embeds `steps_data.json` inside the HTML, so a re-export needs the new data to be written into `app/creative-intelligence.html`.

Methodology in plain words: `docs/Experimentation_Lab_explained.md` and `docs/Experimentation_Lab_Explained.html`. Full method reference: `docs/experimentation-lab-methodology.md`.

## Product docs

- `prd/PRD_1_Creative_Intelligence_Report.docx`: landing page, staged loading and unlock signals, the three tabs, edge cases, metrics. Appendix A holds the insight prompt.
- `prd/PRD_2_Input_Data_Processing.docx`: the data pull, extraction, clustering, product naming, caching and refresh, failure handling. Appendices hold both prompts and a sample API record.
- `docs/samples/api_sample_8_ads.json`: the shape of the table-report API response.

## Placeholders and open items

- **Generate Creative** and **Take Action** buttons are placeholders. They are out of scope for this version.
- The Lab's predicted ROAS and walkthrough are precomputed. A backend job must produce them for real accounts.
- The campaign filter needs `campaign_id` and `campaign_name` added to the table-report API response (PRD 2).
- Product names need a naming step that gives one clean name per product (PRD 2, section 6).

## Conventions

- Plain written copy, no em dashes in deliverables.
- INR shown with L and Cr (for example Rs38.65L). ROAS to two decimals with an x.
- Use "angle" in the UI, never "cluster".
