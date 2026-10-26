---
name: creative-intelligence-skill
description: Full project context for "Creative Intelligence", a feature being designed and built inside fastrr Ads. Covers the product vision, vocabulary, data model, the insight-generation prompt system, the combined single-page HTML build (Creative Overview + Insights & Actionables tabs) with exact architecture, every bug found and fixed with root cause, open TODOs, and this user's working style. Load before continuing any Creative Intelligence discussion or build work in a future session, so context does not need to be re-derived from scratch.
---

# Creative Intelligence — project context

## 0. Where the actual build lives (read this first)

- **Local working file (source of truth, edit this one):**
  `~/Downloads/PROMPTS/build/ci/creative-intelligence.html`
  Single self-contained HTML file. No external data file, no build step.
  The entire dataset (`DATA` object: ads, stage_defs, skus) and the fastrr
  logo (base64 PNG) are embedded directly in the file.
- **Run it locally:** either double-click it to open via `file://` (it is
  fully self-contained, nothing is fetched), or serve it properly:
  ```
  cd ~/Downloads/PROMPTS/build/ci && python3 -m http.server 8934
  ```
  then open `http://localhost:8934/creative-intelligence.html`.
- **Published live artifact (kept in sync, republish after every edit):**
  https://claude.ai/code/artifact/8c478473-25d4-4f24-91e3-2bda23f3b7a5
  Owned by this user, shared org-wide as writer. To update it: read this
  file fresh, make edits, then publish with `url` set to that link so it
  overwrites in place rather than forking a new artifact.
- **Original Creative Overview-only artifact** (superseded, do not edit,
  kept only as the historical starting point):
  https://claude.ai/code/artifact/8c9448c2-c9a3-4786-8e67-42b3d5768c3f
- **Prompt files** (SKU/Account/Campaign DO-STOP insight generation,
  not yet wired into the UI, insight cards are still mock): four `.txt`
  files directly under `~/Downloads/PROMPTS/`, listed in full in
  section 4 below.
- **Source dataset this was built from:**
  `~/Downloads/Shesha Full Creatives Analysis.csv` (350 rows, 288 unique
  ads after dedup by `ad_id`). The `DATA` object embedded in the HTML is
  the already-aggregated, already-canonicalized output of that CSV — do
  not re-derive it from the CSV again, it is baked into the file.


## 1. Product vision
"Creative Intelligence" is a section inside the existing fastrr Ads web
app (not a standalone product). It sits in the left nav alongside
Overview, Insights, Meta Insights, Create, My Requests, Monitor.

Core purpose: NOT a dashboard, NOT a data dump. It is an insight/actionable
feed. The explicit, repeated instruction from the user: "I don't want heavy
data points or dashboards, I want actionable insights hidden to the
marketer that we can excavate from the data." Every screen must answer
"what should I do" and "what should I stop," not just display numbers.

Target user: brand managers and their teams running Meta ads for a brand
on the platform. Multi-tenant by design (works for any brand, Shesha's
data is only the prototyping dataset).

Governing rule for every insight (THE OBVIOUSNESS FILTER): before
shipping any insight, ask "would an experienced brand manager already
believe this without looking at THIS data?" If yes, discard it, a true
fact is not an insight. Permanent rejected-anti-pattern example: "CTA
'Comment for link/info' is half your account's spend, in line with
average, nothing to fix here" — generic platform knowledge, and the
card's own conclusion was "nothing to do," which means it should never
have been generated.


## 2. Vocabulary (use exactly these terms, do not invent synonyms)
- **STAGE** — a fixed part of an ad's structure. 5 mandatory (present in
  nearly every ad): Problem Statement, Hook Line, Primary USP Claim, Use
  Case Scenario, CTA Text. 5 conditional: Testimonial Claim, Proof Points,
  Credibility Signal, Offer Details, Comparison Axis. In code, stage keys
  are hyphenated (`hook-line`, `primary-usp-claim`, `use-case-scenario`,
  `cta-text`, `problem-statement`, `testimonial-claim`, `proof-points`,
  `credibility-signal`, `offer-details`, `comparison-axis`) — this is the
  real `STAGE_DEFS` array's `.key` field, sourced from `DATA.stage_defs`.
