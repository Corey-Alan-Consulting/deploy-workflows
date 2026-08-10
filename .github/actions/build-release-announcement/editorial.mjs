// AI editorial pass: raw per-package changelog entries → the structured
// announcement artifact the coreyalan platform validates and renders.
// Dependency-free (plain fetch against the Anthropic Messages API); the
// hard schema gate lives server-side in the upsert endpoint — on a 400 the
// caller feeds the validation errors back for one retry.

const ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages';
const MODEL = 'claude-sonnet-5';

export function buildPrompt({
  productName,
  productDescription,
  version,
  packages,
  surfaces,
  changelogUrl,
}) {
  const raw = packages
    .map(p => `${p.name}@${p.version}:\n${p.entries.map(e => `- ${e}`).join('\n')}`)
    .join('\n\n');
  const surfaceText = surfaces.map(s => `- ${s.name}: ${s.status}`).join('\n');
  const changelogField = changelogUrl
    ? `\n  "changelogUrl": ${JSON.stringify(changelogUrl)},`
    : '';
  return `You are the release-notes editor for ${productName}, ${productDescription}.
Turn the raw changelog entries below into a release announcement artifact.

Rules:
- Classify every reader-relevant entry as added (new capability), improved, or fixed.
- DROP internal-only noise entirely: CI/workflow changes, dependency bumps, refactors, test-only changes, release chores.
- Rewrite each entry benefit-first and plain-language; keep technical precision, drop commit jargon and package names.
- Merge duplicates that describe the same change from different packages.
- "highlights" = the 1-5 most user-visible items, one line each.
- "summary" = 1-3 sentences a subscriber actually wants to read.
- title must be exactly "${productName} ${version}".
- audience is "internal".

Respond with ONLY a JSON object (no markdown fence, no commentary) of this exact shape:
{
  "title": string,
  "summary": string,
  "highlights": string[],
  "sections": {
    "added":    [{"title": string, "body"?: string}],
    "improved": [{"title": string, "body"?: string}],
    "fixed":    [{"title": string, "body"?: string}]
  },${changelogField}
  "audience": "internal"
}

Shipped surfaces (context only — do not include in sections):
${surfaceText}

Raw changelog entries:
${raw}`;
}

/** Structural pre-flight so obviously-broken output never leaves the runner. */
export function validateArtifact(artifact) {
  const errors = [];
  if (typeof artifact !== 'object' || artifact === null) return ['not an object'];
  if (typeof artifact.title !== 'string' || artifact.title.length === 0)
    errors.push('title missing');
  if (typeof artifact.summary !== 'string' || artifact.summary.length === 0)
    errors.push('summary missing');
  const sections = artifact.sections;
  if (typeof sections !== 'object' || sections === null) {
    errors.push('sections missing');
  } else {
    let total = 0;
    for (const key of ['added', 'improved', 'fixed']) {
      const list = sections[key];
      if (!Array.isArray(list)) {
        errors.push(`sections.${key} not an array`);
        continue;
      }
      total += list.length;
      for (const entry of list) {
        if (typeof entry?.title !== 'string' || entry.title.length === 0) {
          errors.push(`sections.${key} entry without title`);
        }
      }
    }
    if (total === 0) errors.push('sections are empty');
  }
  return errors;
}

export function parseModelJson(text) {
  // Models occasionally fence the JSON despite instructions; unwrap it.
  const unfenced = text.replace(/^\s*```(?:json)?\s*/i, '').replace(/\s*```\s*$/, '');
  return JSON.parse(unfenced);
}

export async function draftArtifact({
  apiKey,
  prompt,
  feedback = null,
  fetchImpl = fetch,
}) {
  const messages = [{ role: 'user', content: prompt }];
  if (feedback) {
    messages.push(
      { role: 'assistant', content: feedback.previous },
      {
        role: 'user',
        content: `That response failed validation:\n${feedback.errors.join('\n')}\nRespond again with ONLY the corrected JSON object.`,
      }
    );
  }
  const res = await fetchImpl(ANTHROPIC_URL, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({ model: MODEL, max_tokens: 4096, messages }),
  });
  if (!res.ok) {
    throw new Error(`Anthropic API ${res.status}: ${(await res.text()).slice(0, 300)}`);
  }
  const body = await res.json();
  const text = body.content?.map(block => block.text ?? '').join('') ?? '';
  return { text, artifact: parseModelJson(text) };
}

/** Draft with one structural-validation retry. */
export async function editorial(opts) {
  const first = await draftArtifact(opts);
  let errors = validateArtifact(first.artifact);
  if (errors.length === 0) return first.artifact;

  const second = await draftArtifact({
    ...opts,
    feedback: { previous: first.text, errors },
  });
  errors = validateArtifact(second.artifact);
  if (errors.length > 0) {
    throw new Error(`AI artifact failed validation after retry: ${errors.join('; ')}`);
  }
  return second.artifact;
}
