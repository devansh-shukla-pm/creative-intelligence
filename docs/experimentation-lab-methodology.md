---
name: creative_experimentation_memory
description: "Full context on the Experimentation Lab, a standalone deterministic creative-recipe recommendation engine explored alongside Creative Intelligence. Covers the 5-step methodology, the statistical fixes applied (hygiene filter, DerSimonian-Laird tau-squared), per-SKU findings, and honest limitations. Load before continuing any Experimentation Lab work."
metadata: 
  node_type: memory
  type: project
  originSessionId: b4679364-31e2-4542-93b7-f0f5ec4d261e
  modified: 2026-09-15T08:55:23.969Z
---

# Experimentation Lab

Sibling effort to [[creative-intelligence-project-skill]] (see that skill,
`creative-intelligence-skill`, for the main Creative Intelligence product
context, vocabulary, and tabs). This memory covers a separate, standalone
concept demo built to answer one question the user raised directly: "can I
build a recommendation engine (using polynomial regression or similar) that
suggests which 5-angle combination, one Angle per mandatory Stage, would
work best, an experimentation lab idea."

Live artifact: https://claude.ai/code/artifact/ef460594-412d-40ce-bbb5-b8b4eb01385b
Explicitly kept separate from the Creative Overview tab and not yet wired
into Creative Intelligence's nav, this is a mechanism under evaluation, not
a shipped feature. The user asked to see it work before deciding whether it
becomes a real tab.

**Why not polynomial regression**: rejected early in discussion. The real
problem is combinatorial (5 categorical slots, each with 8-15 discrete
options) with far too little data (a few hundred ads per SKU vs tens of
thousands of possible 5-way combinations) to fit any model claiming to know
the full combinatorial space. The chosen approach is fully deterministic
arithmetic instead, no trained model anywhere in the pipeline.


## The 5/6-step methodology, in order

1. **Data hygiene filter** — exclude any ad with `spend < MIN_AD_SPEND`
   (₹10) from every downstream calculation: baseline, main effects, sigma^2,
   tau^2, pairwise cells, evidence, everything. This is a sanity floor, not
   a confidence parameter, no real Meta ad delivery costs less than ₹10, an
   ad below that with real revenue attached is a tracking/attribution
   artifact (e.g. a delayed view-through conversion crediting a near-zero
   spend ad), not signal. Kept as a fixed constant deliberately, unlike K
   below, because this represents a category-of-error check, not a judgment
   about how much evidence is "enough."

2. **Main effects per stage** — group each mandatory stage's eligible ads by
   Angle, weighted-average ROAS, keep only angles with n>=3 (`MIN_N_MAIN`).

3. **Derive K empirically per SKU** (never a fixed guess, never borrowed
   across SKUs), using DerSimonian-Laird variance-component estimation:
   - sigma^2 = pooled WITHIN-angle noise (ads on the same angle still
     scatter around their own angle's mean; pool that scatter across every
     angle with n>=3).
   - tau^2 = genuine BETWEEN-angle spread, corrected for sampling noise.
     The naive version (`variance(angle_means)`) OVERSTATES tau^2 because
     it conflates real differences with noise from small samples. The
     correct estimator weights each angle's mean by its own precision
     (n/sigma^2) before computing spread, and explicitly subtracts out the
     portion of observed spread that noise alone explains. This was a real
     bug found and fixed mid-project, not a stylistic choice, first attempt
     gave K=1.3 for Night Repair Cream (wrong, blended within+between
     noise), corrected DerSimonian-Laird version gives K=11.25 (properly
     separated). Formula: weight w_i = n_i/sigma^2, Q = sum(w_i*(mean_i -
     weighted_grand_mean)^2), tau^2 = max(0, (Q-(k-1)) / (sum(w_i) -
     sum(w_i^2)/sum(w_i))).
   - K_raw = sigma^2/tau^2. K_used = K_raw clamped to [0.5, 20].
   - If tau^2 estimate is <=0 (noise fully explains the observed spread),
     treat as K_raw = infinity, maximal low-confidence, not a silent
     fallback.
   - High K_raw (>20, clamp fires) = "angles barely differ once noise is
     removed," a real weak-signal finding for that SKU, surfaced as a
     visible low-confidence banner, not hidden.
   - Low K_raw (<0.5) = different kind of concern, too few angles feeding
     the tau^2 estimate to trust the estimate itself, flagged separately
     with different wording than the high-K case (data-quality problem vs
     statistical-uncertainty problem are conceptually distinct and should
     never share one generic warning).

4. **Shrink every main effect toward baseline using K_used**: `shrunk =
   (n*raw + K*baseline) / (n+K)`. A thin, flashy sample gets pulled hard
   toward baseline; a well-proven angle barely moves. Initial recipe =
   argmax(shrunk) per stage.

5. **Synergy scan across all 10 stage-pairs**: for every pair of angles
   that actually ran together with real evidence (n>=3, spend>=Rs8,000),
   `expected = baseline + (angle A's shrunk lift) + (angle B's shrunk
   lift)`, `synergy = observed - expected`. Positive means the pair
   performs better together than simple addition predicts, negative means
   the opposite, both are real findings worth keeping, not just positives.

6. **Local search (2 passes, 5 stages)**: swap a stage's pick only if doing
   so increases the total score (sum of 5 shrunk main effects + all
   pairwise synergies among the picks) versus keeping the current pick.
   This is what lets a proven, evidenced partnership beat an unproven but
   higher solo number, the central mechanism of the whole engine.

7. **Evidence check on the final 5 picks**: of the 10 possible pairs among
   them, how many have actually run together (with expected/synergy shown
   for each), and has the full 5-way combination ever run at all (almost
   always 0 times, this is meant to recommend what to test next, not
   rediscover something already known).