- **ANGLE** — the specific, canonicalized creative choice within a stage
  (e.g. within Hook Line, "Direct grey hair problem"). Never say "cluster"
  in UI copy or insight text.
- **APPROACH** — the ad's overall persuasion strategy: Push Product / Push
  Problem / Push Differentiation / Push Brand / Push Offer. This is NOT
  customer lifecycle despite the source CSV column being named "Customer
  life cycle" — see gaps below.
- **LEVEL** — the scope being analyzed: Account, Campaign, SKU (Category
  is out of current scope).
- **SKU** — one of 10 canonical products in `DATA.skus`: lip-balm,
  root-touch-up-powder, hair-colour-dye, tan-removal, kumkumadi-oil,
  night-repair-cream, hair-oil, day-cream, face-wash, face-serum. An ad's
  `skus` field is an ARRAY (supports multi-SKU/combo ads); `is_multi_sku`
  is `true` when it spans more than one. Combo ads are always kept in
  their own bucket, never split or double-counted into single-SKU rollups
  (enforced everywhere via `ad.skus.length===1 && ad.skus[0]===X` checks).


## 3. Data model: `DATA` object shape (embedded in the HTML)

```js
DATA = {
  meta: {
    source: "Shesha Full Creatives Analysis.csv",
    total_ads: 288,
    sku_coverage_note: "...", campaign_coverage_note: "...",
    partnership_proxy_note: "...",
  },
  stage_defs: [ {key, label, mandatory: bool, question}, ... ],  // 10 entries
  skus: [ {id, name}, ... ],  // 10 canonical SKUs, see above
  ads: [
    {
      ad_id, creative_id, creative_url, media_type, status,
      skus: string[], is_multi_sku: bool, category, campaign: string|null,
      approach, is_creator_led: bool,
      spend, revenue, roas, ads_count, frequency,
      lpv_pct, atc_pct, conv_pct,
      stages: { "<stage-key>": "<angle label>" | "" },  // 10 keys
    }, ...
  ]
}
```

**Real, currently-unsolved data gaps** (CSV-era limitations, expected to
resolve once this runs on the live Meta API instead of a CSV export):
- `campaign` is non-null on only 84/288 ads (~29%), extracted from
  `ad_name` via a `cis_XXXX`-style regex, not a real Meta campaign ID.
- No real Partnership Ads field; `is_creator_led` is a proxy from
  `creator_presence`.
- No real new-vs-returning-customer field; `approach` is a persuasion-
  strategy tag, not lifecycle, despite the source column's misleading name.
- No timestamps anywhere in the data. Any staleness/decay/time-based
  insight type is **permanently blocked** until real dated data exists —
  never approximate this with row order or ad_id ordering (this was
  explicitly called out and rejected earlier in the project).


## 4. Insight generation prompt system (NOT yet wired into the UI)

Four fully self-contained prompt files exist under `~/Downloads/PROMPTS/`,
each scope-locked to one Level so materiality thresholds stay calibrated
to that altitude. **The Insights & Actionables tab's insight cards are
still hardcoded mock content** (`IA_MOCK_CARDS` in the HTML) — these
prompts have not been connected to an LLM call or wired to render real
cards yet. That is the next major piece of work on this project.

- `Creative Intel - Account Level DO-STOP Insight Prompt.txt` — DO/STOP
  for the whole account, thresholds: DO needs n_ads>=5, roas>=1.2x
  baseline, spend_share<3% (fallback n>=3, roas>=1.3x); STOP needs
  spend_share>=15% plus fatigue/broken_stage/drag diagnosis, preferred in
  that order.
- `Creative Intel - Campaign Level DO-STOP Insight Prompt.txt` — same
  shape, proportionally smaller thresholds (DO: n>=3, roas>=1.2x
  baseline, spend_share<10%; STOP: spend_share>=25%), explicitly must not
  duplicate what the SKU Composition / Creative Concentration structural
  cards already show.
