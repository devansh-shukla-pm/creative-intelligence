#!/usr/bin/env node
/* Regression test for the semantic guard in build_insight_inputs.js.
   Run: node test_semantic_guard.js
   Add a line to `tests` whenever a nonsense suggestion ever slips through. */
const s = require('fs').readFileSync(__dirname + '/build_insight_inputs.js', 'utf8');
const a = s.indexOf('const PRODUCT_PROFILES'), b = s.indexOf('/* ------------------------------ helpers');
const { fitsProduct, tagsOf } = new Function(s.slice(a, b) + ';return {fitsProduct,tagsOf};')();
const tests = [
  // [creative text, product id, should it make sense?]
  ['Direct grey hair problem', 'face-wash', false], ['Direct grey hair problem', 'face-serum', false],
  ['Direct grey hair problem', 'hair-oil', false], ['Direct grey hair problem', 'lip-balm', false],
  ['Direct grey hair problem', 'root-touch-up-powder', true], ['Direct grey hair problem', 'hair-colour-dye', true],
  ['Grey hair coverage', 'face-wash', false], ['Quick grey root touch-up', 'night-repair-cream', false],
  ['Nighttime skincare & repair', 'lip-balm', false], ['Nighttime skincare & repair', 'face-wash', false],
  ['Nighttime skincare & repair', 'night-repair-cream', true], ['Daily lip care', 'face-wash', false],
  ['Post-sun/tan care', 'hair-oil', false], ['Post-sun/tan care', 'tan-removal', true],
  ['Hair growth & strength formula', 'face-serum', false], ['No harsh chemicals in hair dye', 'face-serum', false],
  ['Chemical vs. natural hair color', 'face-wash', false], ['Personal transformation claim', 'face-wash', true],
  ['Shark Tank / TV endorsement', 'lip-balm', true], ['Skin problem narrative', 'hair-oil', false],
  ['Skin problem narrative', 'face-wash', true], ['Acne & scar concerns', 'lip-balm', false],
  ['Seeking glowing skin solution', 'hair-colour-dye', false],
];
let bad = 0;
tests.forEach(([t, p, exp]) => { const got = fitsProduct(t, p); if (got !== exp) { bad++; console.log('MISMATCH', t, '->', p, 'expected', exp, 'got', got, JSON.stringify(tagsOf(t))); } });
console.log(bad ? bad + ' mismatch(es)' : 'all ' + tests.length + ' semantic tests pass');
process.exit(bad ? 1 : 0);
