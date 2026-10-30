"""Queue landing rules against disposable git remotes (docs/design/fab.md, 6 and 8)."""

import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fab import gate, log, queue
from fab.sh import Failed, Result, run
from fab.tests.support import FakeRunner, GIT_ENV, git, git_pair, tmp_home


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    sibling = path.with_name(path.name + '.new')
    sibling.write_text(content)
    sibling.replace(path)


class CoreTest(unittest.TestCase):
    def test_bisect_lands_in_order_and_does_not_recheck_green_groups(self):
        branches = [queue.Branch(str(i), str(i), i) for i in range(4)]
        calls, landed = [], []

        def check(group):
            calls.append(([b.name for b in group], list(landed)))
            if branches[1] in group:
                return False
            landed.extend(b.name for b in group)
            return True

        self.assertEqual(queue.bisect(branches, check), ([branches[0], *branches[2:]], [branches[1]]))
        self.assertEqual(calls, [(['0', '1', '2', '3'], []), (['0', '1'], []), (['0'], []),
                                 (['1'], ['0']), (['2', '3'], ['0'])])
        self.assertEqual(queue.bisect([], lambda group: self.fail('empty checked')), ([], []))
        self.assertEqual(queue.bisect(branches, lambda group: True), (branches, []))

    def test_candidates_only_ready_task_refs_oldest_then_name(self):
        prefix = 'refs/remotes/origin/'
        fake = FakeRunner().on(['git', 'for-each-ref'], Result(0, '\n'.join([
            prefix + 'ready/draft/new new 30', prefix + 'ready/draft/z z 10',
            prefix + 'ready/draft/a a 10', prefix + 'ready/draft/tried same 1',
            prefix + 'ready/orphan orphan 1', prefix + 'topic/unready other 0']) + '\n'))
        self.assertEqual(queue.candidates(Path('/repo'), {'draft/tried': 'same'}, sh=fake), [
            queue.Branch('draft/a', 'a', 10), queue.Branch('draft/z', 'z', 10),
            queue.Branch('draft/new', 'new', 30)])


