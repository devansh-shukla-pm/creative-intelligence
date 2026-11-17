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

// Cancels the GitHub Actions run that is processing a report. Best effort: the worker also stops by itself at its next progress
// update once the report is marked cancelled, so a failure here only means it stops a few seconds later.
export async function cancelReportRun(reportId) {
  const { mode, githubRepo, githubToken } = config.dispatch;
  if (mode !== 'github' || !githubToken) return false;
  const h = { Authorization: `Bearer ${githubToken}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'creative-intelligence' };
  for (const status of ['in_progress', 'queued']) {
    const r = await fetch(`https://api.github.com/repos/${githubRepo}/actions/workflows/report.yml/runs?status=${status}&per_page=30`, { headers: h });
    if (!r.ok) continue;
    const runs = (await r.json()).workflow_runs || [];
    const hit = runs.find(x => String(x.display_title || x.name || '').includes(reportId));
    if (hit) {
      const c = await fetch(`https://api.github.com/repos/${githubRepo}/actions/runs/${hit.id}/cancel`, { method: 'POST', headers: h });
      return c.status === 202;
    }
  }
  return false;
}
