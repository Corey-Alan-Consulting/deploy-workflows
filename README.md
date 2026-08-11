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
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/build-push-nextjs.yml@v1
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
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/build-push-nextjs.yml@v1
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
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/build-push-generic.yml@v1
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
| `runner` | `ubuntu-latest` | Build-job runner label. Default is GitHub-hosted (also the break-glass fallback). Pass a homelab ARC scale-set label to build on the staging cluster — the caller flips back to `ubuntu-latest` to fall back (manual break-glass). A container build needs a dind-capable staging runner. |

## Versioning

| Trigger | Image Tags | Behavior |
|---------|-----------|----------|
| Push to `main` | `{sha}`, `latest` | Continuous deployment |
| Tag `v1.2.3` | `{sha}`, `latest`, `v1.2.3` | Versioned release |

Rollback: update the Helm values in platform-infra to a previous image digest.

## Releases & pinning

This repo ships immutable release tags (`v1.0.0`, `v1.1.0`, …) plus a moving
major tag (`v1`). Callers must **not** reference `@main` — a push here executes
with every caller's secrets and cloud identity on their next release.

- **Callers:** pin `uses:` to the release commit SHA with a version comment
  (`@<sha> # v1.0.0`). Renovate bumps the pin when a new tag is cut.
- **Inside this repo:** the reusable workflows reference the composite
  action at `@v1` (a same-commit SHA pin is impossible; the major tag is
  moved atomically at release).

Cutting a release from `main`:

```bash
git tag v1.x.y && git tag -f v1 && git push origin v1.x.y && git push -f origin v1
```

Majors (breaking input/behavior changes) get a new `v2` line; leave `v1`
pointing at the last v1 release.

## Examples

### Next.js with Prisma and build-time secrets (pnpm)

```yaml
jobs:
  deploy:
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/build-push-nextjs.yml@v1
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
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/build-push-nextjs.yml@v1
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
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/build-push-nextjs.yml@v1
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
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/build-push-nextjs.yml@v1
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
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/build-push-nextjs.yml@v1
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
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/release.yml@v1
    secrets:
      GITOPS_APP_ID: ${{ secrets.GITOPS_APP_ID }}
      GITOPS_APP_PRIVATE_KEY: ${{ secrets.GITOPS_APP_PRIVATE_KEY }}
```

### Caller requirements

- pnpm workspace with a `version-packages` script. Use the retry wrapper
  (`node scripts/changeset-version-retry.mjs && pnpm install --lockfile-only`)
  rather than a bare `changeset version` — `@changesets/changelog-github` makes a
  GitHub GraphQL call per changeset that intermittently fails with
  `ERR_STREAM_PREMATURE_CLOSE`; the wrapper retries it.
- `.changeset/config.json` present.
- `GITOPS_APP_ID` / `GITOPS_APP_PRIVATE_KEY` available to the repo (org secrets
  scoped to it), and the GitHub App installed on the repo.
- Each **publishable** (non-private) package registers an npm Trusted Publisher
  and builds itself in its own `prepublishOnly`. Private packages are versioned
  and tagged but never published.

### Inputs / secrets

| Input | Default | Description |
|-------|---------|-------------|
| `node-version` | `22` | Node version (22+ required for npm OIDC) |
| `app-release-package` | `''` | Optional workspace package (e.g. a private deployable app). When set and in the published set, cuts a GitHub Release `<name>@<version>` from `CHANGELOG.md` so a `release: published` workflow (e.g. release-email) fires |

| Secret | Required | Description |
|--------|----------|-------------|
| `GITOPS_APP_ID` | yes | GitHub App id; pushes version commit/tags past branch protection |
| `GITOPS_APP_PRIVATE_KEY` | yes | Paired App private key |
| `NPM_TOKEN` | no | npm **read** token to install restricted `@scope/*` deps during `pnpm install`. Step-scoped, never used to publish (publishing is OIDC). Pass only from repos that consume a private package |

