import { config } from '../../lib/config.js';
import { handler, redirect, addCookie, cookie, sendJson } from '../../lib/http.js';
import { randomToken, sign } from '../../lib/crypto.js';
import { loginUrl } from '../../lib/meta.js';
import { q } from '../../lib/db.js';
import { createSession } from '../../lib/session.js';

export default handler('GET', async (req, res) => {
  if (config.meta.mock) {
    // Local development without a Meta app: log in as a demo tester.
    await q(`INSERT INTO users (id, name, token_enc) VALUES ('mock-user','Demo Tester','mock')
             ON CONFLICT (id) DO UPDATE SET last_login_at = now()`);
    await createSession(res, 'mock-user');
    return redirect(res, '/');
  }
  const state = randomToken(16);
  addCookie(res, cookie('ci_oauth', sign(state, 600), { maxAge: 600, secure: config.isProd }));
  redirect(res, loginUrl(state));
});
