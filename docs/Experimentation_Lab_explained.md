# Experimentation Lab, explained simply

## 1. The goal
Every ad is built from 5 parts. We want to suggest the best combination of those 5 parts for the next ad, and say honestly how much extra ROAS that could bring.

## 2. Words you need
- **ROAS**: revenue divided by ad spend. If Rs 1 of spend brings back Rs 3, ROAS is 3x.
- **Stage**: one of the 5 parts of an ad: Problem, Hook, Claim (USP), Use-case, CTA.
- **Angle**: the specific choice within a stage, for example "Comment for link" in the CTA stage.
- **Recipe**: one angle chosen for each of the 5 stages.
- **Baseline**: the product's overall ROAS across all its ads. It is the "normal" to beat.

## 3. Clean the data
Ads that spent under Rs 10 are thrown out, because a ROAS of 100x on Rs 10 is a fluke or a tracking glitch. We also use a log scale for ROAS, so one extreme ad cannot dominate.

## 4. The core problem: luck
Imagine a new restaurant with two 5-star reviews. Is it great, or were those two friends being nice? You would guess "probably good, but not as good as 5 stars". Ads work the same way. An angle used in 2 ads with ROAS 5x is probably not really a 5x angle. Luck has to be removed before we trust any number.

## 5. Shrinkage (pulling numbers back toward normal)
We move each angle's ROAS part of the way back toward the product baseline.
- Little evidence: pulled back a lot.
- Strong evidence: barely moved.

Formula: `trusted = baseline + trust x (observed - baseline)`, where trust is between 0 and 1. The restaurant with 2 reviews gets trust near 0.2. The one with 2,000 reviews gets trust near 1.

## 6. Spend is evidence
An ad that spent Rs 2 lakh has a very precisely measured ROAS. An ad that spent Rs 300 does not. In our data, ads above about Rs 60K spend stay within about 13% of their product's norm, while ads under about Rs 400 swing wildly. So high-spend results get more weight and are not pulled down much.

Careful: "this ad's ROAS is accurate" is different from "this hook caused it". The audience, offer or creator could be the real reason. That is why we still test on unseen ads.

## 7. DerSimonian-Laird, in one paragraph
It asks one question: how much of the difference between angles is real, and how much is just noise?
- Noise is how much ads using the same angle disagree with each other.
- Real difference is how much angles differ after noise is subtracted.
- The ratio of the two tells us how hard to shrink. If angles barely differ after removing noise, shrink hard.

In the newer version, noise is allowed to be smaller for high-spend ads, and the shrink strength is chosen by whichever setting predicts unseen ads best.

## 8. Synergy (pairs)
Sometimes two angles work better together than apart. Synergy is the gap between what a pair actually did and what we would expect from adding the two angles' separate effects. A pair term is only kept if it makes predictions better on unseen ads.

## 9. CatBoost, simply
- A decision tree is a game of 20 questions: "Is the hook a question? Is the product skincare?" Each answer leads to a predicted ROAS.
- Boosting builds hundreds of small trees. Each new tree is trained to fix the mistakes of the previous ones.
- CatBoost is a boosting tool that handles text categories (like angle names) well and resists overfitting.
- Why we like it: it finds interactions without us listing them. Why we are careful: with a few hundred ads it can memorize noise.

## 10. The blend
We average the shrinkage model and CatBoost. One is careful and explainable, the other flexible. Averaging two different models usually beats either alone.

## 11. Picking the recipe
We score every combination of supported angles (thousands per product) and show the highest. Rule: an angle needs at least 2 ads behind it.

## 12. Testing, the most important part
- **Cross-validation**: hide some ads, build the model from the rest, then check predictions on the hidden ones. Repeat many times.
- **Fair baselines**: the model must beat just using the product average, otherwise it adds nothing.
- **Shuffle test**: scramble the angle labels so they mean nothing, run everything again, and see if our model still "wins". If it does, it was fooling itself. If it only wins on real labels, the signal is real.

## 13. Calibration (being honest about the size)
Models overstate. We measure how much of a predicted lift actually showed up on hidden ads (for example 18%) and scale the claim by that. That scaled number is what we call "expected".

## 14. How to read the result
- "Model says +19%" is the raw claim.
- "Expect +3%" is the claim after the reality check.
- Only a live test with a control group can prove a real gain.
