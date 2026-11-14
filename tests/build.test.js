import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';

const py = process.env.PYTHON || '.venv/bin/python';
execFileSync(py, ['scripts/build_app.py']);
const demo = fs.readFileSync('app/creative-intelligence.html', 'utf8');
const live = fs.readFileSync('app/report.html', 'utf8');
const scripts = html => [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);

test('both builds are valid JavaScript', () => {
  for (const html of [demo, live]) for (const s of scripts(html)) new Function(s);
});

test('the live build embeds no demo data (nothing client-specific is served from the hosted app)', () => {
  const ads = JSON.parse(fs.readFileSync('app/demo/CREATIVE_AUDIT_DATA.json', 'utf8')).slice(0, 25);
  for (const a of ads) {
    assert.ok(!live.includes(a.ad_id), `live build contains demo ad id ${a.ad_id}`);
    assert.ok(!live.includes(a.ad_name), 'live build contains a demo ad name');
  }
  assert.ok(!live.includes('ads-copy.s3'), 'live build contains demo creative urls');
  assert.ok(live.length < 600_000, 'live build should be small');
});

test('modes are wired as designed', () => {
  assert.match(demo, /const LIVE = false;/);
  assert.match(live, /const LIVE = true;/);
  assert.match(live, /\/api\/report\/boot\?id=/);
  assert.ok(!demo.includes('/api/report/boot?id=\'+encodeURIComponent'));
  assert.ok(demo.includes('"ad_id":"120249988264930425"'), 'demo build keeps its demo data');
});
