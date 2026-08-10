// Live-verification + shipped-surface matrix for the announcement.
//
// Health modes:
//   version — poll until the endpoint reports { version: <released>, status:
//             "healthy" } (the strongest gate; needs a health endpoint that
//             exposes the running version, like capturly.app/api/health).
//   status  — poll until the endpoint returns any 2xx. Weaker, but the Port
//             promote gate that triggers this builder already verified the
//             Argo sync + health, so this is a reachability sanity check for
//             apps whose health endpoint doesn't expose a version.
//   skip    — no wait (tests/dry runs only).

/** Poll prod until `mode` is satisfied, or throw after `timeoutMs`. */
export async function waitForWebLive({
  version,
  healthUrl,
  mode = 'version',
  fetchImpl = fetch,
  timeoutMs = 20 * 60 * 1000,
  intervalMs = 30 * 1000,
  sleep = ms => new Promise(r => setTimeout(r, ms)),
}) {
  if (mode === 'skip') return;
  if (!healthUrl) throw new Error('healthUrl is required unless mode is "skip"');
  const deadline = Date.now() + timeoutMs;
  let last = 'unreachable';
  for (;;) {
    try {
      const res = await fetchImpl(healthUrl);
      if (res.ok) {
        if (mode === 'status') return;
        const body = await res.json();
        last = body.version ?? 'unknown';
        if (body.version === version && body.status === 'healthy') return;
      } else {
        last = `HTTP ${res.status}`;
      }
    } catch {
      last = 'unreachable';
    }
    if (Date.now() >= deadline) {
      throw new Error(
        `Prod never satisfied the "${mode}" health gate for ${version} within ` +
          `${timeoutMs / 60000} minutes (last saw: ${last}) — refusing to announce ` +
          'a release that is not live.'
      );
    }
    await sleep(intervalMs);
  }
}

/**
 * @param {{version: string, repo: string, ghToken: string,
 *          channels?: Array<{name: string, workflow: string, tagPrefix: string}>,
 *          fetchImpl?: typeof fetch}} opts
 * @returns {Promise<Array<{name: string, status: string, detail?: string}>>}
 * Channel lookups are best-effort: a matrix hole must never block the
 * announcement of a verified-live web release. Web-only apps pass no
 * channels and get the bare Web row.
 */
export async function buildSurfaceMatrix({
  version,
  repo,
  ghToken,
  channels = [],
  fetchImpl = fetch,
}) {
  const surfaces = [{ name: 'Web', status: 'live' }];
  for (const channel of channels) {
    try {
      const res = await fetchImpl(
        `https://api.github.com/repos/${repo}/actions/workflows/${channel.workflow}/runs?per_page=10`,
        { headers: { authorization: `Bearer ${ghToken}`, accept: 'application/vnd.github+json' } }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const { workflow_runs: runs = [] } = await res.json();
      const run = runs.find(r => r.head_branch === `${channel.tagPrefix}${version}`);
      if (!run) {
        surfaces.push({ name: channel.name, status: 'not released' });
      } else if (run.conclusion === 'success') {
        surfaces.push({ name: channel.name, status: 'released' });
      } else {
        surfaces.push({ name: channel.name, status: run.conclusion ?? 'in progress' });
      }
    } catch (err) {
      surfaces.push({
        name: channel.name,
        status: 'unknown',
        detail: `lookup failed: ${err instanceof Error ? err.message : String(err)}`,
      });
    }
  }
  return surfaces;
}
