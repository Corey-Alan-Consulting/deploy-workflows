# deploy-workflows

Reusable GitHub Actions workflows for building and deploying containerized applications to GCP Artifact Registry.

**Zero secrets required in your app repo.** Authentication is handled via GCP Workload Identity Federation (WIF), which is set up by Terraform in [platform-infra](https://github.com/Corey-Alan-Consulting/platform-infra).

## Quick Start — Next.js App

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

Full CI/CD pipeline for Next.js applications: test, security scan, build, Docker push, image scan, cleanup.

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
| `pnpm_version` | `9` | pnpm version |
| `dockerfile` | `Dockerfile.prebuilt` | Path to Dockerfile |
| `build_context` | `.` | Docker build context |
| `build_output_paths` | `.next/standalone/`, `.next/static/`, `public/`, `prisma/` | Paths to upload as build artifacts |
| `pre_build_commands` | `""` | Commands before build (e.g. `npx prisma generate`) |
| `build_command` | `pnpm build` | Build command |
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

## Workflow Reference — build-push-generic.yml

Simpler workflow for non-Next.js Docker applications: build, push, sign, cleanup.

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

### Next.js with Prisma and build-time secrets

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

### Monorepo (custom build context)

```yaml
jobs:
  deploy:
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/build-push-nextjs.yml@main
    with:
      app_name: capturly
      gcp_project_id: capturly-app
      gcp_project_number: "614897024362"
      ar_repository: capturly/capturly-web
      dockerfile: apps/web/Dockerfile.prebuilt
      build_context: .
      build_command: "pnpm --filter @capturly/web build"
    permissions:
      contents: read
      id-token: write
      security-events: write
```
