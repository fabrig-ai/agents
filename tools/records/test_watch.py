#!/usr/bin/env -S python3 -I -B
"""Offline watch rules and producer/CLI integration, temporary HOME and origin."""
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch

TOOL = Path(__file__).with_name('watch').resolve()
API = runpy.run_path(str(TOOL))
NOW = 1793271600.0
ISO = API['iso']


class Rules(unittest.TestCase):
    def setUp(self):
        self.config = tomllib.loads(TOOL.with_suffix('.toml').read_text())['rules']
        self.state = {}
        self.names = {
            'lead/tools': dict(name='lead/tools', role='lead', supervisor='s/default', coordinator_mailbox='s/default', aliases=[]),
            'lead/H/tools': dict(name='lead/H/tools', role='lead', supervisor='s/second', coordinator_mailbox='s/second', aliases=[]),
            's/default': dict(name='s/default', role='coordinator', supervisor='director', aliases=['coordinator/dm/one']),
            's/second': dict(name='s/second', role='coordinator', supervisor='director', aliases=[]),
            'ops': dict(name='ops', supervisor='director', aliases=[]),
            's/deploy': dict(name='s/deploy', supervisor='director', aliases=[]),
            'director': dict(name='director', supervisor='', aliases=[]),
        }
        self.data = dict(names=self.names, owned={n: True for n in self.names}, agents=[], waiters={}, mail=[],
                         claims=[], leases=[], refs={}, questions=[], drafts=[])
        self.data.update({k: [] for k in ('runs/hel8', 'heavy/hel8', 'records/queue', 'records/heavy', 'records/sessions', 'records/post', 'records/post-sent')})
        self.calls = []
    def judge(self, now=NOW):
        return API['evaluate'](self.data, self.state, self.config, now)
    def rule(self, rule, now=NOW):
        return [c for c in self.judge(now).values() if c['rule'] == rule]
    def action(self, kind, to, candidate):
        self.calls.append((kind, to, candidate['rule']))
        return 'woken' if kind == 'wake' else 0
    def round(self, now=NOW, errors=None):
        return API['reconcile'](self.state, self.judge(now), errors or {}, self.config, now, self.action)
    def live(self, name='lead/tools'):
        self.data['agents'].append(dict(name=name, sessionId='synthetic-session', status='busy'))
    def mail(self, age, owner='lead/tools', subject='synthetic', sender='test@hel8'):
        self.data['mail'].append(dict(owner=owner, message_id='synthetic-mail', subject=subject,
                                      sender=sender, delivered=NOW-age*60))
    def add_run(self, **fields):
        row = dict(run='synthetic-run', owner='lead/tools', effort='high', started=NOW-600,
                   changed=NOW-600, ended=False, cwd='/synthetic/slots/1', task='task', branch='mc/test')
        row.update(fields)
        self.data['runs/hel8'].append(row)
        return row

    def codex(self, active=False):
        self.names['lead/tools'].update(kind='codex', unit='codex-owner-lead-tools')
        self.data['unit/lead/tools'] = active

    def test_codex_gone_active_draft_even_without_unfinished_part(self):
        self.codex()
        self.live()  # Stale Claude inventory does not make a Codex unit live.
        self.data['drafts'] = [dict(mailbox='s/default', state='active', unfinished_parts=[])]
        gone = next(c for c in self.rule('gone') if c['owner'] == 'lead/tools')
        self.assertEqual(gone['first_to'], 's/default')
        self.assertEqual(gone['supervisor'], 's/default')
        self.assertIn('unit/lead/tools', gone['deps'])
        self.assertNotIn('agents', gone['deps'])
        self.data['unit/lead/tools'] = True
        self.assertFalse([c for c in self.rule('gone') if c['owner'] == 'lead/tools'])
        self.data['unit/lead/tools'] = False
        self.names['lead/tools']['paused'] = True
        self.assertFalse([c for c in self.rule('gone') if c['owner'] == 'lead/tools'])
        self.names['lead/tools']['paused'] = False
        self.data['drafts'][0]['state'] = 'paused'
        self.assertFalse([c for c in self.rule('gone') if c['owner'] == 'lead/tools'])
        self.data['drafts'][0]['state'] = 'active'
        del self.data['unit/lead/tools']
        self.assertFalse([c for c in self.rule('gone') if c['owner'] == 'lead/tools'])

    def test_codex_deaf_skips_wake_and_notifies_coordinator_immediately(self):
        self.codex()
        self.mail(10)
        self.assertFalse(self.rule('deaf'))
        self.data['waiters']['lead/tools'] = dict(alive=True)
        self.assertTrue(self.rule('deaf', NOW+1))
        self.round(NOW+1, errors={'agents': 'unavailable', 'waiters': 'unavailable'})
        self.assertEqual(self.calls, [('send', 's/default', 'deaf')])
        self.round(NOW+2)
        self.assertEqual(len(self.calls), 1)
        self.data['unit/lead/tools'] = True
        self.assertFalse(self.rule('deaf', NOW+3))
        self.data['unit/lead/tools'] = False
        self.names['lead/tools']['paused'] = True
        self.assertFalse(self.rule('deaf', NOW+3))

    def test_codex_unit_failure_freezes_open_episode(self):
        self.codex()
        self.mail(11)
        self.round()
        episode = self.state['episodes']['deaf\tlead/tools']
        del self.data['unit/lead/tools']
        for offset in (1, 2, 3):
            self.round(NOW+offset, errors={'unit/lead/tools': 'unavailable'})
        self.assertIs(self.state['episodes']['deaf\tlead/tools'], episode)
        self.assertEqual(episode['clear'], 0)

    def test_codex_handover_uses_threshold_event_and_coordinator_supervisor(self):
        self.codex(True)
        self.data['records/sessions'] = [dict(kind='context', name='lead/tools', percent=90, time=ISO(NOW-1300))]
        self.assertFalse(self.rule('handover late'))
        self.data['records/sessions'].append(dict(kind='handover-needed', session_kind='codex-owner',
            name='lead/tools', session='owner:1', time=ISO(NOW-1200), first_fired=ISO(NOW-1200)))
        self.assertFalse(self.rule('handover late'))
        late, = self.rule('handover late', NOW+1)
        self.assertEqual(late['supervisor'], 's/default')
        self.round(NOW+1)
        self.assertIn(('send', 'lead/tools', 'handover late'), self.calls)
        self.round(NOW+1201)
        self.assertIn(('send', 's/default', 'handover late'), self.calls)
        self.data['records/sessions'].append(dict(kind='files-current', name='lead/tools', time=ISO(NOW)))
        self.assertFalse(self.rule('handover late', NOW+1202))

    def test_deaf_threshold_live_and_dead_waiter(self):
        self.live()
        self.mail(10)
        self.assertFalse(self.rule('deaf'))
        self.assertTrue(self.rule('deaf', NOW+0.1))
        self.data['waiters']['lead/tools'] = dict(alive=True, session='synthetic-session')
        self.assertFalse(self.rule('deaf', NOW+1))
        self.data['waiters']['lead/tools']['alive'] = False
        self.assertTrue(self.rule('deaf', NOW+1))
        self.data['agents'][0]['status'] = 'completed'
        self.assertFalse(self.rule('deaf', NOW+1))

    def test_renamed_live_session_uses_waiter_holder(self):
        self.live('renamed-session')
        self.data['waiters']['lead/tools'] = dict(alive=False, session='synthetic-session')
        self.mail(11)
        self.assertTrue(self.rule('deaf'))

    def test_gone_active_registration_and_routing(self):
        self.names['lead/H/tools']['unfinished'] = True
        self.data['drafts'] = [dict(mailbox='s/second', state='active')]
        events = self.round()
        self.assertEqual(len(events), 2)
        self.assertIn(('send', 's/second', 'gone'), self.calls)
        self.assertIn(('send', 'director', 'gone'), self.calls)
        self.calls.clear()
        self.round(NOW+1799)
        self.assertEqual(self.calls, [])
        events = self.round(NOW+1800)
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e['kind'] == 'alert-escalate' for e in events))
        self.assertTrue(all(c[1] == 'director' for c in self.calls))
        lead = next(e for e in events if e['owner'] == 'lead/H/tools')
        self.assertEqual(lead['supervisor'], 's/second')

    def test_report_threshold_and_deaf_covers_it(self):
        self.live()
        self.add_run(ended=True)
        self.data['waiters']['lead/tools'] = dict(alive=True)
        self.mail(15, subject='codex-run synthetic-run complete', sender='codex-run@hel8')
        self.assertFalse(self.rule('report unread'))
        self.assertTrue(self.rule('report unread', NOW+1))
        self.data['waiters']['lead/tools']['alive'] = False
        self.assertFalse(self.rule('report unread', NOW+1))

    def test_hung_quiet_threshold_and_effort_median(self):
        row = self.add_run(changed=NOW-1800)
        self.assertFalse(self.rule('run hung'))
        self.assertTrue(self.rule('run hung', NOW+1))
        row.update(changed=NOW, started=NOW-600)
        self.add_run(run='finished', ended=True, started=NOW-200, end=NOW, effort='high')
        self.add_run(run='other-effort', ended=True, started=NOW-10, end=NOW, effort='low')
        self.assertFalse(self.rule('run hung'))
        self.assertTrue(self.rule('run hung', NOW+1))
        row['ended'] = True
        self.assertFalse(self.rule('run hung', NOW+1))

    def test_claim_threshold_and_all_activity(self):
        self.data['claims'] = [dict(subject='hel8-1', host='hel8', number='1', owner='lead/tools', created=NOW-2700)]
        self.assertFalse(self.rule('idle claim'))
        self.assertTrue(self.rule('idle claim', NOW+1))
        self.data['heavy/hel8'] = [dict(cwd='/synthetic/slots/1')]
        self.assertFalse(self.rule('idle claim', NOW+2))
        self.data['heavy/hel8'] = []
        self.assertFalse(self.rule('idle claim', NOW+3))
        self.assertTrue(self.rule('idle claim', NOW+2704))
        self.data['records/heavy'] = [dict(time=ISO(NOW+2704), host='hel8', cwd='/synthetic/slots/1')]
        self.assertFalse(self.rule('idle claim', NOW+2705))
        self.add_run()
        self.assertFalse(self.rule('idle claim', NOW+9999))
        self.data['runs/hel8'] = []
        self.data['records/queue'] = [dict(kind='batch', time=ISO(NOW+9999), steps=[dict(suites=[dict(cwd='/synthetic/slots/1')])])]
        self.assertFalse(self.rule('idle claim', NOW+10000))

    def test_unqueued_tip_age_attempt_and_batch_edges(self):
        self.data['refs'] = {'ready/tools/task': 'a'*40}
        self.judge()
        self.assertFalse(self.rule('unqueued', NOW+1200))
        self.assertEqual([r['subject'] for r in self.rule('unqueued', NOW+1201)], ['queue'])
        self.data['records/queue'] = [dict(kind='batch', time=ISO(NOW+1800))]
        self.assertFalse(self.rule('unqueued', NOW+1800))
        self.assertEqual([r['subject'] for r in self.rule('unqueued', NOW+1801)], ['ready/tools/task'])
        self.data['records/queue'].append(dict(kind='attempt', time=ISO(NOW+1801), branch='ready/tools/task', tip='a'*40))
        self.assertFalse(self.rule('unqueued', NOW+1801))
        self.data['refs']['ready/tools/task'] = 'b'*40
        self.assertFalse(self.rule('unqueued', NOW+1801))
        self.data['refs'] = {}
        self.judge()
        self.assertFalse(self.state['refs'])

    def test_lease_both_edges_and_activity(self):
        row = dict(subject='pkg:example', owner='s/default', since=ISO(NOW-14400), waiters=[dict(since=ISO(NOW-10))])
        self.data['leases'] = [row]
        self.assertFalse(self.rule('lease stall'))
        self.assertTrue(self.rule('lease stall', NOW+1))
        self.data['records/heavy'] = [dict(time=ISO(NOW), packages=['example'])]
        self.assertFalse(self.rule('lease stall', NOW+1))
        row['waiters'][0]['since'] = ISO(NOW-7200)
        self.assertFalse(self.rule('lease stall'))
        self.assertTrue(self.rule('lease stall', NOW+1))
        row['waiters'] = []
        self.assertFalse(self.rule('lease stall', NOW+99999))

    def test_handover_edge_successor_and_files_current(self):
        hook = dict(kind='context-hook', name='lead/tools', session='old', time=ISO(NOW-1200))
        self.data['records/sessions'] = [hook]
        self.assertFalse(self.rule('handover late'))
        self.assertTrue(self.rule('handover late', NOW+1))
        for following in ('files-current', 'successor', 'session-start'):
            with self.subTest(following=following):
                self.data['records/sessions'] = [hook, dict(kind=following, name='lead/tools', session='new', time=ISO(NOW))]
                self.assertFalse(self.rule('handover late', NOW+1))

    def test_handover_repeated_hooks_do_not_reset_clock_and_post_ack_clears(self):
        self.data['records/sessions'] = [dict(kind='context-hook', name='lead/tools', session='old',
                                             time=ISO(NOW-age)) for age in (1201, 1000, 10)]
        self.assertTrue(self.rule('handover late'))
        self.data['records/post'] = [dict(kind='mail', time=ISO(NOW), subject='files current',
                                          **{'from': 'lead/tools@hel8'})]
        self.assertFalse(self.rule('handover late'))

    def test_high_context_reading_does_not_prove_hook_fired(self):
        self.data['records/sessions'] = [dict(kind='context', name='lead/tools', session='old',
                                             percent=99, time=ISO(NOW-9999))]
        self.assertFalse(self.rule('handover late'))

    def test_lease_long_waiter_is_independent_of_activity_inputs(self):
        self.data['leases'] = [dict(subject='pkg:example', owner='s/default', since=ISO(NOW-10),
                                    waiters=[dict(since=ISO(NOW-7201))])]
        self.data.pop('records/heavy')
        events = self.round(errors={'records/heavy': 'failed'})
        self.assertEqual([e['rule'] for e in events], ['lease stall'])

    def test_gone_uses_unfinished_part_from_records(self):
        self.data['drafts'] = [dict(mailbox='s/default', state='active', unfinished_parts=['tools-parser'])]
        self.assertIn('lead/tools', [c['owner'] for c in self.rule('gone')])
        self.data['drafts'][0]['unfinished_parts'] = []
        self.assertNotIn('lead/tools', [c['owner'] for c in self.rule('gone')])

    def test_report_still_alerts_when_deaf_disabled(self):
        self.live()
        self.add_run(ended=True)
        self.mail(16, subject='run synthetic-run ok', sender='codex-run@hel8')
        self.config['deaf']['enabled'] = False
        self.assertTrue(self.rule('report unread'))

    def test_recent_completed_run_prevents_early_idle_claim(self):
        self.data['claims'] = [dict(subject='hel8-1', host='hel8', number='1', owner='lead/tools', created=NOW-9999)]
        self.add_run(ended=True, end=NOW-1)
        self.assertFalse(self.rule('idle claim'))
        self.assertTrue(self.rule('idle claim', NOW+2700))

    def test_question_edge_answer_and_no_supervisor(self):
        self.data['questions'] = [dict(subject='0001', deadline=ISO(NOW))]
        self.assertFalse(self.rule('question due'))
        self.assertTrue(self.rule('question due', NOW+1))
        self.round(NOW+1)
        self.round(NOW+99999)
        self.assertEqual(self.calls, [('send', 'director', 'question due')])
        self.data['questions'][0]['answer'] = 'yes'
        self.assertFalse(self.rule('question due', NOW+1))

    def test_delivery_exit_two_only_recovery(self):
        row = self.add_run(ended=True, post_status=2, told=False)
        self.assertTrue(self.rule('delivery failed'))
        for code in (0, 1, 3):
            row['post_status'] = code
            self.assertFalse(self.rule('delivery failed'))
        row.update(post_status=2, told=True)
        self.assertFalse(self.rule('delivery failed'))
        event = dict(id='event', kind='send', time=ISO(NOW), message_id='mail', **{'from': 's/default', 'exit': 2})
        self.data['records/post'] = [event]
        self.assertTrue(self.rule('delivery failed'))
        self.data['records/post'].append(dict(event, time=ISO(NOW+1), exit=0))
        self.assertFalse(self.rule('delivery failed'))

    def test_dedup_close_recurrence_and_failed_input_freeze(self):
        self.live()
        self.mail(11)
        self.assertEqual([e['kind'] for e in self.round()], ['alert-open'])
        self.assertEqual(self.round(), [])
        self.assertEqual(self.calls, [('wake', 'lead/tools', 'deaf')])
        self.assertEqual(self.round(NOW+1199), [])
        self.assertEqual([e['kind'] for e in self.round(NOW+1200)], ['alert-escalate'])
        self.assertEqual(self.calls[-1], ('send', 's/default', 'deaf'))
        self.data['mail'] = []
        for _ in range(3):
            self.assertFalse(self.round(NOW+1201, errors={'mail': 'failed'}))
        self.assertEqual(self.round(NOW+1202), [])
        self.assertEqual([e['kind'] for e in self.round(NOW+1203)], ['alert-close'])
        self.mail(11)
        events = self.round(NOW+1204)
        self.assertEqual(events[0]['kind'], 'alert-open')
        self.assertEqual(self.calls[-1], ('wake', 'lead/tools', 'deaf'))

    def test_recurrence_event_ids_are_distinct_with_a_frozen_clock(self):
        self.live()
        self.mail(11)
        first = self.round()[0]
        self.data['mail'] = []
        self.round()
        self.round()
        self.mail(11)
        recurrence = self.round()[0]
        self.assertNotEqual(first['id'], recurrence['id'])
        self.assertNotEqual(first['episode'], recurrence['episode'])

    def test_failed_round_breaks_consecutive_clear_streak(self):
        self.live()
        self.mail(11)
        self.round()
        self.data['mail'] = []
        self.assertFalse(self.round(NOW+1))
        self.assertFalse(self.round(NOW+2, errors={'mail': 'failed'}))
        self.assertFalse(self.round(NOW+3))
        self.assertTrue(self.state['episodes'])
        self.assertEqual([e['kind'] for e in self.round(NOW+4)], ['alert-close'])

    def test_every_wake_result_still_escalates(self):
        self.live()
        self.mail(11)
        for result in ('woken', 'queued', 'waiting', 'unwoken: stopped'):
            with self.subTest(result=result):
                state = {}
                candidates = self.judge()
                actions = []
                def act(kind, to, candidate):
                    actions.append((kind, to))
                    return result if kind == 'wake' else 0
                first = API['reconcile'](state, candidates, {}, self.config, NOW, act)
                self.assertEqual(first[0]['wake'], result)
                events = API['reconcile'](state, candidates, {}, self.config, NOW+1200, act)
                self.assertEqual(events[0]['kind'], 'alert-escalate')
                self.assertEqual(actions, [('wake', 'lead/tools'), ('send', 's/default')])

    def test_supervisors_default_second_ops_and_director(self):
        for name, target in [('lead/tools', 's/default'), ('lead/H/tools', 's/second'), ('s/second', 'director'),
                             ('ops', 'director'), ('s/deploy', 'director'), ('director', None)]:
            with self.subTest(name=name):
                self.state, self.calls = {}, []
                self.data['agents'], self.data['mail'] = [], []
                self.live(name)
                self.mail(11, owner=name)
                self.round()
                self.round(NOW+1200)
                self.assertEqual(self.calls, [('wake', name, 'deaf')] + ([('send', target, 'deaf')] if target else []))

    def test_paused_not_ours_and_rules_disabled(self):
        self.live()
        self.mail(11)
        self.data['owned']['lead/tools'] = False
        self.assertFalse(self.rule('deaf'))
        self.data['owned']['lead/tools'] = True
        self.config['deaf']['enabled'] = False
        self.assertFalse(self.rule('deaf'))
        self.config['deaf']['enabled'] = True
        candidates = self.judge()
        self.assertFalse(API['reconcile']({}, candidates, {'agents': 'failed'}, self.config, NOW, self.action))
        self.assertFalse(self.calls)

    def test_failed_send_retried_and_success_not_repeated(self):
        self.data['questions'] = [dict(subject='0001', deadline=ISO(NOW-1))]
        candidates = self.judge()
        state = {}
        API['reconcile'](state, candidates, {}, self.config, NOW, lambda *a: 2)
        self.assertFalse(next(iter(state['episodes'].values()))['notified'])
        API['reconcile'](state, candidates, {}, self.config, NOW+1, self.action)
        API['reconcile'](state, candidates, {}, self.config, NOW+2, self.action)
        self.assertEqual(len(self.calls), 1)

    def test_handover_updates_keep_first_clock_and_do_not_reopen_after_ack(self):
        first = ISO(NOW-1300)
        self.data['records/sessions'] = [
            dict(kind='handover-needed', name='lead/tools', session='old', time=ISO(NOW-10),
                 first_fired=first, last_fired=ISO(NOW-10))]
        self.assertTrue(self.rule('handover late'))
        self.data['records/sessions'].append(dict(kind='files-current', name='lead/tools', time=ISO(NOW-100)))
        self.assertFalse(self.rule('handover late'))

    def test_post_sent_failures_retry_and_missing_stream_freeze(self):
        row = dict(id='send-fail', kind='send', time=ISO(NOW), message_id='mail',
                   **{'from': 's/default@hel8', 'exit': 2})
        self.data['records/post-sent'] = [row]
        candidates = self.rule('delivery failed')
        self.assertEqual(len(candidates), 1)
        self.assertIn('records/post-sent', candidates[0]['deps'])
        self.assertEqual(candidates[0]['owner'], 's/default')
        self.assertEqual(candidates[0]['escalate_to'], 'ops')
        self.round()
        self.assertEqual(self.calls, [('send', 's/default', 'delivery failed')])
        self.data.pop('records/post-sent')
        self.round(NOW+1, errors={'records/post-sent': 'missing'})
        self.assertTrue(self.state['episodes'])
        self.data['records/post-sent'] = [row, dict(row, id='send-ok', exit=0, time=ISO(NOW+1))]
        self.assertFalse(self.rule('delivery failed'))
        self.round(NOW+2)
        self.round(NOW+3)
        self.assertFalse(self.state['episodes'])

    def test_launcher_pause_and_supervisor_are_authoritative(self):
        self.live()
        self.mail(11)
        self.names['lead/tools']['paused'] = True
        self.assertFalse(self.rule('deaf'))
        self.names['lead/tools']['paused'] = False
        self.names['lead/tools']['supervisor'] = 'custom-supervisor'
        self.assertEqual(self.rule('deaf')[0]['supervisor'], 'custom-supervisor')


    def test_fixed_identity_episodes_freeze_when_names_is_unavailable(self):
        self.names['ops']['always_watched'] = True
        self.data['records/post-sent'] = [dict(id='fixed-fail', kind='send', time=ISO(NOW),
                                             message_id='fixed-mail', **{'from': 'ops', 'exit': 2})]
        self.round()
        self.assertTrue(self.state['episodes'])
        self.data['names'] = {}
        for offset in (1, 2, 3):
            self.round(NOW+offset, errors={'names': 'unavailable'})
        self.assertTrue(self.state['episodes'])



