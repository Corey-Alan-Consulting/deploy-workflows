#!/usr/bin/env python3
"""Reflect live Play + App Store state into Port's `mobileRelease` blueprint.

The read path for the mobile-promotion feature: polls what is actually released
on each store and upserts one Port entity per (service, platform, track) so the
catalog is the source of truth ("android production = 2.6.0 @ 20%, ios appstore =
2.5.1 live, ios in review = 2.6.0"). Run on a schedule by sync-store-state.yml.

Best-effort per platform: a failure syncing one platform still syncs the other,
and the process exits non-zero if anything failed so the schedule surfaces it.

Auth:
  * Play  — keyless ADC (the WIF file google-github-actions/auth materializes).
  * App Store Connect — ASC_ISSUER_ID / ASC_KEY_ID / ASC_PRIVATE_KEY (BWS).
  * Port  — PORT_CLIENT_ID / PORT_CLIENT_SECRET (BWS), exchanged for a token.

App config comes from the STORE_SYNC_APPS env var — a JSON array of entries, one
per app: {"service", "android_package", "android_tracks", "ios_app_id"}. Each
"service" must match the app's Port service entity. A second app onboards by
appending an entry; no code change.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import google.auth
import google_auth_httplib2
import httplib2
import jwt
import requests
from googleapiclient.discovery import build as google_build
from googleapiclient.errors import HttpError

PLAY_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
ASC_BASE = "https://api.appstoreconnect.apple.com"
PORT_BASE = os.environ.get("PORT_API_BASE", "https://api.port.io")
TIMEOUT = 60

# Apps to sync, from the caller (JSON array). Empty = nothing to do.
APPS = json.loads(os.environ.get("STORE_SYNC_APPS") or "[]")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Port ------------------------------------------------------------------
def port_token() -> str:
    resp = requests.post(
        f"{PORT_BASE}/v1/auth/access_token",
        json={
            "clientId": os.environ["PORT_CLIENT_ID"],
            "clientSecret": os.environ["PORT_CLIENT_SECRET"],
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["accessToken"]


def port_upsert(token: str, identifier: str, title: str, service: str, props: dict) -> None:
    body = {
        "identifier": identifier,
        "title": title,
        "properties": {k: v for k, v in props.items() if v is not None},
        "relations": {"service": service},
    }
    resp = requests.post(
        f"{PORT_BASE}/v1/blueprints/mobileRelease/entities",
        params={"upsert": "true", "merge": "true", "create_missing_related_entities": "false"},
        headers={"Authorization": f"Bearer {token}"},
        json=body,
        timeout=TIMEOUT,
    )
    if not resp.ok:
        raise RuntimeError(f"Port upsert {identifier} -> {resp.status_code}: {resp.text}")
    print(f"  upserted {identifier}")


# --- Android ---------------------------------------------------------------
def sync_android(token: str, app: dict) -> None:
    package = app.get("android_package")
    if not package:
        return  # iOS-only app
    credentials, _ = google.auth.default(scopes=[PLAY_SCOPE])
    authed_http = google_auth_httplib2.AuthorizedHttp(
        credentials, http=httplib2.Http(timeout=TIMEOUT)
    )
    service = google_build("androidpublisher", "v3", http=authed_http, cache_discovery=False)
    edits = service.edits()
    edit_id = edits.insert(packageName=package).execute()["id"]
    store_url = f"https://play.google.com/store/apps/details?id={package}"

    for track in app.get("android_tracks", []):
        body = edits.tracks().get(packageName=package, editId=edit_id, track=track).execute()
        releases = [r for r in body.get("releases", []) if r.get("versionCodes")]
        if not releases:
            continue
        release = max(releases, key=lambda r: max(int(v) for v in r["versionCodes"]))
        fraction = release.get("userFraction")
        port_upsert(
            token,
            identifier=f"{app['service']}-android-{track}",
            title=f"{app['service']} · android · {track}",
            service=app["service"],
            props={
                "platform": "android",
                "track": track,
                "version_name": release.get("name"),
                "build_number": str(max(int(v) for v in release["versionCodes"])),
                "status": release.get("status"),
                "rollout_fraction": round(fraction * 100, 1) if fraction is not None else 100,
                "store_url": store_url,
                "synced_at": now_iso(),
            },
        )
    # edits are read-only here; abandon so we never leave a dangling draft edit.
    edits.delete(packageName=package, editId=edit_id).execute()


# --- iOS -------------------------------------------------------------------
def asc_token() -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": os.environ["ASC_ISSUER_ID"],
            "iat": now,
            "exp": now + 15 * 60,
            "aud": "appstoreconnect-v1",
        },
        os.environ["ASC_PRIVATE_KEY"],
        algorithm="ES256",
        headers={"kid": os.environ["ASC_KEY_ID"], "typ": "JWT"},
    )


def sync_ios(token: str, app: dict) -> None:
    app_id = app.get("ios_app_id")
    if not app_id:
        return  # Android-only app
    headers = {"Authorization": f"Bearer {asc_token()}"}
    store_url = f"https://apps.apple.com/app/id{app_id}"

    # App Store versions: newest few, so we capture both the live one and any in
    # review / pending release.
    resp = requests.get(
        f"{ASC_BASE}/v1/apps/{app_id}/appStoreVersions",
        params={"limit": 5, "fields[appStoreVersions]": "versionString,appStoreState,releaseType"},
        headers=headers,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    for version in resp.json().get("data", []):
        attrs = version["attributes"]
        state = attrs.get("appStoreState")
        # "appstore" track = the version that is live or the one currently moving
        # toward live; skip terminal/replaced states to avoid churning the entity.
        if state in {"REPLACED_WITH_NEW_VERSION", "REMOVED_FROM_SALE"}:
            continue
        live = state == "READY_FOR_SALE"
        port_upsert(
            token,
            identifier=f"{app['service']}-ios-appstore",
            title=f"{app['service']} · ios · appstore",
            service=app["service"],
            props={
                "platform": "ios",
                "track": "appstore",
                "version_name": attrs.get("versionString"),
                "status": state,
                "rollout_fraction": 100 if live else None,
                "store_url": store_url,
                "synced_at": now_iso(),
            },
        )
        break  # first non-terminal version is the one that matters

    # TestFlight: latest processed build.
    builds = requests.get(
        f"{ASC_BASE}/v1/builds",
        params={
            "filter[app]": app_id,
            "sort": "-uploadedDate",
            "limit": 1,
            "fields[builds]": "version,processingState",
            "include": "preReleaseVersion",
        },
        headers=headers,
        timeout=TIMEOUT,
    )
    builds.raise_for_status()
    data = builds.json()
    if data.get("data"):
        b = data["data"][0]
        pre = {i["id"]: i for i in data.get("included", []) if i["type"] == "preReleaseVersions"}
        rel = b.get("relationships", {}).get("preReleaseVersion", {}).get("data") or {}
        version_name = pre.get(rel.get("id"), {}).get("attributes", {}).get("version")
        port_upsert(
            token,
            identifier=f"{app['service']}-ios-testflight",
            title=f"{app['service']} · ios · testflight",
            service=app["service"],
            props={
                "platform": "ios",
                "track": "testflight",
                "version_name": version_name,
                "build_number": b["attributes"].get("version"),
                "status": b["attributes"].get("processingState"),
                "store_url": store_url,
                "synced_at": now_iso(),
            },
        )


def main() -> int:
    if not APPS:
        print("STORE_SYNC_APPS is empty — nothing to sync.")
        return 0
    token = port_token()
    failures = 0
    for app in APPS:
        print(f"Syncing {app['service']}…")
        for label, fn in (("android", sync_android), ("ios", sync_ios)):
            try:
                fn(token, app)
            except (HttpError, requests.RequestException, RuntimeError, KeyError) as err:
                failures += 1
                print(f"  {label} sync failed: {err}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
