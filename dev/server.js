// Local dev server: serves ./app and mounts the same handlers that run on Vercel.
//   MOCK_META=1 DISPATCH_MODE=local DATABASE_URL=... ENCRYPTION_KEY=... node dev/server.js
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { migrate } from '../lib/db.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const port = Number(process.env.PORT || 8935);
const types = { '.html': 'text/html; charset=utf-8', '.js': 'application/javascript', '.css': 'text/css', '.json': 'application/json', '.jpg': 'image/jpeg', '.png': 'image/png', '.svg': 'image/svg+xml' };

await migrate();

const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, `http://${req.headers.host}`);
  if (u.pathname.startsWith('/api/')) {
    const file = path.join(root, u.pathname.replace(/\/$/, '') + '.js');
    if (!file.startsWith(path.join(root, 'api')) || !fs.existsSync(file)) { res.statusCode = 404; return res.end('{"error":"Not found"}'); }
    try { const mod = await import(pathToFileURL(file).href); return await mod.default(req, res); }
    catch (e) { console.error(e); res.statusCode = 500; return res.end('{"error":"Server error"}'); }
  }
  let p = u.pathname === '/' ? '/index.html' : u.pathname;
  const file = path.join(root, 'app', p);
  if (!file.startsWith(path.join(root, 'app')) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.statusCode = 404; return res.end('Not found'); }
  res.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');
  fs.createReadStream(file).pipe(res);
});
server.listen(port, () => console.log(`dev server on http://localhost:${port}`));
