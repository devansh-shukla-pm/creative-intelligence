import { handler, sendJson } from '../../lib/http.js';
import { destroySession } from '../../lib/session.js';

export default handler('POST', async (req, res) => {
  await destroySession(req, res);
  sendJson(res, 200, { ok: true });
});
