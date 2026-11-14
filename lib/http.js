// Tiny helpers so handlers work identically on Vercel and on the local dev server (plain Node req/res only).
export function sendJson(res, status, body, headers = {}) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  for (const [k, v] of Object.entries(headers)) res.setHeader(k, v);
  res.end(JSON.stringify(body));
}
export function sendText(res, status, text, type = 'text/plain; charset=utf-8') {
  res.statusCode = status;
  res.setHeader('Content-Type', type);
  res.setHeader('Cache-Control', 'no-store');
  res.end(text);
}
export function redirect(res, url, status = 302) {
  res.statusCode = status;
  res.setHeader('Location', url);
  res.end();
}
export function parseCookies(req) {
  const out = {};
  for (const part of (req.headers.cookie || '').split(';')) {
    const i = part.indexOf('=');
    if (i > 0) out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim());
  }
  return out;
}
export function cookie(name, value, { maxAge, secure = true, httpOnly = true, sameSite = 'Lax', path = '/' } = {}) {
  let c = `${name}=${encodeURIComponent(value)}; Path=${path}; SameSite=${sameSite}`;
  if (httpOnly) c += '; HttpOnly';
  if (secure) c += '; Secure';
  if (maxAge !== undefined) c += `; Max-Age=${maxAge}`;
  return c;
}
export function addCookie(res, c) {
  const prev = res.getHeader('Set-Cookie');
  res.setHeader('Set-Cookie', prev ? [].concat(prev, c) : [c]);
}
export function url(req) {
  return new URL(req.url, `http://${req.headers.host || 'localhost'}`);
}
export async function readJson(req) {
  if (req.body && typeof req.body === 'object') return req.body;   // Vercel pre-parses JSON bodies
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const raw = Buffer.concat(chunks).toString('utf8');
  if (!raw) return {};
  try { return JSON.parse(raw); } catch { throw new HttpError(400, 'Invalid JSON body'); }
}
export class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
// Wrap a handler: method check, error to JSON.
export function handler(methods, fn) {
  const allowed = [].concat(methods);
  return async (req, res) => {
    try {
      if (!allowed.includes(req.method)) throw new HttpError(405, 'Method not allowed');
      await fn(req, res);
    } catch (e) {
      const status = e.status || 500;
      if (status >= 500) console.error(e);
      if (!res.headersSent) sendJson(res, status, { error: status >= 500 ? 'Server error' : e.message });
    }
  };
}