class Heartbeats(unittest.TestCase):
    def test_interval_boundaries_and_alert_exceptions(self):
        due = API['heartbeat_due']
        state = {'heartbeat': {'time': NOW, 'failed_inputs': []}}
        self.assertTrue(due({}, [], {}, NOW, 900))
        self.assertFalse(due(state, [], {}, NOW + 899, 900))
        self.assertTrue(due(state, [], {}, NOW + 900, 900))
        self.assertFalse(due(state, [], {}, NOW - 1, 900))
        for kind in ('alert-open', 'alert-escalate', 'alert-close'):
            self.assertTrue(due(state, [{'kind': kind}], {}, NOW + 1, 900))
        self.assertTrue(due(state, [], {'agents': 'failed'}, NOW + 1, 900))
        state['heartbeat']['failed_inputs'] = ['agents']
        self.assertFalse(due(state, [], {'agents': 'different failure reason'}, NOW + 1, 900))
        self.assertTrue(due(state, [], {}, NOW + 1, 900))


class Integration(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='watch-test-')
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.real_git = shutil.which('git')
        env = {k: v for k, v in os.environ.items() if not k.startswith(('GIT_', 'RECORDS_'))}
        env.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / '.config'),
                   GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1',
                   GIT_AUTHOR_NAME='Test', GIT_AUTHOR_EMAIL='test@example.invalid',
                   GIT_COMMITTER_NAME='Test', GIT_COMMITTER_EMAIL='test@example.invalid')
        self.environment = patch.dict(os.environ, env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.origin = self.home / 'origin.git'
        self.seed = self.home / 'seed'
        self.git('init', '--bare', '--initial-branch=main', str(self.origin))
        self.git('clone', str(self.origin), str(self.seed))
        self.write(self.seed / 'README.md', '# Synthetic\n')
        for source in ('queue', 'heavy', 'sessions', 'post', 'post-sent'):
            self.write(self.seed / f'events/{source}/README.md', '# Synthetic\n')
        self.git('-C', str(self.seed), 'add', '.')
        self.git('-C', str(self.seed), 'commit', '-m', 'seed')
        self.git('-C', str(self.seed), 'push', 'origin', 'main')
        self.tmp = self.home / 'src/rust/tmp'
        self.write(self.tmp / 'post/machines', 'hel8 local\nbuilder fake.invalid\n')
        (self.tmp / 'codex-run').mkdir(parents=True)
        self.write(self.tmp / 'heavy/state.json', '{"tasks":{}}')
        inventory = subprocess.run([str(TOOL.parents[1] / 'session/start'), 'names', '--json'],
                                   env=dict(os.environ, RECORDS_REPO=str(self.home/'records')),
                                   text=True, capture_output=True)
        self.assertEqual(inventory.returncode, 0, inventory.stderr)
        self.write(self.home / 'names.json', inventory.stdout)
        self.write(self.home / 'agents.json', '[]')
        self.write(self.home / 'refs', '')
        self.write(self.home / 'claims', '')
        self.write(self.home / 'waiters', '')
        self.write(self.home / 'leases', '[]')
        self.write(self.home / 'remote', '{"runs":[],"heavy":[],"errors":[]}')
        self.env = dict(os.environ, PATH=str(self.bin)+os.pathsep+os.environ['PATH'],
                        RECORDS_REPO=str(self.home / 'records'), RECORDS_ORIGIN=str(self.origin))
        self.fake('systemctl', "import os, sys\nassert sys.argv[1:4] == ['--user', 'is-active', '--quiet']\nsys.exit(int(os.environ.get('UNIT_EXIT', '3')))\n")
        self.fake('post', """from pathlib import Path
import os,sys
home=Path(os.environ['HOME'])
if sys.argv[1]=='waiters': print((home/'waiters').read_text(),end='')
else:
 with (home/'post.log').open('a') as out: out.write(__import__('json').dumps(sys.argv[1:])+'\\n')
 if sys.argv[1]=='wake': print(os.environ.get('WAKE_RESULT','queued'))
 sys.exit(int(os.environ.get('POST_EXIT','0')))
""")
        self.fake('session-start', """import os,sys
from pathlib import Path
home=Path(os.environ['HOME'])
if os.environ.get('FAIL_INPUT')=='session-start': sys.exit(2)
if sys.argv[1]=='names':
 assert sys.argv[1:]==['names','--json']
 print((home/'names.json').read_text())
else: sys.exit(1 if sys.argv[2] in os.environ.get('UNOWNED','').split(',') else 0)
""")
        for name, file in [('claude','agents.json'), ('claim','claims'), ('lease','leases'), ('ssh','remote')]:
            self.fake(name, f"import os,sys\nfrom pathlib import Path\nif os.environ.get('FAIL_INPUT')=={name!r}: sys.exit(2)\nprint((Path(os.environ['HOME'])/{file!r}).read_text(),end='')\n")
        self.fake('git', f"import os,sys\nfrom pathlib import Path\nif sys.argv[1]=='ls-remote': print((Path(os.environ['HOME'])/'refs').read_text(),end='')\nelse: os.execv({self.real_git!r}, [{self.real_git!r}]+sys.argv[1:])\n")
    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path
    def git(self, *args):
        result = subprocess.run([self.real_git, *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout
    def fake(self, name, program):
        self.write(self.bin / name, '#!/usr/bin/env python3\n'+program).chmod(0o700)
    def invoke(self, dry=False, code=0, post=True, **env):
        config = self.write(self.home/'watch.toml', TOOL.with_suffix('.toml').read_text().replace(
            'post = false', 'post = true' if post else 'post = false'))
        result = subprocess.run([str(TOOL), '--once', '--config', str(config)] + (['--dry-run'] if dry else []),
                                env=dict(self.env, **env), capture_output=True, text=True)
        self.assertEqual(result.returncode, code, result.stdout+result.stderr)
        return result
    def mail(self):
        self.write(self.home/'agents.json', '[{"name":"lead/jig","sessionId":"session","status":"busy"}]')
        path = self.write(self.tmp/'post/lead+jig/new/synthetic.md',
                          'Id: synthetic\nFrom: test@hel8\nTo: lead/jig@hel8\nSubject: synthetic\n\nPRIVATE BODY MUST NEVER APPEAR\n')
        old = datetime.now(timezone.utc).timestamp()-660
        os.utime(path, (old, old))
        return path
    def state(self):
        return json.loads((self.home/'.local/state/watch/state.json').read_text())
    def events(self):
        self.git('-C', str(self.seed), 'pull', '--ff-only')
        return [json.loads(line) for path in (self.seed/'events/watch/hel8').glob('*.jsonl') for line in path.read_text().splitlines()]
    def test_codex_cli_reads_unit_and_sends_deaf_directly_to_coordinator(self):
        path = self.write(self.tmp/'post/lead+u+jig/new/owner-mail.md',
                          'Id: owner-mail\nFrom: test@hel8\nTo: lead/u/jig@hel8\nSubject: synthetic\n\n')
        old = datetime.now(timezone.utc).timestamp()-660
        os.utime(path, (old, old))
        # Unit liveness is independent of Claude availability.
        active = self.invoke(dry=True, UNIT_EXIT='0', FAIL_INPUT='claude')
        self.assertNotIn('deaf lead/u/jig', active.stdout)
        inactive = self.invoke(dry=True, UNIT_EXIT='3', FAIL_INPUT='claude')
        self.assertIn("would post send --as watch s/upgrades 'watch: deaf lead/u/jig'", inactive.stdout)
        self.assertNotIn('post wake lead/u/jig', inactive.stdout)
        failed = self.invoke(dry=True, UNIT_EXIT='1')
        self.assertNotIn('watch: deaf lead/u/jig', failed.stdout)
        heartbeat = next(json.loads(line) for line in failed.stdout.splitlines()
                         if line.startswith('{') and json.loads(line).get('kind') == 'heartbeat')
        self.assertIn('unit/lead/u/jig', heartbeat['inputs_failed'])

    def test_dry_run_no_state_no_posts_no_append_no_clone(self):
        self.mail()
        before = self.git('--git-dir', str(self.origin), 'rev-parse', 'main')
        result = self.invoke(dry=True)
        self.assertIn('would post wake lead/jig', result.stdout)
        self.assertIn('"kind": "alert-open"', result.stdout)
        self.assertNotIn('PRIVATE BODY', result.stdout)
        self.assertFalse((self.home/'.local').exists())
        self.assertFalse((self.home/'records').exists())
        self.assertFalse((self.home/'post.log').exists())
        self.assertEqual(self.git('--git-dir', str(self.origin), 'rev-parse', 'main'), before)
    def test_cli_events_state_modes_dedup_close_and_recurrence(self):
        mail = self.mail()
        self.invoke()
        self.invoke()
        events = self.events()
        self.assertEqual(sum(e['kind']=='alert-open' for e in events), 1)
        self.assertEqual(sum(e['kind']=='heartbeat' for e in events), 1)
        self.assertEqual(json.loads((self.home/'post.log').read_text()), ['wake', 'lead/jig'])
        state = self.home/'.local/state/watch/state.json'
        self.assertEqual(state.stat().st_mode & 0o777, 0o600)
        self.assertEqual(next(iter(self.state()['episodes'].values()))['wake'], 'queued')
        mail.unlink()
        self.invoke()
        self.assertTrue(self.state()['episodes'])
        self.invoke()
        self.assertFalse(self.state()['episodes'])
        self.assertEqual(sum(e['kind']=='alert-close' for e in self.events()), 1)
        self.mail()
        self.invoke()
        self.assertEqual(sum(e['kind']=='alert-open' for e in self.events()), 2)
    def test_silent_mode_publishes_without_sending_or_waking(self):
        self.assertFalse(tomllib.loads(TOOL.with_suffix('.toml').read_text())['alerts']['post'])
        self.mail()
        self.write(self.home/'remote', json.dumps({'runs': [dict(
            run='hung', owner='lead/jig', cwd='/synthetic/slots/1', started=0, changed=0, effort='high', ended=False)], 'heavy': [], 'errors': []}))
        result = self.invoke(post=False)
        self.assertIn('would post wake lead/jig', result.stdout)
        self.assertIn('would post send --as watch lead/jig', result.stdout)
        self.assertNotIn('PRIVATE BODY', result.stdout)
        self.assertFalse((self.home/'post.log').exists())
        events = self.events()
        self.assertTrue(any(e['kind'] == 'alert-open' for e in events))
        self.assertEqual(events[-1]['kind'], 'heartbeat')
        self.assertEqual(next(e['wake'] for e in events if e.get('rule') == 'deaf'), 'suppressed')
        state = self.state()
        self.assertTrue(state['episodes'])
        for episode in state['episodes'].values():
            episode['opened'] -= 3600
        self.write(self.home/'.local/state/watch/state.json', json.dumps(state))
        result = self.invoke(post=False)
        supervisor = next(e['supervisor'] for e in events if e.get('rule') == 'deaf')
        self.assertIn('would post send --as watch ' + supervisor, result.stdout)
        self.assertTrue(any(e['kind'] == 'alert-escalate' for e in self.events()))
        self.assertFalse((self.home/'post.log').exists())
        self.assertEqual(sum(e['kind'] == 'heartbeat' for e in self.events()), 2)

    def test_alerts_and_heartbeat_use_one_push_per_poll(self):
        pushes = self.home/'pushes'
        hook = self.write(self.origin/'hooks/post-receive',
            '#!/usr/bin/env python3\nfrom pathlib import Path\n'
            f'with Path({str(pushes)!r}).open("a") as out: out.write("push\\n")\n')
        hook.chmod(0o700)
        mail = self.mail()
        self.invoke()
        self.assertEqual(pushes.read_text().splitlines(), ['push'])
        self.invoke()
        self.assertEqual(pushes.read_text().splitlines(), ['push'])
        mail.unlink()
        self.invoke()
        self.assertEqual(pushes.read_text().splitlines(), ['push'])
        self.invoke()
        self.assertEqual(pushes.read_text().splitlines(), ['push', 'push'])
        self.assertEqual(sum(e['kind'] == 'alert-close' for e in self.events()), 1)
        state = self.state()
        state['heartbeat']['time'] -= 900
        API['atomic'](self.home/'.local/state/watch/state.json', state)
        self.invoke()
        self.assertEqual(pushes.read_text().splitlines(), ['push'] * 3)

    def test_heartbeat_interval_and_failed_input_changes(self):
        self.invoke()
        self.assertEqual(len(self.events()), 1)
        head = self.git('--git-dir', str(self.origin), 'rev-parse', 'main')
        self.invoke()
        self.assertEqual(self.git('--git-dir', str(self.origin), 'rev-parse', 'main'), head)
        state = self.state()
        state['heartbeat']['time'] -= 900
        API['atomic'](self.home/'.local/state/watch/state.json', state)
        self.invoke()
        self.assertEqual(len(self.events()), 2)
        self.invoke(FAIL_INPUT='claude')
        self.assertEqual(len(self.events()), 3)
        self.assertIn('agents', self.events()[-1]['inputs_failed'])
        self.invoke(FAIL_INPUT='claude')
        self.assertEqual(len(self.events()), 3)
        self.invoke()
        self.assertEqual(len(self.events()), 4)
        self.assertFalse(self.events()[-1]['inputs_failed'])

    def test_failure_isolation_and_paused_names(self):
        self.mail()
        self.invoke(FAIL_INPUT='claude')
        self.assertFalse(self.state()['episodes'])
        heartbeat = self.events()[-1]
        self.assertIn('agents', heartbeat['inputs_failed'])
        self.invoke(UNOWNED='lead/jig')
        self.assertFalse(self.state()['episodes'])
        self.invoke(FAIL_INPUT='ssh')
        self.assertTrue(self.state()['episodes'])
        self.assertIn('runs/builder', self.events()[-1]['inputs_failed'])
    def test_publication_failure_keeps_outbox_and_replays_without_repeating_wake(self):
        self.mail()
        hook = self.write(self.origin/'hooks/pre-receive', '#!/bin/sh\nexit 1\n')
        hook.chmod(0o700)
        self.invoke(code=2)
        self.assertTrue(self.state()['pending'])
        ids = [e['id'] for e in self.state()['pending']]
        hook.unlink()
        self.invoke()
        self.assertFalse(self.state()['pending'])
        events = self.events()
        self.assertTrue(set(ids).issubset({e['id'] for e in events}))
        self.assertEqual(len(events), len({e['id'] for e in events}))
        self.assertEqual((self.home/'post.log').read_text().count('wake'), 1)

    def test_dry_run_keeps_existing_state_bytes_unchanged(self):
        self.mail()
        self.invoke()
        path = self.home/'.local/state/watch/state.json'
        before = path.read_bytes()
        posts = (self.home/'post.log').read_bytes()
        remote = self.git('--git-dir', str(self.origin), 'rev-parse', 'main')
        self.invoke(dry=True)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual((self.home/'post.log').read_bytes(), posts)
        self.assertEqual(self.git('--git-dir', str(self.origin), 'rev-parse', 'main'), remote)

    def test_bad_remote_runs_and_leases_are_failed_inputs(self):
        self.write(self.home/'remote', '{"runs":[{}],"heavy":[],"errors":[]}')
        self.write(self.home/'leases', '[{"subject":"pkg:example","owner":"s/dynamic-memory","since":"bad","waiters":[]}]')
        self.invoke()
        heartbeat = self.events()[-1]
        self.assertIn('runs/builder', heartbeat['inputs_failed'])
        self.assertIn('leases', heartbeat['inputs_failed'])
        self.assertFalse(self.state()['episodes'])

    def test_probe_real_producer_shapes_and_header_joins(self):
        task = self.write(self.home/'task.md', '+++\ntask="test"\nbranch="mc/example"\ndraft="wave"\n+++\n')
        run = self.tmp/'codex-run/synthetic'
        self.write(run/'meta', f'to=lead/jig@hel8\nstarted={ISO(NOW)}\neffort=high\ndir=/synthetic/slots/1\ntask={task}\n')
        self.write(run/'events.jsonl', '')
        self.write(self.tmp/'codex-run/runs.tsv', '\t'.join(['synthetic','lead/jig',ISO(NOW),ISO(NOW+60),'0','1','model','high',str(task),'report','thread','1/0/1','2'])+'\n')
        result = API['probe']()
        self.assertFalse(result['errors'])
        row = result['runs'][0]
        self.assertTrue(row['ended'])
        self.assertEqual(row['post_status'], 2)
        self.assertEqual(row['branch'], 'mc/example')
        self.assertEqual(row['end']-row['started'], 60)
        self.assertNotIn('task_body', row)
    def test_launcher_identity_contract_supervisors_and_prefix(self):
        rows = API['identities']((self.home/'names.json').read_text())
        self.assertEqual(rows['lead/jig']['supervisor'], 's/dynamic-memory')
        self.assertEqual(rows['lead/q/jig']['supervisor'], 's/qa')
        for name in ('s/qa', 'ops', 's/deploy'):
            self.assertEqual(rows[name]['supervisor'], 'director')
        self.assertEqual(rows['director']['supervisor'], '')
        self.assertEqual(rows['s/qa']['name_prefix'], 'coordinator/q/')
        self.assertTrue(rows['ops']['always_watched'])
        for text in ('{"lead/unmapped": {}}', '[{"mailbox":"lead/unmapped"}]'):
            with self.assertRaises(ValueError):
                API['identities'](text)
        # Preserve the launcher-supplied supervisor rather than inferring one.
        custom = API['identities']('[{"mailbox":"s/custom","role":"coordinator","supervisor":"other"}]')
        self.assertEqual(custom['s/custom']['supervisor'], 'other')

    def test_claim_and_waiter_parsers_reject_malformed(self):
        rows = API['claims']('builder 1 [pool]: lead/jig: synthetic (since '+ISO(NOW)+'); held 0d 00:00:00\n')
        self.assertEqual(rows[0]['host'], 'builder')
        self.assertEqual(API['waiters']('lead/jig 1 dead session')['lead/jig']['alive'], False)
        for parser, value in [('claims','nonsense'), ('waiters','lead/jig invalid')]:
            with self.assertRaises(ValueError): API[parser](value)
    def test_names_failure_does_not_invent_fixed_identities(self):
        self.mail()
        result = self.invoke(dry=True, FAIL_INPUT='session-start')
        heartbeat = next(json.loads(line) for line in result.stdout.splitlines()
                         if line.startswith('{') and json.loads(line)['kind'] == 'heartbeat')
        self.assertIn('names', heartbeat['inputs_failed'])
        self.assertEqual(heartbeat['inputs']['session-start'], str(self.bin / 'session-start'))
        self.assertEqual(heartbeat['alerts_open'], 0)
        self.assertNotIn('would post ', result.stdout)

    def test_sibling_resolution_and_heartbeat_paths(self):
        global TOOL
        original_tool = TOOL
        self.env['PATH'] = str(self.bin) + os.pathsep + '/usr/bin:/bin'
        release = self.home / 'release/tools'
        helper = release / 'session/session_lib.py'
        helper.parent.mkdir(parents=True)
        shutil.copy2(TOOL.parents[1] / 'session/session_lib.py', helper)
        for name in ('watch', 'record', 'watch.toml'):
            target = release / 'records' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original_tool.with_name(name), target)
        for name, relative in (('session-start', 'session/start'), ('lease', 'lease')):
            target = release / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.bin / name, target)
        self.mail()
        launcher = release / 'session/start'
        program = launcher.read_text().split('\n', 1)[1]
        self.write(launcher, '#!/usr/bin/env python3\nimport json,os,sys\nfrom pathlib import Path\n'
                   "with (Path(os.environ['HOME'])/'launcher.log').open('a') as out: out.write(json.dumps(sys.argv[1:])+'\\n')\n" + program)
        launcher.chmod(0o700)
        try:
            TOOL = release / 'records/watch'
            for fallback in (False, True):
                with self.subTest(fallback=fallback):
                    if fallback:
                        (self.bin / 'session-start').unlink()
                        (self.bin / 'lease').unlink()
                    result = self.invoke(dry=True)
                    heartbeat = next(json.loads(line) for line in result.stdout.splitlines()
                                     if line.startswith('{') and json.loads(line)['kind'] == 'heartbeat')
                    expected = {'session-start': str(launcher if fallback else self.bin / 'session-start'),
                                'lease': str(release / 'lease' if fallback else self.bin / 'lease')}
                    self.assertEqual(heartbeat['inputs'], expected)
                    self.assertFalse(heartbeat['inputs_failed'])
                    self.assertIn('would post wake lead/jig', result.stdout)
            calls = [json.loads(line) for line in (self.home / 'launcher.log').read_text().splitlines()]
            self.assertIn(['names', '--json'], calls)
            self.assertIn(['owns', 'lead/jig'], calls)
        finally:
            TOOL = original_tool

    def test_writer_watch_append_only(self):
        record = TOOL.with_name('record')
        row = dict(id='synthetic', time=ISO(NOW), source='watch', host='hel8', kind='heartbeat')
        result = subprocess.run([str(record),'append','--as','watch','watch','hel8'], input=json.dumps(row)+'\n',
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([str(record),'write','--as','watch','README.md'], input='# Refused\n',
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('invalid writer', result.stderr)


if __name__ == '__main__':
    unittest.main()
