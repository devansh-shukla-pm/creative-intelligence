// Starts the worker for a report. Production: a GitHub Actions workflow_dispatch (needs only the fine-grained token permission Actions: read and write). Local dev: spawn the Python worker.
import { spawn } from 'node:child_process';
import { config } from './config.js';

export async function dispatchReport(reportId) {
  const { mode, githubRepo, githubToken, localPython } = config.dispatch;
  if (mode === 'none') return { mode };
  if (mode === 'local') {
    const child = spawn(localPython, ['-m', 'worker.run', '--report', reportId], {
      cwd: new URL('..', import.meta.url).pathname, env: process.env, stdio: 'inherit', detached: true,
    });
    child.unref();
    return { mode };
  }
  if (!githubToken) throw new Error('GITHUB_DISPATCH_TOKEN is not set');
  const r = await fetch(`https://api.github.com/repos/${githubRepo}/actions/workflows/report.yml/dispatches`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${githubToken}`, Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json', 'User-Agent': 'creative-intelligence',
    },
    body: JSON.stringify({ ref: 'main', inputs: { report_id: reportId } }),
  });
  if (r.status !== 204) throw new Error(`GitHub dispatch failed (${r.status}): ${(await r.text()).slice(0, 200)}`);
  return { mode };
}
