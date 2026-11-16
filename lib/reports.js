import { q, one } from './db.js';
import { config } from './config.js';
import { HttpError } from './http.js';
import { dispatchReport } from './dispatch.js';

const DATE = /^\d{4}-\d{2}-\d{2}$/;

export function validateRange(from, to) {
  if (!DATE.test(from || '') || !DATE.test(to || '')) throw new HttpError(400, 'Dates must be YYYY-MM-DD');
  const a = new Date(from + 'T00:00:00Z'), b = new Date(to + 'T00:00:00Z');
  if (!(a <= b)) throw new HttpError(400, 'Start date must be on or before end date');
  if (b > new Date(Date.now() + 86400000)) throw new HttpError(400, 'End date cannot be in the future');
  if ((b - a) / 86400000 > 730) throw new HttpError(400, 'Date range cannot be longer than 2 years');
}

const SIGNALS = r => ({ a: !!r.signal_a, b: !!r.signal_b, c: !!r.signal_c, d: !!r.signal_d });

export function publicReport(r) {
  return {
    id: r.id, account_id: r.account_id, account_name: r.account_name, currency: r.currency,
    date_from: r.date_from, date_to: r.date_to, window_from: r.window_from || null, window_to: r.window_to || null, status: r.status, stage: r.stage,
    signals: SIGNALS(r), progress: r.progress || {}, error: r.error || null,
    created_at: r.created_at, updated_at: r.updated_at,
  };
}

export async function getReportForUser(id, userId) {
  if (!/^[0-9a-f-]{36}$/i.test(id || '')) throw new HttpError(400, 'Bad report id');
  const r = await one(
    `SELECT *, to_char(date_from,'YYYY-MM-DD') AS date_from, to_char(date_to,'YYYY-MM-DD') AS date_to,
            to_char(window_from,'YYYY-MM-DD') AS window_from, to_char(window_to,'YYYY-MM-DD') AS window_to FROM reports WHERE id = $1 AND user_id = $2`,
    [id, userId]);
  if (!r) throw new HttpError(404, 'Report not found');
  return failIfStalled(r);
}

// A worker that dies (job killed, secret missing) would leave a report "running" forever. Detect it lazily.
const STALL_MINUTES = 15;
async function failIfStalled(r) {
  if (!['queued', 'running'].includes(r.status)) return r;
  const last = new Date(r.heartbeat_at || r.dispatched_at || r.created_at).getTime();
  if (Date.now() - last < STALL_MINUTES * 60_000) return r;
  const msg = 'The report worker stopped responding. Try again.';
  await q(`UPDATE reports SET status='failed', error=$2, updated_at=now() WHERE id=$1 AND status IN ('queued','running')`, [r.id, msg]);
  return { ...r, status: 'failed', error: msg };
}

// Reuse a recent identical report, otherwise create one and start the worker.
export async function createReport(user, { account, from, to, force = false }) {
  validateRange(from, to);
  const { reuseHours, reportsPerUserPerDay, runningReportsPerUser } = config.limits;

  if (!force) {
    const ex = await one(
      `SELECT id FROM reports
        WHERE user_id=$1 AND account_id=$2 AND date_from=$3 AND date_to=$4
          AND status IN ('queued','running','done') AND created_at > now() - ($5 || ' hours')::interval
        ORDER BY created_at DESC LIMIT 1`,
      [user.id, account.id, from, to, String(reuseHours)]);
    if (ex) return { id: ex.id, reused: true };
  }

  const today = await one(`SELECT count(*)::int AS n FROM reports WHERE user_id=$1 AND created_at > now() - interval '1 day'`, [user.id]);
  if (today.n >= reportsPerUserPerDay) throw new HttpError(429, `Daily limit of ${reportsPerUserPerDay} reports reached`);
  const running = await one(`SELECT count(*)::int AS n FROM reports WHERE user_id=$1 AND status IN ('queued','running')`, [user.id]);
  if (running.n >= runningReportsPerUser) throw new HttpError(429, 'Too many reports are already running. Wait for one to finish.');

  const r = await one(
    `INSERT INTO reports (user_id, account_id, account_name, currency, date_from, date_to)
     VALUES ($1,$2,$3,$4,$5,$6) RETURNING id`,
    [user.id, account.id, account.name, account.currency, from, to]);
  try {
    await dispatchReport(r.id);
    await q(`UPDATE reports SET dispatched_at = now() WHERE id = $1`, [r.id]);
  } catch (e) {
    await q(`UPDATE reports SET status='failed', error=$2, updated_at=now() WHERE id=$1`, [r.id, `Could not start the worker: ${e.message}`]);
    throw new HttpError(502, 'Could not start the report worker');
  }
  return { id: r.id, reused: false };
}

// Payloads the browser needs. `have` = signals the client already applied, so we only send new pieces.
export async function bootPayload(report, userName, have = []) {
  const sig = SIGNALS(report);
  const kinds = [];
  if (sig.a && !have.includes('a')) kinds.push('audit', 'cmt_ads', 'data');     // data carries metrics only until B
  if (sig.b && !have.includes('b')) kinds.push('data', 'cmt_dims', 'cmt_ads');  // data is replaced with classified ads
  if (sig.c && !have.includes('c')) kinds.push('insights');
  if (sig.d && !have.includes('d')) kinds.push('lab');
  const wanted = [...new Set(kinds)];
  const rows = wanted.length
    ? await q(`SELECT kind, body FROM report_payloads WHERE report_id=$1 AND kind = ANY($2)`, [report.id, wanted])
    : [];
  const p = {}; for (const r of rows) p[r.kind] = r.body;
  return {
    report: publicReport(report), user: { name: userName }, signals: sig, progress: report.progress || {}, error: report.error || null,
    data: p.data || null, cmtAds: p.cmt_ads || null, cmtDims: p.cmt_dims || null, audit: p.audit || null,
    insights: p.insights || null, lab: p.lab || null,
  };
}
