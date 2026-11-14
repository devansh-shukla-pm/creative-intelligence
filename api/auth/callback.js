import { config } from '../../lib/config.js';
import { handler, redirect, url, parseCookies, addCookie, cookie } from '../../lib/http.js';
import { verify, encrypt } from '../../lib/crypto.js';
import { exchangeCode, getMe } from '../../lib/meta.js';
import { q } from '../../lib/db.js';
import { createSession } from '../../lib/session.js';

const fail = (res, why) => redirect(res, `/?login_error=${encodeURIComponent(why)}`);

export default handler('GET', async (req, res) => {
  const u = url(req);
  if (u.searchParams.get('error')) return fail(res, 'Meta login was cancelled');
  const state = u.searchParams.get('state'), code = u.searchParams.get('code');
  const expected = verify(parseCookies(req).ci_oauth);
  addCookie(res, cookie('ci_oauth', '', { maxAge: 0, secure: config.isProd }));
  if (!state || !code || !expected || state !== expected) return fail(res, 'Login session expired. Try again.');

  let tok, me;
  try {
    tok = await exchangeCode(code);
    me = await getMe(tok.token);
  } catch (e) {
    console.error('meta login failed', e.message);
    return fail(res, 'Meta login failed');
  }
  if (config.allowedUserIds.length && !config.allowedUserIds.includes(String(me.id))) {
    return fail(res, 'This account is not on the allowed list');
  }
  await q(
    `INSERT INTO users (id, name, token_enc, token_expires_at) VALUES ($1,$2,$3,$4)
     ON CONFLICT (id) DO UPDATE SET name=$2, token_enc=$3, token_expires_at=$4, last_login_at=now()`,
    [String(me.id), me.name || '', encrypt(tok.token), tok.expiresAt]);
  await createSession(res, String(me.id));
  redirect(res, '/');
});
