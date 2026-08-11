#!/usr/bin/env python3
"""Upload a signed AAB to a Google Play track via the androidpublisher API.

Auth comes from Application Default Credentials — in CI that's the WIF
credential file google-github-actions/auth materializes (keyless; org policy
forbids SA keys). Usage:

  play-upload.py --package app.capturly.mobile --aab path/to/app.aab \
      --track alpha --status completed

Exits non-zero with the API error body on any failure so the run log shows
why Play rejected the upload.
"""

import argparse
import sys

import google.auth
import google_auth_httplib2
import httplib2
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPE = "https://www.googleapis.com/auth/androidpublisher"

# The AAB upload is a large, slow request that has timed out mid-transfer on a
# flaky runner→Google link (the read of Play's response). Give each attempt a
# generous socket timeout and let googleapiclient retry transient failures
# (socket timeouts, 5xx, 429) with exponential backoff so one network blip
# doesn't fail a 40-minute release build.
HTTP_TIMEOUT_SECONDS = 300
MAX_RETRIES = 5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, help="applicationId, e.g. app.capturly.mobile")
    parser.add_argument("--aab", required=True, help="path to the signed .aab")
    parser.add_argument("--track", required=True, help="Play track, e.g. alpha / internal / production")
    parser.add_argument(
        "--status",
        default="completed",
        choices=["completed", "draft", "inProgress", "halted"],
        help="release status for the track (default: completed)",
    )
    parser.add_argument(
        "--user-fraction",
        type=float,
        default=None,
        help="staged-rollout fraction; required by Play for inProgress/halted",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    credentials, _ = google.auth.default(scopes=[SCOPE])
    # Wrap the authorized transport with an explicit timeout; the default has
    # no ceiling, so a stalled read hangs until the runner kills the job.
    authed_http = google_auth_httplib2.AuthorizedHttp(
        credentials, http=httplib2.Http(timeout=HTTP_TIMEOUT_SECONDS)
    )
    service = build("androidpublisher", "v3", http=authed_http, cache_discovery=False)
    edits = service.edits()

    edit_id = edits.insert(packageName=args.package).execute(num_retries=MAX_RETRIES)["id"]

    print(f"Uploading {args.aab} to {args.package} (edit {edit_id})...")
    media = MediaFileUpload(args.aab, mimetype="application/octet-stream", resumable=True)
    # For a resumable upload, execute() forwards num_retries to each chunk, so a
    # transient timeout retries that chunk instead of failing the whole upload.
    bundle = edits.bundles().upload(
        packageName=args.package, editId=edit_id, media_body=media
    ).execute(num_retries=MAX_RETRIES)
    version_code = bundle["versionCode"]
    print(f"Uploaded bundle versionCode={version_code}")

    release = {"versionCodes": [str(version_code)], "status": args.status}
    if args.user_fraction is not None:
        release["userFraction"] = args.user_fraction
    edits.tracks().update(
        packageName=args.package,
        editId=edit_id,
        track=args.track,
        body={"track": args.track, "releases": [release]},
    ).execute(num_retries=MAX_RETRIES)

    edits.commit(packageName=args.package, editId=edit_id).execute(num_retries=MAX_RETRIES)
    print(f"Committed versionCode {version_code} to the {args.track} track ({args.status})")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except HttpError as err:
        # Surface Play's JSON error body — the status line alone never says why.
        print(f"Play API error {err.resp.status}: {err.content.decode(errors='replace')}", file=sys.stderr)
        sys.exit(1)