class GitTest(unittest.TestCase):
    def setUp(self):
        context = tmp_home()
        self.home = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.origin, self.repo = git_pair(self.home)
        self.base = git(self.repo, 'rev-parse', 'HEAD')
        self.data = self.home / 'runtime'
        self.check_calls, self.loads = [], []
        patcher = patch('fab.gate.check_steps', side_effect=self.check_steps)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.q = queue.Queue(self.repo, home=self.data, sh=self.runner, load=self.load)

    def runner(self, argv, **kwargs):
        return run(argv, env={**os.environ, **GIT_ENV}, **kwargs)

    def load(self, repo):
        self.loads.append(repo)
        return {'workspace_root': str(repo), 'workspace_members': ['pkg'],
                'packages': [{'id': 'pkg', 'name': 'pkg', 'manifest_path': str(repo / 'pkg/Cargo.toml')}],
                'resolve': {'nodes': [{'id': 'pkg', 'dependencies': []}]}}

    def check_steps(self, repo, selected, paths, meta, *, lane):
        self.assertEqual(lane, 'gate')
        self.check_calls.append((selected, paths, meta))
        bad = repo / 'bad.txt'
        return [gate.Step('check', ('false' if bad.exists() else 'true',), str(repo))]

    def commit(self, files):
        for name, content in files.items():
            write(self.repo / name, content)
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'Fixture change')
        return git(self.repo, 'rev-parse', 'HEAD')

    def branch(self, name, files, *, base=None, timestamp=None, publish=True):
        git(self.repo, 'switch', '-q', '--detach', base or self.base)
        with patch.dict(os.environ, {} if timestamp is None else {
                'GIT_AUTHOR_DATE': f'{timestamp} +0000', 'GIT_COMMITTER_DATE': f'{timestamp} +0000'}):
            tip = self.commit(files)
        if publish:
            git(self.repo, 'push', '-q', 'origin', f'{tip}:refs/heads/{name}', f'{tip}:refs/heads/ready/{name}')
        return queue.Branch(name, tip, timestamp or 0)

    def records(self, ev=None):
        return [entry for entry in log.read(self.data / 'queue.jsonl') if ev is None or entry['ev'] == ev]

    def assert_clean(self):
        status = git(self.repo, 'status', '--porcelain=v2', '--branch').splitlines()
        self.assertEqual(len(status), 2)
        self.assertEqual(status[1], '# branch.head (detached)')

    def assert_landed(self, branches):
        main = git(self.origin, 'rev-parse', 'main')
        refs = git(self.origin, 'for-each-ref', '--format=%(refname)', 'refs/heads').splitlines()
        ancestors = set(git(self.origin, 'rev-list', main).splitlines())
        for branch in branches:
            self.assertIn(branch.tip, ancestors)
            self.assertNotIn('refs/heads/' + branch.name, refs)
            self.assertNotIn('refs/heads/ready/' + branch.name, refs)
        self.assertEqual({entry['tip'] for entry in self.records('landed')}, {b.tip for b in branches})
        self.assert_clean()

    def test_candidates_and_green_batch_of_two(self):
        a = self.branch('draft/a', {'a.txt': 'a'}, timestamp=1700000000)
        b = self.branch('draft/b', {'b.txt': 'b'}, timestamp=1600000000)
        git(self.repo, 'push', '-q', 'origin', f'{a.tip}:refs/heads/unready',
            f'{a.tip}:refs/heads/ready/orphan')
        git(self.repo, 'fetch', '-q', 'origin')
        self.assertEqual(queue.candidates(self.repo, {}, sh=self.runner), [b, a])
        self.assertEqual(queue.candidates(self.repo, {b.name: b.tip, a.name: 'old'}, sh=self.runner), [a])
        branches = [b, a]
        self.assertTrue(self.q.cycle())
        self.assert_landed(branches)
        self.assertFalse(self.q.cycle())
        batch = self.records('batch')[0]
        self.assertEqual((batch['outcome'], batch['parent'], batch['selection']), ('green', self.base, 'full'))
        self.assertEqual(batch['branches'], [b.name, a.name])
        self.assertTrue(batch['steps'][0].startswith('check:0:'))
        self.assertRegex(Path(batch['log']).name, r'^\d{8}T\d{6}Z\.log$')
        self.assertIn('[check] true', Path(batch['log']).read_text())
        restored = queue.Queue(self.repo, home=self.data, sh=self.runner, load=self.load)
        self.assertEqual(restored.state['tried'], {b.name: b.tip for b in branches})
        self.assertEqual(len(self.loads), 1)

    def test_conflict_is_rejected_and_other_branches_land(self):
        a = self.branch('draft/a', {'README.md': 'a\n'})
        b = self.branch('draft/b', {'README.md': 'b\n'})
        c = self.branch('draft/c', {'c.txt': 'c'})
        self.q.cycle()
        self.assert_landed([a, c])
        rejection, = self.records('rejected')
        self.assertEqual((rejection['branch'], rejection['tip'], rejection['step']), (b.name, b.tip, 'merge'))
        self.assertEqual(self.q.state['tried'][b.name], b.tip)
        self.assertEqual(self.records('batch')[0]['outcome'], 'conflict')
        self.assertIn('CONFLICT', Path(rejection['log']).read_text())

    def test_red_batch_bisects_and_lands_both_good_tips(self):
        # Five real merge/check/push attempts verify that later halves use the newly landed main.
        a = self.branch('draft/a', {'a.txt': 'a'})
        b = self.branch('draft/b', {'bad.txt': 'bad'})
        c = self.branch('draft/c', {'c.txt': 'c'})
        self.q.cycle()
        self.assert_landed([a, c])
        self.assertEqual([(entry['branch'], entry['step']) for entry in self.records('rejected')],
                         [(b.name, 'check')])
        self.assertEqual(self.q.state['tried'][b.name], b.tip)
        self.assertFalse(self.q.cycle())
        batches = self.records('batch')
        self.assertEqual([entry['outcome'] for entry in batches], ['red', 'green', 'red', 'red', 'green'])
        # The final good branch was checked on the main containing the first good branch.
        git(self.origin, 'merge-base', '--is-ancestor', a.tip, batches[-1]['parent'])

    def test_main_movement_refuses_push_without_trying_tips_then_retries(self):
        branch = self.branch('draft/a', {'a.txt': 'a'})
        moved = []

        def runner(argv, **kwargs):
            if argv[:2] == ['git', 'push'] and any('refs/heads/main:' in arg for arg in argv) and not moved:
                tree = git(self.origin, 'rev-parse', 'main^{tree}')
                newer = git(self.origin, 'commit-tree', tree, '-p', self.base, '-m', 'Concurrent main')
                git(self.origin, 'update-ref', 'refs/heads/main', newer)
                moved.append(newer)
            return self.runner(argv, **kwargs)

        self.q.sh = runner
        with self.assertRaises(Failed):
            self.q.cycle()
        self.assertEqual(self.q.state['tried'], {})
        self.assertFalse((self.data / 'queue-state.json').exists())
        self.assertEqual(self.records('batch')[-1]['outcome'], 'error')
        self.assertEqual(self.records('landed'), [])
        self.assertEqual(self.records('rejected'), [])
        self.assertTrue(self.q.cycle())
        self.assert_landed([branch])
        git(self.origin, 'merge-base', '--is-ancestor', moved[0], 'main')

    def test_contained_tip_is_retired_without_checks(self):
        branch = self.branch('draft/a', {'a.txt': 'a'})
        git(self.repo, 'push', '-q', 'origin', f'{branch.tip}:main')
        self.q.cycle()
        self.assert_landed([branch])
        self.assertEqual(self.check_calls, [])
        self.assertEqual(self.q.state['tried'], {branch.name: branch.tip})

    def test_cleanup_lease_preserves_replacement_task_tip(self):
        branch = self.branch('draft/a', {'a.txt': 'a'})
        tree = git(self.origin, 'rev-parse', branch.tip + '^{tree}')
        replacement = git(self.origin, 'commit-tree', tree, '-p', branch.tip, '-m', 'New task tip')
        git(self.origin, 'update-ref', 'refs/heads/' + branch.name, replacement)
        self.q.cycle()
        self.assertEqual(git(self.origin, 'rev-parse', 'refs/heads/' + branch.name), replacement)
        self.assertEqual(len(self.records('landed')), 1)
        self.assertTrue(any(entry['outcome'] == 'error' for entry in self.records('batch')))
        self.assert_clean()

    def test_build_batch_ratchet_conflict_recounts_or_rejects(self):
        script = ('from pathlib import Path\n'
                  'import sys\n'
                  'p = Path("scripts/old-forms.txt")\n'
                  'if Path("raise-count").exists():\n'
                  '    print("count raised")\n'
                  '    sys.exit(1)\n'
                  'sibling = p.with_name(p.name + ".new")\n'
                  'sibling.write_text("7\\n")\n'
                  'sibling.replace(p)\n')
        self.base = self.commit({'jig/scripts/old-forms.txt': '10\n', 'jig/scripts/old_forms.py': script})
        a = self.branch('draft/a', {'jig/scripts/old-forms.txt': '9\n'}, publish=False)
        b = self.branch('draft/b', {'jig/scripts/old-forms.txt': '8\n'}, publish=False)
        c = self.branch('draft/c', {'jig/scripts/old-forms.txt': '6\n', 'jig/raise-count': 'yes'}, publish=False)
        merged, conflicts = queue.build_batch(self.repo, [a, b, c], self.base, sh=self.runner)
        self.assertEqual(merged, [a, b])
        self.assertEqual(conflicts, [(c, 'count raised\n')])
        self.assertEqual((self.repo / 'jig/scripts/old-forms.txt').read_text(), '7\n')
        self.assertFalse((self.repo / 'jig/raise-count').exists())
        self.assert_clean()


