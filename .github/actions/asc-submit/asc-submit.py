#!/usr/bin/env python3
"""Attach a TestFlight build to an App Store version and submit it for review.

This is the iOS analog of promoting Android to production, except Apple gates
go-live behind App Review: this script prepares and SUBMITS; Apple decides when
it ships. It does no upload — it acts on a build already processed in TestFlight
(ci-mobile / the release pipeline put it there).

Steps (App Store Connect API v1, the modern reviewSubmissions flow):
  1. find (or create) the editable appStoreVersion for --version on iOS
  2. set releaseType (AFTER_APPROVAL when --auto-release, else MANUAL)
  3. optionally create a phased release so the rollout ramps once approved
  4. attach the TestFlight build (by --build-number, else the latest VALID one)
  5. create a reviewSubmission, add this version as an item, and submit it

Auth is a JWT (ES256) signed with an App Store Connect API key. Creds come from
the environment (the workflow pulls them from Bitwarden via sm-action):
  ASC_ISSUER_ID, ASC_KEY_ID, ASC_PRIVATE_KEY (the .p8 PEM contents).

Any non-2xx surfaces Apple's JSON error body and exits non-zero. The reviewer
gate lives on the GitHub Environment, not here.
"""

import argparse
import json
import os
import sys
import time

import jwt
import requests

BASE = "https://api.appstoreconnect.apple.com"
AUDIENCE = "appstoreconnect-v1"
PLATFORM = "IOS"
# appStoreVersion states that can still be edited/submitted; anything else means
# there is already a version in flight or shipped for this versionString.
EDITABLE_STATES = {
    "PREPARE_FOR_SUBMISSION",
    "DEVELOPER_REJECTED",
    "REJECTED",
    "METADATA_REJECTED",
    "INVALID_BINARY",
}
TIMEOUT = 60


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-id", required=True, help="Apple ID of the app, e.g. 6757610356")
    parser.add_argument("--version", required=True, help="marketing version to submit, e.g. 2.6.0")
    parser.add_argument("--build-number", default=None, help="TestFlight build to attach (default: latest VALID)")
    parser.add_argument("--phased-release", action="store_true", help="enable Apple 7-day phased rollout once approved")
    parser.add_argument("--auto-release", action="store_true", help="release automatically after approval (else hold for manual)")
    return parser.parse_args()


def make_token() -> str:
    issuer = os.environ["ASC_ISSUER_ID"]
    key_id = os.environ["ASC_KEY_ID"]
    private_key = os.environ["ASC_PRIVATE_KEY"]
    now = int(time.time())
    return jwt.encode(
        {"iss": issuer, "iat": now, "exp": now + 15 * 60, "aud": AUDIENCE},
        private_key,
        algorithm="ES256",
        headers={"kid": key_id, "typ": "JWT"},
    )


class ASC:
    def __init__(self, token: str) -> None:
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def request(self, method: str, path: str, **kwargs):
        resp = self.session.request(method, f"{BASE}{path}", timeout=TIMEOUT, **kwargs)
        if not resp.ok:
            raise SystemExit(f"ASC API {method} {path} -> {resp.status_code}: {resp.text}")
        return resp.json() if resp.content else {}

    def get(self, path: str, params=None):
        return self.request("GET", path, params=params)

    def post(self, path: str, body: dict):
        return self.request("POST", path, json=body)

    def patch(self, path: str, body: dict):
        return self.request("PATCH", path, json=body)


def find_or_create_version(asc: ASC, app_id: str, version: str, release_type: str) -> str:
    existing = asc.get(
        f"/v1/apps/{app_id}/appStoreVersions",
        params={"filter[versionString]": version, "filter[platform]": PLATFORM, "limit": 1},
    ).get("data", [])

    if existing:
        v = existing[0]
        state = v["attributes"].get("appStoreState")
        if state not in EDITABLE_STATES:
            raise SystemExit(
                f"appStoreVersion {version} is in state {state}, which is not editable/submittable. "
                "Nothing to do (it is already in review or released)."
            )
        version_id = v["id"]
        asc.patch(
            f"/v1/appStoreVersions/{version_id}",
            {"data": {"type": "appStoreVersions", "id": version_id, "attributes": {"releaseType": release_type}}},
        )
        print(f"Reusing editable appStoreVersion {version} ({version_id}), releaseType={release_type}")
        return version_id

    created = asc.post(
        "/v1/appStoreVersions",
        {
            "data": {
                "type": "appStoreVersions",
                "attributes": {"platform": PLATFORM, "versionString": version, "releaseType": release_type},
                "relationships": {"app": {"data": {"type": "apps", "id": app_id}}},
            }
        },
    )
    version_id = created["data"]["id"]
    print(f"Created appStoreVersion {version} ({version_id}), releaseType={release_type}")
    return version_id