- `Creative Intel - SKU Level (All SKUs) Insight Prompt.txt` — inter-SKU
  portfolio intelligence: Angle Transfer/Whitespace (proven angle on SKU
  A never tried on sibling SKU B, same Category), Portfolio Truth vs SKU
  Noise (a pooled-looking pattern must independently hold in >=70% of
  SKUs with enough sample to be called a real cross-SKU truth, otherwise
  output a DEBUNKED verdict naming which SKU is carrying the pooled
  average), Angle Staleness (**permanently blocked**, no timestamps).
- `Creative Intel - SKU Level (Specific SKU) Insight Prompt.txt` — intra-
  SKU intelligence: Stage-Pairing Chemistry (a specific two-stage angle
  pair beating the stronger of its two solo averages by >=25%, this is
  exactly what the 3D/2D heatmaps visualize), Approach Alignment
  (dominant-by-spend Approach vs best-performing-by-ROAS Approach
  mismatch — the rebuilt, data-honest version of "customer type
  alignment"), Underused Stage (a stage used in <=15% of this SKU's ads
  but outperforming by >=1.3x when it is used, floor n>=2 since scarcity
  is the point, action is always "test more," never "scale budget").

All four share the same skeleton: ROLE, VOCABULARY, obviousness filter +
a permanent rejected example, a 4-part REAL-candidate test (hidden,
material, actionable, explained), a selection algorithm with numeric
thresholds and a widen-once-then-decline-rather-than-fabricate fallback,
strict JSON output with `"available": false` + `"reason"` when nothing
clears the bar, and a worked example for calibration. Follow this exact
shape if writing a fifth prompt.


## 5. The build: single HTML file architecture

Everything lives in one file. It renders a fastrr-Ads-style shell: a left
sidebar built from a `NAV` array, and a `#content` area whose contents
are swapped by a tiny router. There is no framework — plain template-
literal strings assembled into `innerHTML`, re-rendered on every state
change (the same pattern the original Creative Overview build already
used, kept consistent rather than introducing a different style for the
new tab).

### 5.1 Routing
```js
const NAV = [
  {section:'OVERVIEW', items:[{key:'home', label:'Home', ico:'home'}]},
  {section:'INSIGHTS', items:[...3 disabled placeholder items...]},
  {section:'CREATIVE INTELLIGENCE', items:[
    {key:'creative-overview', label:'Creative Overview', ico:'target', live:true},
    {key:'insights-actionables', label:'Insights & Actionables', ico:'sparkle', live:true},
    {key:'experimentation-lab', label:'Experimentation Lab', ico:'bars'},  // no live:true -> renders disabled + "Soon" badge
  ]},
  ...META INSIGHTS / CREATE / MY REQUESTS / MONITOR sections, all disabled placeholders...
];

const state = {
  page:'creative-overview',            // 'creative-overview' | 'insights-actionables'
  account, campaign, sku, creative, creativeType, dateRangeMonths,
  formatSplitMode, effCampaign, stageFocus, sidebarCollapsed,
  iaLevel:'account', iaCampaign:'all', iaSku:'all',   // Insights & Actionables' own pills
};

function render(){                      // the ONE true entry point
  renderSidebar();
  updates #breadcrumb text based on state.page;
  if(state.page==='insights-actionables') renderInsightsActionables();
  else renderCreativeOverview();
  wires every [data-nav] click to set state.page and call render() again;
}
```
**Any control that changes routing or the sidebar MUST call the top-level
`render()`, never `renderSidebar()` alone** — a bug shipped earlier where
the collapse toggle called only `renderSidebar()`, which rebuilds the nav
items fresh but never re-attaches their click handlers (those are wired
inside `render()`), silently breaking every nav click after a single
collapse/expand. Fixed by routing the toggle through `render()` too.

