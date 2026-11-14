import { handler, sendText, url, HttpError } from '../lib/http.js';
import { requireUser } from '../lib/session.js';
import { one } from '../lib/db.js';

// Serves a stored ad thumbnail. Only for ads in a report the logged-in user owns.
export default handler('GET', async (req, res) => {
  const user = await requireUser(req);
  const adId = url(req).searchParams.get('ad');
  if (!/^\d{5,25}$/.test(adId || '')) throw new HttpError(400, 'Bad ad id');
  const row = await one(
    `SELECT t.content_type, t.bytes FROM thumbs t
      WHERE t.ad_id = $1 AND EXISTS (SELECT 1 FROM reports r WHERE r.user_id = $2 AND r.account_id = t.account_id)`,
    [adId, user.id]);
  if (!row) throw new HttpError(404, 'No thumbnail');
  res.statusCode = 200;
  res.setHeader('Content-Type', row.content_type);
  res.setHeader('Cache-Control', 'private, max-age=604800, immutable');
  res.end(row.bytes);
});
