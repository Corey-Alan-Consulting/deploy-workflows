// Changesets-changelog parsing for the release-announcement builder.
// Dependency-free on purpose: the builder workflow runs on a bare tag
// checkout without pnpm install, and the changesets format is stable
// ("## <version>" sections, "### Patch/Minor/Major Changes" headings,
// "- <hash>: message" bullets).

const VERSION_HEADING = /^## (\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\s*$/;

// Bullets that carry no reader-facing information. "Updated dependencies"
// blocks are changesets' fixed-group bookkeeping; bare version bumps say
// nothing a human needs.
const BOILERPLATE = [/^updated dependencies\b/i, /^@?[\w/.-]+@\d+\.\d+\.\d+$/];

/** Split a CHANGELOG.md into { version -> raw section body }. */
export function splitSections(markdown) {
  const sections = new Map();
  let current = null;
  let buf = [];
  for (const line of markdown.split(/\r?\n/)) {
    const m = line.match(VERSION_HEADING);
    if (m) {
      if (current) sections.set(current, buf.join('\n'));
      current = m[1];
      buf = [];
    } else if (current) {
      buf.push(line);
    }
  }
  if (current) sections.set(current, buf.join('\n'));
  return sections;
}

/**
 * Extract reader-facing entries from one version's section body.
 * Returns strings with the commit-hash prefix stripped; continuation
 * lines (indented) are folded into their bullet.
 */
export function extractEntries(sectionBody) {
  const entries = [];
  let current = null;
  for (const line of sectionBody.split('\n')) {
    const bullet = line.match(/^- (.*)$/);
    if (bullet) {
      if (current !== null) entries.push(current);
      current = bullet[1].trim();
    } else if (current !== null && /^ {2,}\S/.test(line)) {
      current += ' ' + line.trim();
    } else if (current !== null && line.trim() === '') {
      entries.push(current);
      current = null;
    }
  }
  if (current !== null) entries.push(current);

  return entries
    .map(e => e.replace(/^[0-9a-f]{7,40}: /, '').trim())
    // @changesets/changelog-github preamble: "[#105](url) [`hash`](url)
    // Thanks [@user](url)! - message" — strip everything before the message.
    .map(e =>
      e
        .replace(/^(?:\[[^\]]*\]\([^)]*\)\s*)+(?:Thanks \[@[^\]]+\]\([^)]*\)!\s*)?-\s*/, '')
        .trim()
    )
    .filter(e => e.length > 0 && !BOILERPLATE.some(re => re.test(e)))
    // A dependency-bump list rendered as one bullet with children
    // ("Updated dependencies [abc]: - @capturly/x@1.2.3") also matches
    // nothing useful after stripping — drop anything that is now only
    // package@version fragments.
    .filter(e => !/^\[?[0-9a-f]{7,40}\]?$/.test(e));
}

/** Entries for one package's CHANGELOG at a specific version. */
export function entriesForVersion(markdown, version) {
  const section = splitSections(markdown).get(version);
  if (section === undefined) return null; // package didn't release this version
  return extractEntries(section);
}
