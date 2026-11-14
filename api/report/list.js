import { handler, sendJson } from '../../lib/http.js';
import { requireUser } from '../../lib/session.js';
import { q } from '../../lib/db.js';
import { publicReport } from '../../lib/reports.js';

export default handler('GET', async (req, res) => {
  const user = await requireUser(req);
  const rows = await q(
    `SELECT *, to_char(date_from,'YYYY-MM-DD') AS date_from, to_char(date_to,'YYYY-MM-DD') AS date_to
       FROM reports WHERE user_id = $1 ORDER BY created_at DESC LIMIT 10`, [user.id]);
  sendJson(res, 200, { reports: rows.map(publicReport) });
});
