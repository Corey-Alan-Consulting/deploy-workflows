"""Publish-mode steps of release.yml, run out of the workflow file.

The steps are executed against a throwaway git workspace with stub `pnpm`,
`npm` and `gh` binaries that model the registry and GitHub Releases. The cases
replay the 2026-11-02 platform release, where a publish that failed partway
needed tags and Releases deleted by hand before a re-run could finish it.
"""

import json
import os
import subprocess
import tempfile
import textwrap
import unittest

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(ROOT, ".github/workflows/release.yml")

PLAN = "Plan npm publishes"
PUBLISH = "Publish changed packages to npm (OIDC)"
RELEASES = "Create GitHub Releases"
PARITY = "Verify every package version reached the registry"


def load_steps():
    with open(WORKFLOW) as f:
        wf = yaml.safe_load(f)
    return {s["name"]: s for s in wf["jobs"]["release"]["steps"] if "name" in s}


STEPS = load_steps()

PNPM = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
ws = os.environ["STUB_WS"]
if a[:1] == ["list"]:
    out = []
    for rel in json.load(open(os.path.join(ws, ".stub-pkgs.json"))):
        d = os.path.join(ws, rel) if rel != "." else ws
        m = json.load(open(os.path.join(d, "package.json")))
        out.append({"name": m["name"], "version": m["version"], "path": d})
    print(json.dumps(out))
elif a[:1] == ["pack"]:
    m = json.load(open("package.json"))
    open(a[a.index("--out") + 1], "w").write(m["name"] + "\n" + m["version"] + "\n")
'''

NPM = r'''#!/usr/bin/env python3
import json, os, sys
state = os.environ["STUB_STATE"]
reg_path = os.path.join(state, "registry.json")
reg = json.load(open(reg_path))
cfg = json.load(open(os.path.join(state, "config.json")))
a = sys.argv[1:]
if a[0] == "view":
    spec, field = a[1], a[2]
    name, _, ver = spec[1:].partition("@")
    name = spec[0] + name
    if name in cfg["unreadable"] or name not in reg:
        sys.exit(1)
    if field == "version":
        if ver not in reg[name]:
            sys.exit(1)
        print(ver)
    else:
        print(name)
elif a[0] == "publish":
    name, ver = open(a[1]).read().split()
    with open(os.path.join(state, "publish.log"), "a") as f:
        f.write(f"{name}@{ver}\n")
    if name in cfg["fail_publish"]:
        print(f"npm error 404 Not Found - PUT https://registry.npmjs.org/{name}")
        sys.exit(1)
    if ver in reg.get(name, []):
        print("npm error 403 403 Forbidden - PUT https://registry.npmjs.org/x - "
              f"You cannot publish over the previously published versions: {ver}.")
        sys.exit(1)
    reg.setdefault(name, []).append(ver)
    json.dump(reg, open(reg_path, "w"))
'''

GH = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
state = os.environ["STUB_STATE"]
path = os.path.join(state, "releases.json")
rels = json.load(open(path))
a = sys.argv[1:]
assert a[0] == "release", a
tag = a[2]
if a[1] == "view":
    sys.exit(0 if tag in rels else 1)
if a[1] == "create":
    assert "--verify-tag" in a, "a Release must never create its tag"
    if subprocess.run(["git", "rev-parse", "-q", "--verify", "refs/tags/" + tag],
                      capture_output=True).returncode:
        sys.exit("tag not found")
    if tag in rels:
        sys.exit('Validation Failed: {"resource":"Release","code":"already_exists"}')
    rels.append(tag)
    json.dump(rels, open(path, "w"))
'''