> **⚠️ Trusted Publishing + reusable workflows.** The OIDC token's `workflow`
> claim is the **caller's** `release.yml`, so keep that filename and point each
> npm Trusted Publisher at the **package repo** + `release.yml` (unchanged from a
> non-reusable setup). Reusable workflows also expose a `job_workflow_ref` claim;
> if a publish is ever rejected with an OIDC mismatch, add a publisher entry for
> `deploy-workflows` / `release.yml`. **Verify the publish on one repo before
> rolling this out fleet-wide.**

## Composite Actions — native & mobile release primitives

Building blocks for cross-platform (desktop / mobile) release pipelines. These
are the shared leaves the forthcoming reusable native-release workflows call;
they can also be used directly from an app repo today. Each is pinned the same
way as the reusable workflows (`@<sha> # v1.x.y`, or `@v1` inside this repo).

| Action | Purpose |
|--------|---------|
| `desktop-build-setup` | The shared front half of every desktop release: checkout → Bitwarden secrets (two-project pattern) → pnpm + Node with the private registry → install-with-retry → Turbo remote cache → build → an app-specific `prebuild-command` hook (e.g. FFmpeg). A desktop workflow calls this, then does only its own signing + electron-builder + publish. |
| `publish-desktop-feed` | Publish freshly built electron-builder artifacts to the **beta** channel of a Cloudflare R2 update feed (versioned binaries immutable at bucket root; `latest*.yml` renamed to `beta*.yml` no-cache; website installer staged for later promotion). Stable files are never touched — promotion is a separate approval-gated workflow. |
| `play-publish` | Upload a signed AAB to a Google Play track (`mode: upload`) or promote a closed track to production (`mode: promote`). Auth is keyless Application Default Credentials — run `google-github-actions/auth` first. |
| `verify-aab-alignment` | Fail the build if any `arm64-v8a` `.so` in an AAB/APK lacks 16 KB-aligned LOAD segments (Play targetSdk 35+ hard gate). Pure stdlib. |
| `asc-submit` | Attach a processed TestFlight build to an App Store version and submit for App Review via the App Store Connect API. The iOS build itself is produced elsewhere (e.g. Xcode Cloud). |

Signing **identities** stay per-app: pass them in (R2 creds, Play package + WIF
service account, App Store Connect key). The actions carry only the shared
**mechanism**, never an app's credentials or identifiers.

```yaml
# Android: build → verify → upload to the alpha track, then (gated) promote
- uses: google-github-actions/auth@… # keyless WIF; no SA key
  with:
    workload_identity_provider: ${{ inputs.wif_provider }}
    service_account: ${{ inputs.wif_sa }}
- uses: Corey-Alan-Consulting/deploy-workflows/.github/actions/verify-aab-alignment@v1
  with:
    bundle: android/app/build/outputs/bundle/release/app-release.aab
- uses: Corey-Alan-Consulting/deploy-workflows/.github/actions/play-publish@v1
  with:
    mode: upload
    package: com.example.app
    aab: android/app/build/outputs/bundle/release/app-release.aab
    track: alpha
```

```yaml
# Desktop: after electron-builder --mac/--win --publish never
- uses: Corey-Alan-Consulting/deploy-workflows/.github/actions/publish-desktop-feed@v1
  with:
    platform: mac              # or win
    bucket: example-updates
    installer-basename: Example
    r2-account-id: ${{ env.R2_ACCOUNT_ID }}
    r2-access-key-id: ${{ env.R2_ACCESS_KEY_ID }}
    r2-secret-access-key: ${{ env.R2_SECRET_ACCESS_KEY }}
```

## Reusable Workflows — desktop release

`desktop-release-macos.yml`, `desktop-release-windows.yml`, and
`desktop-release-linux.yml` build, sign, and publish an electron app to a
Cloudflare R2 update feed (mac/win) or the Snap Store (linux). Each sits on the
`desktop-build-setup` action and adds only its platform's signing + packaging.

**Signing identities stay per-app.** You pass them as a `bitwarden/sm-action`
mapping in `signing-secret-ids`, using these canonical env NAMEs:

