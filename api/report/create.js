import { handler, sendJson, readJson, HttpError } from '../../lib/http.js';
import { requireUser } from '../../lib/session.js';
import { decrypt } from '../../lib/crypto.js';
import { config } from '../../lib/config.js';
import { getAdAccount, MOCK_ACCOUNTS } from '../../lib/meta.js';
import { createReport, validateRange } from '../../lib/reports.js';

export default handler('POST', async (req, res) => {
  const user = await requireUser(req);
  const body = await readJson(req);
  const accountId = String(body.account_id || '').replace(/^act_/, '');
  if (!/^\d{5,20}$/.test(accountId)) throw new HttpError(400, 'Pick an ad account');
  validateRange(body.date_from, body.date_to);

  // Confirm the logged-in user can read this account (also gives us the name and currency).
  let account;
  if (config.meta.mock) {
    account = MOCK_ACCOUNTS.find(a => a.id === accountId) || { id: accountId, name: `Account ${accountId}`, currency: 'INR' };
  } else {
    try { account = await getAdAccount(decrypt(user.token_enc), accountId); }
    catch (e) { throw new HttpError(e.status === 401 ? 401 : 403, e.status === 401 ? 'Meta login expired. Connect Meta again.' : 'You do not have access to this ad account'); }
  }
  const r = await createReport(user, { account, from: body.date_from, to: body.date_to, force: !!body.force });
  sendJson(res, 200, r);
});
