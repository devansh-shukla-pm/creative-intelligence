import { handler, sendJson } from '../lib/http.js';
import { requireUser } from '../lib/session.js';
import { decrypt } from '../lib/crypto.js';
import { config } from '../lib/config.js';
import { listAdAccounts, MOCK_ACCOUNTS } from '../lib/meta.js';

export default handler('GET', async (req, res) => {
  const user = await requireUser(req);
  if (config.meta.mock) return sendJson(res, 200, { accounts: MOCK_ACCOUNTS });
  try {
    sendJson(res, 200, { accounts: await listAdAccounts(decrypt(user.token_enc)) });
  } catch (e) {
    if (e.status === 401) return sendJson(res, 401, { error: 'Meta login expired. Connect Meta again.' });
    throw e;
  }
});