class Harness:
    """A workspace, its registry and its Releases, persisted across runs."""

    def __init__(self, d, packages, registry, releases=(), unreadable=(), app=""):
        self.d = d
        self.ws = os.path.join(d, "ws")
        self.state = os.path.join(d, "state")
        self.bin = os.path.join(d, "bin")
        self.app = app
        for p in (self.ws, self.state, self.bin):
            os.makedirs(p)
        for name, body in (("pnpm", PNPM), ("npm", NPM), ("gh", GH)):
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write(body)
            os.chmod(path, 0o755)
        rels = []
        for rel, manifest in packages.items():
            d2 = os.path.join(self.ws, rel)
            os.makedirs(d2, exist_ok=True)
            with open(os.path.join(d2, "package.json"), "w") as f:
                json.dump(manifest, f)
            with open(os.path.join(d2, "CHANGELOG.md"), "w") as f:
                f.write(f"# {manifest['name']}\n\n## {manifest['version']}\n\n- a change\n\n## 0.0.1\n\n- old\n")
            rels.append(rel)
        with open(os.path.join(self.ws, ".stub-pkgs.json"), "w") as f:
            json.dump(rels, f)
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "release")
        self.sha = self.git("rev-parse", "HEAD").strip()
        self.write("registry.json", registry)
        self.write("releases.json", list(releases))
        self.configure(unreadable=list(unreadable), fail_publish=[])

    def git(self, *args):
        return subprocess.run(["git", "-C", self.ws, *args], check=True,
                              capture_output=True, text=True).stdout

    def write(self, name, data):
        with open(os.path.join(self.state, name), "w") as f:
            json.dump(data, f)

    def read(self, name):
        with open(os.path.join(self.state, name)) as f:
            return json.load(f)

    def configure(self, **cfg):
        self.write("config.json", {"unreadable": [], "fail_publish": [], **cfg})

    def tag(self, *tags, at=None):
        for t in tags:
            self.git("-c", "user.name=t", "-c", "user.email=t@t",
                     "tag", "-a", t, "-m", t, at or self.sha)

    def advance(self):
        """A later push to main that changes no version."""
        self.git("-c", "user.name=t", "-c", "user.email=t@t",
                 "commit", "-q", "--allow-empty", "-m", "docs")
        self.sha = self.git("rev-parse", "HEAD").strip()

    def publishes(self):
        p = os.path.join(self.state, "publish.log")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            out = f.read().split()
        os.remove(p)
        return out

    def step(self, name, extra_env=None):
        tmp = tempfile.mkdtemp(dir=self.d)
        out = os.path.join(tmp, "output")
        open(out, "w").close()
        env = {
            "PATH": self.bin + os.pathsep + os.environ["PATH"],
            "HOME": self.d,
            "GITHUB_SHA": self.sha,
            "GITHUB_WORKSPACE": self.ws,
            "RUNNER_TEMP": self.runner_temp,
            "GITHUB_OUTPUT": out,
            "STUB_WS": self.ws,
            "STUB_STATE": self.state,
            **(extra_env or {}),
        }
        p = subprocess.run(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", STEPS[name]["run"]],
            cwd=self.ws, env=env, capture_output=True, text=True,
        )
        with open(out) as f:
            outputs = dict(l.split("=", 1) for l in f.read().splitlines() if "=" in l)
        return p.returncode, p.stdout + p.stderr, outputs

    def run(self):
        """One attempt of the publish-mode tail, honouring each step's `if:`."""
        self.runner_temp = tempfile.mkdtemp(dir=self.d)
        r = {"log": ""}
        rc, log, outputs = self.step(PLAN)
        r["log"] += log
        r["plan"] = rc
        publish = "skipped"
        if rc == 0 and outputs.get("publish-count", "0") != "0":
            rc2, log, _ = self.step(PUBLISH)
            r["log"] += log
            publish = "success" if rc2 == 0 else "failure"
        r["publish"] = publish
        if rc == 0:
            rc3, log, _ = self.step(RELEASES, {"APP_PACKAGE": self.app,
                                               "PUBLISH_OUTCOME": publish,
                                               "GH_TOKEN": "x"})
            r["log"] += log
            r["releases"] = rc3
        rc4, log, _ = self.step(PARITY, {"NODE_AUTH_TOKEN": ""})
        r["log"] += log
        r["parity"] = rc4
        r["ok"] = rc == 0 and publish != "failure" and r.get("releases") == 0 and rc4 == 0
        r["published"] = self.publishes()
        return r


def pkg(name, version, private=False):
    m = {"name": name, "version": version}
    if private:
        m["private"] = True
    return m


A, B, C = "@s/alpha", "@s/bravo", "@s/charlie"
LIBS = {
    "packages/alpha": pkg(A, "1.1.0"),
    "packages/bravo": pkg(B, "0.2.1"),
    "packages/charlie": pkg(C, "2.0.0"),
}
OLD = {A: ["1.0.0"], B: ["0.2.0"], C: ["1.9.0"]}
TAGS = (f"{A}@1.1.0", f"{B}@0.2.1", f"{C}@2.0.0")


