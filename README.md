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

### Optional Secrets

| Secret | Description |
|--------|-------------|
| `bws_access_token` | Bitwarden Secrets Manager token (for build-time secrets) |
| `build_secrets` | Bitwarden secret mappings (bitwarden/sm-action format) |

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
      app_name: smm-web
      gcp_project_id: coreyalan-smm
      gcp_project_number: "949337891045"
      ar_repository: coreyalan-smm/smm-web
      dockerfile: apps/web/Dockerfile.prebuilt
      build_command: "pnpm --filter @smm/web build"
      pre_build_commands: "pnpm --filter @smm/db db:generate && pnpm --filter @smm/db build && pnpm --filter @smm/shared build && pnpm --filter @smm/core build"
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
