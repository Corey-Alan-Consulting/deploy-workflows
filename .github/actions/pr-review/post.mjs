// Publishes review.mjs's findings as ONE advisory GitHub review. This is the
// only step holding a GitHub token, and it never runs a model.
//
// Findings on a line the diff touches become inline comments; the rest go in
// the review body. A hidden marker per finding (kind + file) lets a later push
// skip what an earlier review already said, so synchronize events do not
// repeat themselves.
//
// Usage: node post.mjs --findings <file> --patch <file>
//   env: GH_TOKEN, REPO (owner/name), PR, HEAD_SHA

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const API = 'https://api.github.com';

// path -> Set of head-side line numbers GitHub accepts a comment on.
export function commentableLines(patch) {
  const out = new Map();
  let path = null;
  let line = 0;
  for (const raw of patch.split('\n')) {
    if (raw.startsWith('+++ ')) {
      path = raw.slice(4) === '/dev/null' ? null : raw.slice(4).replace(/^b\//, '');
      if (path && !out.has(path)) out.set(path, new Set());
      continue;
    }
    const hunk = raw.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (hunk) { line = Number(hunk[1]); continue; }
    if (!path || raw.startsWith('--- ') || raw.startsWith('\\')) continue;
    if (raw.startsWith('+') || raw.startsWith(' ')) { out.get(path).add(line); line += 1; }
  }
  return out;
}

export const marker = (f) => `<!-- pr-review:${f.kind}:${f.file} -->`;

const CLASS_LABEL = {
  decision: 'needs a decision',
  behavioral: 'changes behaviour',
  mechanical: 'mechanical fix',
};

function render(f) {
  const lines = [
    `**${f.severity}** · ${CLASS_LABEL[f.class]} · \`${f.kind}\``,
    '',
    f.summary,
  ];
  if (f.evidence) lines.push('', `<sub>Evidence: ${f.evidence}</sub>`);
  if (f.fix) lines.push('', `Suggested: ${f.fix}`);
  lines.push('', marker(f));
  return lines.join('\n');
}

export function buildReview(result, patch, alreadyPosted) {
  const lines = commentableLines(patch);
  const fresh = result.findings.filter((f) => !alreadyPosted.has(marker(f)));
  const comments = [];
  const general = [];
  for (const f of fresh) {
    if (f.line && lines.get(f.file)?.has(f.line)) {
      comments.push({ path: f.file, line: f.line, side: 'RIGHT', body: render(f) });
    } else {
      general.push(`- \`${f.file}${f.line ? `:${f.line}` : ''}\`: ${render(f).replace(/\n+/g, ' ')}`);
    }
  }
  if (fresh.length === 0) return null;
  const body = [
    `### Automated review: ${fresh.length} finding${fresh.length === 1 ? '' : 's'}`,
    '',
    `Advisory: nothing here blocks the merge. Independent passes (${Object.keys(result.passes).join(', ')}) `
      + `were aggregated by discarding (${result.dropped} dropped). Resolve a thread to mark it handled.`,
    ...(general.length ? ['', '**Not on a changed line**', '', ...general] : []),
  ].join('\n');
  return { body, comments, general: general.length };
}

async function gh(path, token, init = {}) {
  const r = await fetch(`${API}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', ...init.headers },
  });
  if (!r.ok) throw new Error(`${init.method ?? 'GET'} ${path}: ${r.status} ${await r.text()}`);
  return r.status === 204 ? null : r.json();
}

async function main() {
  const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, all) =>
    (i % 2 === 0 ? [...a, [v.replace(/^--/, ''), all[i + 1]]] : a), []));
  const { GH_TOKEN: token, REPO: repo, PR: pr, HEAD_SHA: sha } = process.env;
  const result = JSON.parse(readFileSync(args.findings, 'utf8'));
  const patch = readFileSync(args.patch, 'utf8');

  const posted = new Set();
  for (let page = 1; ; page += 1) {
    const batch = await gh(`/repos/${repo}/pulls/${pr}/comments?per_page=100&page=${page}`, token);
    for (const c of batch) for (const m of c.body.matchAll(/<!-- pr-review:[^>]+ -->/g)) posted.add(m[0]);
    if (batch.length < 100) break;
  }
  const reviews = await gh(`/repos/${repo}/pulls/${pr}/reviews?per_page=100`, token);
  for (const rv of reviews) for (const m of (rv.body ?? '').matchAll(/<!-- pr-review:[^>]+ -->/g)) posted.add(m[0]);

  const review = buildReview(result, patch, posted);
  if (!review) { console.log('pr-review: nothing new to post'); return; }
  await gh(`/repos/${repo}/pulls/${pr}/reviews`, token, {
    method: 'POST',
    body: JSON.stringify({ commit_id: sha, event: 'COMMENT', body: review.body, comments: review.comments }),
  });
  console.log(`pr-review: posted ${review.comments.length} inline + ${review.general} general`);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main().catch((e) => { console.error(`::error::${e.message}`); process.exit(1); });
}