8. **Two final predictions**:
   - Naive additive = baseline + sum of the 5 RAW (unshrunk) main effects.
     Deliberately the "wrong, overconfident" number, shown crossed out.
   - Honest / evidence-weighted = spend-weighted average of ONLY the
     real tested pairs' observed ROAS from step 7:
     `sum(observed_i * spend_i) / sum(spend_i)`, shown as a full visible
     table (pair, observed, spend, observed*spend) with the final division,
     not just an output number, so a non-technical viewer can follow the
     arithmetic by hand.


## Validated numeric findings (Night Repair Cream, the reference example)

Baseline 2.78x, 70 eligible ads (15 excluded for near-zero spend, carrying
Rs11,514 of phantom revenue that would otherwise have inflated whichever
angle absorbed it). K_used = K_raw = 11.25 (sigma^2=1.321, tau^2=0.117, no
clamp fired). Final recipe: Product safety/authenticity concern -> Personal
product review opener -> Skin brightening & tan removal -> Daily skincare &
wellness -> Shop online/now, 3 swaps fired (Hook, USP, CTA all moved from
their solo-best pick to a better-evidenced partner). 7 of 10 pairs among
the final picks have real evidence, 0 ads have ever run the full 5-way
combo. Naive additive = 2.98x. Honest evidence-weighted = 2.80x. Uplift vs
baseline = **+0.55%**, modest and credible, this is the number to trust.

Before these fixes were applied (naive tau^2, no hygiene filter), the same
SKU showed a flashier but overstated +5.0% uplift, most of that gap was the
bug, not a real finding.


## Two important corrections the fix surfaced, worth remembering

- **Root Touch Up Powder**, initially flagged (pre-fix) as the strongest
  clean win in a 9-SKU stress test (+11.3% uplift, full pair coverage), now
  shows a **low-confidence banner** post-fix, K_raw = 211.5. The earlier
  result was very likely the same inflated-tau^2 problem, just larger. Not
  a broken finding, the tool correctly admitting it has no real signal here
  once the math is done properly.
- **Lip Balm** originally produced a nonsense 35.81x raw ROAS on a Hook
  angle, traced to a single ad with Rs0.00 recorded spend and Rs2,750.35
  attributed revenue (a tracking artifact). After the hygiene filter, Lip
  Balm no longer has enough eligible ads to clear the n>=3 floor for Hook
  Line or Primary USP Claim at all, and now correctly returns "insufficient
  data, no recommendation" rather than any recipe, degraded or otherwise.
  This is the intended, designed behavior, not a regression, the user
  explicitly endorsed excluding under-evidenced SKUs from the board rather
  than forcing a degraded answer ("that is also fine from a design lens").

Of the 4 SKUs in the demo's dropdown (Night Repair Cream, Hair Colour/Dye,
Root Touch Up Powder, Lip Balm), only Night Repair Cream currently produces
a recipe worth standing behind post-fix. Worth knowing before giving a
walkthrough, the corrected version is more honest, not more impressive.


## Honest limitations (stated to the user directly, keep stating them)

- No predictive validation exists yet. Nothing here has been tested by
  actually launching a recommended recipe and measuring it. Report this as
  internal/statistical validation of the mechanism, never as proof of
  future accuracy, until that real test loop exists.
- Structurally limited to PAIRWISE (2-way) interactions. A genuine 3-way or
  5-way interaction effect is invisible to this method by design, checking
  higher-order combinations runs straight into the same data-sparsity wall
  that ruled out a full regression approach in the first place. This is
  the parked [[creative-intel-3d-combination-lab]] idea's territory, a
  different, complementary tool, not a fix for this one's ceiling.
- The mechanism is a snapshot, not a learning system. Re-running it on the
  same historical data always gives the same answer, it does not get
  smarter as new tests actually run, that requires a real feedback loop
  (bandit / Bayesian-optimization style "what to test next" prioritization
  was discussed as the natural phase-2 direction, not yet built).
- Zero creative/editorial judgment. The engine has no idea whether two
  recommended angles make a coherent, filmable script together, a human
  still sanity-checks that.
- MIN_AD_SPEND (Rs10) and the pairwise floors (n>=3, spend>=Rs8,000) are
  fixed constants, reasonable and explained, but not empirically derived
  the way K is per SKU, worth another pass if this becomes a real feature
  across brands with very different spend scales.


## Vocabulary specific to this sub-feature (in addition to Stage/Angle/
## Approach/Lever from the main Creative Intelligence skill)

- **Main effect**: an Angle's own average ROAS, considered alone.
- **Shrinkage / K**: how hard a thin-sample main effect gets pulled toward
  the SKU's baseline before being trusted, derived per SKU, never guessed.
- **Synergy**: the gap between what two angles' combined performance
  actually was and what simple addition of their individual effects would
  predict. Positive = real teamwork, negative = real clash, both are kept.
- **Evidence-weighted / honest prediction**: the spend-weighted average of
  real tested pairs backing a recipe, the number meant to be trusted.
- **Naive additive prediction**: the sum of 5 raw main effects with no
  synergy or shrinkage correction, deliberately shown as the wrong,
  overconfident answer for contrast.


## Where the working code lives (this session's scratchpad, not permanent)

`recipe_lab.html` (template) / `experimentation_lab.html` (published
build) hold the live JS engine. `corrected_engine.py` and `stress_test.py`
hold the Python mirror used to hand-verify every number before it shipped
to the artifact. These live in a session-scratchpad path that does not
persist between sessions, the *methodology* documented above is what to
reconstruct from, not the specific file paths.
