// Aggregate reader-facing changelog entries across every workspace package
// for one release. In a changesets fixed group the root package's changelog
// is empty by construction (changesets never targets the root), so the real
// content lives per-package — this aggregation is the fix for the
// perpetually-empty release email.

import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { entriesForVersion } from './changelog.mjs';

const WORKSPACE_GLOBS = ['apps', 'packages'];

/**
 * @param {string} repoRoot checkout of the release tag
 * @param {string} rootVersion the released app version (for error context)
 * @returns {{ packages: Array<{name: string, version: string, entries: string[]}> }}
 * @throws when no package contributed a single entry — a changeset is
 *         required for release, so an empty union is a pipeline bug.
 */
export function aggregateChangelogs(repoRoot, rootVersion) {
  const packages = [];
  // Single-package repos (jlshaw, blue-sky, coreyalan): the root package IS
  // the app and its CHANGELOG carries the real entries. In monorepos the
  // root section is dependency-cascade boilerplate, which the entry filter
  // drops — so including root is safe everywhere.
  const rootPkgPath = join(repoRoot, 'package.json');
  const rootChangelogPath = join(repoRoot, 'CHANGELOG.md');
  if (existsSync(rootPkgPath) && existsSync(rootChangelogPath)) {
    const pkg = JSON.parse(readFileSync(rootPkgPath, 'utf8'));
    if (pkg.version) {
      const entries = entriesForVersion(readFileSync(rootChangelogPath, 'utf8'), pkg.version);
      if (entries !== null && entries.length > 0) {
        packages.push({ name: pkg.name ?? 'root', version: pkg.version, entries });
      }
    }
  }
  for (const dir of WORKSPACE_GLOBS) {
    const base = join(repoRoot, dir);
    if (!existsSync(base)) continue;
    for (const entry of readdirSync(base, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const pkgDir = join(base, entry.name);
      const pkgJsonPath = join(pkgDir, 'package.json');
      const changelogPath = join(pkgDir, 'CHANGELOG.md');
      if (!existsSync(pkgJsonPath) || !existsSync(changelogPath)) continue;

      const pkg = JSON.parse(readFileSync(pkgJsonPath, 'utf8'));
      if (!pkg.version) continue;
      const markdown = readFileSync(changelogPath, 'utf8');
      // Each package contributes the section for ITS version at this tag —
      // fixed-group members share the app version; independents carry their
      // own. A package whose changelog has no section for its current
      // version didn't release here.
      const entries = entriesForVersion(markdown, pkg.version);
      if (entries === null || entries.length === 0) continue;
      packages.push({ name: pkg.name ?? entry.name, version: pkg.version, entries });
    }
  }

  const total = packages.reduce((n, p) => n + p.entries.length, 0);
  if (total === 0) {
    throw new Error(
      `No changelog entries found for ${rootVersion} across any workspace package — ` +
        'a changeset is required for release, so this is a builder bug, not "no changes".'
    );
  }
  return { packages };
}