Adding a new live tab: add a NAV entry with `live:true`, add a branch in
`render()`'s if/else, write `render<TabName>()` self-contained (build its
own HTML string, set `#content.innerHTML`, then wire its own controls).

### 5.2 Creative Overview (`renderCreativeOverview`)
Unchanged in overall shape from the original standalone build: config bar
(Ad Account/Campaign/SKU/Creative/Creative Type/date-range), Performance
Summary (4 cards), Format Split donut + Spend Efficiency side by side,
Creative Stage Overview (Spend-vs-Revenue chart + a Ranking list).

Changed in this project's later sessions:
- **Funnel Tier pills (Mandatory/Conditional/All) removed entirely.**
  Replaced with a single horizontal row of all 10 stages as pills
  (`.stage-pill-row` / `.stagepill`, one per `STAGE_DEFS` entry, `state.
  stageFocus` set directly on click). Conditional stages get a small
  dot badge (`.optdot`, title="Conditional stage") so that distinction
  isn't lost without the tier filter.
- **Ranking list now has a Spend column.** `hBar()` gained a
  `opts.showSpend` / `item.spendLabel` path rendering `.hbar-spend`, and
  a `.hbar-header` row (Angle / ROAS / Ads / Spend) sits above the list
  so it reads as a real table, not an unlabeled bar chart.

### 5.3 Insights & Actionables (`renderInsightsActionables`) — the new tab
Structure top to bottom, exactly per the user's explicit spec: **pills,
then insight cards, then winning/losing table, then 2D heatmap, then 3D
heatmap.**

**Pills** (`renderIaPills`): a 3-way `.pill-toggle` (Account/Campaign/
SKU, `state.iaLevel`). Selecting Campaign reveals an `xselect` dropdown
of real campaign codes ranked by ad count (`iaCampaignOptions()`) plus
All Campaigns / Unattributed. Selecting SKU reveals an `xselect` of the
10 real SKUs plus All SKUs, each showing its live ad count
(`iaSkuAdCount`). Scoping is `iaScopedAds()` — filters `DATA.ads` by
`iaLevel`/`iaCampaign`/`iaSku`, and **every section below inherits this
same scope** (the 2D/3D heatmaps do NOT have their own separate SKU
filter, by deliberate design decision, to keep one source of truth for
"what am I looking at" on this page).

**Insight cards** (`renderIaInsightCards`): 4 cards, **still 100% mock
content** (`IA_MOCK_CARDS`: DO/STOP/CHEMISTRY/WHITESPACE), each clearly
labeled "Mock preview — prompt-based insights come next." Redesigned
with a tone-colored icon chip, a colored top accent bar
(`--accent-color` inline var mapped to `--color-status-<tone>`), and a
pill-style mock badge — all using tokens already defined elsewhere in
the file, not new ones. **This is the piece still waiting on the section
4 prompts being wired to a real LLM call.**

**Winning & Losing Combinations** (`renderIaComboTable` /
`iaComboRows` / `renderIaComboRow`): pools every (Stage, Angle) pair
across all 10 stages within the current scope, floor n>=3 ads and
spend>0, ranks top 5 by ROAS descending (Winning) and ascending
(Losing). Each row is its own rounded card (not a flat list) with a
rank badge, the angle name, a sub-line (STAGE · dominant-SKU-in-group ·
n ads · spend), a tier-colored ROAS value, and a **real "View" link**
that opens the `creative_url` of the single highest-spend ad backing
that combination in a new tab (`repAd`/`repAdId`/`creativeUrl` tracked
per group in `iaComboRows`). If no creative URL exists the link renders
disabled instead of dead.

**2D heatmap** (`mountIaHeatmap2D`): pick any two stages as X/Y, angle x
angle grid (top 6 angles per axis by ad count), Min ads/cell AND **Min
spend/cell** sliders (both must clear for a cell to count as sufficient),
4 quick-view presets, solid tier-colored fill cells (white bold text,
not the earlier low-opacity-tint-plus-border look), a continuous-ish
color read via `iaRangeHeatColor`/`iaRobustDomain` scaled to what's
actually on screen. Self-mounted: owns its own local `st` object and
redraws only its own `#ia2dRoot` subtree on interaction, independent of
the page-level `render()`.

