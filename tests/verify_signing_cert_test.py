"""verify-signing-cert action script, run against stub keytool and apksigner."""

import os
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, ".github/actions/verify-signing-cert/verify-signing-cert.sh")

GOOD = "15:2F:BD:F2:85:38:84:DB:83:38:71:B8:83:DE:7D:FC:26:D2:A1:E9:84:D5:4D:C7:19:19:72:DE:19:30:0C:5A"
GOOD_HEX = GOOD.replace(":", "").lower()
OTHER = "AA:" * 31 + "AA"


def keytool_output(*fingerprints):
    out = []
    for i, fp in enumerate(fingerprints, 1):
        out += [f"Signer #{i}:", "", "Certificate #1:", "Owner: CN=t",
                "Certificate fingerprints:", "\t SHA1: 00:11",
                f"\t SHA256: {fp}", ""]
    return "\n".join(out)


def apksigner_output(*digests):
    return "\n".join(
        f"Signer #{i} certificate SHA-256 digest: {d}" for i, d in enumerate(digests, 1)
    )


def apksigner_v31_output(digest):
    # Shape of `apksigner verify --print-certs` when a v3.1 block is present.
    return "\n".join([
        f"Signer (minSdkVersion=33, maxSdkVersion=2147483647) certificate SHA-256 digest: {digest}",
        f"Signer (minSdkVersion=24, maxSdkVersion=32) certificate SHA-256 digest: {digest}",
        f"Source Stamp Signer certificate SHA-256 digest: {OTHER.replace(':', '').lower()}",
    ])


def apksigner_37_output(digest):
    # build-tools 37 labels signers by scheme.
    return "\n".join([
        "V2 Signer: certificate DN: CN=t",
        f"V2 Signer: certificate SHA-256 digest: {digest}",
        f"V3.0 Signer: certificate SHA-256 digest: {digest}",
        "V3.0 Signer: certificate SHA-1 digest: 00",
    ])


class VerifySigningCertTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bin = os.path.join(self.tmp.name, "bin")
        self.sdk = os.path.join(self.tmp.name, "sdk")
        os.makedirs(self.bin)

    def stub(self, path, output, code=0):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(f"#!/bin/sh\ncat <<'OUT'\n{output}\nOUT\nexit {code}\n")
        os.chmod(path, 0o755)

    def run_script(self, expected=GOOD, apk=""):
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}",
               "ANDROID_HOME": self.sdk, "BUNDLE": "app.aab", "APK": apk,
               "EXPECTED": expected}
        return subprocess.run(["bash", SCRIPT], env=env, capture_output=True, text=True)

    def test_aab_match(self):
        self.stub(os.path.join(self.bin, "keytool"), keytool_output(GOOD))
        r = self.run_script(expected=GOOD_HEX.upper())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_aab_mismatch(self):
        self.stub(os.path.join(self.bin, "keytool"), keytool_output(GOOD, OTHER))
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn("::error::AAB is signed by certificate aaaa", r.stdout)

    def test_aab_unsigned(self):
        self.stub(os.path.join(self.bin, "keytool"), "Not a signed jar file")
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn("::error::AAB has no signing certificate", r.stdout)

    def test_keytool_error(self):
        self.stub(os.path.join(self.bin, "keytool"), "boom", code=1)
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn("::error::keytool could not read", r.stdout)

    def test_malformed_pin(self):
        r = self.run_script(expected="15:2F")
        self.assertEqual(r.returncode, 1)
        self.assertIn("::error::expected-sha256 is not a SHA-256 digest", r.stdout)

    def test_apk_uses_newest_build_tools(self):
        self.stub(os.path.join(self.bin, "keytool"), keytool_output(GOOD))
        self.stub(os.path.join(self.sdk, "build-tools/9.0.0/apksigner"), apksigner_output(OTHER))
        self.stub(os.path.join(self.sdk, "build-tools/35.0.0/apksigner"), apksigner_output(GOOD_HEX))
        r = self.run_script(apk="app.apk")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("APK: signing certificate matches", r.stdout)

    def test_apk_v31_signers(self):
        self.stub(os.path.join(self.bin, "keytool"), keytool_output(GOOD))
        self.stub(os.path.join(self.sdk, "build-tools/35.0.0/apksigner"), apksigner_v31_output(GOOD_HEX))
        r = self.run_script(apk="app.apk")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("APK: signing certificate matches", r.stdout)

    def test_apk_build_tools_37_labels(self):
        self.stub(os.path.join(self.bin, "keytool"), keytool_output(GOOD))
        self.stub(os.path.join(self.sdk, "build-tools/37.0.0/apksigner"), apksigner_37_output(GOOD_HEX))
        r = self.run_script(apk="app.apk")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("APK: signing certificate matches", r.stdout)

    def test_apk_no_signer_lines_prints_output(self):
        self.stub(os.path.join(self.bin, "keytool"), keytool_output(GOOD))
        self.stub(os.path.join(self.sdk, "build-tools/35.0.0/apksigner"), "Verifies")
        r = self.run_script(apk="app.apk")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Verifies", r.stdout)
        self.assertIn("::error::APK has no signing certificate", r.stdout)

    def test_apk_mismatch(self):
        self.stub(os.path.join(self.bin, "keytool"), keytool_output(GOOD))
        self.stub(os.path.join(self.sdk, "build-tools/35.0.0/apksigner"),
                  apksigner_output(GOOD_HEX, OTHER.replace(":", "").lower()))
        r = self.run_script(apk="app.apk")
        self.assertEqual(r.returncode, 1)
        self.assertIn("::error::APK is signed by certificate", r.stdout)

    def test_apk_rejected(self):
        self.stub(os.path.join(self.bin, "keytool"), keytool_output(GOOD))
        self.stub(os.path.join(self.sdk, "build-tools/35.0.0/apksigner"), "DOES NOT VERIFY", code=1)
        r = self.run_script(apk="app.apk")
        self.assertEqual(r.returncode, 1)
        self.assertIn("::error::apksigner rejected app.apk", r.stdout)

    def test_apksigner_missing(self):
        self.stub(os.path.join(self.bin, "keytool"), keytool_output(GOOD))
        r = self.run_script(apk="app.apk")
        self.assertEqual(r.returncode, 1)
        self.assertIn("::error::apksigner not found", r.stdout)


if __name__ == "__main__":
    unittest.main()
