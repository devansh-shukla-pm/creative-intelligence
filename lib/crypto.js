import crypto from 'node:crypto';
import { config } from './config.js';

function key() {
  if (!config.encryptionKey) throw new Error('ENCRYPTION_KEY is not set');
  const k = Buffer.from(config.encryptionKey, 'base64');
  if (k.length !== 32) throw new Error('ENCRYPTION_KEY must be 32 bytes, base64 encoded');
  return k;
}

// AES-256-GCM. Output: base64(iv).base64(tag).base64(ciphertext)
export function encrypt(plain) {
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv('aes-256-gcm', key(), iv);
  const ct = Buffer.concat([c.update(plain, 'utf8'), c.final()]);
  return [iv, c.getAuthTag(), ct].map(b => b.toString('base64')).join('.');
}
export function decrypt(blob) {
  const [iv, tag, ct] = blob.split('.').map(s => Buffer.from(s, 'base64'));
  const d = crypto.createDecipheriv('aes-256-gcm', key(), iv);
  d.setAuthTag(tag);
  return Buffer.concat([d.update(ct), d.final()]).toString('utf8');
}

export const sha256 = s => crypto.createHash('sha256').update(s).digest('hex');
export const randomToken = (bytes = 32) => crypto.randomBytes(bytes).toString('hex');

// Signed, expiring value (used for the OAuth state cookie).
export function sign(value, ttlSeconds) {
  const exp = Math.floor(Date.now() / 1000) + ttlSeconds;
  const payload = `${value}.${exp}`;
  const mac = crypto.createHmac('sha256', key()).update(payload).digest('base64url');
  return `${payload}.${mac}`;
}
export function verify(signed) {
  if (!signed) return null;
  const i = signed.lastIndexOf('.');
  const payload = signed.slice(0, i), mac = signed.slice(i + 1);
  const want = crypto.createHmac('sha256', key()).update(payload).digest('base64url');
  const a = Buffer.from(mac), b = Buffer.from(want);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;
  const j = payload.lastIndexOf('.');
  if (Number(payload.slice(j + 1)) < Math.floor(Date.now() / 1000)) return null;
  return payload.slice(0, j);
}
