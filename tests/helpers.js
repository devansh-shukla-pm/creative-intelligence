import http from 'node:http';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

// Starts the real handlers on an ephemeral port. Env must be set before this module graph is imported.
export async function startApi(root = path.resolve('.')) {
  const server = http.createServer(async (req, res) => {
    const u = new URL(req.url, 'http://x');
    const file = path.join(root, u.pathname + '.js');
    if (!file.startsWith(path.join(root, 'api')) || !fs.existsSync(file)) { res.statusCode = 404; return res.end('{}'); }
    const mod = await import(pathToFileURL(file).href);
    await mod.default(req, res);
  });
  await new Promise(r => server.listen(0, r));
  const base = `http://127.0.0.1:${server.address().port}`;
  return { base, close: () => new Promise(r => server.close(r)) };
}

// Minimal cookie-jar fetch.
export function client(base) {
  let jar = {};
  return async (p, opts = {}) => {
    const cookie = Object.entries(jar).map(([k, v]) => `${k}=${v}`).join('; ');
    const r = await fetch(base + p, { redirect: 'manual', ...opts, headers: { ...(opts.headers || {}), cookie } });
    for (const sc of r.headers.getSetCookie?.() || []) {
      const [pair] = sc.split(';'); const i = pair.indexOf('=');
      const k = pair.slice(0, i), v = pair.slice(i + 1);
      if (/Max-Age=0/i.test(sc)) delete jar[k]; else jar[k] = v;
    }
    return r;
  };
}
