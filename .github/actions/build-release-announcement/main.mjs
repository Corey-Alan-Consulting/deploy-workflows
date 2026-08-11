#!/usr/bin/env node
// Release-announcement builder entrypoint (multi-brand). Run from a checkout
// of the release tag with env:
//   VERSION                     released app version (e.g. 0.4.2)
//   PRODUCT_NAME                brand name for the title/prompt (e.g. Dispatchr)
//   PRODUCT_DESCRIPTION         one clause for the prompt (e.g. "a social
//                               dispatching platform")
//   HEALTH_URL                  prod endpoint to verify before announcing
//   HEALTH_MODE                 version | status | skip (see matrix.mjs)
//   CHANGELOG_URL               optional public changelog link for the email
//   CHANNELS_JSON               optional JSON array of extra release channels
//                               [{name, workflow, tagPrefix}]
//   GITHUB_REPOSITORY           owner/repo (provided by Actions)
//   GITHUB_TOKEN                for channel-run lookups
//   ANTHROPIC_OAUTH_TOKEN       editorial pass — short-lived federated token
//                               (or DEPRECATED ANTHROPIC_API_KEY fallback)
//   COREYALAN_API_URL           e.g. https://coreyalan.com
//   COREYALAN_RELEASE_API_KEY   sk_live_* with release-announcements scopes;
//                               its source binding selects the tenant
//   GITHUB_OUTPUT / GITHUB_STEP_SUMMARY  standard Actions files
//
// Exit codes are load-bearing: any failure must fail the workflow loudly —
// a silently skipped announcement is how the old system rotted.

import { appendFileSync } from 'node:fs';
import { aggregateChangelogs } from './aggregate.mjs';
import { waitForWebLive, buildSurfaceMatrix } from './matrix.mjs';
import { buildPrompt, editorial } from './editorial.mjs';

const env = name => {
  const v = process.env[name];
  if (!v) throw new Error(`Missing required env: ${name}`);
  return v;
};

// Federated (Bearer) token preferred; static key is the deprecated fallback.
const anthropicAuth = () => {
  const token = process.env.ANTHROPIC_OAUTH_TOKEN;
  if (token) return { token };
  return { apiKey: env('ANTHROPIC_API_KEY') };
};

const version = env('VERSION');
const productName = env('PRODUCT_NAME');
const productDescription = env('PRODUCT_DESCRIPTION');
const repo = env('GITHUB_REPOSITORY');
const apiUrl = env('COREYALAN_API_URL').replace(/\/$/, '');
const releaseKey = env('COREYALAN_RELEASE_API_KEY');
const changelogUrl = process.env.CHANGELOG_URL || undefined;
const channels = process.env.CHANNELS_JSON ? JSON.parse(process.env.CHANNELS_JSON) : [];

console.log(`Building release announcement for ${productName} ${version}`);

const healthMode = process.env.HEALTH_MODE || 'version';
if (healthMode !== 'skip') {
  console.log(`Waiting for prod (${healthMode} gate)…`);
  await waitForWebLive({ version, healthUrl: env('HEALTH_URL'), mode: healthMode });
  console.log('Prod is live.');
}

const { packages } = aggregateChangelogs(process.cwd(), version);
console.log(
  `Aggregated ${packages.reduce((n, p) => n + p.entries.length, 0)} entries from ${packages.length} packages.`
);

const surfaces = await buildSurfaceMatrix({
  version,
  repo,
  ghToken: env('GITHUB_TOKEN'),
  channels,
});

const promptArgs = { productName, productDescription, version, packages, surfaces, changelogUrl };
const artifact = await editorial({
  ...anthropicAuth(),
  prompt: buildPrompt(promptArgs),
});

// Rollup: supersede any unsent drafts for older versions. The server only
// touches DRAFT rows, so listing generously is safe; we name the last few
// patch versions below this one.
const [maj, min, pat] = version.split('.').map(Number);
const supersedes = [];
for (let p = pat - 1; p >= 0 && supersedes.length < 5; p--) {
  supersedes.push(`${maj}.${min}.${p}`);
}

// Idempotency scope: replays of THIS workflow run reuse the key, while a
// regeneration (new run, same version) gets a fresh one — the editorial
// pass is non-deterministic, so a version-only key 409s IDEMPOTENCY_CONFLICT
// on every re-draft. Cross-run dedup is the (source, version) upsert itself.
const runScope = process.env.GITHUB_RUN_ID
  ? `-${process.env.GITHUB_RUN_ID}.${process.env.GITHUB_RUN_ATTEMPT ?? 1}`
  : '';

const upsert = async (content, idempotencySuffix = '') => {
  const res = await fetch(`${apiUrl}/api/v1/release-announcements`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-api-key': releaseKey,
      'idempotency-key': `release-announce-${version}${runScope}${idempotencySuffix}`,
    },
    body: JSON.stringify({ version, content, surfaces, supersedes }),
  });
  return { status: res.status, body: await res.json().catch(() => ({})) };
};

let result = await upsert(artifact);
if (result.status === 400 && result.body?.details?.errors) {
  // Server-side schema is the hard gate; give the model its errors once.
  console.warn('Server rejected artifact, retrying editorial with feedback…');
  const retried = await editorial({
    ...anthropicAuth(),
    prompt:
      buildPrompt(promptArgs) +
      `\n\nA previous attempt failed server validation with:\n${JSON.stringify(result.body.details.errors)}`,
  });
  result = await upsert(retried, '-retry');
}

if (result.status !== 200) {
  throw new Error(
    `Draft upsert failed: HTTP ${result.status} ${JSON.stringify(result.body).slice(0, 500)}`
  );
}

const { summary, superseded } = result.body.data;
console.log(`Draft ${summary.id} created (superseded: ${superseded.join(', ') || 'none'}).`);

if (process.env.GITHUB_OUTPUT) {
  appendFileSync(process.env.GITHUB_OUTPUT, `announcement_id=${summary.id}\n`);
  appendFileSync(process.env.GITHUB_OUTPUT, `announcement_version=${summary.version}\n`);
}
if (process.env.GITHUB_STEP_SUMMARY) {
  appendFileSync(
    process.env.GITHUB_STEP_SUMMARY,
    `## Release announcement draft — ${productName} ${summary.version}\n\n` +
      `Announcement \`${summary.id}\` (supersedes: ${superseded.join(', ') || 'none'})\n\n` +
      `**${artifact.title}** — ${artifact.summary}\n\n` +
      surfaces.map(s => `- ${s.name}: ${s.status}`).join('\n') +
      '\n\nApprove the send in Port (Announce Release run).\n'
  );
}
