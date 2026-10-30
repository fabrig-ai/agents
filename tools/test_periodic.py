"""Deployed archives run pinned Git history; owner notices use private services."""
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


def put(path, text, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    sibling = path.with_name(path.name + '.new')
    sibling.write_text(text)
    sibling.chmod(mode)
    sibling.replace(path)


CHECK = '''#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
root=Path.cwd()
sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
assert subprocess.check_output(['git','show','HEAD~1:historical'],text=True)=='history'
assert subprocess.check_output(['git','archive','HEAD~1'])
tier=sys.argv[sys.argv.index('--tier')+1]
with (Path.home()/'runs').open('a') as stream: stream.write(json.dumps([tier,sha,str(root)])+'\\n')
rows=json.loads(os.environ.get('PERIODIC_ROWS','[]'))
Path(sys.argv[sys.argv.index('--json')+1]).write_text(json.dumps(dict(files=rows,reasons=[])))
'''


class PeriodicSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='periodic-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        (self.home / 'tmp').mkdir()
        self.source = self.home / 'src/fabrig/agents'
        self.source.mkdir(parents=True)
        self.env = dict(os.environ, HOME=str(self.home), AGENTS_PERIODIC='1',
                        GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1',
                        GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid',
                        GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid',
                        PATH=str(self.home / 'bin') + ':' + os.environ['PATH'], TMPDIR=str(self.home / 'tmp'))
        put(self.home / 'bin/post', '#!/bin/sh\nprintf "%s\\n" "$*" >> "$HOME/mail"\ncat "$6" >> "$HOME/mail"\n', 0o755)
        put(self.source / 'historical', 'history')
        self.git('init', '-b', 'main')
        self.git('add', '.')
        self.git('commit', '-qm', 'history')
        put(self.source / 'tools/periodic', (ROOT / 'tools/periodic').read_text(), 0o755)
        put(self.source / 'tools/check.sh', CHECK, 0o755)
        self.git('add', '.')
        self.git('commit', '-qm', 'release')
        self.sha = self.git('rev-parse', 'HEAD')
        self.release = self.home / 'src/fabrig/releases' / ('agents-' + self.sha)
        self.release.mkdir(parents=True)
        archive = subprocess.check_output(['git', 'archive', self.sha], cwd=self.source, env=self.env)
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
            stream.extractall(self.release, filter='data')
        put(self.release / '.fleet-release.json', json.dumps(dict(sha=self.sha, origin=str(self.source))))
        self.current = self.home / 'src/fabrig/current'
        self.current.symlink_to(self.release)
        # Fleet may move its clone after the archive was deployed.
        put(self.source / 'later', 'later')
        self.git('add', '.')
        self.git('commit', '-qm', 'later')

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.source, env=self.env,
                                       stderr=subprocess.DEVNULL, text=True).strip()

    def run_periodic(self, expected):
        result = subprocess.run(['python3', '-I', '-B', str(self.current / 'tools/periodic')],
                                cwd=self.home, env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def assert_setup_notice_and_cleanup(self):
        self.run_periodic(1)
        self.assertTrue((self.home / 'mail').is_file(), 'snapshot setup failure must notify ops')
        mail = (self.home / 'mail').read_text()
        self.assertEqual(mail.count('ops@hel8'), 1)
        self.assertIn('snapshot setup failed', mail)
        self.assertFalse((self.home / 'runs').exists())
        self.assertFalse(list((self.home / 'tmp').iterdir()))
        if (self.home / 'clone-path').exists():
            self.assertFalse(Path((self.home / 'clone-path').read_text()).exists())

    def trace_clone(self, fail=False):
        real = shutil.which('git')
        script = ("#!/usr/bin/env python3\nimport os,sys\nfrom pathlib import Path\n" +
                  "if 'clone' in sys.argv:\n" +
                  " path=Path(sys.argv[-1]); (Path.home()/'clone-path').write_text(str(path))\n" +
                  (" path.mkdir(); (path/'partial').touch(); sys.exit(23)\n" if fail else '') +
                  "os.execv(" + repr(real) + ",[" + repr(real) + ",*sys.argv[1:]])\n")
        put(self.home / 'bin/git', script, 0o755)

    def test_missing_release_sha_field_notifies_ops_and_cleans_snapshot(self):
        put(self.release / '.fleet-release.json', '{}')
        self.assert_setup_notice_and_cleanup()

    def test_unavailable_release_sha_notifies_ops_and_cleans_partial_snapshot(self):
        put(self.release / '.fleet-release.json', json.dumps(dict(sha='0' * 40)))
        self.trace_clone()
        self.assert_setup_notice_and_cleanup()

    def test_clone_failure_notifies_ops_and_cleans_partial_snapshot(self):
        self.trace_clone(fail=True)
        self.assert_setup_notice_and_cleanup()

    def test_deployed_archive_runs_both_tiers_with_pinned_history(self):
        self.assertFalse((self.release / '.git').exists())
        source_head = self.git('rev-parse', 'HEAD')
        self.run_periodic(0)
        runs = [json.loads(line) for line in (self.home / 'runs').read_text().splitlines()]
        self.assertEqual([row[:2] for row in runs], [['periodic', self.sha], ['gate', self.sha]])
        for _, _, directory in runs:
            self.assertNotEqual(Path(directory), self.release)
            self.assertNotEqual(Path(directory), self.source)
            self.assertFalse(Path(directory).exists())
        self.assertEqual(self.git('rev-parse', 'HEAD'), source_head)
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_wall_only_overrun_notifies_its_owner_alone_and_with_another_notice(self):
        wall = dict(file='wall.py', owner='s/wall', failed=False, over=False, starved=False,
                    wall_s=16, wall_limit_s=15)
        other = dict(file='other.py', owner='s/other', failed=True, over=False, starved=False,
                     wall_s=1, wall_limit_s=15)
        for rows in ([wall], [wall, other]):
            with self.subTest(rows=len(rows)):
                (self.home / 'mail').unlink(missing_ok=True)
                self.env['PERIODIC_ROWS'] = json.dumps(rows)
                self.run_periodic(1)
                mail = (self.home / 'mail').read_text()
                self.assertEqual(mail.count('s/wall@hel8'), 2)
                self.assertEqual(mail.count('s/other@hel8'), 2 if len(rows) == 2 else 0)
                self.assertNotIn('ops@hel8', mail)


if __name__ == '__main__':
    unittest.main()
