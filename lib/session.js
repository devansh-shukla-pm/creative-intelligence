import { q, one } from './db.js';
import { config } from './config.js';
import { sha256, randomToken } from './crypto.js';
import { parseCookies, cookie, addCookie, HttpError } from './http.js';

export const SESSION_COOKIE = 'ci_session';

export async function createSession(res, userId) {
  const id = randomToken(32);
  const days = config.sessionDays;
  await q(
    `INSERT INTO sessions (id_hash, user_id, expires_at) VALUES ($1, $2, now() + ($3 || ' days')::interval)`,
    [sha256(id), userId, String(days)],
  );
  addCookie(res, cookie(SESSION_COOKIE, id, { maxAge: days * 86400, secure: config.isProd }));
}

export async function getUser(req) {
  const id = parseCookies(req)[SESSION_COOKIE];
  if (!id) return null;
  return one(
    `SELECT u.id, u.name, u.token_enc, u.token_expires_at
       FROM sessions s JOIN users u ON u.id = s.user_id
      WHERE s.id_hash = $1 AND s.expires_at > now()`,
    [sha256(id)],
  );
}

export async function requireUser(req) {
  const u = await getUser(req);
  if (!u) throw new HttpError(401, 'Not logged in');
  return u;
}

export async function destroySession(req, res) {
  const id = parseCookies(req)[SESSION_COOKIE];
  if (id) await q(`DELETE FROM sessions WHERE id_hash = $1`, [sha256(id)]);
  addCookie(res, cookie(SESSION_COOKIE, '', { maxAge: 0, secure: config.isProd }));
}
