// node:test suite for the reusable release-announcement builder. Run with:
//   node --test .github/actions/build-release-announcement/announcement.test.mjs
// Dependency-free like the scripts themselves — no vitest/jest harness.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { splitSections, extractEntries, entriesForVersion } from './changelog.mjs';
import { aggregateChangelogs } from './aggregate.mjs';
import { waitForWebLive, buildSurfaceMatrix } from './matrix.mjs';
import { buildPrompt, validateArtifact, parseModelJson, editorial } from './editorial.mjs';

const CHANGESETS_MD = `# @dispatchr/web

## 0.4.2

### Patch Changes

- d67ff98f: Fix a feed crash when a boosted post is deleted mid-scroll; the
  timeline now tombstones it instead.
- 595c78cb: Fix avatar uploads over 5 MB silently failing.
- Updated dependencies [ac8f7e4f]
  - @dispatchr/ui@0.4.2

## 0.4.1

### Patch Changes

- 9f664974: Faster timeline hydration on slow connections.
`;

const EMPTY_ROOT_MD = `# Changelog

## 0.4.2

## 0.4.1
`;

test('splitSections maps versions to bodies', () => {
  const sections = splitSections(CHANGESETS_MD);
  assert.deepEqual([...sections.keys()], ['0.4.2', '0.4.1']);
  assert.match(sections.get('0.4.1'), /hydration/);
});

test('extractEntries strips hashes, folds continuations, drops dependency noise', () => {
  const entries = extractEntries(splitSections(CHANGESETS_MD).get('0.4.2'));
  assert.equal(entries.length, 2);
  assert.match(entries[0], /^Fix a feed crash/);
  assert.match(entries[0], /tombstones it instead\.$/); // continuation folded
  assert.ok(!entries.some(e => /Updated dependencies/i.test(e)));
});

// @changesets/changelog-github format — what the single-package brand repos
// (jlshaw, blue-sky, coreyalan) produce for their root CHANGELOG.
const GITHUB_FORMAT_MD = `# Changelog

## 0.13.3

### Patch Changes

- [#105](https://github.com/o/r/pull/105) [\`d065488\`](https://github.com/o/r/commit/d065488) Thanks [@NX211](https://github.com/NX211)! - Publish Persistence Pays episodes 2, 3, and 4.

- [#105](https://github.com/o/r/pull/105) [\`d065488\`](https://github.com/o/r/commit/d065488) Thanks [@NX211](https://github.com/NX211)! - Resolve Trivy image vulnerabilities.
  - **Migration image**: patch OS packages and upgrade npm to 11.x.
`;