| Platform | Required `signing-secret-ids` NAMEs |
|----------|--------------------------------------|
| macOS | `APPLE_API_KEY_B64`, `APPLE_API_KEY_ID`, `APPLE_API_ISSUER`, `CSC_LINK`, `CSC_KEY_PASSWORD`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` |
| Windows | `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_ENDPOINT`, `AZURE_CODE_SIGNING_NAME`, `AZURE_CERT_PROFILE_NAME`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` |
| Linux | `SNAPCRAFT_STORE_CREDENTIALS` |

App-specific prebuild work (e.g. downloading FFmpeg) goes in `prebuild-command`;
app-specific build-time env can be exported from there via `>> $GITHUB_ENV`.

```yaml
# .github/workflows/release-macos.yml  (in the app repo)
name: Release macOS
on:
  push:
    tags: ['myapp@*']
  workflow_dispatch:

jobs:
  macos:
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/desktop-release-macos.yml@v1
    with:
      turbo-team: myapp
      turbo-api: ${{ vars.TURBO_API }}
      r2-bucket: myapp-updates
      installer-basename: MyApp
      signing-secret-ids: |
        11111111-1111-1111-1111-111111111111 > APPLE_API_KEY_B64
        22222222-2222-2222-2222-222222222222 > APPLE_API_KEY_ID
        33333333-3333-3333-3333-333333333333 > APPLE_API_ISSUER
        44444444-4444-4444-4444-444444444444 > CSC_LINK
        55555555-5555-5555-5555-555555555555 > CSC_KEY_PASSWORD
        66666666-6666-6666-6666-666666666666 > R2_ACCOUNT_ID
        77777777-7777-7777-7777-777777777777 > R2_ACCESS_KEY_ID
        88888888-8888-8888-8888-888888888888 > R2_SECRET_ACCESS_KEY
      build-secret-ids: |
        99999999-9999-9999-9999-999999999999 > LICENSE_JWKS
      prebuild-command: ./scripts/prepare-desktop-mac.sh
      publish: ${{ startsWith(github.ref, 'refs/tags/') }}
    secrets:
      bws-token-signing: ${{ secrets.BWS_TOKEN_SIGNING }}
      bws-token-build: ${{ secrets.BWS_TOKEN_BUILD }}
      npm-token: ${{ secrets.NPM_TOKEN }}
      turbo-token: ${{ secrets.TURBO_TOKEN }}
      turbo-signature-key: ${{ secrets.TURBO_CACHE_SIGNATURE_KEY }}
```

Windows adds `publisher-name` + `azure-subscription-id` and needs
`id-token: write` (keyless Authenticode via Azure Trusted Signing). Linux takes a
required `version` (stamped into `snapcraft.yaml`) and a `snap-channel`. Set
`publish` from the tag check so PR/dispatch dry-runs build without publishing.

## Reusable Workflows — mobile release

`android-release.yml` builds a signed AAB and uploads it to a Google Play track
(keyless WIF). `ios-submit.yml` is the App Store submit gate — the iOS build
itself is produced by Xcode Cloud and delivered to TestFlight; this workflow
graduates a TestFlight build to App Review, **actor-locked to the Port GitHub
App** so it runs only after a Port approval.

`signing-secret-ids` NAMEs:

| Workflow | Required NAMEs |
|----------|----------------|
| Android | `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD` |
| iOS submit | `ASC_SUBMIT_ISSUER_ID`, `ASC_SUBMIT_KEY_ID`, `ASC_SUBMIT_PRIVATE_KEY_B64` |

```yaml
# .github/workflows/release-android.yml  (in the app repo)
name: Release Android
on:
  push:
    tags: ['@example/mobile@*']

jobs:
  android:
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/android-release.yml@v1
    with:
      package-name: com.example.app
      gcp-project: example-app
      wif-provider: projects/123/locations/global/workloadIdentityPools/github-actions/providers/github
      wif-service-account: play-publisher-ci@example-app.iam.gserviceaccount.com
      workspace-build-filter: '@example/mobile^...'
      forbidden-manifest-permissions: 'AD_ID|READ_MEDIA_IMAGES|READ_MEDIA_VIDEO'
      track: alpha
      signing-secret-ids: |
        aaaaaaaa-... > ANDROID_KEYSTORE_BASE64
        bbbbbbbb-... > ANDROID_KEYSTORE_PASSWORD
        cccccccc-... > ANDROID_KEY_ALIAS
        dddddddd-... > ANDROID_KEY_PASSWORD
      build-secret-ids: |
        eeeeeeee-... > SENTRY_AUTH_TOKEN
    secrets:
      bws-token-signing: ${{ secrets.BWS_TOKEN_SIGNING }}
      bws-token-build: ${{ secrets.BWS_TOKEN_BUILD }}
      npm-token: ${{ secrets.NPM_TOKEN }}
```

