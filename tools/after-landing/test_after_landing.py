#!/usr/bin/env python3
"""Gate contracts for docs/design/after-landing.md; process E2E is periodic."""

import json
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from types import SimpleNamespace
from unittest import mock

# Isolated direct execution (-I) omits this directory from sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from after_landing_fixtures import (
    HERE, app, CoreSandbox as Sandbox, CoreBisectionSandbox as BisectionSandbox,
)


class ReviewTests(Sandbox):
    def test_conflicting_and_hostless_routes_are_faults(self):
        original_rows = list(self.scenario['registry'])
        leads = self.slot / 'tools/queue/leads.txt'
        original_leads = leads.read_text()
        cases = [
            (original_rows + [dict(role='lead', branch_key='skein', coordinator_mailbox='s/other')], original_leads, 'skein'),
            (original_rows + [dict(role='lead', branch_key='q', coordinator_mailbox='s/other')], original_leads, 'q'),
            (original_rows, original_leads + 'ops ops@other-host\n', 'ops'),
            (original_rows, 'ops ops\n', 'ops'),
            (original_rows, original_leads + 'extra s/dynamic-memory@other-host\n', 'skein'),
        ]
        for rows, text, key in cases:
            with self.subTest(key=key, rows=rows, text=text):
                self.scenario['registry'] = rows
                self.save_scenario()
                app.atomic(leads, text)
                with self.assertRaises(app.Fault):
                    self.runner.resolve({key})
        self.scenario['registry'] = original_rows
        self.save_scenario()
        # leads.txt can legitimately address the lead while the registry
        # selects that lead's coordinator. Registry ownership takes precedence.
        app.atomic(leads, original_leads + 'skein lead/skein@hel8\n')
        self.assertEqual(self.runner.resolve({'skein'}), {'skein': 's/dynamic-memory@hel8'})


class BisectionTests(BisectionSandbox):
    def test_large_bisect_event_keeps_result_and_private_probe_details(self):
        event = self.runner.event('after-landing-bisect', self.base + ':1:bisect:1',
                                  commit=self.base, tip=self.base, attempt=1, GOOD=self.base,
                                  candidate_count=4, result='range', culprit_commit=None,
                                  identities=[['qa-skein', 'binary', 'x' * 20000]],
                                  probes=[dict(commit=self.base, outcome='unknown')])
        bounded = self.runner.bounded_event(event)
        self.assertLess(len(json.dumps(bounded).encode()) + 1, 16384)
        self.assertEqual(bounded['identities_count'], 1)
        self.assertEqual(bounded['result'], 'range')
        detail = Path(bounded['details'])
        self.assertEqual(detail.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(detail.read_text()), event)

    def test_initial_numbers_use_first_parent_age_not_lexical_hash(self):
        old, newer, middle, tip = ('f' * 40, 'a' * 40, 'b' * 40, 'c' * 40)
        active = dict(tip=tip, attempt=1, profiles=['qa-jig', 'qa-skein'], baseline={})
        alerts = []
        for profile in active['profiles']:
            # Deliberately insert the newer GOOD first as well.
            for name, good in [('two', newer), ('one', old)]:
                key = self.key(name, profile)
                active['baseline'][key] = dict(result='pass', commit=good)
                alerts.append(dict(identity=json.loads(key)))
        def git(slot, *argv):
            if argv[0] == 'rev-list':
                return '\n'.join([newer, middle, tip] if argv[-1] == old + '..' + tip else [middle, tip])
            self.assertEqual(argv[0], 'rev-parse')
            return old if argv[-1] == newer + '^1' else newer
        run = dict(id=tip + ':1', notification=dict(destinations=[]))
        with mock.patch.object(app, 'git', side_effect=git):
            phase = self.runner.pending_bisection(active, alerts, run)
        self.assertEqual([group['GOOD'] for group in phase['groups']], [old, newer, old, newer])
        self.assertEqual([group['profile'] for group in phase['groups']], ['qa-jig', 'qa-jig', 'qa-skein', 'qa-skein'])
        self.assertEqual([group['number'] for group in phase['groups']], ['1', '2', '3', '4'])


class ParserTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='after-landing-parser-')
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)

    def test_pinned_nextest_junit(self):
        fixture = self.home / 'fixture.xml'
        app.atomic(fixture, '''<?xml version="1.0" encoding="UTF-8"?>
<testsuites name="nextest-run" tests="3" failures="1">
  <testsuite name="my-package::integration" tests="3" failures="1">
    <testcase name="module::ok" classname="my-package::integration" time="0.001"/>
    <testcase name="module::broken" classname="my-package::integration" time="0.002">
      <failure message="test failed" type="test failure">assertion failed\nsecond line</failure>
    </testcase>
    <testcase name="module::ignored" classname="my-package::integration"><skipped/></testcase>
  </testsuite>
</testsuites>''')
        count, results = app.junit(fixture, 'qa-skein')
        self.assertEqual(count, 3)
        self.assertEqual([r['result'] for r in results.values()], ['pass', 'fail', 'unobserved'])
        self.assertEqual(list(results.values())[1]['identity'], ['qa-skein', 'my-package::integration', 'module::broken'])
        self.assertEqual(list(results.values())[1]['error'], 'assertion failed')
        app.atomic(fixture, '<testsuites tests="2"><testsuite name="x"><testcase name="a"/></testsuite></testsuites>')
        with self.assertRaises(app.Fault):
            app.junit(fixture, 'qa-skein')

    def test_exact_filter_unquoted_safe_identities(self):
        for binary, test in [
            ('temper-client-browser-world::qa_all',
             'qa_task_pages::typed_agent_address_survives_reload_and_a_lineage_round_trip'),
            ('package-123::qa_all_4', 'module_5::test-678'),
        ]:
            with self.subTest(binary=binary, test=test):
                self.assertEqual(app.exact_filter(binary, test),
                                 f'binary_id(={binary}) & test(={test})')

    def test_exact_filter_refuses_unsafe_identities(self):
        unsafe = ['', 'a)b', 'a(b', 'a,b', 'a&b', 'a|b', 'a b', 'a\tb',
                  'a\nb', 'a\u00a0b', 'a\\b', '/a', '#a', '~a', '=a', 'a"b']
        for identity in unsafe:
            for binary, test in [(identity, 'safe'), ('safe', identity)]:
                with self.subTest(binary=binary, test=test):
                    with self.assertRaisesRegex(app.Fault, 'identity not expressible as an exact filter'):
                        app.exact_filter(binary, test)

    def test_confirmation_selection_requires_one_same_executed_identity(self):
        identity = json.dumps(['qa-skein', 'binary', 'test'])
        passed = {identity: dict(result='pass')}
        self.assertEqual(app.validate_rerun(identity, 1, passed), 'pass')
        for count, results in [(0, {}), (2, passed), (1, {'different': dict(result='fail')}),
                               (1, {identity: dict(result='unobserved')}),
                               (1, {identity: dict(result='fail'), 'other': dict(result='pass')})]:
            with self.subTest(count=count, results=results):
                with self.assertRaises(app.Fault):
                    app.validate_rerun(identity, count, results)

    def test_config_round_trip_and_duration(self):
        import tomllib
        original = dict(profile={'qa-skein': {'default-filter': 'test(="a")',
                                              'overrides': [{'filter': 'all()', 'retries': 2}],
                                              'junit': {'path': '/tmp/not-used.xml'}}}, experimental=['x'])
        encoded = '\n'.join(json.dumps(k) + ' = ' + app.toml_value(v) for k, v in original.items())
        self.assertEqual(tomllib.loads(encoded), original)
        self.assertEqual(app.duration('1h 2m 3s 4ms'), 3723.004)
        for value in ('infinite', '0s', 'x1s', None):
            with self.assertRaises(app.Fault):
                app.duration(value)


