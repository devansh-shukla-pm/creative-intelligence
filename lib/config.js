// All environment access in one place. Defaults are for local dev; production values come from Vercel env vars.
const env = process.env;

export const config = {
  isProd: env.VERCEL_ENV === 'production' || env.NODE_ENV === 'production',
  databaseUrl: env.DATABASE_URL || '',
  encryptionKey: env.ENCRYPTION_KEY || '',           // base64, 32 bytes. Generate: openssl rand -base64 32
  appUrl: (env.APP_URL || '').replace(/\/$/, ''),    // e.g. https://creative-intelligence.vercel.app (no trailing slash)
  meta: {
    appId: env.META_APP_ID || '',
    appSecret: env.META_APP_SECRET || '',
    apiVersion: env.META_API_VERSION || 'v23.0',
    scopes: env.META_SCOPES || 'ads_read,pages_read_engagement,pages_show_list',
    mock: env.MOCK_META === '1',                     // local dev without a Meta app
  },
  sessionDays: Number(env.SESSION_DAYS || 14),
  allowedUserIds: (env.ALLOWED_META_USER_IDS || '').split(',').map(s => s.trim()).filter(Boolean),
  limits: {
    reportsPerUserPerDay: Number(env.REPORTS_PER_USER_PER_DAY || 20),
    runningReportsPerUser: Number(env.RUNNING_REPORTS_PER_USER || 2),
    reuseHours: Number(env.REPORT_REUSE_HOURS || 6),
  },
  dispatch: {
    mode: env.DISPATCH_MODE || 'github',             // github | local | none
    githubRepo: env.GITHUB_REPO || 'devansh-shukla-pm/creative-intelligence',
    githubToken: env.GITHUB_DISPATCH_TOKEN || '',    // fine-grained token, Actions: read & write on this repo
    localPython: env.LOCAL_PYTHON || '.venv/bin/python',
  },
};

export function requireConfig(...keys) {
  const missing = keys.filter(k => !k.split('.').reduce((o, p) => (o ? o[p] : undefined), config));
  if (missing.length) throw new Error(`Missing configuration: ${missing.join(', ')}`);
}
