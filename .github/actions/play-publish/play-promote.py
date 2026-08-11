#!/usr/bin/env python3
"""Promote the version already on a closed Play track to the production track.

No rebuild and no upload: this reads the versionCodes currently released on the
source track (default `alpha`, where release-android.yml publishes) and releases
those same bundles to `production`, optionally as a staged rollout. Auth is the
same keyless Application Default Credentials as play-upload.py (the WIF file
google-github-actions/auth materializes; org policy forbids SA keys). Usage:

  play-promote.py --package app.capturly.mobile --from-track alpha \
      --rollout-percentage 20 [--expect-version 2.6.0]

Rollout: 100 releases to everyone (status completed); <100 does a staged rollout
(status inProgress, userFraction = pct/100) — re-run at 100 to finish the ramp.
Exits non-zero with the Play error body on any failure.
"""

import argparse
import sys

import google.auth
import google_auth_httplib2
import httplib2
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPE = "https://www.googleapis.com/auth/androidpublisher"
HTTP_TIMEOUT_SECONDS = 120
MAX_RETRIES = 5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, help="applicationId, e.g. app.capturly.mobile")
    parser.add_argument("--from-track", default="alpha", help="source closed track (default: alpha)")
    parser.add_argument("--to-track", default="production", help="destination track (default: production)")
    parser.add_argument(
        "--rollout-percentage",
        type=float,
        default=100.0,
        help="production rollout percent 1-100 (default: 100 = full release)",
    )
    parser.add_argument(
        "--expect-version",
        default=None,
        help="optional marketing version to assert the source release name contains, as a safety check",
    )
    return parser.parse_args()


def active_version_codes(edits, package: str, edit_id: str, track: str):
    """Return (versionCodes, release_name) for the live release on `track`."""
    body = edits.tracks().get(packageName=package, editId=edit_id, track=track).execute(
        num_retries=MAX_RETRIES
    )
    # A track can carry a draft alongside a live release; take the newest release
    # that actually has version codes assigned (the one users are getting).
    releases = [r for r in body.get("releases", []) if r.get("versionCodes")]
    if not releases:
        raise SystemExit(f"No released version on the '{track}' track — nothing to promote.")
    release = max(releases, key=lambda r: max(int(v) for v in r["versionCodes"]))
    return release["versionCodes"], release.get("name", "")


def main() -> int:
    args = parse_args()
    if not 1 <= args.rollout_percentage <= 100:
        raise SystemExit("--rollout-percentage must be between 1 and 100")

    credentials, _ = google.auth.default(scopes=[SCOPE])
    authed_http = google_auth_httplib2.AuthorizedHttp(
        credentials, http=httplib2.Http(timeout=HTTP_TIMEOUT_SECONDS)
    )
    service = build("androidpublisher", "v3", http=authed_http, cache_discovery=False)
    edits = service.edits()

    edit_id = edits.insert(packageName=args.package).execute(num_retries=MAX_RETRIES)["id"]

    version_codes, source_name = active_version_codes(edits, args.package, edit_id, args.from_track)
    print(f"Source track '{args.from_track}' active versionCodes={version_codes} (release '{source_name}')")

    if args.expect_version and args.expect_version not in source_name:
        raise SystemExit(
            f"Safety check failed: --expect-version {args.expect_version!r} not found in "
            f"the source release name {source_name!r}. Refusing to promote."
        )

    full = args.rollout_percentage >= 100
    release = {
        "versionCodes": version_codes,
        "status": "completed" if full else "inProgress",
    }
    if not full:
        release["userFraction"] = round(args.rollout_percentage / 100.0, 4)
    if source_name:
        release["name"] = source_name

    edits.tracks().update(
        packageName=args.package,
        editId=edit_id,
        track=args.to_track,
        body={"track": args.to_track, "releases": [release]},
    ).execute(num_retries=MAX_RETRIES)

    edits.commit(packageName=args.package, editId=edit_id).execute(num_retries=MAX_RETRIES)
    rollout = "100% (completed)" if full else f"{args.rollout_percentage}% (inProgress)"
    print(f"Promoted versionCodes {version_codes} to '{args.to_track}' at {rollout}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except HttpError as err:
        print(f"Play API error {err.resp.status}: {err.content.decode(errors='replace')}", file=sys.stderr)
        sys.exit(1)