class PartialReleaseRecovers(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)

    def harness(self, **kw):
        kw.setdefault("packages", LIBS)
        kw.setdefault("registry", json.loads(json.dumps(OLD)))
        return Harness(self._d.name, **kw)

    def test_one_failure_does_not_strand_the_rest_and_a_rerun_finishes(self):
        h = self.harness()
        h.tag(*TAGS)
        h.configure(fail_publish=[B])

        first = h.run()
        self.assertFalse(first["ok"])
        self.assertEqual(first["publish"], "failure")
        self.assertEqual(sorted(first["published"]), sorted(TAGS))
        self.assertEqual(sorted(h.read("releases.json")), [f"{A}@1.1.0", f"{C}@2.0.0"])
        self.assertIn("MISSING   @s/bravo@0.2.1", first["log"])

        h.configure()  # trusted publisher fixed
        second = h.run()
        self.assertTrue(second["ok"], second["log"])
        self.assertEqual(second["published"], [f"{B}@0.2.1"])
        self.assertEqual(sorted(h.read("releases.json")), sorted(TAGS))

        third = h.run()
        self.assertTrue(third["ok"], third["log"])
        self.assertEqual(third["published"], [])

    def test_releases_left_by_an_old_run_do_not_block_the_publish(self):
        # Attempt 3: tags and Releases exist, the versions are not on npm.
        h = self.harness(releases=list(TAGS))
        h.tag(*TAGS)
        r = h.run()
        self.assertTrue(r["ok"], r["log"])
        self.assertEqual(sorted(r["published"]), sorted(TAGS))
        self.assertEqual(sorted(h.read("releases.json")), sorted(TAGS))

    def test_old_tags_on_an_earlier_commit_still_publish_when_readable(self):
        # A version committed on main but missing from npm is published on any
        # publish-mode run, regardless of where (or whether) its tag is.
        h = self.harness()
        h.tag(*TAGS)
        h.advance()
        r = h.run()
        self.assertTrue(r["ok"], r["log"])
        self.assertEqual(sorted(r["published"]), sorted(TAGS))
        # ...but a later commit never cuts Releases for older versions.
        self.assertEqual(h.read("releases.json"), [])

    def test_unreadable_registry_publishes_on_the_tagging_commit_only(self):
        registry = json.loads(json.dumps(OLD))
        registry[A].append("1.1.0")  # already published; npm will refuse it
        h = self.harness(registry=registry, unreadable=[A, B, C])
        h.tag(*TAGS)
        r = h.run()
        self.assertTrue(r["ok"], r["log"])
        self.assertIn("is already on the registry", r["log"])
        self.assertEqual(sorted(h.read("releases.json")), sorted(TAGS))
        self.assertIn("Registry parity unverified", r["log"])

        h.advance()
        later = h.run()
        self.assertTrue(later["ok"], later["log"])
        self.assertEqual(later["published"], [])

    def test_nothing_to_do_publishes_nothing(self):
        registry = {A: ["1.1.0"], B: ["0.2.1"], C: ["2.0.0"]}
        h = self.harness(registry=registry, releases=list(TAGS))
        h.tag(*TAGS)
        r = h.run()
        self.assertTrue(r["ok"], r["log"])
        self.assertEqual(r["published"], [])
        self.assertIn("0 package(s) to publish", r["log"])

    def test_private_packages_are_released_but_never_published(self):
        pkgs = dict(LIBS)
        pkgs["apps/site"] = pkg("site", "3.0.0", private=True)
        registry = {A: ["1.1.0"], B: ["0.2.1"], C: ["2.0.0"]}
        h = self.harness(packages=pkgs, registry=registry)
        h.tag(*TAGS, "site@3.0.0")
        r = h.run()
        self.assertTrue(r["ok"], r["log"])
        self.assertEqual(r["published"], [])
        self.assertIn("site@3.0.0", h.read("releases.json"))

    def test_uncommitted_version_is_never_published(self):
        h = self.harness()
        h.tag(*TAGS)
        with open(os.path.join(h.ws, "packages/alpha/package.json"), "w") as f:
            json.dump(pkg(A, "9.9.9"), f)
        r = h.run()
        self.assertNotEqual(r["plan"], 0)
        self.assertIn("Version drift", r["log"])
        self.assertEqual(r["published"], [])


class AppRelease(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)

    def test_app_release_waits_for_publishes_then_a_rerun_cuts_it(self):
        pkgs = {".": pkg("app", "0.5.0", private=True), "packages/sdk": pkg("@s/sdk", "0.3.0")}
        h = Harness(self._d.name, packages=pkgs, registry={"@s/sdk": ["0.2.0"]}, app="app")
        h.tag("app@0.5.0", "@s/sdk@0.3.0")
        h.configure(fail_publish=["@s/sdk"])
        first = h.run()
        self.assertFalse(first["ok"])
        self.assertEqual(h.read("releases.json"), [])

        h.configure()
        second = h.run()
        self.assertTrue(second["ok"], second["log"])
        # Only the app gets a Release in app mode.
        self.assertEqual(h.read("releases.json"), ["app@0.5.0"])

    def test_single_package_repo_uses_v_tags(self):
        h = Harness(self._d.name, packages={".": pkg("app", "1.2.0", private=True)},
                    registry={}, app="app")
        h.tag("v1.2.0")
        r = h.run()
        self.assertTrue(r["ok"], r["log"])
        self.assertEqual(h.read("releases.json"), ["v1.2.0"])


class WorkflowWiring(unittest.TestCase):
    def test_action_never_creates_releases(self):
        cs = next(s for s in STEPS.values() if s.get("id") == "changesets")
        self.assertIs(cs["with"]["create-github-releases"], False)
        self.assertIs(cs["with"]["push-git-tags"], True)

    def test_publish_mode_only(self):
        self.assertIn("has-changesets == 'false'", STEPS[PLAN]["if"])
        for name in (PUBLISH, "Build library packages (topological)"):
            self.assertIn("steps.plan.outputs.publish-count", STEPS[name]["if"])

    def test_recovery_steps_survive_a_failed_publish(self):
        self.assertIn("!cancelled()", STEPS[RELEASES]["if"])
        self.assertIn("steps.plan.outcome == 'success'", STEPS[RELEASES]["if"])
        self.assertIn("!cancelled()", STEPS[PARITY]["if"])

    def test_publish_step_holds_no_registry_token(self):
        # OIDC only: an NODE_AUTH_TOKEN here would publish with the read token.
        self.assertNotIn("NODE_AUTH_TOKEN", STEPS[PUBLISH].get("env", {}))


if __name__ == "__main__":
    unittest.main()
