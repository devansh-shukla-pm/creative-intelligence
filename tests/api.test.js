import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import fs from 'node:fs';
import crypto from 'node:crypto';

// A throwaway Postgres for the test run.
const py = process.env.PYTHON || '.venv/bin/python';
import os from 'node:os';
import path from 'node:path';
const pgDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ci-api-pg-'));
const pgProc = spawn(py, ['dev/pg.py', pgDir], { stdio: ['ignore', 'pipe', 'inherit'] });
const uri = await new Promise(res => pgProc.stdout.once('data', d => res(String(d).trim())));

process.env.DATABASE_URL = uri;
process.env.ENCRYPTION_KEY = crypto.randomBytes(32).toString('base64');
process.env.MOCK_META = '1';
process.env.DISPATCH_MODE = 'none';
process.env.APP_URL = 'http://localhost';

const { migrate, q, closeDb } = await import('../lib/db.js');
const { startApi, client } = await import('./helpers.js');
await migrate();
const api = await startApi();
const c = client(api.base);

test.after(async () => { await api.close(); await closeDb(); pgProc.kill(); });

test('not logged in: me is null, protected routes are 401', async () => {
  const me = await (await c('/api/me')).json();
  assert.equal(me.user, null);
  assert.equal((await c('/api/accounts')).status, 401);
  assert.equal((await c('/api/report/status?id=00000000-0000-0000-0000-000000000000')).status, 401);
});

test('mock login creates a session and lists accounts', async () => {
  const r = await c('/api/auth/login');
  assert.equal(r.status, 302);
  const me = await (await c('/api/me')).json();
  assert.equal(me.user.name, 'Demo Tester');
  const acc = await (await c('/api/accounts')).json();
  assert.ok(acc.accounts.length >= 1);
});