class ShellTest(unittest.TestCase):
    def setUp(self):
        context = tmp_home()
        self.home = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)

    def test_selected_metadata_periodic_full_and_ratchet_commit(self):
        repo = self.home / 'clone'
        branch = queue.Branch('draft/a', 'tip', 0)
        baseline = 'jig/scripts/old-forms.txt'
        fake = FakeRunner().on(['git', 'rev-parse'], lambda call: Result(
            0, 'tip\ntip\n' if len(call.argv) == 4 else 'parent\n')).on(
                ['git', 'diff', '--name-only', '-z'], Result(0, baseline + '\0'))
        meta = {'workspace_root': str(repo), 'workspace_members': ['pkg'],
                'packages': [{'id': 'pkg', 'name': 'pkg', 'manifest_path': str(repo / 'pkg/Cargo.toml')}],
                'resolve': {'nodes': [{'id': 'pkg', 'dependencies': []}]}}
        loads, selections = [], []

        def load(path):
            loads.append(path)
            return meta

        def checks(path, selected, paths, data, *, lane):
            selections.append(selected)
            self.assertEqual(lane, 'gate')
            if isinstance(selected, set):
                self.assertEqual(data, meta)
            self.assertIn(['git', 'commit', '-m', 'Lower old-form baselines'], fake.argvs())
            return [gate.Step('check', ('true',), str(repo))]

        q = queue.Queue(repo, full_every=2, sh=fake, load=load)
        with patch('fab.queue.build_batch', return_value=([branch], [])), \
                patch('fab.gate.changed_paths', return_value=['pkg/src/lib.rs']), \
                patch('fab.gate.ratchet_steps', return_value=[gate.Step('ratchet:jig', ('true',), str(repo))]), \
                patch('fab.gate.check_steps', side_effect=checks):
            self.assertTrue(q.attempt([branch]))
            self.assertEqual(loads, [repo])
            self.assertTrue(q.attempt([branch]))
        self.assertEqual(selections, [{'pkg'}, 'full'])
        self.assertEqual(loads, [repo])
        self.assertEqual(q.state['batches_since_full'], 0)
        steps = next(entry['steps'] for entry in log.read(q.log_path) if entry['ev'] == 'batch')
        self.assertTrue(steps[0].startswith('ratchet:jig:0:'))
        self.assertTrue(steps[1].startswith('check:0:'))

    def test_red_full_batch_keeps_full_checks_during_bisection(self):
        branches = [queue.Branch('draft/' + name, name, 0) for name in ('a', 'bad', 'c')]
        fake = FakeRunner().on(['git', 'rev-parse'], Result(0, 'parent\n')).on(['false'], Result(1))
        q = queue.Queue(self.home / 'clone', sh=fake, full_every=3)
        q.state['batches_since_full'] = 2
        group, selections = [], []

        def build(repo, batch, base, *, sh):
            group[:] = batch
            return list(batch), []

        def checks(repo, selected, paths, meta, *, lane):
            selections.append(selected)
            return [gate.Step('check', ('false' if branches[1] in group else 'true',), str(repo))]

        with patch('fab.queue.candidates', return_value=branches), \
                patch('fab.queue.build_batch', side_effect=build), \
                patch('fab.gate.changed_paths', return_value=['README.md']), \
                patch('fab.gate.check_steps', side_effect=checks):
            self.assertTrue(q.cycle())
        self.assertEqual(selections, ['full'] * 5)
        self.assertEqual(q.state['tried']['draft/bad'], 'bad')

    def test_attempt_sweeps_old_build_output_after_green_and_red_checks(self):
        started_ns = 1_700_000_000_000_000_000
        branch = queue.Branch('draft/task', 'tip', 0)
        for green in (True, False):
            with self.subTest(green=green):
                repo = self.home / str(green)
                incremental = repo / 'target/debug/incremental'
                old = repo / 'target/debug/deps/old-test'
                fresh = old.with_name('fresh-test')
                write(incremental / 'cache', 'incremental data')
                write(old, 'old executable')
                old.chmod(0o755)
                os.utime(old, ns=(started_ns - 1, started_ns - 1))
                expected_freed = sum(path.stat().st_blocks * 512 for path in
                                     (incremental, incremental / 'cache', old))
                fake = FakeRunner().on(['git', 'rev-parse'], Result(0, 'parent\n')).on(
                    ['check'], Result(0 if green else 1))
                q = queue.Queue(repo, home=self.home / ('runtime-' + str(green)), sh=fake)

                def checks(repo, selected, paths, meta, *, lane):
                    write(fresh, 'fresh executable')
                    fresh.chmod(0o755)
                    os.utime(fresh, ns=(started_ns, started_ns))
                    return [gate.Step('check', ('check',), str(repo))]

                with patch('fab.queue.time.time_ns', return_value=started_ns), \
                        patch('fab.queue.build_batch', return_value=([branch], [])), \
                        patch('fab.gate.changed_paths', return_value=['README.md']), \
                        patch('fab.gate.check_steps', side_effect=checks):
                    self.assertEqual(q.attempt([branch]), green)
                self.assertFalse(incremental.exists())
                self.assertFalse(old.exists())
                self.assertEqual(fresh.read_text(), 'fresh executable')
                batch, = [entry for entry in log.read(q.log_path) if entry['ev'] == 'batch']
                self.assertEqual(batch['outcome'], 'green' if green else 'red')
                self.assertEqual(batch['freed'], expected_freed)
                self.assertNotIn('sweep_error', batch)

    def test_sweep_failure_preserves_attempt_result_and_error(self):
        branch = queue.Branch('draft/task', 'tip', 0)
        for operation in ('sweep_plan', 'remove'):
            for fails in (False, True):
                with self.subTest(operation=operation, fails=fails):
                    fake = FakeRunner().on(['git', 'rev-parse'], Result(0, 'parent\n'))
                    if fails:
                        fake.on(['git', 'status'], Result(0, '?? untracked\n'))
                    q = queue.Queue(self.home / 'clone', sh=fake)
                    with patch('fab.queue.build_batch', return_value=([], [])), \
                            patch('fab.queue.slots.' + operation, side_effect=OSError('sweep refused')):
                        if fails:
                            with self.assertRaisesRegex(RuntimeError, 'uncommitted or untracked'):
                                q.attempt([branch])
                        else:
                            self.assertTrue(q.attempt([branch]))
                    batch = log.read(q.log_path)[-1]
                    self.assertEqual(batch['outcome'], 'error' if fails else 'green')
                    self.assertEqual(batch['sweep_error'], 'sweep refused')
                    self.assertNotIn('freed', batch)

    def test_failed_cleanup_keeps_contained_tip_eligible_for_retry(self):
        branch = queue.Branch('draft/task', 'tip', 0)
        fake = FakeRunner().on(['git', 'rev-parse'], Result(0, 'parent\n')).on(
            ['git', 'push'], Result(1, err='remote unavailable'))
        q = queue.Queue(self.home / 'clone', sh=fake)
        with patch('fab.queue.build_batch', return_value=([], [])):
            self.assertTrue(q.attempt([branch]))
        self.assertEqual(q.state['tried'], {})
        batch = next(entry for entry in log.read(q.log_path) if entry['ev'] == 'batch')
        self.assertEqual(batch['outcome'], 'error')
        self.assertIn('remote unavailable', Path(batch['log']).read_text())
        q.sh = FakeRunner().on(['git', 'rev-parse'], Result(0, 'parent\n'))
        with patch('fab.queue.build_batch', return_value=([], [])):
            self.assertTrue(q.attempt([branch]))
        self.assertEqual(q.state['tried'], {branch.name: branch.tip})

    def test_dirty_checkout_refused_without_discarding_work(self):
        fake = FakeRunner().on(['git', 'status'], Result(0, '?? untracked\n'))
        q = queue.Queue(self.home / 'clone', sh=fake)
        with self.assertRaisesRegex(RuntimeError, 'uncommitted or untracked'):
            q.attempt([queue.Branch('draft/task', 'tip', 0)])
        self.assertEqual(q.state['tried'], {})
        self.assertEqual(fake.argvs(), [['git', 'status', '--porcelain']])

    def test_run_stops_and_sleeps_only_on_idle_or_errors(self):
        stop = self.home / 'stop'
        q = queue.Queue(self.home / 'clone', sh=FakeRunner())
        sleeps = []
        outcomes = iter([True, False, RuntimeError('fetch refused'), True])
        calls = []

        def cycle():
            outcome = next(outcomes)
            calls.append(outcome)
            if len(calls) == 4:
                write(stop, '')
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with patch.object(q, 'cycle', side_effect=cycle):
            q.run(stop=stop, idle=0.25, sleep=sleeps.append)
        self.assertEqual(sleeps, [0.25, 0.25])
        self.assertEqual(len(calls), 4)
        self.assertEqual(log.read(q.log_path)[0]['error'], 'fetch refused')
        with patch.object(q, 'cycle', side_effect=AssertionError('stopped')):
            q.run(stop=stop, sleep=sleeps.append)

    def test_log_since_includes_boundary_and_skips_torn_line(self):
        path = log.home() / 'queue.jsonl'
        for ts in ('2026-10-29T00:00:00.000Z', '2026-10-30T00:00:00.000Z', '2026-10-31T00:00:00.000Z'):
            log.append('batch', path=path, ts=ts, outcome='green')
        write(path, path.read_text() + '{torn')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(queue.main(['log', '--since', '2026-10-30T00:00:00.000Z']), 0)
        self.assertEqual([json.loads(line)['ts'] for line in output.getvalue().splitlines()],
                         ['2026-10-30T00:00:00.000Z', '2026-10-31T00:00:00.000Z'])

    def test_cli_plan_once_run_and_defaults(self):
        branch = queue.Branch('draft/task', 'tip', 1)
        q = queue.Queue(self.home / 'clone', sh=FakeRunner())
        with patch('fab.queue.Queue', return_value=q) as constructor, \
                patch('fab.queue.candidates', return_value=[branch]), \
                patch.object(q, 'cycle', return_value=True) as cycle, \
                patch.object(q, 'run') as run_loop:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(queue.main(['plan', '--repo', '/clone', '--batch', '2']), 0)
            self.assertEqual(output.getvalue(), 'draft/task\n')
            constructor.assert_called_with(Path('/clone'), batch=2)
            self.assertEqual(queue.main(['once']), 0)
            cycle.assert_called_once_with()
            constructor.assert_called_with(log.home() / 'repos/fabrig', batch=8)
            self.assertEqual(queue.main(['run']), 0)
            run_loop.assert_called_once_with(stop=q.home / 'queue.stop')
            cycle.side_effect = RuntimeError('unavailable')
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(queue.main(['once']), 1)
            self.assertIn('unavailable', errors.getvalue())


if __name__ == '__main__':
    unittest.main()