class ContractTests(Sandbox):
    """Pin loop decisions without crossing the guardian/process boundary."""

    def prepare(self):
        self.runner.state['active'] = None
        self.runner.state['queue'] = [dict(tip=self.base, suspects=[], coalesced=[],
                                           seen_at=self.clock.time(), attempt=0, pairs={})]
        self.runner.prepare()
        return self.runner.state['active']

    def test_coalescing_and_faulted_front_preserve_coverage(self):
        queue = [dict(tip=str(n), suspects=[dict(commit=str(n))], coalesced=[],
                      seen_at=self.clock.time(), attempt=0, pairs={}) for n in range(4)]
        self.runner.state['queue'] = queue
        self.runner.prepare()
        item, = self.runner.state['queue']
        self.assertEqual(item['tip'], '3')
        self.assertEqual(item['coalesced'], ['0', '1', '2'])
        self.assertEqual(item['suspects'], [dict(commit=str(n)) for n in range(4)])
        self.assertEqual(self.runner.state['hour']['coalesced'], 3)
        self.runner.state['active'] = None
        queue[0].update(attempt=1, pairs={'qa-skein': dict(status='faulted')})
        self.runner.state['queue'] = queue
        self.runner.prepare()
        self.assertEqual(len(self.runner.state['queue']), 4)
        self.assertEqual(self.runner.state['active']['tip'], '0')
        self.assertEqual(self.runner.state['active']['attempt'], 2)

    def test_enrolled_tiers_keep_contract_order_and_retry_only_faults(self):
        profiles = ['exhaustive-skein', 'qa-skein', 'qa-smith', 'qa-jig', 'process-jig',
                    'browser-skein', 'browser-jig', 'browser-temper', 'qa-temper']
        self.assertEqual(tomllib.loads((HERE / 'tiers.toml').read_text())['profiles'], profiles)
        app.atomic(self.tiers, 'profiles=' + json.dumps(profiles))
        active = self.prepare()
        self.assertEqual(active['profiles'], profiles)
        self.assertFalse(any(p.startswith('live-') or p == 'process-temper' for p in active['profiles']))
        self.runner.state['queue'][0]['pairs'] = {
            p: dict(status='faulted' if p == 'qa-jig' else 'ran') for p in profiles}
        self.runner.state['active'] = None
        self.runner.prepare()
        self.assertEqual(self.runner.state['active']['profiles'], ['qa-jig'])

    def test_identity_classification_preserves_unobserved_history(self):
        identity = ['qa-skein', 'pkg::qa', 'one']
        key = json.dumps(identity, separators=(',', ':'))
        cases = [
            (None, 'fail', 'fail', 'unattributed', 'red'),
            ('pass', 'fail', 'fail', 'new', 'red'),
            ('red', 'fail', 'fail', 'standing', 'red'),
            ('red', 'fail', 'pass', 'flake', 'pass'),
            ('red', 'pass', None, 'recovered', 'pass'),
            ('pass', 'pass', None, 'passing', 'pass'),
            ('red', 'unobserved', None, 'unobserved', 'unobserved'),
            ('pass', 'unobserved', None, 'unobserved', 'unobserved'),
        ]
        for old, result, repeated, state, last in cases:
            with self.subTest(old=old, result=result, repeated=repeated):
                active = self.prepare()
                if old is not None:
                    active['baseline'][key] = dict(result=old, commit=self.base)
                replies = [(1, {key: dict(identity=identity, result=result, error='first error')},
                            dict(log='main.log', elapsed=1))]
                if repeated:
                    replies.append((1, {key: dict(identity=identity, result=repeated)},
                                    dict(log='rerun.log', elapsed=1)))
                with mock.patch.object(self.runner, 'launch', side_effect=replies) as launch:
                    outcome = self.runner.pair('qa-skein')
                observation = active['observations']['qa-skein'][key]
                self.assertEqual((observation['state'], observation['result']), (state, last))
                self.assertEqual(launch.call_count, 2 if repeated else 1)
                if repeated:
                    self.assertEqual(launch.call_args.args, tuple(identity))
                self.assertEqual(outcome['status'], 'ran')
                self.assertEqual(bool(outcome['new']), state == 'new')
                self.assertEqual(bool(outcome['red']), last == 'red')
                if last == 'unobserved':
                    self.assertNotIn(key, active['updates'])
                    self.assertEqual(active['baseline'][key]['result'], old)
                else:
                    self.assertEqual(active['updates'][key], dict(result=last, commit=self.base))

    def test_replay_retains_evidence_and_rejects_selection_changes(self):
        active = self.prepare()
        active['pairs']['qa-skein'] = dict(red=[], new=[])
        for result, state in [('pass', 'passing'), ('unobserved', 'unobserved'), ('red', 'new')]:
            with self.subTest(state=state):
                observation = dict(result=result, state=state, logs=['saved.log'], event=None, alert=None)
                self.runner.stage_observation('qa-skein', state, observation)
                replay = self.runner.stage_observation('qa-skein', state, dict(observation, logs=['redo.log']))
                self.assertIs(replay, observation)
                with self.assertRaisesRegex(app.Fault, 'replayed outcome changed'):
                    self.runner.stage_observation('qa-skein', state, dict(observation, result='changed'))
                saved = json.loads(self.runner.path.read_text())
                self.assertEqual(saved['active']['observations']['qa-skein'][state], observation)
        active['selections']['qa-skein'] = ['saved identity']
        with mock.patch.object(self.runner, 'launch', return_value=(0, {}, dict(log='new.log', elapsed=0))):
            with self.assertRaisesRegex(app.Fault, 'replayed test selection changed'):
                self.runner.pair('qa-skein')

    def test_outbox_records_precede_posts_and_retry_ids_survive_restart(self):
        event = self.runner.event('after-landing-run', self.base + ':1', commit=self.base, verdict='red')
        self.runner.post(event['id'], 'ops@hel8', 'id: ' + event['id'], records=[event])
        with mock.patch.object(app, 'command', return_value=SimpleNamespace(returncode=1)) as command:
            self.runner.deliver()
        self.assertEqual(command.call_count, 1)
        first_batch = command.call_args.kwargs['data']
        self.assertEqual(command.call_args.args[0][0], self.args.record)
        self.runner = app.Runner(self.args)
        bodies = []
        def delivered(argv, **kwargs):
            if argv[0] == self.args.post:
                bodies.append(Path(argv[-1]).read_text())
            return SimpleNamespace(returncode=0 if argv[0] == self.args.record else 1)
        with mock.patch.object(app, 'command', side_effect=delivered) as command:
            self.runner.deliver()
        self.assertEqual([call.args[0][0] for call in command.call_args_list], [self.args.record, self.args.post])
        self.assertEqual(command.call_args_list[0].kwargs['data'], first_batch)
        self.assertTrue(self.runner.state['outbox'][0]['recorded'])
        for code in (3, 0):
            if code == 0:
                self.runner.post(event['id'], 'ops@hel8', bodies[0].rstrip('\n'))
            self.runner = app.Runner(self.args)
            def accepted(argv, **kwargs):
                self.assertEqual(argv[0], self.args.post)
                self.assertEqual(Path(argv[-1]).read_text(), bodies[0])
                return SimpleNamespace(returncode=code)
            with mock.patch.object(app, 'command', side_effect=accepted):
                self.runner.deliver()
            self.assertEqual(self.runner.state['outbox'], [])

    def test_trim_waits_for_known_completion_and_saved_verdict(self):
        self.runner.state['last_run'] = dict(id='run', verdict='green', faulted=[])
        self.runner.state['trim_pending'] = dict(id='run', started=False)
        self.runner.state['active'] = dict(invocation=dict(result='unknown'))
        with mock.patch.object(app, 'command') as command:
            self.runner.trim()
            command.assert_not_called()
        self.runner.state['active'] = None
        def trimmed(argv, **kwargs):
            saved = json.loads(self.runner.path.read_text())
            self.assertEqual(saved['last_run']['verdict'], 'green')
            self.assertEqual(saved['trim_pending'], dict(id='run', started=True))
            self.assertEqual(argv[-3:], ['--older', '0', self.slot])
            return SimpleNamespace(returncode=0, stdout=f'{self.slot}: 2 executables, 1.234 GB freed; 100.000 GB free; 0 processes skipped\n', stderr='')
        with mock.patch.object(app, 'command', side_effect=trimmed) as command:
            self.runner.trim()
            self.runner.trim()
        self.assertEqual(command.call_count, 1)
        self.assertIsNone(self.runner.state['trim_pending'])
        self.assertEqual(self.runner.state['hour']['trim_bytes'], 1_234_000_000)

    def test_state_privacy_and_single_runner_lock(self):
        self.runner.save()
        self.assertEqual(self.runner.directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.runner.path.stat().st_mode & 0o777, 0o600)
        with app.lock(self.runner.directory / 'runner.lock'):
            with self.assertRaises(app.Fault):
                with app.lock(self.runner.directory / 'runner.lock'):
                    pass

    def group(self, names=('one',), count=6):
        chain = ['c' + str(n) for n in range(count + 1)]
        return dict(number='1', profile='qa-skein', GOOD=chain[0], chain=chain,
                    candidates=chain[1:], lo=0, hi=count, probes=[], result=None, culprit=None,
                    identities=[json.dumps(['qa-skein', 'pkg::qa', name], separators=(',', ':')) for name in names])

    def test_bisection_search_endpoints_and_unknown_order(self):
        group = self.group()
        self.assertEqual(self.runner.bisect_target(group), 'c0')
        group['probes'].append(dict(commit='c0', outcome='good'))
        for commit in ('c3', 'c2', 'c4', 'c1', 'c5'):
            self.assertEqual(self.runner.bisect_target(group), commit)
            group['probes'].append(dict(commit=commit, outcome='unknown'))
        self.assertIsNone(self.runner.bisect_target(group))
        self.assertEqual(group['result'], 'range')
        group.update(lo=2, hi=3, result=None)
        self.assertIsNone(self.runner.bisect_target(group))
        self.assertEqual((group['result'], group['culprit']), ('culprit proven', 'c3'))
        self.assertNotIn('c6', [probe['commit'] for probe in group['probes']])

    def test_bisection_split_is_atomic_and_numbers_survive_reload(self):
        group = self.group(('one', 'two', 'three'))
        outcomes = dict(zip(group['identities'], ['bad', 'good', 'unknown']))
        self.runner.state['bisect'] = dict(groups=[group], probe=dict(attempts=[]))
        self.runner.save_bisect_probe(0, 'c3', outcomes, [dict(log='probe.log')])
        saved = json.loads(self.runner.path.read_text())['bisect']
        self.assertIsNone(saved['probe'])
        self.assertEqual([part['number'] for part in saved['groups']], ['1.1', '1.2', '1.3'])
        self.assertEqual([(part['lo'], part['hi']) for part in saved['groups']], [(0, 3), (3, 6), (0, 6)])
        self.assertEqual([part['probes'][0]['outcome'] for part in saved['groups']], ['bad', 'good', 'unknown'])
        self.runner = app.Runner(self.args)
        self.assertEqual(self.runner.state['bisect'], saved)

    def test_bisection_probe_requires_exact_selection_and_confirmation(self):
        group = self.group()
        key, = group['identities']
        def reply(result):
            return (1, {key: dict(result=result)}, dict(log='probe.log'))
        for first, confirmation, expected in [('pass', None, 'good'), ('unobserved', None, 'unknown'),
                                               ('fail', 'fail', 'bad'), ('fail', 'pass', 'unknown'),
                                               ('fail', 'unobserved', 'unknown'), ('fail', None, 'unbuildable')]:
            with self.subTest(first=first, confirmation=confirmation):
                replies = [reply(first)]
                if first == 'fail':
                    replies.append(reply(confirmation) if confirmation else (0, None, dict(log='build.log')))
                with mock.patch.object(app, 'git') as git, mock.patch.object(self.runner, 'launch', side_effect=replies) as launch:
                    outcomes, logs = self.runner.bisect_probe(group, 'c3')
                self.assertEqual(outcomes, {key: expected})
                self.assertEqual(git.call_args_list, [mock.call(self.slot, 'checkout', '--detach', '--force', 'c3'), mock.call(self.slot, 'clean', '-fd')])
                self.assertEqual(launch.call_args, mock.call('qa-skein', identities=[key]))
                self.assertEqual(len(logs), len(replies))
        with mock.patch.object(app, 'git'), mock.patch.object(self.runner, 'launch', return_value=(0, {}, dict(log='wrong.log'))):
            with self.assertRaisesRegex(app.Fault, 'bisection selection differs'):
                self.runner.bisect_probe(group, 'c3')

    def test_bisection_budget_and_deadline_preserve_narrowed_interval(self):
        for count, expired in ((16, False), (2, True)):
            with self.subTest(count=count, expired=expired):
                group = self.group()
                group.update(lo=2, hi=4, probes=[dict(commit='c0', outcome='good'), dict(commit='c2', outcome='good')])
                phase = dict(groups=[group], invocation=None, probe=None, completed=None,
                             count=count, deadline=self.clock.time() + (-1 if expired else 100))
                self.runner.state['bisect'] = phase
                with mock.patch.object(self.runner, 'bisect_probe') as probe, mock.patch.object(self.runner, 'finish_bisection') as finish:
                    self.runner.bisect()
                probe.assert_not_called()
                finish.assert_called_once_with()
                self.assertEqual(group['result'], 'range')
                self.assertEqual((group['lo'], group['hi']), (2, 4))
                self.assertEqual(phase['count'], count)
                self.assertIsNotNone(phase['completed'])


    def test_suspect_classification_uses_first_parent_metadata(self):
        metadata = {
            'merge': 'parent branch-tip\nMerge ready/skein/task',
            'foreign': "parent foreign-tip\nMerge commit 'foreign'",
            'baseline': 'parent\nqueue baseline',
            'fast-forward': 'parent\nMerge ready/skein/not-a-merge',
        }
        def git(slot, *argv):
            self.assertEqual(slot, self.slot)
            if argv[0] == 'rev-list':
                self.assertEqual(argv, ('rev-list', '--first-parent', '--reverse', 'previous..tip'))
                return '\n'.join(metadata)
            self.assertEqual(argv[:3], ('show', '-s', '--format=%P%n%s'))
            return metadata[argv[-1]]
        with mock.patch.object(app, 'git', side_effect=git):
            suspects = app.suspects(self.slot, 'previous', 'tip')
        self.assertEqual([row['kind'] for row in suspects], ['branch', 'other', 'other', 'other'])
        self.assertEqual(suspects[0], dict(commit='merge', subject='Merge ready/skein/task',
                         kind='branch', key='skein', task='task', branch='ready/skein/task', tip='branch-tip'))
        self.assertEqual([row['commit'] for row in suspects], list(metadata))

    def test_resolver_qualifies_registry_and_fallback_without_guessing(self):
        self.assertEqual(self.runner.resolve({'skein', 'q-jig', 'coord', 'q', 'u', 'ops', 'mc'}),
                         dict(skein='s/dynamic-memory@hel8', **{'q-jig': 's/qa@hel8'},
                              coord='s/dynamic-memory@hel8', q='s/qa@hel8', u='s/upgrades@hel8',
                              ops='ops@hel8', mc='s/multi-coord@hel8'))
        with self.assertRaisesRegex(app.Fault, 'no route for missing'):
            self.runner.resolve({'missing'})
        self.scenario['registry_fault'] = True
        with self.assertRaisesRegex(app.Fault, 'launcher registry unreadable'):
            self.runner.resolve({'skein'})

    def test_bounded_run_keeps_complete_private_evidence_and_stable_id(self):
        event = self.runner.event('after-landing-run', 'run-' + 'x' * 20000,
                                  commit=self.base, verdict='red',
                                  suspects=[dict(commit=str(n), subject='x' * 600) for n in range(100)],
                                  pairs={'qa-skein': dict(status='ran', selected=1000, executed=1000,
                                         failed=1000, red=['red-' + str(n) for n in range(1000)])})
        bounded = self.runner.bounded_event(event)
        self.assertLess(len(json.dumps(bounded).encode()) + 1, 16384)
        self.assertTrue(bounded['id'].startswith('sha256:'))
        self.assertEqual(bounded['verdict'], 'red')
        self.assertEqual(bounded['confirmed_red_count'], 1000)
        self.assertEqual(bounded['suspects_count'], 100)
        detail = Path(bounded['details'])
        self.assertEqual(detail.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(detail.read_text()), event)
        self.assertEqual(self.runner.bounded_event(event), bounded)


if __name__ == '__main__':
    unittest.main()
