import { handler, sendJson, url } from '../../lib/http.js';
import { requireUser } from '../../lib/session.js';
import { getReportForUser, publicReport } from '../../lib/reports.js';

export default handler('GET', async (req, res) => {
  const user = await requireUser(req);
  const r = await getReportForUser(url(req).searchParams.get('id'), user.id);
  sendJson(res, 200, publicReport(r));
});
