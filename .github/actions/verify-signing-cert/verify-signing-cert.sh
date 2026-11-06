#!/usr/bin/env bash
# Env: BUNDLE (.aab), APK (optional .apk), EXPECTED (cert SHA-256).
set -euo pipefail

fail() { echo "::error::$*"; exit 1; }
norm() { tr -d ': \t\r' | tr '[:upper:]' '[:lower:]'; }

want=$(printf '%s' "$EXPECTED" | norm)
[[ $want =~ ^[0-9a-f]{64}$ ]] || fail "expected-sha256 is not a SHA-256 digest"

check() { # label, newline-separated digests
  [ -n "$2" ] || fail "$1 has no signing certificate"
  local d
  while IFS= read -r d; do
    [ "$d" = "$want" ] || fail "$1 is signed by certificate $d, expected $want"
  done <<< "$2"
  echo "$1: signing certificate matches"
}

# The AAB is JAR-signed (keytool); the APK uses the APK signature scheme (apksigner).
out=$(keytool -printcert -jarfile "$BUNDLE") || fail "keytool could not read $BUNDLE"
check AAB "$(sed -n 's/^[[:space:]]*SHA256:[[:space:]]*//p' <<< "$out" | norm)"

if [ -n "${APK:-}" ]; then
  tools="${ANDROID_HOME:-}/build-tools"
  [ -d "$tools" ] || fail "apksigner not found: no $tools"
  apksigner=$(find "$tools" -name apksigner -type f | sort -V | tail -n 1)
  [ -n "$apksigner" ] || fail "apksigner not found under $tools"
  out=$("$apksigner" verify --print-certs "$APK") || fail "apksigner rejected $APK"
  check APK "$(sed -n 's/^Signer #[0-9]* certificate SHA-256 digest: //p' <<< "$out" | norm)"
fi
