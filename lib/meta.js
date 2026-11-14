// Meta (Facebook) Login + the few Graph calls the API layer needs. The heavy pulls happen in the worker.
import { config, requireConfig } from './config.js';

const base = () => `https://graph.facebook.com/${config.meta.apiVersion}`;

export const MOCK_ACCOUNTS = [
  { id: '1000000000001', name: 'Shesha Ayurveda (mock account)', currency: 'INR' },
];

export function redirectUri() { return `${config.appUrl}/api/auth/callback`; }

export function loginUrl(state) {
  requireConfig('meta.appId', 'appUrl');
  const p = new URLSearchParams({
    client_id: config.meta.appId,
    redirect_uri: redirectUri(),
    state,
    scope: config.meta.scopes,
    response_type: 'code',
  });
  return `https://www.facebook.com/${config.meta.apiVersion}/dialog/oauth?${p}`;
}

async function graph(path, params = {}, token) {
  const p = new URLSearchParams(params);
  if (token) p.set('access_token', token);
  const r = await fetch(`${base()}${path}?${p}`);
  const body = await r.json().catch(() => ({}));
  if (!r.ok || body.error) {
    const e = new Error(body.error?.message || `Meta API error ${r.status}`);
    e.code = body.error?.code;
    e.status = r.status === 401 || body.error?.code === 190 ? 401 : 502;
    throw e;
  }
  return body;
}

export async function exchangeCode(code) {
  requireConfig('meta.appId', 'meta.appSecret', 'appUrl');
  const short = await graph('/oauth/access_token', {
    client_id: config.meta.appId, client_secret: config.meta.appSecret, redirect_uri: redirectUri(), code,
  });
  // Swap the short-lived token for a long-lived one (about 60 days).
  const long = await graph('/oauth/access_token', {
    grant_type: 'fb_exchange_token', client_id: config.meta.appId, client_secret: config.meta.appSecret,
    fb_exchange_token: short.access_token,
  });
  const expiresIn = Number(long.expires_in || 60 * 86400);
  return { token: long.access_token, expiresAt: new Date(Date.now() + expiresIn * 1000) };
}

export const getMe = token => graph('/me', { fields: 'id,name' }, token);

export async function listAdAccounts(token) {
  const out = [];
  let after;
  for (let i = 0; i < 10; i++) {
    const r = await graph('/me/adaccounts', {
      fields: 'account_id,name,currency,account_status', limit: '100', ...(after ? { after } : {}),
    }, token);
    for (const a of r.data || []) {
      out.push({ id: String(a.account_id), name: a.name || `Account ${a.account_id}`, currency: a.currency || '', active: a.account_status === 1 });
    }
    after = r.paging?.cursors?.after;
    if (!r.paging?.next) break;
  }
  return out;
}

// Confirms the user can really read this account (and returns its name and currency).
export async function getAdAccount(token, accountId) {
  const a = await graph(`/act_${accountId}`, { fields: 'account_id,name,currency' }, token);
  return { id: String(a.account_id), name: a.name, currency: a.currency };
}
