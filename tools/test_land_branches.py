"""Branch cleanup after a successful push, including a deletion handshake race."""
import shutil
import unittest
import test_land as fixture


class BranchLifecycleTests(fixture.LandFixture):
    def test_keep_branch_retains_local_but_deletes_matching_remote(self):
        self.git('push', 'origin', 'HEAD:feature')
        self.land('--local', '--keep-branch')
        self.assertEqual(self.git('branch', '--show-current'), 'feature')
        self.assertEqual(self.git('ls-remote', '--heads', 'origin', 'refs/heads/feature'), '')

    def test_remote_branch_moved_is_preserved(self):
        self.git('push', 'origin', 'HEAD:feature')
        other = self.home / 'upstream'
        self.command('git', '-C', other, 'fetch', 'origin', 'feature')
        self.command('git', '-C', other, 'switch', '-c', 'feature', 'FETCH_HEAD')
        fixture.put(other / 'other', 'new branch tip')
        for args in [('add', '.'), ('commit', '-qm', 'moved branch'), ('push', 'origin', 'feature')]:
            self.command('git', '-C', other, *args)
        moved = self.command('git', '-C', other, 'rev-parse', 'HEAD')
        self.land('--local')
        self.assertIn('moved; keeping remote branch',self.last_result.stderr)
        self.assertEqual(self.git('ls-remote', '--heads', 'origin', 'refs/heads/feature').split()[0], moved)
        self.assertNotIn('feature', self.git('branch', '--format=%(refname:short)'))

    def test_branch_move_during_delete_handshake_is_preserved(self):
        self.git('push', 'origin', 'HEAD:feature')
        other = self.home / 'upstream'
        self.command('git', '-C', other, 'fetch', 'origin', 'feature')
        self.command('git', '-C', other, 'switch', '-c', 'feature', 'FETCH_HEAD')
        fixture.put(other / 'other', 'later tip')
        self.command('git', '-C', other, 'add', '.')
        self.command('git', '-C', other, 'commit', '-qm', 'concurrent branch update')
        moved = self.command('git', '-C', other, 'rev-parse', 'HEAD')
        # Make the new object reachable in the fixture bare remote, but keep
        # feature unchanged until the real delete command reads advertised refs.
        self.command('git', '-C', other, 'push', 'origin', 'HEAD:other')
        real = shutil.which('git')
        wrapper = ("#!/usr/bin/env python3\nimport os,subprocess,sys\n" +
                   "real=" + repr(real) + "\n" +
                   "if '--delete' in sys.argv:\n" +
                   " subprocess.run([real,'--git-dir'," + repr(str(self.origin)) +
                   ", 'update-ref','refs/heads/feature'," + repr(moved) + "],check=True)\n" +
                   "os.execv(real,[real,*sys.argv[1:]])\n")
        fixture.put(self.bin / 'git', wrapper, True)
        self.land('--local')
        self.assertIn('remote branch moved; refusing deletion', self.last_result.stderr)
        self.assertEqual(self.git('ls-remote', '--heads', 'origin', 'refs/heads/feature').split()[0], moved)

    def test_published_pre_rebase_tip_can_be_deleted_after_landing(self):
        self.git('push', 'origin', 'HEAD:feature')
        other = self.home / 'upstream'
        fixture.put(other / 'b/upstream', 'upstream first')
        for args in [('add', '.'), ('commit', '-qm', 'upstream'), ('push', 'origin', 'main')]:
            self.command('git', '-C', other, *args)
        before = self.git('rev-parse', 'HEAD')
        self.land('--local')
        self.assertNotEqual(self.git('rev-parse', 'HEAD'), before)
        self.assertEqual(self.git('ls-remote', '--heads', 'origin', 'refs/heads/feature'), '')
        self.assertNotIn('feature', self.git('branch', '--format=%(refname:short)'))


if __name__ == "__main__":
    unittest.main()
