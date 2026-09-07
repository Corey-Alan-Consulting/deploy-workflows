// Artifact → GitHub-release-body markdown. Backfills the structurally
// empty body changesets leaves on the root release tag, so the GitHub
// Releases page tells the same story as the email and changelog.
//
// Lifted verbatim from capturly, which carried the only working copy while
// every other repo shipped empty release bodies. Brand-agnostic already —
// the tag is built by the caller, not here.

const SECTION_META = [
  { key: 'added', label: '✨ New' },
  { key: 'improved', label: '📈 Improved' },
  { key: 'fixed', label: '🛠 Fixed' },
];

export function artifactToMarkdown({ content, surfaces }) {
  const lines = [content.summary, ''];

  if (Array.isArray(content.highlights) && content.highlights.length > 0) {
    for (const highlight of content.highlights) lines.push(`> ${highlight}`);
    lines.push('');
  }

  for (const meta of SECTION_META) {
    const entries = content.sections?.[meta.key] ?? [];
    if (entries.length === 0) continue;
    lines.push(`### ${meta.label}`, '');
    for (const entry of entries) {
      lines.push(entry.body ? `- **${entry.title}** — ${entry.body}` : `- **${entry.title}**`);
    }
    lines.push('');
  }

  if (Array.isArray(surfaces) && surfaces.length > 0) {
    lines.push("### Where it's live", '');
    for (const surface of surfaces) {
      lines.push(
        `- ${surface.name}: ${surface.status}${surface.detail ? ` (${surface.detail})` : ''}`
      );
    }
    lines.push('');
  }

  if (content.changelogUrl) {
    lines.push(`[Full changelog](${content.changelogUrl})`);
  }
  return lines.join('\n').trim() + '\n';
}
