<!-- Copied from framework/checklists/pr-review.md @ b9bf131. Fix it there and re-copy. -->


# PR review checklist

Applies to every PR in every org repo. CI enforces the first section mechanically; the rest is the reviewer's job — including when the reviewer is an agent.

## Mechanical (CI must be green, not overridden)

- [ ] PR title is Conventional Commits — [standards/git-and-releases.md](../standards/git-and-releases.md)
- [ ] Lint, type-check, and tests pass; no new skipped/disabled tests without a linked issue
- [ ] Security scan clean or findings addressed — never merged with a weakened gate (`continue-on-error`, severity filter, removed step) — [standards/ci-cd.md](../standards/ci-cd.md)

## Content

- [ ] No secret values, tokens, or credentials anywhere in the diff (including tests, fixtures, and lockfile URLs) — [standards/security/secrets.md](../standards/security/secrets.md)
- [ ] User-visible change carries a Changeset; breaking change says so in the changeset body
- [ ] New/changed Prisma migration is backward-compatible one release back (expand-then-contract) — [standards/data/postgres.md](../standards/data/postgres.md)
- [ ] New endpoints: correct auth surface (session vs API-key), rate-limit preset applied where required, CSRF posture correct — [standards/security/csrf-and-rate-limiting.md](../standards/security/csrf-and-rate-limiting.md)
- [ ] Error paths are loud: failures reach Sentry or the caller; any fail-open is deliberate, commented, and monitored
- [ ] New dependencies justified; third-party GitHub Actions SHA-pinned — [standards/security/supply-chain.md](../standards/security/supply-chain.md)
- [ ] New env vars added to the app's Bitwarden project + `secrets/<app>.json` (+ staging values) — not just `.env.example`

## Consistency

- [ ] Change doesn't contradict a framework page; if reality legitimately changed, the framework PR accompanies this one (or is linked) — [meta/BACKLOG.md](../meta/BACKLOG.md) drift log otherwise
- [ ] Config that must track code (cron manifests, route maps, OpenAPI specs) updated together, ideally guarded by a drift test — [standards/testing.md](../standards/testing.md)
- [ ] Follows the repo's current conventions rather than reintroducing legacy patterns (Jest/ESLint 8/etc. in a migrated area)
