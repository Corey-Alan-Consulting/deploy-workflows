#!/usr/bin/env node
// Backfill the GitHub Release body for the root tag from the announcement
// artifact. Runs in the send workflow after a successful send. Env:
//   ANNOUNCEMENT_ID, TAG_PREFIX, COREYALAN_API_URL,
//   COREYALAN_RELEASE_API_KEY, GITHUB_REPOSITORY, GITHUB_TOKEN
//
// Generalised from capturly's copy, which hardcoded `capturly@${version}`.
// The tag is now TAG_PREFIX + version, which covers both shapes in use:
// `reggiesbbq@0.9.0` (workspace repos) and `v0.1.17` (single-package repos,
// where the prefix is just "v").

import { artifactToMarkdown } from './to-markdown.mjs';

const env = name => {
  const v = process.env[name];
  if (!v) throw new Error(`Missing required env: ${name}`);
  return v;
};

const apiUrl = env('COREYALAN_API_URL').replace(/\/$/, '');
const repo = env('GITHUB_REPOSITORY');
const ghHeaders = {
  authorization: `Bearer ${env('GITHUB_TOKEN')}`,
  accept: 'application/vnd.github+json',
};

const annRes = await fetch(
  `${apiUrl}/api/v1/release-announcements/${env('ANNOUNCEMENT_ID')}`,
  { headers: { 'x-api-key': env('COREYALAN_RELEASE_API_KEY') } }
);
if (!annRes.ok) {
  throw new Error(`Failed to load announcement: HTTP ${annRes.status}`);
}
const { data } = await annRes.json();
const tag = `${env('TAG_PREFIX')}${data.version}`;

const relRes = await fetch(
  `https://api.github.com/repos/${repo}/releases/tags/${encodeURIComponent(tag)}`,
  { headers: ghHeaders }
);
if (!relRes.ok) {
  throw new Error(`Release for ${tag} not found: HTTP ${relRes.status}`);
}
const release = await relRes.json();

const body = artifactToMarkdown({ content: data.content, surfaces: data.surfaces });
const patch = await fetch(`https://api.github.com/repos/${repo}/releases/${release.id}`, {
  method: 'PATCH',
  headers: { ...ghHeaders, 'content-type': 'application/json' },
  body: JSON.stringify({ body }),
});
if (!patch.ok) {
  throw new Error(`Release body patch failed: HTTP ${patch.status}`);
}
console.log(`Backfilled release body for ${tag} (release ${release.id}).`);
