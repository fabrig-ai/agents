#!/usr/bin/env python3
"""Black-box lease tests: all commands have a temporary HOME and local git."""

import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from urllib.parse import quote


TOOL = Path(__file__).resolve().with_name("lease")
PYTHON = os.sys.executable
A = "pkg:alpha"
B = "pkg:beta"
N = "pkg:nested"
D = "doc:skein/docs/design/plan.md"
F = "doc:jig/docs/foundation/base.md"


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.repo = self.home / "src/fabrig/main"
        self.repo.mkdir(parents=True)
        self.state = self.home / "src/fabrig/leases"
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update(HOME=str(self.home), PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_AUTHOR_NAME="Lease Test", GIT_AUTHOR_EMAIL="test@example.invalid",
                        GIT_COMMITTER_NAME="Lease Test", GIT_COMMITTER_EMAIL="test@example.invalid")
        self.git("init", "-q")
        files = {
            "Cargo.toml": '[workspace]\nmembers = ["skein/alpha", "skein/alpha/nested", "jig/beta"]\n',
            "Cargo.lock": "# lock\n",
            "skein/alpha/Cargo.toml": '[package]\nname = "alpha"\nversion = "0.1.0"\n',
            "skein/alpha/src/lib.rs": "// alpha\n",
            "skein/alpha/nested/Cargo.toml": '[package]\nname = "nested"\nversion = "0.1.0"\n',
            "skein/alpha/nested/src/lib.rs": "// nested\n",
            "jig/beta/Cargo.toml": '[package]\nname = "beta"\nversion = "0.1.0"\n',
            "jig/beta/src/lib.rs": "// beta\n",
            "skein/docs/design/plan.md": "# Plan\n",
            "skein/docs/design/plan.status.md": "Status\n",
            "jig/docs/foundation/base.md": "# Foundation\n",
            "skein/alpha/scripts/old-forms.txt": "old\n",
            "skein/scripts/old-forms.txt": "old\n",
            ".config/test.toml": "# config\n",
            "README.md": "# workspace\n",
        }
        for path, content in files.items():
            self.write(path, content)
        self.commit()
        self.base = self.git("rev-parse", "HEAD").strip()
        post = self.bin / "post"
        post.write_text(
            f"#!{PYTHON}\n"
            "import json, os, pathlib, sys\n"
            "with (pathlib.Path.home() / 'post.jsonl').open('a') as log:\n"
            "    log.write(json.dumps({'args': sys.argv[1:], 'body': sys.stdin.read()}) + '\\n')\n"
            "print('fake post diagnostic', file=sys.stderr)\n"
            "sys.exit(int(os.environ.get('POST_EXIT', '0')))\n")
        post.chmod(0o700)

    def write(self, path, content):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.repo), *args], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")

    def command(self, *args):
        return [PYTHON, "-I", "-B", str(TOOL), "--fabrig", str(self.repo), *args]

    def run_lease(self, *args, code=0):
        result = subprocess.run(self.command(*args), env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def rows(self, *args):
        return json.loads(self.run_lease("list", "--json", *args).stdout)

    def record(self, subject=A):
        return json.loads((self.state / quote(subject, safe="")).read_text())

    def changed(self, paths):
        for path in paths:
            target = self.repo / path
            content = target.read_text() if target.exists() else ""
            self.write(path, content + "\n# change\n")
        self.commit()

    def check(self, *args, code=0, base=None, tip="HEAD"):
        return self.run_lease("check", "s/b", "--repo", str(self.repo),
                              "--base", base or self.base, "--tip", tip, *args, code=code)

    def test_take_is_atomic_idempotent_and_reports_all_holders(self):
        self.run_lease("take", "s/a", "wave one", A)
        before = (self.state / quote(A, safe="")).read_bytes()
        self.run_lease("lend", "s/a", A, "--to", "abc-jig/fix-x")
        lent = self.record()
        self.run_lease("take", "s/a", "a new description", A)
        self.assertEqual(self.record(), lent)
        self.assertEqual(json.loads(before)["what"], "wave one")
        refusal = self.run_lease("take", "s/b", "wave two", B, A, code=1).stdout
        self.assertIn("pkg:alpha held by s/a (age ", refusal)
        self.assertFalse((self.state / quote(B, safe="")).exists())
        self.run_lease("take", "s/c", "wave three", B)
        refusal = self.run_lease("take", "s/b", "try", A, B, N, code=1).stdout
        self.assertIn("held by s/a", refusal)
        self.assertIn("held by s/c", refusal)
        self.assertEqual(len(self.rows()), 2)

    def test_fifo_free_priority_unwant_and_duplicate_wants(self):
        free = self.run_lease("want", "s/b", "later", A)
        self.assertIn("free to take", free.stdout)
        self.assertEqual(self.rows(), [])
        self.run_lease("take", "s/a", "wave", A)
        self.run_lease("want", "s/b", "next wave", A)
        first = self.record()["waiters"][0]
        self.run_lease("want", "s/c", "third wave", A)
        self.run_lease("want", "s/b", "duplicate", A)
        self.assertEqual(self.record()["waiters"][0], first)
        self.assertEqual([w["owner"] for w in self.record()["waiters"]], ["s/b", "s/c"])
        self.run_lease("release", "s/a", A)
        self.assertIsNone(self.record()["owner"])
        refused = self.run_lease("take", "s/c", "jump queue", A, B, code=1)
        self.assertIn("first waiter s/b", refused.stdout)
        self.assertFalse((self.state / quote(B, safe="")).exists())
        self.run_lease("want", "s/d", "fourth", A)
        self.run_lease("take", "s/b", "next wave", A)
        self.assertEqual([w["owner"] for w in self.record()["waiters"]], ["s/c", "s/d"])
        self.run_lease("unwant", "s/c", A)
        self.run_lease("release", "s/b", A)
        self.run_lease("unwant", "s/d", A)
        self.assertEqual(self.rows(), [])

    def test_release_notifies_and_clears_lends(self):
        self.run_lease("take", "s/a", "wave", A, B)
        self.run_lease("lend", "s/a", A, "--to", "abc-jig/fix-x")
        self.run_lease("want", "s/b", "next", A)
        self.run_lease("want", "s/c", "after", A)
        self.run_lease("release", "s/a", "--all")
        record = self.record()
        self.assertIsNone(record["owner"])
        self.assertIsNone(record["what"])
        self.assertIsNone(record["since"])
        self.assertEqual(record["lends"], [])
        self.assertFalse((self.state / quote(B, safe="")).exists())
        calls = [json.loads(line) for line in (self.home / "post.jsonl").read_text().splitlines()]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["args"], ["send", "--as", "lease", "s/b@hel8", "lease free: " + A])
        self.assertEqual(len(calls[0]["body"].splitlines()), 1)
        self.run_lease("release", "s/a", A)
        self.assertEqual(len((self.home / "post.jsonl").read_text().splitlines()), 1)

    def test_post_failure_does_not_undo_release(self):
        for exit_code in (3, 7):
            with self.subTest(exit=exit_code):
                self.run_lease("take", "s/a", "wave", A)
                self.run_lease("want", "s/b", "next", A)
                self.env["POST_EXIT"] = str(exit_code)
                result = self.run_lease("release", "s/a", A)
                self.assertEqual("post failed" in result.stderr, exit_code == 7)
                if exit_code == 7:
                    self.assertIn("exit 7", result.stderr)
                    self.assertIn("fake post diagnostic", result.stderr)
                self.assertIsNone(self.record()["owner"])
                self.run_lease("unwant", "s/b", A)

    def test_missing_post_is_reported_after_release(self):
        (self.bin / "post").unlink()
        # Do not accidentally call a real post from the inherited PATH.
        for command in ("git",):
            import shutil
            (self.bin / command).symlink_to(shutil.which(command))
        self.env["PATH"] = str(self.bin)
        self.run_lease("take", "s/a", "wave", A)
        self.run_lease("want", "s/b", "next", A)
        result = self.run_lease("release", "s/a", A)
        self.assertIn("post failed", result.stderr)
        self.assertIsNone(self.record()["owner"])

    def test_holder_only_operations_and_release_all(self):
        self.run_lease("take", "s/a", "wave", A, B)
        self.run_lease("take", "s/b", "other", N)
        for command in ("release", "lend", "unlend"):
            extra = ["--to", "abc-jig/fix-x"] if command != "release" else []
            self.run_lease(command, "s/b", N, A, *extra, code=1)
            self.assertEqual(self.record(N)["owner"], "s/b")
        self.run_lease("release", "s/a", "--all")
        self.assertEqual([r["subject"] for r in self.rows()], [N])
        self.run_lease("release", "s/a", B)
        self.run_lease("lend", "s/a", B, "--to", "abc-jig/fix-x", code=1)

    def test_lend_and_unlend_affect_check(self):
        self.changed(["skein/alpha/src/lib.rs"])
        self.run_lease("take", "s/a", "wave", A)
        self.assertIn("outside pkg:alpha (held by s/a)", self.check(code=1).stdout)
        self.run_lease("lend", "s/a", A, "--to", "abc-jig/fix-x")
        self.run_lease("lend", "s/a", A, "--to", "abc-jig/fix-x")
        self.assertEqual(self.record()["lends"], ["abc-jig/fix-x"])
        self.assertEqual(self.check("--branch", "abc-jig/fix-x").stdout, "inside pkg:alpha\n")
        self.check("--branch", "abc-jig/another", code=1)
        self.run_lease("unlend", "s/a", A, "--to", "abc-jig/fix-x")
        self.check("--branch", "abc-jig/fix-x", code=1)

    def test_check_longest_prefix_and_manifest_itself(self):
        self.changed(["skein/alpha/nested/src/lib.rs", "skein/alpha/nested/Cargo.toml"])
        self.run_lease("take", "s/b", "wave", A)
        self.assertEqual(self.check(code=1).stdout, "outside pkg:nested (unleased)\n")
        self.run_lease("take", "s/b", "wave", N)
        self.assertEqual(self.check().stdout, "inside pkg:nested\n")

    def test_check_each_mapping_and_exemption(self):
        self.changed(["skein/alpha/src/lib.rs", "jig/beta/src/lib.rs",
                      "skein/docs/design/plan.md", "skein/docs/design/plan.status.md",
                      "jig/docs/foundation/base.md", "Cargo.toml", "Cargo.lock",
                      ".config/test.toml", "skein/alpha/scripts/old-forms.txt",
                      "skein/scripts/old-forms.txt", "README.md"])
        result = self.check(code=1)
        self.assertEqual(set(result.stdout.splitlines()), {
            "unowned README.md", f"outside {A} (unleased)", f"outside {B} (unleased)",
            f"outside {D} (unleased)", f"outside {F} (unleased)"})
        self.run_lease("take", "s/b", "wave", A, B, D, F)
        result = self.check()
        self.assertEqual(set(result.stdout.splitlines()), {
            "unowned README.md", f"inside {A}", f"inside {B}", f"inside {D}", f"inside {F}"})

    def test_status_alone_maps_to_document(self):
        self.changed(["skein/docs/design/plan.status.md"])
        self.assertEqual(self.check(code=1).stdout, f"outside {D} (unleased)\n")

    def test_unowned_only_and_exempt_only_succeed_without_state(self):
        self.changed(["README.md", "Cargo.lock", ".config/test.toml"])
        self.assertEqual(self.check().stdout, "unowned README.md\n")
        self.assertFalse(self.state.exists())
        self.assertEqual(self.check(base="HEAD").stdout, "")
        self.assertFalse(self.state.exists())

    def test_check_is_read_only_for_missing_and_existing_state(self):
        self.changed(["skein/alpha/src/lib.rs"])
        self.check(code=1)
        self.assertFalse(self.state.exists())
        self.run_lease("take", "s/b", "wave", A)
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
                  for p in self.state.iterdir()}
        self.state.chmod(0o500)
        self.check()
        after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
                 for p in self.state.iterdir()}
        self.assertEqual(before, after)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o500)
        self.state.chmod(0o700)

    def test_catalog_uses_head_and_check_uses_tip(self):
        self.write("skein/alpha/Cargo.toml", '[package]\nname = "uncommitted"\n')
        self.run_lease("take", "s/a", "wave", A)
        self.run_lease("take", "s/a", "wave", "pkg:uncommitted", code=2)
        self.write("skein/alpha/Cargo.toml", '[package]\nname = "renamed"\n')
        self.commit()
        self.assertEqual(self.check(code=1).stdout, "outside pkg:renamed (unleased)\n")
        self.git("checkout", "-q", self.base)
        tip = self.git("rev-parse", "HEAD@{1}").strip()
        self.assertEqual(self.check(tip=tip, code=1).stdout, "outside pkg:renamed (unleased)\n")

    def test_new_docs_and_invalid_subjects_owners_and_branches(self):
        self.run_lease("take", "s/a", "wave", "doc:skein/docs/design/new.md", F)
        for subject in ("pkg:missing", "doc:skein/docs/design/plan.status.md",
                        "doc:skein/docs/other/no.md", "doc:temper/docs/design/new.md",
                        "doc:skein/docs/design/has space.md", "doc:skein/docs/design/new.txt", "unknown"):
            with self.subTest(subject=subject):
                result = self.run_lease("take", "s/a", "wave", subject, code=2)
                self.assertIn(subject, result.stderr)
        for owner in ("lead/a", "s/", "s/-a", "s/Upper", "s/a/b", "s/a\n"):
            with self.subTest(owner=owner):
                self.run_lease("take", owner, "wave", A, code=2)
        for branch in ("bad..branch", "bad branch", "-bad", "HEAD", ""):
            self.run_lease("lend", "s/a", F, "--to", branch, code=2)
        self.run_lease("release", "s/a", code=2)
        self.run_lease("release", "s/a", A, "--all", code=2)

    def test_list_filter_text_and_permissions(self):
        self.run_lease("take", "s/a", "wave", A, D)
        self.run_lease("take", "s/b", "other", B)
        self.run_lease("lend", "s/a", D, "--to", "abc-jig/fix-x")
        self.run_lease("want", "s/b", "next", D)
        self.run_lease("want", "s/c", "later", D)
        self.assertEqual(len(self.rows("--owner", "s/a")), 2)
        output = self.run_lease("list", "--owner", "s/a").stdout
        self.assertIn("lends=abc-jig/fix-x waiters=s/b,s/c", output)
        self.assertIn("since=", output)
        self.assertIn("age=", output)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        for path in self.state.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertTrue((self.state / quote(D, safe="")).exists())
        self.assertEqual(self.record(D)["since"][-6:], "+00:00")
        self.run_lease("release", "s/a", D)
        self.assertIn(f"{D} free", self.run_lease("list").stdout)

    def test_two_concurrent_takes_leave_one_holder(self):
        # Repeat with a fresh directory so creation and lock acquisition race too.
        for iteration in range(5):
            with self.subTest(iteration=iteration):
                processes = [subprocess.Popen(self.command("take", owner, "race", A), env=self.env,
                                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                             for owner in ("s/a", "s/b")]
                for process in processes:
                    output, errors = process.communicate(timeout=20)
                    self.assertIn(process.returncode, (0, 1), output + errors)
                self.assertEqual(sorted(p.returncode for p in processes), [0, 1])
                self.assertEqual(len(self.rows()), 1)
                self.run_lease("release", self.record()["owner"], A)

    def test_record_permissions_do_not_depend_on_umask(self):
        result = subprocess.run(self.command("take", "s/a", "wave", A), env=self.env,
                                capture_output=True, text=True, umask=0o777)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.record()["owner"], "s/a")
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        for path in self.state.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main(verbosity=2)