test('create report validates input', async () => {
  const post = body => c('/api/report/create', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  assert.equal((await post({ account_id: 'abc', date_from: '2026-08-01', date_to: '2026-10-01' })).status, 400);
  assert.equal((await post({ account_id: '1000000000001', date_from: '2026-10-05', date_to: '2026-10-01' })).status, 400);
  assert.equal((await post({ account_id: '1000000000001', date_from: 'x', date_to: 'y' })).status, 400);
});

test('create report, reuse identical request, limits, ownership', async () => {
  const post = body => c('/api/report/create', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  const a = await (await post({ account_id: '1000000000001', date_from: '2026-08-01', date_to: '2026-10-01' })).json();
  assert.ok(a.id); assert.equal(a.reused, false);
  const b = await (await post({ account_id: '1000000000001', date_from: '2026-08-01', date_to: '2026-10-01' })).json();
  assert.equal(b.id, a.id); assert.equal(b.reused, true);

  const st = await (await c(`/api/report/status?id=${a.id}`)).json();
  assert.equal(st.status, 'queued'); assert.deepEqual(st.signals, { a: false, b: false, c: false, d: false });

  // a second user cannot read it
  await q(`INSERT INTO users (id,name,token_enc) VALUES ('other','Other','x')`);
  const { createSession } = await import('../lib/session.js');
  const fakeRes = { headers: {}, getHeader() {}, setHeader(k, v) { this.headers[k] = v; } };
  await createSession(fakeRes, 'other');
  const ck = [].concat(fakeRes.headers['Set-Cookie'])[0].split(';')[0];
  const r2 = await fetch(`${api.base}/api/report/status?id=${a.id}`, { headers: { cookie: ck } });
  assert.equal(r2.status, 404);
});

test('boot payload only sends pieces the client does not have', async () => {
  const post = body => c('/api/report/create', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  const { id } = await (await post({ account_id: '1000000000001', date_from: '2026-07-01', date_to: '2026-07-31', force: true })).json();
  await q(`INSERT INTO report_payloads (report_id, kind, body) VALUES ($1,'audit','[{"ad_id":"1"}]'),($1,'data','{"ads":[]}'),($1,'cmt_ads','[]')`, [id]);
  await q(`UPDATE reports SET signal_a = now() WHERE id = $1`, [id]);
  let p = await (await c(`/api/report/boot?id=${id}&format=json`)).json();
  assert.deepEqual(p.signals, { a: true, b: false, c: false, d: false });
  assert.ok(p.audit && p.data && p.cmtAds); assert.equal(p.insights, null);
  p = await (await c(`/api/report/boot?id=${id}&format=json&have=a`)).json();
  assert.equal(p.audit, null);
  const js = await (await c(`/api/report/boot?id=${id}`)).text();
  assert.ok(js.startsWith('window.__BOOT = '));
});

test('thumbnails are served only to owners of the account', async () => {
  await q(`INSERT INTO thumbs (account_id, ad_id, bytes) VALUES ('1000000000001','1200001', $1)`, [Buffer.from('jpegbytes')]);
  const ok = await c('/api/thumb?ad=1200001');
  assert.equal(ok.status, 200); assert.equal(await ok.text(), 'jpegbytes');
  assert.equal((await c('/api/thumb?ad=999999')).status, 404);
  assert.equal((await c('/api/thumb?ad=abc')).status, 400);
});

test('tokens are encrypted at rest', async () => {
  const { encrypt, decrypt, sign, verify } = await import('../lib/crypto.js');
  const e = encrypt('EAAB-secret-token');
  assert.ok(!e.includes('secret')); assert.equal(decrypt(e), 'EAAB-secret-token');
  assert.equal(verify(sign('abc', 60)), 'abc');
  assert.equal(verify(sign('abc', 60) + 'x'), null);
  assert.equal(verify(sign('abc', -5)), null);
});

test('a report whose worker went silent is marked failed', async () => {
  const post = body => c('/api/report/create', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  await q(`UPDATE reports SET status='done'`);       // earlier tests left reports queued; the per-user running limit would block this one
  const { id } = await (await post({ account_id: '1000000000001', date_from: '2026-06-01', date_to: '2026-06-30', force: true })).json();
  await q(`UPDATE reports SET status='running', heartbeat_at = now() - interval '30 minutes' WHERE id=$1`, [id]);
  const st = await (await c(`/api/report/status?id=${id}`)).json();
  assert.equal(st.status, 'failed'); assert.match(st.error, /stopped responding/);
});

test('running-report limit protects LLM spend', async () => {
  const post = body => c('/api/report/create', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  await q(`UPDATE reports SET status='done'`);
  const mk = (a, b) => post({ account_id: '1000000000001', date_from: a, date_to: b, force: true });
  assert.equal((await mk('2026-01-01', '2026-01-31')).status, 200);
  assert.equal((await mk('2026-02-01', '2026-02-28')).status, 200);
  assert.equal((await mk('2026-03-01', '2026-03-31')).status, 429);
});

test('cancel stops a running report, frees the running slot, and only the owner can do it', async () => {
  const post = (url, body) => c(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  await q(`UPDATE reports SET status='done'`);
  const { id } = await (await post('/api/report/create', { account_id: '1000000000001', date_from: '2025-05-01', date_to: '2025-05-31', force: true })).json();
  await q(`UPDATE reports SET status='running' WHERE id=$1`, [id]);

  // another user cannot cancel it
  const { createSession } = await import('../lib/session.js');
  const fakeRes = { headers: {}, getHeader() {}, setHeader(k, v) { this.headers[k] = v; } };
  await createSession(fakeRes, 'other');
  const ck = [].concat(fakeRes.headers['Set-Cookie'])[0].split(';')[0];
  const r2 = await fetch(`${api.base}/api/report/cancel`, { method: 'POST', headers: { cookie: ck, 'content-type': 'application/json' }, body: JSON.stringify({ id }) });
  assert.equal(r2.status, 404);
  assert.equal((await (await c(`/api/report/status?id=${id}`)).json()).status, 'running');

  const r = await (await post('/api/report/cancel', { id })).json();
  assert.equal(r.status, 'cancelled');
  const st = await (await c(`/api/report/status?id=${id}`)).json();
  assert.equal(st.status, 'cancelled');
  // a cancelled report is not reused for an identical request
  const again = await (await post('/api/report/create', { account_id: '1000000000001', date_from: '2025-05-01', date_to: '2025-05-31' })).json();
  assert.notEqual(again.id, id);
  // cancelling a finished report is a harmless no-op
  await q(`UPDATE reports SET status='done' WHERE id=$1`, [again.id]);
  assert.equal((await (await post('/api/report/cancel', { id: again.id })).json()).status, 'done');
});
