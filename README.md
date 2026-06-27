# deploy-workflows

Reusable GitHub Actions workflows for building and deploying containerized applications to GCP Artifact Registry.

**Zero secrets required in your app repo.** Authentication is handled via GCP Workload Identity Federation (WIF), which is set up by Terraform in [platform-infra](https://github.com/Corey-Alan-Consulting/platform-infra).

## Quick Start — Next.js App (pnpm)

```yaml
# .github/workflows/deploy.yml
name: Deploy
on:
  push:
    branches: [main]
    tags: ['v*']

jobs:
  deploy:
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/build-push-nextjs.yml@main
    with:
      app_name: my-app
      gcp_project_id: my-gcp-project
      gcp_project_number: "123456789"
      ar_repository: my-app/my-web
    permissions:
      contents: read
      id-token: write
      security-events: write
```

## Quick Start — npm/yarn App

```yaml
jobs:
  deploy:
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/build-push-nextjs.yml@main
    with:
      app_name: my-app
      gcp_project_id: my-gcp-project
      gcp_project_number: "123456789"
      ar_repository: my-app/my-web
      package_manager: npm
      dockerfile: Dockerfile
      build_mode: dockerfile
    permissions:
      contents: read
      id-token: write
      security-events: write
```

## Quick Start — Generic Docker App

```yaml
# .github/workflows/deploy.yml
name: Deploy
on:
  push:
    branches: [main]
    tags: ['v*']

jobs:
  deploy:
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/build-push-generic.yml@main
    with:
      app_name: my-service
      gcp_project_id: my-gcp-project
      gcp_project_number: "123456789"
      ar_repository: my-service/my-image
    permissions:
      contents: read
      id-token: write
```

## How It Works

1. Your app repo calls a reusable workflow from this repo
2. The workflow authenticates to GCP using Workload Identity Federation (OIDC — no service account keys)
3. Builds your Docker image and pushes to Artifact Registry
4. Signs the image with Cosign (keyless, using GitHub OIDC)
5. Optionally scans for vulnerabilities with Trivy
6. Cleans up old images from Artifact Registry

The image push to Artifact Registry triggers the GitOps pipeline in platform-infra, which updates the Helm values and lets Argo CD deploy.

## Prerequisites

Before using these workflows, the following must be set up via Terraform in platform-infra:

- GCP Workload Identity Federation pool and provider for your GitHub repo
- `github-actions` service account in your GCP project
- Artifact Registry repository
- IAM bindings for image push and GKE image pull

Run the onboarding process in platform-infra to set all of this up automatically.

## Authentication Convention

WIF values are derived from your inputs automatically:

| Input | Derived Value |
|-------|--------------|
| `gcp_project_number` | `projects/{number}/locations/global/workloadIdentityPools/github-pool/providers/github-provider` |
| `gcp_project_id` | `github-actions@{project_id}.iam.gserviceaccount.com` |

If your project uses non-standard naming, use `wif_provider_override` and `wif_sa_override`.

## Workflow Reference — build-push-nextjs.yml

Full CI/CD pipeline: test, security scan, build, Docker push, image sign, image scan, cleanup. Supports pnpm, npm, and yarn. Supports prebuilt and self-contained Dockerfile modes.

### Required Inputs

| Input | Description |
|-------|-------------|
| `app_name` | Application name |
| `gcp_project_id` | GCP project ID |
| `gcp_project_number` | GCP project number |
| `ar_repository` | Artifact Registry repo/image path |

### Optional Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `node_version` | `20` | Node.js version |
| `package_manager` | `pnpm` | Package manager: `pnpm`, `npm`, or `yarn` |
| `pnpm_version` | `""` | pnpm version (only for `package_manager: pnpm`) |
| `dockerfile` | `Dockerfile.prebuilt` | Path to Dockerfile |
| `build_context` | `.` | Docker build context |
| `build_mode` | `prebuilt` | `prebuilt` (build on runner) or `dockerfile` (multi-stage Docker) |
| `build_output_paths` | `.next/standalone/`, `.next/static/`, `public/`, `prisma/` | Paths to upload as build artifacts (prebuilt mode only) |
| `preserve_artifact_paths` | `false` | Preserve full directory paths in artifacts (prevents prefix stripping) |
| `pre_build_commands` | `""` | Commands before build (e.g. `npx prisma generate`) |
| `build_command` | `""` | Override build command (empty = auto from `package_manager`) |
| `install_command` | `""` | Override install command (empty = auto, `skip` to skip) |
| `lint_command` | `""` | Override lint command (empty = auto, `skip` to skip) |
| `test_command` | `""` | Override test command (empty = auto, `skip` to skip) |
| `enable_lint` | `true` | Run linting |
| `enable_test` | `true` | Run tests |
| `enable_security_scan` | `true` | Run Trivy scanning |
| `enable_image_cleanup` | `true` | Clean old images |
| `images_to_keep` | `10` | Images to retain during cleanup |
| `registry` | `us-central1-docker.pkg.dev` | AR hostname |
| `wif_provider_override` | `""` | Override WIF provider path |
| `wif_sa_override` | `""` | Override service account email |
| `turbo_team` | `""` | Per-app Turborepo remote-cache namespace (defaults to `app_name`) |

### Optional Secrets

| Secret | Description |
|--------|-------------|
| `bws_access_token` | Bitwarden Secrets Manager token (for build-time secrets) |
| `build_secrets` | Bitwarden secret mappings (bitwarden/sm-action format) |
| `npm_auth_token` | npmjs.org token for installing private scoped packages |
| `turbo_token` | Bearer token for the shared Turborepo remote cache. Empty → local cache only |
| `turbo_signature_key` | HMAC key for Turbo cache artifact signing (needs `remoteCache.signature` in `turbo.json`). Empty → local cache only |

> **Remote cache:** the cache base URL comes from the org variable `vars.TURBO_API`.
> This workflow runs only on tag / default-branch pushes, so passing `turbo_token`
> keeps cache **writes** confined to trusted release builds (Tier 1). Both secrets
> are optional — without them the build falls back to the local cache and never
> blocks on a cache outage.

### Build Modes

**`prebuilt` (default):** Builds the app on the runner, uploads build artifacts, then a lightweight Dockerfile copies the pre-built output into the image. Best for Next.js standalone builds where you want fast Docker layer caching.

**`dockerfile`:** Skips the build job entirely. Docker builds directly from the repo using a self-contained multi-stage Dockerfile. The test and security scan jobs still run. Best for apps with their own Dockerfile that handles everything.

### Package Manager Auto-Detection

When commands are left empty (the default), they are auto-detected from `package_manager`:

| Command | pnpm | npm | yarn |
|---------|------|-----|------|
| Install | `pnpm install --frozen-lockfile` | `npm ci` | `yarn install --frozen-lockfile` |
| Build | `pnpm build` | `npm run build` | `yarn build` |
| Lint | `pnpm lint` | `npm run lint` | `yarn lint` |
| Test | `pnpm test -- --passWithNoTests` | `npm test -- --passWithNoTests` | `yarn test --passWithNoTests` |
| Audit | `pnpm audit --audit-level=moderate` | `npm audit --audit-level=moderate` | `yarn audit --level moderate` |

Set any command to `skip` to skip that step entirely.

## Workflow Reference — build-push-generic.yml

Simpler workflow for non-Node.js Docker applications: build, push, sign, cleanup.

### Required Inputs

Same as Next.js workflow: `app_name`, `gcp_project_id`, `gcp_project_number`, `ar_repository`.

### Optional Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `dockerfile` | `Dockerfile` | Path to Dockerfile |
| `build_context` | `.` | Docker build context |
| `build_args` | `""` | Docker build args (newline-separated KEY=VALUE) |
| `enable_image_cleanup` | `true` | Clean old images |
| `images_to_keep` | `10` | Images to retain |
| `registry` | `us-central1-docker.pkg.dev` | AR hostname |

## Versioning

| Trigger | Image Tags | Behavior |
|---------|-----------|----------|
| Push to `main` | `{sha}`, `latest` | Continuous deployment |
| Tag `v1.2.3` | `{sha}`, `latest`, `v1.2.3` | Versioned release |

Rollback: update the Helm values in platform-infra to a previous image digest.

## Examples

### Next.js with Prisma and build-time secrets (pnpm)

```yaml
jobs:
  deploy:
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/build-push-nextjs.yml@main
    with:
      app_name: coreyalan
      gcp_project_id: corey-alan-prod
      gcp_project_number: "718603937762"
      ar_repository: coreyalan/coreyalan-web
      pre_build_commands: "npx prisma generate"
    secrets:
      bws_access_token: ${{ secrets.BWS_ACCESS_TOKEN }}
      build_secrets: |
        abc123 > NEXT_PUBLIC_STRIPE_KEY
        def456 > NEXT_PUBLIC_APP_URL
    permissions:
      contents: read
      id-token: write
      security-events: write
```

### Monorepo with preserved artifact paths

```yaml
jobs:
  deploy:
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/build-push-nextjs.yml@main
    with:
      app_name: dispatchr-web
      gcp_project_id: dispatchr-social
      gcp_project_number: "949337891045"
      ar_repository: dispatchr-social/dispatchr-web
      dockerfile: apps/web/Dockerfile.prebuilt
      build_command: "pnpm --filter @dispatchr/web build"
      pre_build_commands: "pnpm --filter @dispatchr/db db:generate && pnpm --filter @dispatchr/db build && pnpm --filter @dispatchr/shared build && pnpm --filter @dispatchr/core build"
      preserve_artifact_paths: true
      build_output_paths: |
        apps/web/.next/standalone/
        apps/web/.next/static/
        apps/web/public/
    permissions:
      contents: read
      id-token: write
      security-events: write
```

### npm app with self-contained Dockerfile

```yaml
jobs:
  deploy:
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/build-push-nextjs.yml@main
    with:
      app_name: my-npm-app
      gcp_project_id: my-project
      gcp_project_number: "123456789"
      ar_repository: my-app/my-web
      package_manager: npm
      build_mode: dockerfile
      dockerfile: Dockerfile
    permissions:
      contents: read
      id-token: write
      security-events: write
```

### Skip lint and tests (handled by separate PR workflow)

```yaml
jobs:
  deploy:
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/build-push-nextjs.yml@main
    with:
      app_name: my-app
      gcp_project_id: my-project
      gcp_project_number: "123456789"
      ar_repository: my-app/my-web
      enable_lint: false
      enable_test: false
    permissions:
      contents: read
      id-token: write
      security-events: write
```

### Custom test runner (e.g., Nx, Turbo)

```yaml
jobs:
  deploy:
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/build-push-nextjs.yml@main
    with:
      app_name: my-app
      gcp_project_id: my-project
      gcp_project_number: "123456789"
      ar_repository: my-app/my-web
      lint_command: "npx nx run-many --target=lint"
      test_command: "npx nx run-many --target=test"
      build_command: "npx nx run web:build"
    permissions:
      contents: read
      id-token: write
      security-events: write
```

## Reusable Workflow — release.yml (Changesets + npm publish)

For repos that **publish npm packages** (e.g. `platform`), not container images.
One run either opens a "chore: release packages" version PR or, when that PR is
merged, tags versions and publishes each changed package to npm over Trusted
Publishing (OIDC — no `NPM_TOKEN`).

```yaml
# .github/workflows/release.yml  (in the package repo)
name: Release
on:
  push:
    branches: [main]

concurrency:
  group: release-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: false

jobs:
  release:
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/release.yml@main
    secrets:
      GITOPS_APP_ID: ${{ secrets.GITOPS_APP_ID }}
      GITOPS_APP_PRIVATE_KEY: ${{ secrets.GITOPS_APP_PRIVATE_KEY }}
```

### Caller requirements

- pnpm workspace with a `version-packages` script (e.g.
  `changeset version && pnpm install --lockfile-only`) and `.changeset/config.json`.
- `GITOPS_APP_ID` / `GITOPS_APP_PRIVATE_KEY` available to the repo (org secrets
  scoped to it), and the GitHub App installed on the repo.
- Each publishable package registers an npm Trusted Publisher.

### Inputs / secrets

| Input | Default | Description |
|-------|---------|-------------|
| `node-version` | `22` | Node version (22+ required for npm OIDC) |

| Secret | Required | Description |
|--------|----------|-------------|
| `GITOPS_APP_ID` | yes | GitHub App id; pushes version commit/tags past branch protection |
| `GITOPS_APP_PRIVATE_KEY` | yes | Paired App private key |

> **⚠️ Trusted Publishing + reusable workflows.** The OIDC token's `workflow`
> claim is the **caller's** `release.yml`, so keep that filename and point each
> npm Trusted Publisher at the **package repo** + `release.yml` (unchanged from a
> non-reusable setup). Reusable workflows also expose a `job_workflow_ref` claim;
> if a publish is ever rejected with an OIDC mismatch, add a publisher entry for
> `deploy-workflows` / `release.yml`. **Verify the publish on one repo before
> rolling this out fleet-wide.**

## Renovate Preset

Shared dependency-update policy for all repos. Reference it from each repo's
`renovate.json`:

```json
{ "extends": ["github>Corey-Alan-Consulting/deploy-workflows:renovate-config"] }
```

It provides:

- **Private-registry auth** for restricted `@corey-alan-consulting/*` packages via
  a read-only `NPM_READ_TOKEN` injected by the Renovate runner (never committed —
  the preset is public and holds no secret).
- **Automerge of first-party packages** (`@corey-alan-consulting/**`) on green CI
  after a 1-day release age, so internal package bumps flow with no manual work.
- **Grouped Auth.js bumps** (`next-auth`, `@auth/*`) so the beta convergence stays
  coordinated across repos.

Run **one** bot: standardize on Renovate and disable Dependabot *version* updates
(keep its security alerts). The same read-only token serves local installs
(`~/.npmrc`), CI installs, and Renovate — rotate it in one place.
