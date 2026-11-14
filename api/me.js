import { handler, sendJson } from '../lib/http.js';
import { getUser } from '../lib/session.js';
import { config } from '../lib/config.js';

export default handler('GET', async (req, res) => {
  const u = await getUser(req);
  sendJson(res, 200, {
    user: u ? { id: u.id, name: u.name } : null,
    meta_configured: config.meta.mock || !!(config.meta.appId && config.meta.appSecret),
    mock: config.meta.mock,
  });
});
