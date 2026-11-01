"""Queue landing rules against disposable git remotes (docs/design/fab.md, 6 and 8)."""

import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fab import gate, log, queue, receipts, reds, wake
from fab.sh import Failed, Result, run
from fab.tests.landing_checks import MAIN, TIP, FakeNextest, alone, kept, receipt, receipt_text
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
        # Disposable repositories do not need git's automatic maintenance after pushes or merges.
        settings = patch.dict(os.environ, {'GIT_CONFIG_COUNT': '4',
                              'GIT_CONFIG_KEY_0': 'receive.autogc', 'GIT_CONFIG_VALUE_0': 'false',
                              'GIT_CONFIG_KEY_1': 'maintenance.auto', 'GIT_CONFIG_VALUE_1': 'false',
                              'GIT_CONFIG_KEY_2': 'gc.auto', 'GIT_CONFIG_VALUE_2': '0',
                              'GIT_CONFIG_KEY_3': 'core.fsync', 'GIT_CONFIG_VALUE_3': 'none'})
        settings.start()
        self.addCleanup(settings.stop)
        self.origin, self.repo = git_pair(self.home)
        self.base = git(self.repo, 'rev-parse', 'HEAD')
        self.data = self.home / 'runtime'
        self.check_calls, self.loads = [], []
        patcher = patch('fab.gate.check_steps', side_effect=self.check_steps)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.q = queue.Queue(self.repo, home=self.data, sh=self.runner, load=self.load)

    def runner(self, argv, **kwargs):
        # Fake checks write neither checkout files nor ratchet baselines; clean is asserted below.
        if (list(argv) in (['git', 'status', '--porcelain'], ['git', 'clean', '-fd']) or
                list(argv[:5]) == ['git', 'diff', '--name-only', '-z', '--']):
            return Result(0)
        if argv[0] in ('true', 'false'):
            return Result(0 if argv[0] == 'true' else 1)
        if argv[0] == 'short-of-disk':
            return Result(75, err='heavy: Infra: disk\n')
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
        command = 'short-of-disk' if (repo / 'disk.txt').exists() else 'false' if bad.exists() else 'true'
        return [gate.Step('fmt', ('true',), str(repo)),
                gate.Step('check', (command,), str(repo))]

    def commit(self, files):
        for name, content in files.items():
            write(self.repo / name, content)
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'Fixture change')
        return git(self.repo, 'rev-parse', 'HEAD')

    def branch(self, name, files, *, base=None, timestamp=None, publish=True):
        # Import fixture commits without checking out and staging each branch's files.
        stamp = timestamp or 1700000000
        stream = (f"commit refs/fixtures/{name}\nmark :1\n"
                  f"committer fab <fab@example.invalid> {stamp} +0000\n"
                  f"data 15\nFixture change\n\nfrom {base or self.base}\n")
        for path, content in files.items():
            stream += f"M 100644 inline {json.dumps(path)}\ndata {len(content.encode())}\n{content}\n"
        stream += "\nget-mark :1\ndone\n"
        tip = self.runner(['git', 'fast-import', '--quiet'], cwd=str(self.repo),
                          input=stream, check=True).out.strip()
        if publish:
            published = stream.replace("\nget-mark :1\ndone\n",
                f"\nreset refs/heads/{name}\nfrom :1\n\n"
                f"reset refs/heads/ready/{name}\nfrom :1\n\ndone\n")
            self.runner(['git', 'fast-import', '--quiet'], cwd=str(self.origin), input=published, check=True)
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

    def _nextest(self, result="pass"):
        fake = FakeNextest({None: [("pkg::wire", "round_trip", "fail")],
                            alone("pkg::wire", "round_trip"): [("pkg::wire", "round_trip", result)]},
                           fallback=self.runner)
        self.q.sh = fake
        patcher = patch('fab.gate.check_steps', return_value=[gate.Step(
            'default', ('heavy', '--gate', 'cargo', 'nextest', 'run', '-p', 'pkg', '--no-fail-fast'),
            str(self.repo))])
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def test_red_classes_across_group_bisection_limit_and_landing(self):
        # Eight real attempts verify deferred groups, confirmed reds, limits and later landing.
        branches = [self.branch(f'draft/{name}', {f'pkg/{name}.rs': name}) for name in 'abc']
        for branch in branches:
            kept(self.data, receipt(branch.tip, self.base))
        fake = self._nextest()
        with self.subTest(outcome='collateral group'):
            self._assert_collateral_group(fake)
        with self.subTest(outcome='confirmed red bisection'):
            self._assert_confirmed_group(fake, branches)
        self.q.batch = 1
        with self.subTest(outcome='tip limit'):
            self._assert_tip_limit(fake, branches[0])
        with self.subTest(outcome='no receipt'):
            self._assert_uncovered_red(fake, branches[0])
        with self.subTest(outcome='collateral then landed'):
            kept(self.data, receipt(branches[0].tip, git(self.origin, 'rev-parse', 'main')))
            self._assert_collateral_landing(fake, branches)

    def _assert_collateral_group(self, fake):
        self.assertTrue(self.q.cycle())
        self.assertEqual([entry['outcome'] for entry in self.records('batch')], ['collateral'])
        self.assertEqual(len(self.records('collateral')), 3)
        self.assertEqual((self.records('rejected'), self.q.state['tried']), ([], {}))
        self.assertEqual(len(fake.calls), 2)
        self.assert_clean()

    def _assert_confirmed_group(self, fake, branches):
        fake.results[alone('pkg::wire', 'round_trip')] = [('pkg::wire', 'round_trip', 'fail')]
        self.q.state['batches_since_full'] = self.q.full_every - 1
        original = self.q.attempt
        groups = []

        def attempt(group):
            green = original(group)
            groups.append(list(group))
            fake.results[alone('pkg::wire', 'round_trip')] = [('pkg::wire', 'round_trip', 'pass')]
            if len(groups) == 2:
                fake.results[None] = [('pkg::wire', 'round_trip', 'pass')]
            return green

        with patch.object(self.q, 'attempt', side_effect=attempt):
            self.q.cycle()
        batches = self.records('batch')[1:]
        self.assertEqual([entry['outcome'] for entry in batches], ['red', 'collateral', 'green'])
        self.assertEqual(batches[0]['stands'], 'pkg::wire round_trip failed alone')
        self.assertEqual([[branch.name for branch in group] for group in groups],
                         [[branch.name for branch in group] for group in
                          (branches, branches[:1], branches[1:])])
        self.assertEqual(self.q.state['tried'], {branch.name: branch.tip for branch in branches[1:]})
        self.assertEqual(self.q.state['collateral'], {
            branches[0].name: {'tip': branches[0].tip, 'count': reds.LIMIT}})
        self.assertTrue(self.q._force_full)
        fake.results[None] = [('pkg::wire', 'round_trip', 'fail')]

    def _assert_tip_limit(self, fake, branch):
        self.q.full_every = 1
        before = len(fake.calls)
        self.assertEqual(len([entry for entry in self.records('collateral')
                              if entry['branch'] == branch.name]), reds.LIMIT)
        self.assertTrue(self.q.cycle())
        self.assertEqual(self.q.last_outcome, 'red')
        self.assertEqual(self.q.state['tried'][branch.name], branch.tip)
        self.assertEqual(self.q.state['collateral'], {})
        self.assertEqual(len(fake.calls) - before, 1)
        self.assertNotIn('stands', self.records('batch')[-1])
        rejection = self.records('rejected')[-1]
        self.assertEqual((rejection['branch'], rejection['tip'], rejection['step']),
                         (branch.name, branch.tip, 'default'))
        self.assertTrue(self.q._force_full)

    def _assert_collateral_landing(self, fake, branches):
        branch = branches[0]
        self.q.state['tried'].pop(branch.name)
        tried = dict(self.q.state['tried'])
        rejected = len(self.records('rejected'))
        self.q.full_every = 5
        self.q.state['batches_since_full'] = self.q.full_every - 1
        self.assertTrue(self.q.cycle())
        self.assertEqual(self.q.last_outcome, 'collateral')
        batch = self.records('batch')[-1]
        collateral = self.records('collateral')[-1]
        self.assertEqual((batch['outcome'], batch['retried']), ('collateral', ['pkg::wire round_trip']))
        self.assertEqual((collateral['branch'], collateral['tip'], collateral['step'], collateral['tests']),
                         (branch.name, branch.tip, 'default', ['pkg::wire round_trip']))
        self.assertEqual(collateral['log'], batch['log'])
        self.assertEqual([step.rsplit(':', 2)[0] for step in batch['steps']], ['default', 'retry:default'])
        self.assertEqual((len(self.records('rejected')), self.q.state['tried']), (rejected, tried))
        self.assertFalse(self.q._force_full)
        restored = queue.Queue(self.repo, home=self.data, sh=fake, load=self.load)
        self.assertEqual(restored.state['collateral'], {branch.name: {'tip': branch.tip, 'count': 1}})
        before = len(fake.calls)
        self.assertTrue(restored.cycle())
        self.assertEqual((restored.last_outcome, restored.state['collateral']), ('green', {}))
        self.assertEqual(len(fake.calls), before)
        self.assert_landed(branches)
        self.q = restored

    def _assert_uncovered_red(self, fake, branch):
        self.q.state['tried'].pop(branch.name)
        receipts.path(self.data, branch.tip).unlink()
        before = len(fake.calls)
        self.q.cycle()
        batch = self.records('batch')[-1]
        self.assertEqual((batch['outcome'], batch['stands']), ('red', 'pkg::wire round_trip not prechecked'))
        self.assertEqual(len(fake.calls), before + 1)
        self.assertEqual(self.q.state['tried'][branch.name], branch.tip)
        self.assertEqual(self.q.state['collateral'], {})

    def test_single_receipt_lands_with_only_fmt_for_the_queues_package_selection(self):
        branch = self.branch('draft/a', {'pkg/src/lib.rs': 'pub fn a() {}'})
        destination = kept(self.data, receipt(branch.tip, self.base))
        self.q.state['batches_since_full'] = 2
        self.assertTrue(self.q.cycle())
        self.assert_landed([branch])
        batch, = self.records('batch')
        self.assertEqual(batch['receipt'], str(destination))
        self.assertEqual(batch['selection'], ['pkg'])
        self.assertEqual([step.rsplit(':', 2)[0] for step in batch['steps']], ['fmt'])
        self.assertEqual(self.q.state['batches_since_full'], 3)
        self.assertEqual(self.check_calls[0][0], {'pkg'})
        self.assertEqual(self.check_calls[0][2]['workspace_root'], str(self.repo))
        self.assertGreaterEqual(len(self.loads), 1)
        self.assertNotIn('[check]', Path(batch['log']).read_text())

    def test_unusable_receipts_and_periodic_full_batch_run_check(self):
        branch = self.branch('draft/a', {'pkg/src/lib.rs': 'pub fn a() {}'}, publish=False)
        merged, conflicts = queue.build_batch(self.repo, [branch], self.base, sh=self.runner)
        self.assertEqual((merged, conflicts), ([branch], []))
        detail = self.data / 'checks.log'
        values = (None, receipt(branch.tip, MAIN), receipt(branch.tip, self.base, outcome='red'),
                  receipt(branch.tip, self.base), receipt(branch.tip, self.base))
        for index, value in enumerate(values):
            with self.subTest(case=index):
                if value is not None:
                    kept(self.data, value)
                self.q.state['batches_since_full'] = self.q.full_every - 1 if index == 3 else 0
                self.q._force_full = index == 4
                record = {}
                green, outcomes, _ = self.q._checks(
                    self.base, ['pkg/src/lib.rs'], detail, record, merged)
                self.assertTrue(green)
                self.assertEqual([step.name for step in outcomes], ['fmt', 'check'])
                self.assertNotIn('receipt', record)
                if index >= 3:
                    self.assertEqual(record['selection'], 'full')
                    self.assertEqual(self.q.state['batches_since_full'], 0)
        self.q.state['batches_since_full'] = 2
        self.q._force_full = False
        record = {}
        green, outcomes, selected = self.q._checks(
            self.base, ['Cargo.toml'], detail, record, merged)
        self.assertTrue(green)
        self.assertEqual(selected, 'full')
        self.assertEqual([step.name for step in outcomes], ['fmt'])
        self.assertEqual(record['receipt'], str(receipts.path(self.data, branch.tip)))
        self.assertEqual(self.q.state['batches_since_full'], 3)

    def test_candidates_and_green_batch_of_two(self):
        a = self.branch('draft/a', {'a.txt': 'a'}, timestamp=1700000000)
        b = self.branch('draft/b', {'b.txt': 'b'}, timestamp=1600000000)
        git(self.repo, 'push', '-q', 'origin', f'{a.tip}:refs/heads/unready',
            f'{a.tip}:refs/heads/ready/orphan')
        git(self.repo, 'fetch', '-q', 'origin')
        self.assertEqual(queue.candidates(self.repo, {}, sh=self.runner), [b, a])
        self.assertEqual(queue.candidates(self.repo, {b.name: b.tip, a.name: 'old'}, sh=self.runner), [a])
        branches = [b, a]
        for branch in branches:
            kept(self.data, receipt(branch.tip, self.base))
        self.assertTrue(self.q.cycle())
        self.assert_landed(branches)
        self.assertFalse(self.q.cycle())
        batch = self.records('batch')[0]
        self.assertEqual((batch['outcome'], batch['parent'], batch['selection']), ('green', self.base, 'full'))
        self.assertEqual(batch['branches'], [b.name, a.name])
        self.assertNotIn('receipt', batch)
        self.assertTrue(batch['steps'][0].startswith('fmt:0:'))
        self.assertTrue(batch['steps'][1].startswith('check:0:'))
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
        self.assertEqual([entry['outcome'] for entry in self.records('batch')], ['green'])
        self.assertEqual(self.q.state['tried'], {branch.name: branch.tip})
        self.assert_clean()

    def test_a_branch_readied_by_hand_lands_cleanly_without_its_task_ref(self):
        branch = self.branch('ops/hand', {'a.txt': 'a'})
        git(self.origin, 'update-ref', '-d', 'refs/heads/' + branch.name)
        self.q.cycle()
        self.assertEqual([entry['outcome'] for entry in self.records('batch')], ['green'])
        self.assertEqual(len(self.records('landed')), 1)
        self.assertEqual(self.q.state['tried'], {branch.name: branch.tip})
        self.assertEqual(git(self.origin, 'for-each-ref', 'refs/heads/ready/'), '')

    def test_a_check_short_of_disk_is_an_error_and_goes_again(self):
        branch = self.branch('draft/a', {'disk.txt': 'x'})
        with self.assertRaisesRegex(RuntimeError, 'Infra: disk at check'):
            self.q.cycle()
        self.assertEqual(self.records('rejected'), [])
        self.assertEqual(self.records('batch')[-1]['outcome'], 'error')
        self.assertEqual(self.q.state['tried'], {})
        self.assertEqual([found.tip for found in queue.candidates(self.repo, self.q.state['tried'], sh=self.runner)],
                         [branch.tip])
        self.assert_clean()

    def test_build_batch_ratchet_conflict_recounts_or_rejects(self):
        self.base = self.commit({'jig/scripts/old-forms.txt': '10\n'})

        def recount(call):
            self.assertEqual(call.argv[-1], '--write')
            if (self.repo / 'jig/raise-count').exists():
                return Result(1, 'count raised\n')
            write(self.repo / 'jig/scripts/old-forms.txt', '7\n')
            return Result(0)

        fake = FakeRunner().on(['python3', '-I', '-B'], recount).on(
            [], lambda call: self.runner(call.argv, cwd=call.cwd))
        a = self.branch('draft/a', {'jig/scripts/old-forms.txt': '9\n'}, publish=False)
        b = self.branch('draft/b', {'jig/scripts/old-forms.txt': '8\n'}, publish=False)
        c = self.branch('draft/c', {'jig/scripts/old-forms.txt': '6\n', 'jig/raise-count': 'yes'}, publish=False)
        merged, conflicts = queue.build_batch(self.repo, [a, b, c], self.base, sh=fake)
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

    def test_collateral_attempt_still_rejects_conflict_and_starts_new_tip_count(self):
        a, b = queue.Branch('draft/a', TIP, 0), queue.Branch('draft/b', MAIN, 0)
        fake = FakeNextest({None: [('pkg', 'unit', 'fail')],
                            alone('pkg', 'unit'): [('pkg', 'unit', 'pass')]},
                           fallback=FakeRunner().on(['git', 'rev-parse'], Result(0, MAIN + '\n')))
        q = queue.Queue(self.home / 'clone', full_every=1, sh=fake)
        q.state['collateral'][a.name] = {'tip': MAIN, 'count': reds.LIMIT}
        q.state['collateral'][b.name] = {'tip': MAIN, 'count': 1}
        kept(q.home, receipt())
        with patch('fab.queue.build_batch', return_value=([a], [(b, 'conflict')])), \
                patch('fab.gate.changed_paths', return_value=['Cargo.toml']), \
                patch('fab.gate.check_steps', return_value=[gate.Step(
                    'default', ('heavy', '--gate', 'cargo', 'nextest', 'run'), str(q.repo))]):
            self.assertFalse(q.attempt([a, b]))
        self.assertEqual(q.last_outcome, 'collateral')
        self.assertEqual(q.state['tried'], {b.name: b.tip})
        self.assertEqual(q.state['collateral'], {a.name: {'tip': TIP, 'count': 1}})
        records = log.read(q.log_path)
        self.assertEqual([entry['ev'] for entry in records], ['collateral', 'rejected', 'batch'])
        self.assertEqual((records[1]['branch'], records[1]['step']), (b.name, 'merge'))

    def test_collateral_half_stops_its_split_but_next_half_still_runs(self):
        branches = [queue.Branch(f'draft/{n}', str(n), n) for n in range(4)]
        q = queue.Queue(self.home / 'clone', sh=FakeRunner())
        groups = []

        def attempt(group):
            groups.append(list(group))
            q.last_merged = list(group)
            q.last_outcome = ('red', 'collateral', 'green')[len(groups) - 1]
            return q.last_outcome == 'green'

        with patch('fab.queue.candidates', return_value=branches), patch.object(q, 'attempt', attempt):
            self.assertTrue(q.cycle())
        self.assertEqual(groups, [branches, branches[:2], branches[2:]])

    def test_reused_full_selection_counts_and_commits_baseline_before_only_fmt(self):
        repo = self.home / 'clone'
        branch = queue.Branch('draft/a', TIP, 0)
        fake = FakeRunner().on(['git', 'rev-parse'], Result(0, MAIN + '\n')).on(
            ['git', 'diff', '--name-only', '-z'], Result(0, 'jig/scripts/old-forms.txt\0'))
        q = queue.Queue(repo, sh=fake)
        q.state['batches_since_full'] = 2
        destination = kept(q.home, receipt())
        with patch('fab.queue.build_batch', return_value=([branch], [])), \
                patch('fab.gate.changed_paths', return_value=['Cargo.toml']), \
                patch('fab.gate.ratchet_steps', return_value=[
                    gate.Step('ratchet:jig', ('ratchet', '--write'), str(repo))]), \
                patch('fab.gate.check_steps', return_value=[
                    gate.Step('fmt', ('fmt',), str(repo)),
                    gate.Step('check', ('check',), str(repo))]) as checks:
            self.assertTrue(q.attempt([branch]))
        self.assertEqual(checks.call_args.args[1:4], ('full', ['Cargo.toml'], None))
        calls = fake.argvs()
        self.assertLess(calls.index(['ratchet', '--write']),
                        calls.index(['git', 'commit', '-m', 'Lower old-form baselines']))
        self.assertLess(calls.index(['git', 'commit', '-m', 'Lower old-form baselines']),
                        calls.index(['fmt']))
        self.assertNotIn(['check'], calls)
        batch, = [entry for entry in log.read(q.log_path) if entry['ev'] == 'batch']
        self.assertEqual((batch['selection'], batch['receipt']), ('full', str(destination)))
        self.assertEqual([step.rsplit(':', 2)[0] for step in batch['steps']], ['ratchet:jig', 'fmt'])
        self.assertEqual(q.state['batches_since_full'], 3)

    def test_red_fmt_or_ratchet_rejects_reused_tip_with_that_step(self):
        branch = queue.Branch('draft/a', TIP, 0)
        for failed in ('fmt', 'ratchet:jig'):
            with self.subTest(failed=failed):
                fake = FakeRunner().on(['git', 'rev-parse'], Result(0, MAIN + '\n')).on(
                    ['false'], Result(1))
                q = queue.Queue(self.home / 'clone', home=self.home / failed, sh=fake)
                kept(q.home, receipt())
                ratchets = [gate.Step('ratchet:jig', ('false',), str(q.repo))] if failed != 'fmt' else []
                with patch('fab.queue.build_batch', return_value=([branch], [])), \
                        patch('fab.gate.changed_paths', return_value=['Cargo.toml']), \
                        patch('fab.gate.ratchet_steps', return_value=ratchets), \
                        patch('fab.gate.check_steps', return_value=[
                            gate.Step('fmt', ('false',), str(q.repo)),
                            gate.Step('check', ('check',), str(q.repo))]):
                    self.assertFalse(q.attempt([branch]))
                rejected, batch = log.read(q.log_path)
                self.assertEqual((rejected['ev'], rejected['branch'], rejected['step']),
                                 ('rejected', branch.name, failed))
                self.assertEqual(q.state['tried'], {branch.name: branch.tip})
                self.assertEqual(batch['outcome'], 'red')
                self.assertIn('receipt', batch)
                self.assertEqual([step.rsplit(':', 2)[0] for step in batch['steps']], [failed])
                self.assertNotIn(['check'], fake.argvs())

    def test_receipt_cli_keeps_stdin_without_constructing_queue(self):
        text = receipt_text(receipt())
        with patch('fab.queue.Queue', side_effect=AssertionError('queue constructed')), \
                patch('sys.stdin', io.StringIO(text)):
            self.assertEqual(queue.main(['receipt', TIP]), 0)
        self.assertEqual(receipts.load(log.home(), TIP), receipt())
        self.assertEqual(receipts.path(log.home(), TIP).read_text(), text)

    def test_receipt_cli_refusal_reports_error_and_keeps_nothing(self):
        with patch('sys.stdin', io.StringIO(receipt_text(receipt(main='short')))), \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(queue.main(['receipt', TIP]), 1)
        self.assertEqual(errors.getvalue(), 'fab queue: main must be a full lowercase SHA\n')
        self.assertFalse(receipts.path(log.home(), TIP).exists())

    def test_untry_only_writes_request_and_cycle_consumes_each_once_before_fetch(self):
        fake = FakeRunner()
        q = queue.Queue(self.home / 'clone', sh=fake)
        q.state['tried'] = {'draft/a': 'a', 'draft/b': 'b', 'draft/keep': 'keep'}
        q._save()
        before = q.state_path.read_text()
        # The CLI must leave the running queue's state alone, even if its clone is unavailable.
        with patch('fab.queue.Queue', side_effect=AssertionError('queue constructed')):
            for name in ('draft/a', 'draft/b', 'draft/unknown'):
                self.assertEqual(queue.main(['untry', name]), 0)
        requests = q.home / 'queue-untry'
        self.assertEqual({p.name for p in requests.iterdir()},
                         {'draft%2Fa', 'draft%2Fb', 'draft%2Funknown'})
        self.assertEqual(q.state_path.read_text(), before)
        write(requests / '.untry-in-progress', '')

        def fetch(call):
            self.assertEqual(json.loads(q.state_path.read_text())['tried'], {'draft/keep': 'keep'})
            self.assertEqual({p.name for p in requests.iterdir()}, {'.untry-in-progress'})
            return Result(0)

        fake.on(['git', 'fetch'], fetch)
        self.assertFalse(q.cycle())
        self.assertEqual(q.state['tried'], {'draft/keep': 'keep'})
        entries = log.read(q.log_path)
        self.assertEqual([(e['ev'], e['branch'], e['tip']) for e in entries],
                         [('untried', 'draft/a', 'a'), ('untried', 'draft/b', 'b'),
                          ('untried', 'draft/unknown', None)])
        q.state['tried']['draft/a'] = 'a'
        q._save()
        q.sh = FakeRunner()
        self.assertFalse(q.cycle())
        self.assertEqual(q.state['tried']['draft/a'], 'a')
        self.assertEqual(log.read(q.log_path), entries)
        restored = queue.Queue(q.repo, sh=FakeRunner())
        self.assertEqual(restored.state['tried'], q.state['tried'])

    def test_untry_makes_the_same_tip_a_candidate_in_this_cycle(self):
        branch = queue.Branch('draft/a', 'same', 1)
        fake = FakeRunner().on(['git', 'for-each-ref'],
                              Result(0, 'refs/remotes/origin/ready/draft/a same 1\n'))
        q = queue.Queue(self.home / 'clone', sh=fake)
        q.state['tried'][branch.name] = branch.tip
        q._save()
        self.assertFalse(q.cycle())
        self.assertEqual(queue.main(['untry', branch.name]), 0)
        with patch.object(q, 'attempt', return_value=True) as attempt:
            self.assertTrue(q.cycle())
        attempt.assert_called_once_with([branch])
        self.assertEqual(json.loads(q.state_path.read_text())['tried'], {})

    def test_untry_remains_consumed_when_fetch_fails(self):
        fake = FakeRunner().on(['git', 'fetch'], Result(1, err='offline'))
        q = queue.Queue(self.home / 'clone', sh=fake)
        q.state['tried']['draft/a'] = 'a'
        q._save()
        self.assertEqual(queue.main(['untry', 'draft/a']), 0)
        with self.assertRaises(Failed):
            q.cycle()
        self.assertEqual(json.loads(q.state_path.read_text())['tried'], {})
        self.assertEqual(log.read(q.log_path)[0]['ev'], 'untried')
        self.assertEqual(list((q.home / 'queue-untry').iterdir()), [])

    def test_untry_requires_a_branch_and_other_commands_reject_one(self):
        for argv in (['untry'], ['receipt'], ['untry', '..'], ['untry', ''],
                     ['once', 'draft/a'], ['run', TIP], ['plan', TIP], ['log', TIP]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as error:
                queue.main(argv)
            self.assertEqual(error.exception.code, 2)

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
            constructor.assert_called_with(Path('/clone'), batch=2, wake=wake.wake)
            self.assertEqual(queue.main(['once']), 0)
            cycle.assert_called_once_with()
            constructor.assert_called_with(log.home() / 'repos/fabrig', batch=8, wake=wake.wake)
            self.assertEqual(queue.main(['run']), 0)
            run_loop.assert_called_once_with(stop=q.home / 'queue.stop')
            cycle.side_effect = RuntimeError('unavailable')
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(queue.main(['once']), 1)
            self.assertIn('unavailable', errors.getvalue())


class QueueWakeTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.branches = [queue.Branch('draft/a', 'a', 1), queue.Branch('draft/b', 'b', 2)]
        self.notes = []
        self.q = queue.Queue(self.home / 'clone', sh=FakeRunner(), wake=self.notes.append)
        self.enterContext(patch.object(queue, 'candidates', return_value=self.branches))

    def test_bisected_attempts_wake_once_in_record_order_and_clear_for_the_next_cycle(self):
        a, b = self.branches
        groups = []

        def attempt(group):
            groups.append(list(group))
            self.q.last_merged = list(group)
            if len(group) == 2:
                return False
            if group == [a]:
                self.q._retire(group, 'main')
                return True
            self.q._reject(b, 'test', self.home / 'checks.log')
            return False

        with patch.object(self.q, 'attempt', side_effect=attempt):
            self.assertTrue(self.q.cycle())
        self.assertEqual(groups, [[a, b], [a], [b]])
        self.assertEqual(self.notes, ['queue landed draft/a, rejected draft/b'])
        self.assertEqual([record['ev'] for record in log.read(self.q.log_path)], ['landed', 'rejected'])
        with patch.object(queue, 'candidates', return_value=[]):
            self.assertFalse(self.q.cycle())
        self.assertEqual(len(self.notes), 1)

    def test_idle_and_attempt_without_landing_or_rejection_never_wake(self):
        with patch.object(queue, 'candidates', return_value=[]):
            self.assertFalse(self.q.cycle())
        with patch.object(self.q, 'attempt', return_value=True):
            self.assertTrue(self.q.cycle())
        self.assertEqual(self.notes, [])

    def test_queue_without_a_wake_still_records_decisions(self):
        q = queue.Queue(self.home / 'clone', sh=FakeRunner())

        def attempt(group):
            q._retire(group[:1], 'main')
            q._reject(group[1], 'test', self.home / 'checks.log')
            return True

        with patch.object(q, 'attempt', side_effect=attempt), \
                patch.object(wake, 'wake', side_effect=AssertionError('unexpected wake')):
            self.assertTrue(q.cycle())
        self.assertEqual([record['ev'] for record in log.read(q.log_path)], ['landed', 'rejected'])

    def test_attempt_error_after_a_record_still_wakes_and_keeps_the_error(self):
        def attempt(group):
            self.q._reject(group[0], 'merge', self.home / 'checks.log')
            raise RuntimeError('checks failed')

        with patch.object(self.q, 'attempt', side_effect=attempt):
            with self.assertRaisesRegex(RuntimeError, 'checks failed'):
                self.q.cycle()
        self.assertEqual(self.notes, ['queue rejected draft/a'])

    def test_raising_wake_is_printed_does_not_fail_the_cycle_and_is_not_retried(self):
        def deliver(reason):
            self.assertEqual(log.read(self.q.log_path)[-1]['ev'], 'rejected')
            self.notes.append(reason)
            raise OSError('cannot reach dispatcher')

        def attempt(group):
            self.q._reject(group[0], 'merge', self.home / 'checks.log')
            return True

        self.q.wake = deliver
        with patch.object(self.q, 'attempt', side_effect=attempt), \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertTrue(self.q.cycle())
        self.assertEqual(self.notes, ['queue rejected draft/a'])
        self.assertEqual(errors.getvalue(), 'fab queue: wake: cannot reach dispatcher\n')
        with patch.object(self.q, 'attempt', return_value=True):
            self.assertTrue(self.q.cycle())
        self.assertEqual(len(self.notes), 1)

    def test_failed_record_has_no_note_to_wake(self):
        def attempt(group):
            self.q._reject(group[0], 'merge', self.home / 'checks.log')

        with patch.object(self.q, 'attempt', side_effect=attempt), \
                patch.object(queue.log, 'append', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                self.q.cycle()
        self.assertEqual(self.notes, [])


class UnitTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.directory = self.home / 'units'
        self.gate = {'g': queue.machines.Host('g', 'free@g', ('gate', 'builder'), hostname='g')}
        self.builder = {'g': queue.machines.Host('g', 'free@g', ('builder',), hostname='g')}
        self.enterContext(patch.dict(os.environ, {'FAB_HOST': 'g'}))

    def install(self, known, fake):
        return queue.install(sh=fake, directory=self.directory, known=known,
                             repo=Path('/q'), checkout=Path('/i'))

    def test_unit_runs_the_queue_and_drains_on_stop(self):
        text = queue.unit(home=Path('/h/fab'), checkout=Path('/h/fab/install'), repo=Path('/h/q'))
        self.assertIn('Environment=FAB_HOME=/h/fab\n', text)
        self.assertIn('ExecStartPre=/usr/bin/rm -f /h/fab/queue.stop\n', text)
        self.assertIn('ExecStart=/usr/bin/bash -lc "exec /h/fab/install/bin/fab queue run --repo /h/q"\n', text)
        self.assertIn('touch /h/fab/queue.stop; while kill -0 $$MAINPID', text)
        self.assertIn('TimeoutStopSec=1h\nKillSignal=SIGINT\nRestart=on-failure\n', text)
        self.assertTrue(text.endswith('[Install]\nWantedBy=default.target\n'))
        with self.assertRaises(ValueError):
            queue.unit(repo=Path('/bad$path'))

    def test_first_install_on_a_gate_writes_reloads_enables_and_starts(self):
        fake = FakeRunner()
        line = self.install(self.gate, fake)
        self.assertEqual((self.directory / queue.UNIT).read_text(),
                         queue.unit(repo=Path('/q'), checkout=Path('/i')))
        self.assertEqual(fake.argvs(), [['systemctl', '--user', 'daemon-reload'],
                                        ['systemctl', '--user', 'enable', queue.UNIT],
                                        ['systemctl', '--user', 'restart', '--no-block', queue.UNIT]])
        self.assertTrue(line.endswith('enabled and restarting'))

    def test_a_deploy_restarts_an_enabled_queue_and_keeps_a_paused_one_stopped(self):
        write(self.directory / queue.UNIT, 'old\n')
        for enabled, last in ((Result(0), 'restart'), (Result(1), 'daemon-reload')):
            with self.subTest(enabled=enabled.code):
                fake = FakeRunner().on(['systemctl', '--user', 'is-enabled'], enabled)
                line = self.install(self.gate, fake)
                self.assertIn(last, fake.argvs()[-1])
                self.assertEqual('left disabled' in line, enabled.code == 1)
                self.assertNotEqual((self.directory / queue.UNIT).read_text(), 'old\n')

    def test_a_machine_without_the_gate_role_disables_a_unit_it_has(self):
        fake = FakeRunner()
        self.assertEqual(self.install(self.builder, fake), 'fab-queue.service: no gate role here: nothing to do')
        self.assertEqual(fake.argvs(), [])
        write(self.directory / queue.UNIT, 'old\n')
        line = self.install(self.builder, fake)
        self.assertEqual(fake.argvs()[-2:], [['systemctl', '--user', 'disable', queue.UNIT],
                                             ['systemctl', '--user', 'stop', '--no-block', queue.UNIT]])
        self.assertEqual((self.directory / queue.UNIT).read_text(), 'old\n')
        self.assertIn('disabled and stopping', line)

    def test_main_install_prints_its_line(self):
        out = io.StringIO()
        with patch.object(queue, 'install', return_value='done') as install, \
                contextlib.redirect_stdout(out):
            self.assertEqual(queue.main(['install', '--repo', '/q']), 0)
        install.assert_called_once_with(repo=Path('/q'))
        self.assertEqual(out.getvalue(), 'done\n')


if __name__ == '__main__':
    unittest.main()