test('extractEntries strips the changelog-github preamble and keeps the message', () => {
  const entries = extractEntries(splitSections(GITHUB_FORMAT_MD).get('0.13.3'));
  assert.equal(entries.length, 2);
  assert.equal(entries[0], 'Publish Persistence Pays episodes 2, 3, and 4.');
  assert.match(entries[1], /^Resolve Trivy image vulnerabilities\./);
  assert.match(entries[1], /Migration image/); // sub-bullet folded in
  assert.ok(!entries.some(e => /Thanks \[@/.test(e)));
});

test('aggregateChangelogs includes a single-package repo root as the app package', () => {
  const root = mkdtempSync(join(tmpdir(), 'ra-root-'));
  writeFileSync(
    join(root, 'package.json'),
    JSON.stringify({ name: 'jlshaw-link', version: '0.13.3' })
  );
  writeFileSync(join(root, 'CHANGELOG.md'), GITHUB_FORMAT_MD);
  const { packages } = aggregateChangelogs(root, '0.13.3');
  assert.equal(packages.length, 1);
  assert.equal(packages[0].name, 'jlshaw-link');
  assert.equal(packages[0].entries.length, 2);
});

test('entriesForVersion returns null for versions a package never released', () => {
  assert.equal(entriesForVersion(CHANGESETS_MD, '9.9.9'), null);
});

test('the empty-root-changelog case yields no entries (the original bug)', () => {
  assert.deepEqual(entriesForVersion(EMPTY_ROOT_MD, '0.4.2'), []);
});

const scaffoldRepo = ({ webChangelog, rootChangelog }) => {
  const root = mkdtempSync(join(tmpdir(), 'ra-test-'));
  mkdirSync(join(root, 'apps/web'), { recursive: true });
  writeFileSync(
    join(root, 'apps/web/package.json'),
    JSON.stringify({ name: '@dispatchr/web', version: '0.4.2' })
  );
  writeFileSync(join(root, 'apps/web/CHANGELOG.md'), webChangelog);
  writeFileSync(
    join(root, 'package.json'),
    JSON.stringify({ name: 'dispatchr', version: '0.4.2' })
  );
  writeFileSync(join(root, 'CHANGELOG.md'), rootChangelog);
  return root;
};

test('aggregateChangelogs collects per-package entries despite an empty root', () => {
  const root = scaffoldRepo({ webChangelog: CHANGESETS_MD, rootChangelog: EMPTY_ROOT_MD });
  const { packages } = aggregateChangelogs(root, '0.4.2');
  assert.equal(packages.length, 1);
  assert.equal(packages[0].name, '@dispatchr/web');
  assert.equal(packages[0].entries.length, 2);
});

test('aggregateChangelogs hard-fails when the union is empty', () => {
  const root = scaffoldRepo({ webChangelog: EMPTY_ROOT_MD, rootChangelog: EMPTY_ROOT_MD });
  assert.throws(() => aggregateChangelogs(root, '0.4.2'), /builder bug/);
});

test('waitForWebLive (version mode) resolves once prod serves the version', async () => {
  let calls = 0;
  const fetchImpl = async () => ({
    ok: true,
    json: async () =>
      ++calls < 3
        ? { version: '0.4.1', status: 'healthy' }
        : { version: '0.4.2', status: 'healthy' },
  });
  await waitForWebLive({
    version: '0.4.2',
    healthUrl: 'https://example.com/api/health',
    mode: 'version',
    fetchImpl,
    timeoutMs: 10_000,
    intervalMs: 1,
    sleep: () => Promise.resolve(),
  });
  assert.equal(calls, 3);
});

test('waitForWebLive (status mode) resolves on any 2xx without reading a body', async () => {
  let calls = 0;
  const fetchImpl = async () => {
    calls++;
    return calls < 2 ? { ok: false, status: 503 } : { ok: true };
  };
  await waitForWebLive({
    version: '0.4.2',
    healthUrl: 'https://example.com/',
    mode: 'status',
    fetchImpl,
    timeoutMs: 10_000,
    intervalMs: 1,
    sleep: () => Promise.resolve(),
  });
  assert.equal(calls, 2);
});

test('waitForWebLive throws at the deadline instead of announcing a dead release', async () => {
  const fetchImpl = async () => ({
    ok: true,
    json: async () => ({ version: '0.4.1', status: 'healthy' }),
  });
  await assert.rejects(
    waitForWebLive({
      version: '0.4.2',
      healthUrl: 'https://example.com/api/health',
      mode: 'version',
      fetchImpl,
      timeoutMs: 0,
      intervalMs: 1,
      sleep: () => Promise.resolve(),
    }),
    /refusing to announce/
  );
});

test('waitForWebLive skip mode returns immediately without a URL', async () => {
  await waitForWebLive({ version: '0.4.2', mode: 'skip' });
});

test('waitForWebLive demands a URL for polling modes', async () => {
  await assert.rejects(
    waitForWebLive({ version: '0.4.2', mode: 'status' }),
    /healthUrl is required/
  );
});

test('buildSurfaceMatrix with no channels is the bare Web row', async () => {
  const surfaces = await buildSurfaceMatrix({
    version: '0.4.2',
    repo: 'o/r',
    ghToken: 't',
    fetchImpl: async () => {
      throw new Error('must not be called');
    },
  });
  assert.deepEqual(surfaces, [{ name: 'Web', status: 'live' }]);
});

test('buildSurfaceMatrix maps run conclusions and degrades per-channel', async () => {
  const channels = [
    { name: 'Desktop', workflow: 'release-desktop.yml', tagPrefix: 'app@' },
    { name: 'Android', workflow: 'release-android.yml', tagPrefix: 'mobile@' },
    { name: 'Extension', workflow: 'release-extension.yml', tagPrefix: 'ext@' },
  ];
  const fetchImpl = async url => {
    if (url.includes('release-desktop')) {
      return {
        ok: true,
        json: async () => ({
          workflow_runs: [{ head_branch: 'app@0.4.2', conclusion: 'success' }],
        }),
      };
    }
    if (url.includes('release-android')) {
      return {
        ok: true,
        json: async () => ({
          workflow_runs: [{ head_branch: 'mobile@0.4.2', conclusion: null }],
        }),
      };
    }
    throw new Error('boom');
  };
  const surfaces = await buildSurfaceMatrix({
    version: '0.4.2',
    repo: 'o/r',
    ghToken: 't',
    channels,
    fetchImpl,
  });
  assert.deepEqual(surfaces[0], { name: 'Web', status: 'live' });
  assert.equal(surfaces.find(s => s.name === 'Desktop').status, 'released');
  assert.equal(surfaces.find(s => s.name === 'Android').status, 'in progress');
  assert.equal(surfaces.find(s => s.name === 'Extension').status, 'unknown');
});

const GOOD_ARTIFACT = {
  title: 'Dispatchr 0.4.2',
  summary: 'Fixes.',
  highlights: ['x'],
  sections: { added: [], improved: [], fixed: [{ title: 'Feed stability' }] },
  audience: 'internal',
};

test('validateArtifact accepts the contract and rejects empty sections', () => {
  assert.deepEqual(validateArtifact(GOOD_ARTIFACT), []);
  assert.ok(
    validateArtifact({ ...GOOD_ARTIFACT, sections: { added: [], improved: [], fixed: [] } })
      .length > 0
  );
});

test('parseModelJson unwraps fenced output', () => {
  const parsed = parseModelJson('```json\n{"a":1}\n```');
  assert.deepEqual(parsed, { a: 1 });
});

test('editorial retries once with validation feedback, then succeeds', async () => {
  let calls = 0;
  const fetchImpl = async (_url, init) => {
    calls++;
    const body = JSON.parse(init.body);
    if (calls === 1) {
      return {
        ok: true,
        json: async () => ({ content: [{ text: '{"title":"broken"}' }] }),
      };
    }
    // The retry must carry the failure feedback back to the model.
    assert.match(JSON.stringify(body.messages), /failed validation/);
    return {
      ok: true,
      json: async () => ({ content: [{ text: JSON.stringify(GOOD_ARTIFACT) }] }),
    };
  };
  const artifact = await editorial({ token: 'sk-ant-oat01-k', prompt: 'p', fetchImpl });
  assert.equal(calls, 2);
  assert.equal(artifact.title, 'Dispatchr 0.4.2');
});

test('editorial authenticates with the federated token as a Bearer', async () => {
  const seen = [];
  const fetchImpl = async (_url, init) => {
    seen.push(init.headers);
    return { ok: true, json: async () => ({ content: [{ text: JSON.stringify(GOOD_ARTIFACT) }] }) };
  };
  await editorial({ token: 'sk-ant-oat01-abc', prompt: 'p', fetchImpl });
  assert.equal(seen[0].authorization, 'Bearer sk-ant-oat01-abc');
  assert.equal(seen[0]['x-api-key'], undefined);
});

test('editorial fails loudly when the retry is still invalid', async () => {
  const fetchImpl = async () => ({
    ok: true,
    json: async () => ({ content: [{ text: '{"title":"still broken"}' }] }),
  });
  await assert.rejects(editorial({ token: 'sk-ant-oat01-k', prompt: 'p', fetchImpl }), /after retry/);
});

test('buildPrompt pins the branded title and embeds every raw entry', () => {
  const prompt = buildPrompt({
    productName: 'Dispatchr',
    productDescription: 'a social dispatching platform',
    version: '0.4.2',
    packages: [{ name: '@dispatchr/web', version: '0.4.2', entries: ['Fix the thing'] }],
    surfaces: [{ name: 'Web', status: 'live' }],
    changelogUrl: 'https://example.com/changelog',
  });
  assert.match(prompt, /Dispatchr 0\.4\.2/);
  assert.match(prompt, /a social dispatching platform/);
  assert.match(prompt, /Fix the thing/);
  assert.match(prompt, /"changelogUrl": "https:\/\/example\.com\/changelog"/);
});

test('buildPrompt omits changelogUrl from the contract when none is configured', () => {
  const prompt = buildPrompt({
    productName: 'Dispatchr',
    productDescription: 'a social dispatching platform',
    version: '0.4.2',
    packages: [{ name: '@dispatchr/web', version: '0.4.2', entries: ['Fix the thing'] }],
    surfaces: [{ name: 'Web', status: 'live' }],
  });
  assert.ok(!prompt.includes('changelogUrl'));
});