def resolve_build(asc: ASC, app_id: str, version: str, build_number: str | None) -> str:
    params = {
        "filter[app]": app_id,
        "filter[preReleaseVersion.version]": version,
        "sort": "-uploadedDate",
        "limit": 20,
        "fields[builds]": "version,processingState",
    }
    if build_number:
        params["filter[version]"] = build_number
    builds = asc.get("/v1/builds", params=params).get("data", [])
    valid = [b for b in builds if b["attributes"].get("processingState") == "VALID"]
    if not valid:
        raise SystemExit(
            f"No processed (VALID) TestFlight build found for version {version}"
            + (f" build {build_number}" if build_number else "")
            + ". Wait for TestFlight processing to finish, then retry."
        )
    build = valid[0]
    print(f"Attaching build {build['attributes'].get('version')} ({build['id']})")
    return build["id"]


def attach_build(asc: ASC, version_id: str, build_id: str) -> None:
    asc.patch(
        f"/v1/appStoreVersions/{version_id}",
        {
            "data": {
                "type": "appStoreVersions",
                "id": version_id,
                "relationships": {"build": {"data": {"type": "builds", "id": build_id}}},
            }
        },
    )


def set_phased_release(asc: ASC, version_id: str) -> None:
    # Creating the phased-release object with an INACTIVE state enables a phased
    # rollout that Apple activates automatically when the version is released.
    asc.post(
        "/v1/appStoreVersionPhasedReleases",
        {
            "data": {
                "type": "appStoreVersionPhasedReleases",
                "attributes": {"phasedReleaseState": "INACTIVE"},
                "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": version_id}}},
            }
        },
    )
    print("Enabled phased release")


def open_review_submission(asc: ASC, app_id: str) -> str:
    # Reuse an existing un-submitted submission if one is open, else create one.
    open_states = "READY_FOR_REVIEW"
    existing = asc.get(
        "/v1/reviewSubmissions",
        params={"filter[app]": app_id, "filter[platform]": PLATFORM, "filter[state]": open_states, "limit": 1},
    ).get("data", [])
    if existing:
        submission_id = existing[0]["id"]
        print(f"Reusing open reviewSubmission {submission_id}")
        return submission_id
    created = asc.post(
        "/v1/reviewSubmissions",
        {
            "data": {
                "type": "reviewSubmissions",
                "attributes": {"platform": PLATFORM},
                "relationships": {"app": {"data": {"type": "apps", "id": app_id}}},
            }
        },
    )
    submission_id = created["data"]["id"]
    print(f"Created reviewSubmission {submission_id}")
    return submission_id


def main() -> int:
    args = parse_args()
    release_type = "AFTER_APPROVAL" if args.auto_release else "MANUAL"
    asc = ASC(make_token())

    version_id = find_or_create_version(asc, args.app_id, args.version, release_type)
    build_id = resolve_build(asc, args.app_id, args.version, args.build_number)
    attach_build(asc, version_id, build_id)
    if args.phased_release:
        set_phased_release(asc, version_id)

    submission_id = open_review_submission(asc, args.app_id)
    asc.post(
        "/v1/reviewSubmissionItems",
        {
            "data": {
                "type": "reviewSubmissionItems",
                "relationships": {
                    "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": submission_id}},
                    "appStoreVersion": {"data": {"type": "appStoreVersions", "id": version_id}},
                },
            }
        },
    )
    asc.patch(
        f"/v1/reviewSubmissions/{submission_id}",
        {"data": {"type": "reviewSubmissions", "id": submission_id, "attributes": {"submitted": True}}},
    )
    print(f"Submitted {args.version} for App Review (releaseType={release_type}, phased={args.phased_release}).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyError as missing:
        print(f"Missing required env var: {missing}", file=sys.stderr)
        sys.exit(2)
    except requests.RequestException as err:
        print(f"HTTP error talking to App Store Connect: {err}", file=sys.stderr)
        sys.exit(1)
