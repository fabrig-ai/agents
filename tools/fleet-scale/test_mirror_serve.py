"""Exercise the actual forced command and Git wire protocol without sshd."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

SERVE = Path(__file__).with_name("mirror-serve")


class MirrorServeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.env = dict(os.environ, HOME=str(self.home), GIT_CONFIG_GLOBAL="/dev/null",
                        GIT_CONFIG_SYSTEM="/dev/null")
        self.mirrors = self.home / "src/fabrig/mirror"
        self.mirrors.mkdir(parents=True)
        for name in ("agents", "fabrig"):
            self.git("init", "--bare", str(self.mirrors / (name + ".git")))
        self.outside = self.home / "outside.git"
        self.git("init", "--bare", str(self.outside))

    def git(self, *args):
        return subprocess.run(["git", *args], env=self.env, check=True, capture_output=True)

    def serve(self, command):
        return subprocess.run([str(SERVE)], env=dict(self.env, SSH_ORIGINAL_COMMAND=command),
                              input=b"", capture_output=True)

    def test_refusals(self):
        mirror = str(self.mirrors / "agents.git")
        link = self.home / "link.git"
        link.symlink_to(mirror)
        cases = [
            "", "sh", "git-receive-pack " + shlex.quote(mirror),
            "git-upload-archive " + shlex.quote(mirror),
            "git-upload-pack " + shlex.quote(str(self.outside)),
            "git-upload-pack " + shlex.quote(str(link)),
            "git-upload-pack '~/src/fabrig/mirror/../mirror/agents.git'",
            "git-upload-pack " + shlex.quote(mirror) + " extra",
            "git-upload-pack " + shlex.quote(mirror) + "; touch " + str(self.home / "injected"),
            "git-upload-pack '$(touch " + str(self.home / "injected") + ")'",
            "git-upload-pack " + shlex.quote(mirror) + "\ntouch " + str(self.home / "injected"),
            "git-upload-pack " + shlex.quote(mirror) + " | cat",
        ]
        for command in cases:
            with self.subTest(command=command):
                self.assertEqual(self.serve(command).returncode, 1)
        self.assertFalse((self.home / "injected").exists())

    def test_symlink_inside_mirror_path_refused(self):
        original = self.mirrors / "agents.git"
        moved = self.home / "moved.git"
        original.rename(moved)
        original.symlink_to(moved)
        self.assertEqual(self.serve("git-upload-pack '~/src/fabrig/mirror/agents.git'").returncode, 1)

    def test_real_fetch_both_mirrors_quoted_and_unquoted(self):
        working = self.home / "working"
        self.git("init", str(working))
        self.git("-C", str(working), "-c", "user.name=Fixture", "-c",
                 "user.email=fixture@example.invalid", "commit", "--allow-empty", "-m", "fixture")
        expected = self.git("-C", str(working), "rev-parse", "HEAD").stdout.strip()
        harness = self.home / "ssh-harness"
        # Git supplies target and original command as the last two arguments.
        harness.write_text("#!/usr/bin/env python3\nimport os,sys\n"
                           "os.environ['SSH_ORIGINAL_COMMAND']=sys.argv[-1]\n"
                           "os.execv(" + repr(str(SERVE)) + ",[" + repr(str(SERVE)) + "])\n")
        harness.chmod(0o755)
        env = dict(self.env, GIT_SSH_COMMAND=shlex.quote(str(harness)),
                   GIT_SSH_VARIANT="ssh")
        for name in ("agents", "fabrig"):
            self.git("-C", str(working), "push", str(self.mirrors / (name + ".git")), "HEAD:main")
            destination = self.home / ("fetched-" + name)
            self.git("init", str(destination))
            result = subprocess.run(["git", "-C", str(destination), "fetch",
                                     "ssh://fixture/~/src/fabrig/mirror/" + name + ".git",
                                     "main"], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.git("-C", str(destination), "rev-parse", "FETCH_HEAD").stdout.strip(), expected)
            # Empty stdin ends the protocol after advertisement; success here
            # specifically demonstrates acceptance without shell path quotes.
            result = self.serve("git-upload-pack " + str(self.mirrors / (name + ".git")))
            self.assertNotIn(b"request refused", result.stderr)


if __name__ == "__main__":
    unittest.main()
