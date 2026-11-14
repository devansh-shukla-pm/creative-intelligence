import { handler, sendJson, sendText, url } from '../../lib/http.js';
import { requireUser } from '../../lib/session.js';
import { getReportForUser, bootPayload } from '../../lib/reports.js';

// format=js   -> `window.__BOOT = {...}` loaded by a blocking <script> before the app starts
// format=json -> same payload for polling; `have=a,b` skips payloads the browser already applied
export default handler('GET', async (req, res) => {
  const u = url(req);
  const user = await requireUser(req);
  const report = await getReportForUser(u.searchParams.get('id'), user.id);
  const have = (u.searchParams.get('have') || '').split(',').filter(Boolean);
  const body = await bootPayload(report, user.name, have);
  if (u.searchParams.get('format') === 'json') return sendJson(res, 200, body);
  sendText(res, 200, `window.__BOOT = ${JSON.stringify(body).replace(/</g, '\\u003c')};`, 'application/javascript; charset=utf-8');
});