**3D heatmap** (`mountIaHeatmap3D`): the rotatable cube lab. X/Y/Z stage
pickers, Min ads/cell AND Min spend/cell sliders, 4 quick-view presets,
Reset view. Built entirely from CSS 3D transforms (no WebGL, no
external library) — cubes are 6 absolutely-positioned `<div>` faces
under `transform-style:preserve-3d`; axis lines and the leader-lines to
staggered tick labels are drawn as dense chains of tiny cubes
(`beadLine`), never as long flat planes (see bug list below for why).
Value labels and axis titles are billboarded (`addBillboard`/
`applyBillboard`, counter-rotate by `-state.ry/-state.rx` so they always
face the camera). Idle auto-rotate: a `requestAnimationFrame` loop turns
the cube slowly after ~2.6s of no interaction, guarded by an
`IA3D_MOUNT_TOKEN` counter so a stale loop from a previous mount (e.g.
after changing the top-level pills, which fully re-renders the page)
stops itself for good instead of leaking forever. Graphic polish pass:
rounded/glossy cube faces, per-cube drop shadow, a colored floor glow
under each cube matching its own color, glowing axis rods.

### 5.4 Shared helpers worth knowing about
- `esc()` — general HTML-escape (safe for text nodes AND attribute
  values, since it also escapes `<`/`>`).
- `tipHtml(title, rows)` — returns real, structural HTML for a tooltip
  (escapes only the leaf text via `esc()` internally). Use this whenever
  setting `.dataset.tip` or `.innerHTML` **directly via JS** (no HTML
  parsing involved).
- `tipAttr(title, rows)` — `esc(tipHtml(...))`, i.e. double-escaped. Use
  this ONLY when embedding into an HTML **template string** as an
  attribute value (`data-tip="${tipAttr(...)}"`) that will later be
  parsed by the browser via an `innerHTML` assignment — the browser
  un-escapes it once during parsing. **Never use `tipAttr` for a direct
  `el.dataset.tip = ...` JS assignment** — see bug list, this was a real
  shipped bug.
- `wireTooltips(root)` — finds every `[data-tip]` under `root`, wires
  mouseenter/mousemove/mouseleave to a single shared `#chartTooltip` div,
  setting `.innerHTML = el.dataset.tip` (expects real HTML, not escaped).
- `fmtINR`, `fmtNum`, `fmtRoas`, `tierOf(roas)`, `tierColor(tier)` — the
  ROAS quality ladder is poor(error/red) < average(warning/amber) <
  good(info/blue) < excellent(success/green). Reuse this everywhere a
  quality judgment is being color-coded; never invent a new scale.
- `xselect(opts)` + `wireXSelects(root, handlers)` — the reusable
  searchable-dropdown component; `opts.id` must match a key in the
  `handlers` object passed to `wireXSelects`.


## 6. Design tokens actually in use (CSS variables, real values)
```
--color-surface-page:#0b0b10   --color-surface-card:#131319
--color-surface-card-deep:#0f0f15   --color-surface-chip:#191922
--color-text-heading:#f5f4f9   --color-text-secondary:#c1bfcf
--color-text-muted:#9a97ac   --color-text-subtle:#847f98   --color-text-faint:#5d5a6d
--color-text-accent:#c1a3f5
--color-border-default:rgba(255,255,255,.07)   --color-border-strong:rgba(255,255,255,.13)
--color-border-purple:#8b6ae0
--color-accent:#a78bfa   --color-accent-soft:rgba(167,139,250,.12)
--gradient-primary:linear-gradient(100deg,#ec4899,#a855f7)   -- reserved for a few real moments only (active nav item, active pill, top accent bars), never spread decoratively
--color-status-success:#3ecf8e (excellent)  --color-status-info:#5b9df9 (good)
--color-status-warning:#e8a53d (average)    --color-status-error:#ea5470 (poor)
--radius-sm:8px --radius-md:10px --radius-lg:12px --radius-xl:16px --radius-pill:999px
--sp-1:4px ... --sp-8:40px (4px-step spacing scale)
--font-primary:'Plus Jakarta Sans'   --font-mono:'Inter' (used for all tabular numbers via the `.tabnum`/`.num` class)
```
3D-lab axis identity colors are a separate pink/purple/lavender trio
(`#a78bfa` / `#ec4899` / `#f0abfc`) deliberately chosen to NOT collide
with the green/blue/amber/red ROAS quality scale used for cube fill —
axis color means "which axis," never "how good."


