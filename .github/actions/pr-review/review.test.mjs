// node:test suite for the PR review harness. Run with:
//   node --test .github/actions/pr-review/review.test.mjs
// No model calls: covers parsing, normalisation, the agent's environment and
// fence, and how findings map onto a GitHub review.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseModelJson, normalizeFindings, reviewable, agentEnv, agentSettings } from './review.mjs';
import { commentableLines, buildReview, marker } from './post.mjs';

test('parseModelJson takes bare JSON, a fenced block, or JSON after a lead-in', () => {
  assert.deepEqual(parseModelJson('{"findings":[]}'), { findings: [] });
  assert.deepEqual(parseModelJson('```json\n{"findings":[1]}\n```'), { findings: [1] });
  assert.deepEqual(parseModelJson('Here you go:\n{"dropped":2}'), { dropped: 2 });
  assert.equal(parseModelJson('no json here'), null);
  assert.equal(parseModelJson(undefined), null);
});

test('normalizeFindings drops malformed entries and sorts by severity then class', () => {
  const out = normalizeFindings({ findings: [
    { kind: 'a', class: 'mechanical', severity: 'low', file: 'x.ts', line: 3, summary: 's1' },
    { kind: 'b', class: 'decision', severity: 'high', file: 'y.ts', line: 9, summary: 's2' },
    { kind: 'c', file: 'z.ts', summary: 's3' },
    { summary: 'no file' },
    null,
  ] });
  assert.deepEqual(out.map((f) => f.kind), ['b', 'c', 'a']);
  assert.equal(out[1].class, 'decision', 'unknown class defaults to decision: a person reads it');
  assert.equal(out[1].line, null);
});

test('normalizeFindings refuses a kind that is not a slug', () => {
  const [f] = normalizeFindings({ findings: [{ kind: 'Tax is not applied here', file: 'a', summary: 's' }] });
  assert.equal(f.kind, 'unclassified');
});

test('reviewable skips lockfiles, changelogs and build output, but keeps changesets', () => {
  for (const p of ['pnpm-lock.yaml', 'apps/web/CHANGELOG.md', 'apps/web/.next/a.js', 'a.snap']) {
    assert.equal(reviewable(p), false, p);
  }
  assert.equal(reviewable('apps/web/src/lib/tax.ts'), true);
  assert.equal(reviewable('.changeset/x.md'), true, 'the checklist checks the changeset');
  assert.equal(reviewable('packages/db/prisma/migrations/1/migration.sql'), true);
});

test('agentEnv strips every variable that could mint an OIDC token or call GitHub', () => {
  const env = agentEnv({
    ACTIONS_ID_TOKEN_REQUEST_TOKEN: 't', ACTIONS_ID_TOKEN_REQUEST_URL: 'u', ACTIONS_RUNTIME_TOKEN: 'r',
    GITHUB_TOKEN: 'g', GH_TOKEN: 'g', ANTHROPIC_API_KEY: 'k', PATH: '/bin',
  });
  assert.deepEqual(Object.keys(env), ['PATH']);
});

test('agentSettings fences reads to the checkout and denies every acting tool', () => {
  const s = agentSettings({ runnerTemp: '/home/runner/work/_temp' });
  assert.deepEqual(s.permissions.allow, ['Read(./**)'],
    'a bare Grep or Glob allow searches outside the checkout');
  for (const t of ['Bash', 'Edit', 'Write', 'WebFetch', 'WebSearch', 'Task']) {
    assert.ok(s.permissions.deny.includes(t), t);
  }
  assert.ok(s.permissions.deny.includes('Read(//proc/**)'));
  assert.ok(s.permissions.deny.includes('Read(//home/runner/work/_temp/**)'));
});

const PATCH = `diff --git a/src/tax.ts b/src/tax.ts
--- a/src/tax.ts
+++ b/src/tax.ts
@@ -10,3 +10,4 @@ export function tax() {
   const a = 1;
-  const b = 2;
+  const b = 3;
+  const c = 4;
   return a;
diff --git a/src/new.ts b/src/new.ts
--- /dev/null
+++ b/src/new.ts
@@ -0,0 +1,2 @@
+export const x = 1;
+export const y = 2;
diff --git a/src/gone.ts b/src/gone.ts
--- a/src/gone.ts
+++ /dev/null
@@ -1 +0,0 @@
-export const z = 1;
`;

test('commentableLines maps head-side lines inside hunks, including new files', () => {
  const m = commentableLines(PATCH);
  assert.deepEqual([...m.get('src/tax.ts')], [10, 11, 12, 13]);
  assert.deepEqual([...m.get('src/new.ts')], [1, 2]);
  assert.equal(m.has('src/gone.ts'), false);
});

const finding = (o) => ({ kind: 'k', class: 'decision', severity: 'high', file: 'src/tax.ts',
  line: 11, summary: 'wrong rate', evidence: 'read it', fix: 'use saved rate', ...o });

test('buildReview puts on-diff findings inline and the rest in the body', () => {
  const r = buildReview({ findings: [finding(), finding({ kind: 'k2', line: 40 })], passes: { correctness: {} }, dropped: 1 },
    PATCH, new Set());
  assert.equal(r.comments.length, 1);
  assert.equal(r.comments[0].line, 11);
  assert.equal(r.general, 1);
  assert.match(r.body, /src\/tax\.ts:40/);
  assert.match(r.comments[0].body, /<!-- pr-review:k:src\/tax\.ts -->/);
});

test('buildReview skips what an earlier review already posted, and posts nothing when all are known', () => {
  const f = finding();
  const result = { findings: [f], passes: {}, dropped: 0 };
  assert.equal(buildReview(result, PATCH, new Set([marker(f)])), null);
});