```yaml
# .github/workflows/submit-ios.yml  (dispatched by the Port submit action)
name: Submit iOS to App Store
on:
  workflow_dispatch:
    inputs:
      version: { required: true, type: string }
      build_number: { required: false, type: string }

jobs:
  submit:
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/ios-submit.yml@v1
    with:
      app-id: '6757610356'
      version: ${{ inputs.version }}
      build-number: ${{ inputs.build_number }}
      port-actor-id: '310211542'   # port-corey-alan-consulting[bot]
      signing-secret-ids: |
        ffffffff-... > ASC_SUBMIT_ISSUER_ID
        11111111-... > ASC_SUBMIT_KEY_ID
        22222222-... > ASC_SUBMIT_PRIVATE_KEY_B64
    secrets:
      bws-token-signing: ${{ secrets.BWS_TOKEN_SIGNING }}
```

## Reusable Workflows — promotion gates

`promote-desktop.yml` and `promote-android.yml` graduate an already-published build
to everyone — the desktop/Android analogs of merging the prod digest PR. Both do
**no rebuild** and are **actor-locked to the Port GitHub App** (`port-actor-id`)
with a `dispatch-guard`, so they run only after a Port approval; direct dispatch is
refused.

- **`promote-desktop`** rewrites the stable R2 manifests (`latest.yml` /
  `latest-mac.yml`) to the promoted version and refreshes the website download
  aliases. Rollback = re-run with the previous version; ramp = re-run at a higher
  `staging-percentage`. Needs `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` /
  `R2_SECRET_ACCESS_KEY` in `signing-secret-ids`.
- **`promote-android`** re-releases the versionCodes on a closed track to
  production via `play-publish` (promote mode), keyless WIF. Optional
  `expect-version` asserts the source release name before promoting.

```yaml
# dispatched by the Port promote_desktop_release action, after approval
jobs:
  promote:
    uses: Corey-Alan-Consulting/deploy-workflows/.github/workflows/promote-desktop.yml@v1
    with:
      version: ${{ inputs.version }}
      staging-percentage: ${{ inputs.staging_percentage }}
      r2-bucket: example-updates
      installer-basename: Example
      port-actor-id: '310211542'
      signing-secret-ids: |
        66666666-... > R2_ACCOUNT_ID
        77777777-... > R2_ACCESS_KEY_ID
        88888888-... > R2_SECRET_ACCESS_KEY
    secrets:
      bws-token-signing: ${{ secrets.BWS_TOKEN_SIGNING }}
```

## Reusable Workflows — extension release & store-state sync

`extension-release.yml` builds, signs a Verified CRX, and publishes a Chrome
extension to the Web Store (keyless WIF; CRX signing key from Bitwarden). Firefox
(AMO) is not covered — no reusable AMO publish exists to generalize yet.

`sync-store-state.yml` (read-only, scheduled by the caller) polls live Google Play
+ App Store Connect release state and upserts one Port `mobileRelease` entity per
`(service, platform, track)`, so the catalog reflects what is actually live — the
read path that lets a submitted iOS version flip to "live" once Apple approves. Its
`apps-json` input is a JSON array of `{service, android_package?, android_tracks?,
ios_app_id?}` entries, so one workflow covers every app.

`signing-secret-ids` NAMEs: Chrome → `CHROME_CRX_SIGNING_KEY_B64`; store-sync →
`ASC_SUBMIT_ISSUER_ID` / `ASC_SUBMIT_KEY_ID` / `ASC_SUBMIT_PRIVATE_KEY_B64` (+ Port
creds `PORT_CLIENT_ID` / `PORT_CLIENT_SECRET` via `port-secret-ids`).

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