## 7. Bugs found and fixed this project — root causes worth remembering
1. **CSS `transition: grid-template-columns` got the sidebar collapse
   stuck.** Animating `grid-template-columns` is unreliable across
   browsers; here it left the layout computing the pre-collapse 228px
   forever instead of settling on 66px, even though the `.collapsed`
   class and the more-specific CSS rule were both definitely applied.
   Fix: removed the transition, collapse now snaps instantly (correct
   and simpler, don't re-add animation on this property).
2. **Sidebar-collapsed brand text overflow.** Only the "ADS" subtitle
   span was hidden on collapse, not the "fastrr" `<b>` wordmark, which
   then overflowed the narrow 66px rail. (Superseded: brand is now a
   single logo `<img>`, this whole class of bug no longer applies, but
   the lesson — audit ALL text nodes in a container before assuming a
   narrow-mode CSS rule is complete — still applies elsewhere.)
3. **Nav icons vanished when collapsed.** `.sidebar.collapsed .nav-item
   span{display:none}` (meant to hide the text label) also matched the
   icon's own `<span class="ic">` wrapper, since both are plain `<span>`
   elements. Fixed with `:not(.ic)` on the selector. This was a
   pre-existing bug in the original Creative Overview build, not
   something introduced later — worth a broader audit if more
   collapse-mode rules get added.
4. **Nav clicks died after toggling collapse.** The collapse button's
   onclick called `renderSidebar()` directly instead of the top-level
   `render()`. `renderSidebar()` rebuilds the nav DOM nodes fresh but the
   `[data-nav]` click handlers are only (re-)attached inside `render()`.
   Fixed by routing the toggle through `render()`.
5. **3D heatmap tooltips showed raw escaped HTML as literal text**
   (`&lt;div&gt;...`) instead of rendering. Cause: `cube.dataset.tip =
   tipAttr(...)` — `tipAttr` double-escapes for safe embedding in an
   HTML template string, but this was a **direct JS property
   assignment**, which never goes through HTML parsing, so the escaped
   entities were never decoded back and got shown as literal text. Fixed
   by using `tipHtml(...)` (single-escaped at the leaf only) for every
   direct `.dataset.tip =` assignment; keep `tipAttr` only for
   `data-tip="${...}"` inside template strings.
6. **3D cube floor-glow silently didn't render.** Built the glow color
   as `` `${color}59` `` to add alpha — this only works for hex colors
   (`#rrggbb` + 2-hex-digit alpha); `color` here is an `rgb(r,g,b)`
   string from `iaRangeHeatColor`, so appending `59` produced invalid
   CSS that the browser silently dropped. Fixed with a proper
   `iaToRGBA(rgbStr, alpha)` helper that parses the rgb components and
   rebuilds a valid `rgba(...)`.
7. **3D axis rod rendered as two visibly separate parallel lines** at
   certain rotation angles. First attempt built each axis as a hollow
   box (6 faces like a mini cube) — two of its opposite faces sit offset
   by half the tube's thickness from the true centerline, and at a
   raking view angle that offset becomes visually obvious as "two
   rails." Second attempt (two infinite cross-planes exactly through
   the centerline, mathematically correct) still glitched — two large,
   long, coplanar/intersecting flat planes trigger real z-fighting in
   CSS 3D, which has no true z-buffer, just an approximate depth sort.
   **Final, robust fix: render the axis as a dense chain of small
   independent cubes** (`beadLine`), the same primitive already proven
   correct for tick-dots — no long flat geometry left to fight over.
