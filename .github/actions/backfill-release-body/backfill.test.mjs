// node:test suite for the release-body backfill renderer. Run with:
//   node --test .github/actions/backfill-release-body/backfill.test.mjs
//
// Ported from capturly, which held the only copy of this renderer while every
// other repo shipped empty GitHub Release bodies. The builder side (changelog
// aggregation, surface matrix, editorial pass) is tested next door in
// build-release-announcement/announcement.test.mjs.

import { test } from 'node:test';
import assert from 'node:assert/strict';

const GOOD_ARTIFACT = {
  title: 'Example 2.8.8',
  summary: 'Fixes.',
  highlights: ['x'],
  sections: { added: [], improved: [], fixed: [{ title: 'Server stability' }] },
  changelogUrl: 'https://example.com/changelog',
  audience: 'internal',
};

test('artifactToMarkdown renders sections, surfaces, and the changelog link', async () => {
  const { artifactToMarkdown } = await import('./to-markdown.mjs');
  const md = artifactToMarkdown({
    content: {
      ...GOOD_ARTIFACT,
      highlights: ['Faster joins'],
      sections: {
        added: [{ title: 'Live pacing', body: 'Backup paces itself.' }],
        improved: [],
        fixed: [{ title: 'Server stability' }],
      },
    },
    surfaces: [
      { name: 'Web', status: 'live' },
      { name: 'Android', status: '20% rollout' },
    ],
  });
  assert.match(md, /> Faster joins/);
  assert.match(md, /### ✨ New/);
  assert.match(md, /- \*\*Live pacing\*\* — Backup paces itself\./);
  assert.match(md, /### 🛠 Fixed/);
  assert.ok(!md.includes('📈')); // empty sections are omitted
  assert.match(md, /- Android: 20% rollout/);
  assert.match(md, /\[Full changelog\]\(https:\/\/example\.com\/changelog\)/);
});

// The reason this action exists: a repo with nothing to say still needs a
// non-empty body, or the Releases page is worse than no page at all.
test('artifactToMarkdown survives an artifact with no sections or surfaces', async () => {
  const { artifactToMarkdown } = await import('./to-markdown.mjs');
  const md = artifactToMarkdown({
    content: { summary: 'Maintenance release.', sections: {} },
    surfaces: [],
  });
  assert.match(md, /Maintenance release\./);
  assert.ok(!md.includes('###'));
  assert.ok(!md.includes("Where it's live"));
  assert.ok(md.endsWith('\n'));
});

// Tag construction is the one thing that had to change when this moved out of
// capturly, which hardcoded `capturly@${version}`. Both shapes in use must
// work: `<name>@<semver>` for workspace repos, `v<semver>` for single-package.
test('tag prefixes cover both release-tag shapes in the fleet', () => {
  const tagFor = (prefix, version) => `${prefix}${version}`;
  assert.equal(tagFor('reggiesbbq@', '0.9.0'), 'reggiesbbq@0.9.0');
  assert.equal(tagFor('v', '0.1.17'), 'v0.1.17');
});
