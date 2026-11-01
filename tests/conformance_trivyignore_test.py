"""Tests for the trivyignore rule in .github/workflows/conformance.yml.

The rule runs inline in the caller's checkout, so the script is read out of the
workflow itself rather than duplicated here. Run: python3 -m unittest discover -s tests -p '*_test.py'
"""
import datetime
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEP = "Trivy ignore entries carry a statement and an expiry"


def load_script():
    with open(os.path.join(ROOT, ".github/workflows/conformance.yml")) as f:
        wf = yaml.safe_load(f)
    for step in wf["jobs"]["conformance"]["steps"]:
        if step.get("name") == STEP:
            assert "if" not in step, "rule must run in repos without workflow files"
            return step["run"]
    raise AssertionError(f"step {STEP!r} not found")


SCRIPT = load_script()
TODAY = datetime.datetime.now(datetime.timezone.utc).date()


def day(offset):
    return (TODAY + datetime.timedelta(days=offset)).isoformat()


STATEMENT = "Not reachable, the package is build-time only and never shipped."


class TrivyignoreRule(unittest.TestCase):
    def run_rule(self, files):
        with tempfile.TemporaryDirectory() as d:
            for path, body in files.items():
                full = os.path.join(d, path)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w") as f:
                    f.write(textwrap.dedent(body))
            subprocess.run(["git", "init", "-q", d], check=True)
            subprocess.run(["git", "-C", d, "add", "-A"], check=True)
            p = subprocess.run(
                [sys.executable, "-c", SCRIPT], cwd=d, capture_output=True, text=True
            )
            return p.returncode, p.stdout + p.stderr

    def entry(self, expires=None, statement=STATEMENT, extra=""):
        expires = day(30) if expires is None else expires
        return f"""\
            vulnerabilities:
              - id: CVE-2026-0001
                statement: {statement}
                expired_at: {expires}
            {extra}"""

    def assertPass(self, files):
        code, out = self.run_rule(files)
        self.assertEqual(code, 0, out)
        return out

    def assertFail(self, files, needle):
        code, out = self.run_rule(files)
        self.assertEqual(code, 1, out)
        self.assertIn(needle, out)

    def test_no_ignore_files_passes(self):
        self.assertIn("No Trivy ignore files", self.assertPass({"README.md": "x\n"}))

    def test_untracked_files_are_not_checked(self):
        # node_modules and build output are not in git; only tracked files count.
        code, out = self.run_rule({".gitignore": "vendor/\n", "vendor/.trivyignore": "CVE-1\n"})
        self.assertEqual(code, 0, out)

    def test_valid_entry_passes(self):
        self.assertIn("1 entries", self.assertPass({".trivyignore.yaml": self.entry()}))

    def test_all_sections_and_keys_pass(self):
        self.assertPass({".trivyignore.yaml": f"""\
            misconfigurations:
              - id: GCP-0001
                paths: [terraform/bucket.tf]
                statement: {STATEMENT}
                expired_at: {day(90)}
            secrets: []
            licenses:
            vulnerabilities:
              - id: CVE-2026-0002
                purls: ["pkg:npm/foo@1.0.0"]
                statement: {STATEMENT}
                expired_at: {day(0)}
            crypto: []
            """})

    def test_empty_yaml_file_passes(self):
        self.assertPass({".trivyignore.yaml": "# nothing accepted\n"})

    def test_nested_yaml_file_is_checked(self):
        self.assertFail({"infra/.trivyignore.yml": self.entry(statement="short")}, "20+ characters")

    def test_missing_statement_fails(self):
        self.assertFail({".trivyignore.yaml": f"""\
            vulnerabilities:
              - id: CVE-2026-0001
                expired_at: {day(30)}
            """}, "CVE-2026-0001: statement must say why this is acceptable (20+ characters)")

    def test_short_statement_fails(self):
        self.assertFail({".trivyignore.yaml": self.entry(statement="false positive")}, "20+ characters")

    def test_missing_expiry_fails(self):
        self.assertFail({".trivyignore.yaml": f"""\
            vulnerabilities:
              - id: CVE-2026-0001
                statement: {STATEMENT}
            """}, "expired_at must be a YYYY-MM-DD date")

    def test_quoted_expiry_fails(self):
        # Trivy refuses to parse a quoted date, so the file would break every scan.
        self.assertFail({".trivyignore.yaml": self.entry(expires=f'"{day(30)}"')},
                        "expired_at must be a YYYY-MM-DD date")

    def test_non_date_expiry_fails(self):
        self.assertFail({".trivyignore.yaml": self.entry(expires="next-quarter")},
                        "expired_at must be a YYYY-MM-DD date")

    def test_expired_entry_fails(self):
        self.assertFail({".trivyignore.yaml": self.entry(expires=day(-1))},
                        f"exception expired on {day(-1)}")

    def test_beyond_horizon_fails(self):
        self.assertFail({".trivyignore.yaml": self.entry(expires=day(91))},
                        f"is more than 90 days out ({day(90)})")

    def test_camelcase_expiry_fails_with_hint(self):
        self.assertFail({".trivyignore.yaml": f"""\
            misconfigurations:
              - id: GCP-0007
                statement: {STATEMENT}
                expiredAt: {day(30)}
            """}, "unknown key 'expiredAt', which Trivy ignores (did you mean expired_at?)")

    def test_unknown_section_fails(self):
        self.assertFail({".trivyignore.yaml": self.entry(extra="vulnerability: []")},
                        "unknown section 'vulnerability'")

    def test_entry_without_id_fails(self):
        self.assertFail({".trivyignore.yaml": f"""\
            vulnerabilities:
              - statement: {STATEMENT}
                expired_at: {day(30)}
            """}, "entry has no id")

    def test_invalid_yaml_fails(self):
        self.assertFail({".trivyignore.yaml": "vulnerabilities: [\n"}, "not valid YAML")

    def test_plain_file_with_entries_fails(self):
        self.assertFail({".trivyignore": "# accepted\nCVE-2026-0001 exp:2026-12-01\n"},
                        "CVE-2026-0001: plain .trivyignore entries cannot carry a statement")

    def test_plain_file_without_entries_passes(self):
        self.assertPass({".trivyignore": "\n# nothing\n"})

    def test_every_bad_entry_is_reported(self):
        code, out = self.run_rule({".trivyignore.yaml": f"""\
            vulnerabilities:
              - id: CVE-A
              - id: CVE-B
                statement: {STATEMENT}
                expired_at: {day(-5)}
            """})
        self.assertEqual(code, 1, out)
        for needle in ("vulnerabilities/CVE-A: statement", "vulnerabilities/CVE-A: expired_at",
                       "vulnerabilities/CVE-B: exception expired"):
            self.assertIn(needle, out)


if __name__ == "__main__":
    unittest.main()