8. **3D X-axis title was invisible / mis-placed.** Two distinct issues
   stacked: first it was positioned at the exact horizontal center of
   the grid (under the cube cluster, so cubes occluded it) instead of
   past the axis's far end like the Y and Z titles. After moving it to
   the far end, it then clipped outside the `.ia3d-stage` container's
   `overflow:hidden` bounds — because in true 3D with active rotation, a
   position offset that "reads the same" numerically as the Y/Z titles'
   offsets does **not** project to the same screen position; each axis
   needed its own empirically-checked offset (verified via
   `getBoundingClientRect()` against the stage container's rect, not by
   eyeballing a screenshot).

**General lesson for this session's environment**: the Browser-pane tool
used to test this build was frequently reported as "hidden" mid-session,
which made screenshots occasionally render blank even when the DOM was
100% correct (confirmed repeatedly via direct `getComputedStyle`/
`getBoundingClientRect` checks showing correct colors, text, and
geometry). When a screenshot looks wrong but a fix should obviously have
worked, verify with JS DOM introspection before assuming the code is
broken — and when it truly needs a pixel-accurate check (like the 3D
label-clipping bugs above), the DOM/rect check is more reliable than the
pane's screenshot in this environment anyway.


## 8. Open TODOs (in the order the user has been working)
1. Wire the section 4 prompts to a real LLM call and replace
   `IA_MOCK_CARDS` with real generated DO/STOP/CHEMISTRY/WHITESPACE
   cards (or whichever types the actual model output settles on).
2. Build out `experimentation-lab` (currently just a disabled "Soon" nav
   item, intentionally greyed out per explicit request — do not build
   until asked).
3. A second thematic design reference was offered by the user but not
   yet supplied ("if you want more thematic reference I can share that
   as well") — ask for it before doing another broad visual pass if one
   is requested again.
4. The 2D heatmap's 3rd-stage filter slice control (present in the very
   early conceptual spec) was never carried into the final build; not
   confirmed as still wanted.
5. Category-level scoping remains explicitly out of current scope (was
   discussed early, deliberately deferred, not part of the Account/
   Campaign/SKU pill set).


## 9. This user's working style
- Wants short, direct text, no em dashes anywhere (standing memory rule
  `no-em-dashes.md`, applies to every written deliverable).
- Iterates in fast feedback loops on a live build: screenshots a bug,
  expects a real root-cause fix (not a cosmetic patch), then immediately
  moves to the next issue in the same message often as a numbered list
  across "first window" / "second window" (i.e. per-tab) — read these
  carefully, they are usually several independent fixes bundled together,
  not one task.
  Confirming understanding is not the same as being told to build.
  Discussion and planning can and should still move forward while
  building is on hold. Explicitly said "if you feel something can be
  made better, do it" for the overall UI at least once — a standing
  invitation to proactively improve consistency/aesthetics without
  being asked line-by-line, but always within the existing token system,
  never inventing a new palette or component style.
- Rejects any insight that states something an experienced marketer
  would already know, holds every future insight to the obviousness
  filter defined above.
- Wants honest handling of real data gaps (partial coverage, proxies,
  clearly labeled), but explicitly does not want defensive engineering
  for one-off, non-recurring data issues (told to ignore the duplicate-
  row problem once confirmed to be a one-time export mistake).
- Prefers real computed data over placeholder/fake numbers wherever
  possible; the only intentionally-mock content left in the whole build
  is the 4 insight cards, and they are explicitly labeled as mock so
  this is never confused with a real finding.
- Wants a working local copy on disk and a synced published link at all
  times, not just one or the other, in case of session/account changes.
- Building this as a feature of their own product, fastrr Ads (their
  employer's ad-tech platform). Email on file: ads-product@pickrr.com.
