import { handler, sendJson, readJson } from '../../lib/http.js';
import { requireUser } from '../../lib/session.js';
import { getReportForUser } from '../../lib/reports.js';
import { cancelReportRun } from '../../lib/dispatch.js';
import { q } from '../../lib/db.js';

// Stops a report that is queued or running. The report is marked cancelled first (the worker checks that on every progress
// update and stops), then the worker job is cancelled so it stops at once. What was already pulled stays cached.
export default handler('POST', async (req, res) => {
  const user = await requireUser(req);
  const body = await readJson(req);
  const r = await getReportForUser(String(body.id || ''), user.id);
  if (!['queued', 'running'].includes(r.status)) return sendJson(res, 200, { ok: true, status: r.status });
  await q(`UPDATE reports SET status='cancelled', error=NULL, stage=NULL, progress='{}'::jsonb, updated_at=now()
            WHERE id=$1 AND status IN ('queued','running')`, [r.id]);
  let stopped = false;
  try { stopped = await cancelReportRun(r.id); } catch { /* the worker still stops at its next update */ }
  sendJson(res, 200, { ok: true, status: 'cancelled', worker_stopped: stopped });
});
