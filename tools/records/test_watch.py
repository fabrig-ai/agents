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
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from offline_test_support import RecordsSeed, call_main

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
            's/multi-coord': dict(name='s/multi-coord', supervisor='director', aliases=[], always_watched=True),
            'director': dict(name='director', supervisor='', aliases=[]),
        }
        self.data = dict(names=self.names, owned={n: True for n in self.names}, agents=[], waiters={}, mail=[],
                         claims=[], leases=[], refs={}, questions=[], drafts=[])
        self.data.update({k: [] for k in ('runs/hel8', 'heavy/hel8', 'spool/queue', 'spool/heavy', 'spool/sessions', 'spool/post', 'spool/post-sent')})
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

    def test_codex_gone_requires_unfinished_part(self):
        self.codex()
        self.live()  # Stale Claude inventory does not make a Codex unit live.
        self.data['drafts'] = [dict(mailbox='s/default', state='active', unfinished_parts=[])]
        self.assertFalse([c for c in self.rule('gone') if c['owner'] == 'lead/tools'])
        self.data['drafts'][0]['unfinished_parts'] = ['tools-parser']
        gone = next(c for c in self.rule('gone') if c['owner'] == 'lead/tools')
        self.assertNotIn('first_to', gone)
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

    def test_codex_deaf_skips_wake_and_posts_to_owner(self):
        self.codex()
        self.mail(10)
        self.assertFalse(self.rule('deaf'))
        self.data['waiters']['lead/tools'] = dict(alive=True)
        self.assertTrue(self.rule('deaf', NOW+1))
        self.round(NOW+1, errors={'agents': 'unavailable', 'waiters': 'unavailable'})
        self.assertEqual(self.calls, [('send', 'lead/tools', 'deaf')])
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
        self.data['spool/sessions'] = [dict(kind='context', name='lead/tools', percent=90, time=ISO(NOW-1300))]
        self.assertFalse(self.rule('handover late'))
        self.data['spool/sessions'].append(dict(kind='handover-needed', session_kind='codex-owner',
            name='lead/tools', session='owner:1', time=ISO(NOW-1200), first_fired=ISO(NOW-1200)))
        self.assertFalse(self.rule('handover late'))
        late, = self.rule('handover late', NOW+1)
        self.assertEqual(late['supervisor'], 's/default')
        self.round(NOW+1)
        self.assertIn(('send', 'lead/tools', 'handover late'), self.calls)
        self.round(NOW+1201)
        self.assertIn(('send', 's/default', 'handover late'), self.calls)
        self.data['spool/sessions'].append(dict(kind='files-current', name='lead/tools', time=ISO(NOW)))
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
        self.assertIn(('send', 'lead/H/tools', 'gone'), self.calls)
        self.calls.clear()
        self.round(NOW+1799)
        self.assertEqual(self.calls, [])
        events = self.round(NOW+1801)
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e['kind'] == 'alert-escalate' for e in events))
        self.assertEqual(set(c[1] for c in self.calls), {'s/second', 'director'})
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

    def test_hung_requires_quiet_and_elapsed_with_fallback(self):
        row = self.add_run(changed=NOW-3600, started=NOW-5400)
        self.assertFalse(self.rule('run hung'))
        self.assertTrue(self.rule('run hung', NOW+1))
        row['changed'] = NOW
        self.assertFalse(self.rule('run hung', NOW+1))
        row.update(changed=NOW-5401, started=NOW-5400)
        self.assertFalse(self.rule('run hung'))
        row['started'] -= 1
        self.assertTrue(self.rule('run hung'))
        row['ended'] = True
        self.assertFalse(self.rule('run hung'))

    def test_hung_needs_five_completed_samples_at_same_effort(self):
        row = self.add_run(changed=NOW-3601, started=NOW-3601)
        for i in range(4):
            self.add_run(run=f'finished-{i}', ended=True, started=NOW-200, end=NOW)
        for i in range(5):
            self.add_run(run=f'low-{i}', ended=True, started=NOW-10, end=NOW, effort='low')
        self.assertFalse(self.rule('run hung'))
        self.add_run(run='fifth', ended=True, started=NOW-200, end=NOW)
        self.assertTrue(self.rule('run hung'))
        row['changed'] = NOW
        self.assertFalse(self.rule('run hung'))

    def test_hung_median_elapsed_boundary_and_config(self):
        row = self.add_run(changed=NOW-3601, started=NOW-7200)
        for i in range(5):
            self.add_run(run=f'finished-{i}', ended=True, started=NOW-2400, end=NOW)
        self.assertFalse(self.rule('run hung'))
        self.assertTrue(self.rule('run hung', NOW+1))
        self.config['run hung']['median_multiplier'] = 4
        self.assertFalse(self.rule('run hung', NOW+1))
        self.config['run hung']['median_min_samples'] = 6
        self.assertTrue(self.rule('run hung', NOW+1))
        self.config['run hung']['fallback_minutes'] = 180
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
        self.data['spool/heavy'] = [dict(time=ISO(NOW+2704), host='hel8', cwd='/synthetic/slots/1')]
        self.assertFalse(self.rule('idle claim', NOW+2705))
        self.add_run()
        self.assertFalse(self.rule('idle claim', NOW+9999))
        self.data['runs/hel8'] = []
        self.data['spool/queue'] = [dict(kind='batch', time=ISO(NOW+9999), steps=[dict(suites=[dict(cwd='/synthetic/slots/1')])])]
        self.assertFalse(self.rule('idle claim', NOW+10000))

    def test_unqueued_tip_age_attempt_and_batch_edges(self):
        self.data['refs'] = {'ready/tools/task': 'a'*40}
        self.judge()
        self.assertFalse(self.rule('unqueued', NOW+1200))
        self.assertEqual([r['subject'] for r in self.rule('unqueued', NOW+1201)], ['queue'])
        self.data['spool/queue'] = [dict(kind='batch', time=ISO(NOW+1800))]
        self.assertFalse(self.rule('unqueued', NOW+1800))
        self.assertEqual([r['subject'] for r in self.rule('unqueued', NOW+1801)], ['ready/tools/task'])
        self.data['spool/queue'].append(dict(kind='attempt', time=ISO(NOW+1801), branch='ready/tools/task', tip='a'*40))
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
        self.data['spool/heavy'] = [dict(time=ISO(NOW), packages=['example'])]
        self.assertFalse(self.rule('lease stall', NOW+1))
        row['waiters'][0]['since'] = ISO(NOW-7200)
        self.assertFalse(self.rule('lease stall'))
        self.assertTrue(self.rule('lease stall', NOW+1))
        row['waiters'] = []
        self.assertFalse(self.rule('lease stall', NOW+99999))

    def test_handover_edge_successor_and_files_current(self):
        self.live()
        self.data['agents'][0]['sessionId'] = 'old'
        hook = dict(kind='context-hook', name='lead/tools', session='old', time=ISO(NOW-1200))
        self.data['spool/sessions'] = [hook]
        self.assertFalse(self.rule('handover late'))
        self.assertTrue(self.rule('handover late', NOW+1))
        for following in ('files-current', 'successor', 'session-start'):
            with self.subTest(following=following):
                self.data['spool/sessions'] = [hook, dict(kind=following, name='lead/tools', session='old' if following == 'files-current' else 'new', time=ISO(NOW))]
                self.assertFalse(self.rule('handover late', NOW+1))

    def test_handover_repeated_hooks_do_not_reset_clock_and_post_ack_clears(self):
        self.live()
        self.data['agents'][0]['sessionId'] = 'old'
        self.data['spool/sessions'] = [dict(kind='context-hook', name='lead/tools', session='old',
                                             time=ISO(NOW-age)) for age in (1201, 1000, 10)]
        self.assertTrue(self.rule('handover late'))
        self.data['spool/post'] = [dict(kind='mail', time=ISO(NOW), subject='files current',
                                          **{'from': 'lead/tools@hel8'})]
        self.assertFalse(self.rule('handover late'))

    def test_high_context_reading_does_not_prove_hook_fired(self):
        self.data['spool/sessions'] = [dict(kind='context', name='lead/tools', session='old',
                                             percent=99, time=ISO(NOW-9999))]
        self.assertFalse(self.rule('handover late'))

    def test_lease_long_waiter_is_independent_of_activity_inputs(self):
        self.data['leases'] = [dict(subject='pkg:example', owner='s/default', since=ISO(NOW-10),
                                    waiters=[dict(since=ISO(NOW-7201))])]
        self.data.pop('spool/heavy')
        events = self.round(errors={'spool/heavy': 'failed'})
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
        self.data['spool/post'] = [event]
        self.assertTrue(self.rule('delivery failed'))
        self.data['spool/post'].append(dict(event, time=ISO(NOW+1), exit=0))
        self.assertFalse(self.rule('delivery failed'))

    def test_dedup_close_recurrence_and_failed_input_freeze(self):
        self.live()
        self.mail(11)
        self.assertEqual([e['kind'] for e in self.round()], ['alert-open'])
        self.assertEqual(self.round(), [])
        self.assertEqual(self.calls, [('send', 'lead/tools', 'deaf')])
        self.assertEqual(self.round(NOW+1799), [])
        self.assertEqual([e['kind'] for e in self.round(NOW+1801)], ['alert-escalate'])
        self.assertEqual(self.calls[-1], ('send', 's/default', 'deaf'))
        self.data['mail'] = []
        for _ in range(3):
            self.assertFalse(self.round(NOW+1802, errors={'mail': 'failed'}))
        self.assertEqual(self.round(NOW+1803), [])
        self.assertEqual([e['kind'] for e in self.round(NOW+1804)], ['alert-close'])
        self.mail(11)
        events = self.round(NOW+1805)
        self.assertEqual(events[0]['kind'], 'alert-open')
        self.assertEqual(self.calls[-1], ('send', 'lead/tools', 'deaf'))

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

    def test_remedy_failure_retries_at_interval_and_escalates_once(self):
        self.live()
        self.mail(11)
        candidates = self.judge()
        candidates['deaf\tlead/tools']['remedy'] = dict(kind='resume')
        calls = []
        def action(kind, to, candidate):
            calls.append((kind, to))
            return dict(success=False, result='synthetic failure') if kind == 'remedy' else 0
        first = API['reconcile'](self.state, candidates, {}, self.config, NOW, action)
        self.assertEqual([e['kind'] for e in first], ['alert-open', 'remedy'])
        API['reconcile'](self.state, candidates, {}, self.config, NOW+119, action)
        self.assertEqual(calls, [('remedy', 'lead/tools')])
        events = API['reconcile'](self.state, candidates, {}, self.config, NOW+120, action)
        self.assertEqual([e['kind'] for e in events], ['remedy', 'alert-escalate'])
        self.assertNotEqual(first[-1]['id'], events[0]['id'])
        API['reconcile'](self.state, candidates, {}, self.config, NOW+10000, action)
        self.assertEqual(calls, [('remedy', 'lead/tools')]*2 + [('send', 's/default')])

    def test_supervisors_default_second_ops_and_director(self):
        for name, target in [('lead/tools', 's/default'), ('lead/H/tools', 's/second'), ('s/second', 'director'),
                             ('ops', 'director'), ('s/deploy', 'director'), ('s/multi-coord', 'director'), ('director', None)]:
            with self.subTest(name=name):
                self.state, self.calls = {}, []
                self.data['agents'], self.data['mail'] = [], []
                self.live(name)
                if name == 'ops':
                    self.data['unit/ops'] = False
                self.mail(11, owner=name)
                self.round()
                self.round(NOW+1801)
                self.assertEqual(self.calls, [('send', name, 'deaf')] + ([('send', target, 'deaf')] if target else []))

    def test_all_rules_route_open_to_owner_and_escalation_to_supervisor(self):
        self.live()
        self.mail(16)
        self.mail(16, owner='lead/H/tools', subject='codex-run finished', sender='codex-run@hel8')
        self.data['drafts'] = [dict(mailbox='s/default', state='active')]
        self.add_run(owner='s/deploy', started=0, changed=0)
        self.add_run(run='finished', owner='lead/H/tools', ended=True)
        self.data['claims'] = [dict(subject='hel8-2', host='hel8', number='2', owner='lead/tools', created=0)]
        self.data['refs'] = {'ready/test': 'tip'}
        self.state['refs'] = {'ready/test': dict(tip='tip', since=0)}
        self.data['leases'] = [dict(subject='pkg:test', owner='lead/H/tools', since=0,
                                    waiters=[dict(owner='s/default', since=0)])]
        self.data['spool/sessions'] = [dict(kind='context-hook', name='lead/H/tools', time=ISO(0))]
        self.data['questions'] = [dict(subject='question', deadline=ISO(0))]
        self.data['spool/post-sent'] = [dict(id='failed', kind='send', time=ISO(NOW),
                                              **{'from': 'lead/tools', 'exit': 2})]
        candidates = self.judge()
        self.assertEqual({c['rule'] for c in candidates.values()}, set(API['RULES']) - {'waiter orphan', 'waiter dead'})
        for candidate in candidates.values():
            self.assertNotIn('first_to', candidate)
            self.assertEqual(candidate['escalate_to'], self.names[candidate['owner']]['supervisor'])
        self.round()
        self.calls.clear()
        self.round(NOW+20000)
        self.round(NOW+20001)
        escalations = [c for c in self.calls if c[0] == 'send']
        self.assertEqual(len(escalations), sum(bool(c['escalate_to']) for c in candidates.values()))

    def test_silent_catchup_migrates_legacy_and_ignores_cleared_conditions(self):
        self.data['questions'] = [dict(subject='old', deadline=ISO(0)), dict(subject='active', deadline=ISO(0))]
        self.round()
        # Legacy silent mode persisted notified/escalated as true without a mode marker.
        self.state.pop('posts_enabled')
        self.calls.clear()
        self.data['questions'].pop(0)
        candidates = self.judge()
        notices = []
        def send(kind, to, candidate):
            notices.append((kind, to, candidate))
            return 0
        for tick in (NOW+1, NOW+2, NOW+3):
            API['reconcile'](self.state, candidates, {}, self.config, tick, send)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0][2]['subject'], 'active')
        self.assertEqual(notices[0][2]['was_silent_since'], ISO(NOW))
        self.assertNotIn('question due\told', self.state['episodes'])

    def test_silent_overdue_catchup_posts_supervisor_once_with_retry_and_freeze(self):
        self.live('s/deploy')
        self.mail(11, owner='s/deploy')
        candidates = self.judge()
        for tick in (NOW, NOW+1801):
            API['reconcile'](self.state, candidates, {}, self.config, tick, self.action, post=False)
        self.calls.clear()
        notices = []
        def send(kind, to, candidate):
            notices.append((kind, to, candidate))
            return 2 if len(notices) == 1 else 3
        API['reconcile'](self.state, candidates, {'mail': 'unavailable'}, self.config, NOW+1802, send)
        self.assertEqual(notices, [])
        for tick in (NOW+1803, NOW+1804, NOW+1805):
            API['reconcile'](self.state, candidates, {}, self.config, tick, send)
        self.assertEqual([(kind, to) for kind, to, _ in notices], [('send', 'director')]*2)
        self.assertTrue(all(c['was_silent_since'] == ISO(NOW) for _, _, c in notices))

    def test_silent_recent_catchup_to_owner_then_normal_escalation(self):
        self.live()
        self.mail(11)
        candidates = self.judge()
        API['reconcile'](self.state, candidates, {}, self.config, NOW, self.action, post=False)
        self.calls.clear()
        API['reconcile'](self.state, candidates, {}, self.config, NOW+1, self.action)
        API['reconcile'](self.state, candidates, {}, self.config, NOW+2, self.action)
        self.assertEqual(self.calls, [('send', 'lead/tools', 'deaf')])
        API['reconcile'](self.state, candidates, {}, self.config, NOW+1801, self.action)
        self.assertEqual(self.calls[-1], ('send', 's/default', 'deaf'))

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
        self.live()
        self.data['agents'][0]['sessionId'] = 'old'
        first = ISO(NOW-1300)
        self.data['spool/sessions'] = [
            dict(kind='handover-needed', name='lead/tools', session='old', time=ISO(NOW-10),
                 first_fired=first, last_fired=ISO(NOW-10))]
        self.assertTrue(self.rule('handover late'))
        self.data['spool/sessions'].append(dict(kind='files-current', name='lead/tools', time=ISO(NOW-100)))
        self.assertFalse(self.rule('handover late'))

        self.data['spool/sessions'] = [self.data['spool/sessions'][0]]
        self.assertFalse(self.rule('handover late', NOW+15000))

    def test_post_sent_failures_retry_and_missing_stream_freeze(self):
        row = dict(id='send-fail', kind='send', time=ISO(NOW), message_id='mail',
                   **{'from': 's/default@hel8', 'exit': 2})
        self.data['spool/post-sent'] = [row]
        candidates = self.rule('delivery failed')
        self.assertEqual(len(candidates), 1)
        self.assertIn('spool/post-sent', candidates[0]['deps'])
        self.assertEqual(candidates[0]['owner'], 's/default')
        self.assertEqual(candidates[0]['escalate_to'], 'director')
        self.round()
        self.assertEqual(self.calls, [('send', 's/default', 'delivery failed')])
        self.data.pop('spool/post-sent')
        self.round(NOW+1, errors={'spool/post-sent': 'missing'})
        self.assertTrue(self.state['episodes'])
        self.data['spool/post-sent'] = [row, dict(row, id='send-ok', exit=0, time=ISO(NOW+1))]
        self.assertFalse(self.rule('delivery failed'))
        self.round(NOW+2)
        self.round(NOW+3)
        self.assertFalse(self.state['episodes'])

    def test_handover_and_delivery_survive_event_expiry_and_clear_on_new_evidence(self):
        self.live()
        self.data['agents'][0]['sessionId'] = 'old'
        self.data['spool/sessions'] = [dict(kind='handover-needed', name='lead/tools',
                    session='old', time=ISO(NOW-1300), first_fired=ISO(NOW-1300))]
        self.data['spool/post-sent'] = [dict(id='failed', kind='send', message_id='mail',
                    time=ISO(NOW), exit=2, **{'from':'s/default@hel8'})]
        self.assertTrue(self.rule('handover late'))
        self.assertTrue(self.rule('delivery failed'))
        self.data['spool/sessions'] = []
        self.data['spool/post-sent'] = []
        self.assertTrue(self.rule('handover late', NOW+7201))
        self.assertTrue(self.rule('delivery failed', NOW+7201))
        self.data['spool/sessions'] = [dict(kind='files-current', name='lead/tools', time=ISO(NOW+7202))]
        self.data['spool/post-sent'] = [dict(id='retry', kind='send', message_id='mail',
                    time=ISO(NOW+7202), exit=0, **{'from':'s/default@hel8'})]
        self.assertFalse(self.rule('handover late', NOW+7202))
        self.assertFalse(self.rule('delivery failed', NOW+7202))
        self.data['spool/sessions'] = []
        self.data['spool/post-sent'] = []
        self.assertFalse(self.rule('handover late', NOW+15000))
        self.assertFalse(self.rule('delivery failed', NOW+15000))

    def test_lease_and_attempt_facts_outlast_the_spool_window(self):
        self.data['leases'] = [dict(subject='pkg:example', owner='s/default',
                    since=ISO(NOW-18000), waiters=[dict(since=ISO(NOW+8000))])]
        self.data['spool/heavy'] = [dict(time=ISO(NOW), packages=['example'])]
        self.assertFalse(self.rule('lease stall'))
        self.data['spool/heavy'] = []
        self.assertFalse(self.rule('lease stall', NOW+10800))
        self.assertTrue(self.rule('lease stall', NOW+14401))
        self.data['refs'] = {'ready/tools/a':'tip'}
        self.data['spool/queue'] = [dict(kind='attempt', branch='ready/tools/a', tip='tip', time=ISO(NOW))]
        self.assertFalse([c for c in self.rule('unqueued') if c['subject']=='ready/tools/a'])
        self.data['spool/queue'] = []
        self.assertFalse([c for c in self.rule('unqueued', NOW+7201) if c['subject']=='ready/tools/a'])

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
        self.data['spool/post-sent'] = [dict(id='fixed-fail', kind='send', time=ISO(NOW),
                                             message_id='fixed-mail', **{'from': 'ops', 'exit': 2})]
        self.round()
        self.assertTrue(self.state['episodes'])
        self.data['names'] = {}
        for offset in (1, 2, 3):
            self.round(NOW+offset, errors={'names': 'unavailable'})
        self.assertTrue(self.state['episodes'])


class MailHealth(unittest.TestCase):
    setUp = Rules.setUp
    live = Rules.live
    mail = Rules.mail
    codex = Rules.codex
    add_run = Rules.add_run
    judge = Rules.judge
    rule = Rules.rule
    round = Rules.round
    action = Rules.action
    def test_one_episode_per_reader_many_runs_and_turn_evidence(self):
        self.codex(True)
        for i in range(20):
            self.add_run(run=f'run-{i}', ended=True)
            self.mail(16+i, subject=f'codex-run run-{i} complete', sender='codex-run@hel8')
        self.data['turn/lead/tools'] = dict(started=NOW-2200)
        candidate, = self.rule('report unread')
        self.assertEqual(candidate['subject'], 'lead/tools')
        self.assertIn('unread=20;', candidate['evidence'][0])
        self.assertIn('current_turn_s=2200', candidate['evidence'])
        for tick in (0, 120, 1800, 1801, 3600):
            self.round(NOW+tick)
        episodes = [e for e in self.state['episodes'].values() if e['rule'] == 'report unread']
        self.assertEqual(len(episodes), 1)
        self.assertEqual(self.calls, [('send', 'lead/tools', 'report unread'), ('send', 's/default', 'report unread')])

    def test_deaf_requires_idle_and_confirmed_saved_bypass(self):
        self.live()
        self.mail(11)
        agent = self.data['agents'][0]
        agent.update(cwd='/synthetic/start', state='done')
        self.data['saved'] = {'synthetic-session': dict(bypass=True, cwd=agent['cwd'])}
        self.assertIsNone(self.rule('deaf')[0]['remedy'])
        agent['status'] = 'idle'
        self.assertEqual(self.rule('deaf')[0]['remedy']['session'], 'synthetic-session')
        self.data['saved'] = {}
        self.assertIsNone(self.rule('deaf')[0]['remedy'])
        agent['status'] = 'waiting'
        self.assertIsNone(self.rule('deaf')[0]['remedy'])

    def test_gone_launcher_excludes_paused_retired_codex_and_fixed(self):
        identity = dict(role='lead', handle='q', area='jig')
        self.assertEqual(API['launch_role'](identity)['argv'], ['lead', 'q', 'jig'])
        self.assertEqual(API['launch_role'](dict(role='coordinator', handle='q'))['argv'], ['coordinator', 'q'])
        self.assertEqual(API['launch_role'](dict(role='director'))['argv'], ['director'])
        for flag in ({'paused':True}, {'retired':True}, {'kind':'codex'}, {'role':'fixed'}):
            self.assertIsNone(API['launch_role'](dict(identity, **flag)))

    def test_orphan_and_dead_waiter_actions(self):
        self.live()
        current = dict(pid=200, session='synthetic-session', alive=True,
                       process=dict(alive=True, ppid=100, start='1', verified=True))
        orphan = dict(pid=201, session='old', alive=True,
                      process=dict(alive=True, ppid=1, start='2', verified=True))
        dead = dict(pid=202, session='old', alive=False, process=dict(alive=False))
        box = dict(alive=True, session='synthetic-session', records=[current, orphan, dead])
        self.data['waiters']['lead/tools'] = box
        self.assertEqual(self.rule('waiter orphan')[0]['remedy']['pid'], 201)
        self.assertIsNone(self.rule('waiter dead')[0]['remedy'])
        box['records'] = [orphan]
        self.assertIsNone(self.rule('waiter orphan')[0]['remedy'])
        self.data['agents'] = []
        self.assertEqual(self.rule('waiter orphan')[0]['remedy']['pid'], 201)

    def test_stale_waiter_does_not_hide_deaf_successor_and_ops_unit_is_live(self):
        self.live()
        self.mail(11)
        self.data['waiters']['lead/tools'] = dict(alive=True, session='old', records=[dict(
            pid=201,session='old',alive=True,process=dict(alive=True,ppid=1,start='1',verified=True))])
        self.assertTrue(self.rule('deaf'))
        self.data['unit/ops'] = True
        self.data['waiters']['ops'] = dict(alive=True,session='-',records=[dict(
            pid=202,session='-',alive=True,process=dict(alive=True,ppid=1,start='1',verified=True))])
        self.assertFalse([c for c in self.rule('waiter orphan') if c['owner'] == 'ops'])

    def test_handover_old_owner_ack_before_fire_and_claude_successor(self):
        self.codex(True)
        fired = dict(kind='handover-needed', name='lead/tools', session_kind='codex-owner',
                     session='old-owner', time=ISO(NOW-1260), first_fired=ISO(NOW-1260))
        self.data['spool/sessions'] = [fired]
        self.data['spool/post'] = [dict(kind='mail', time=ISO(NOW-1380), subject='files current',
                                     **{'from':'lead/tools@hel8'})]
        self.assertFalse(self.rule('handover late'))
        self.data['spool/post'] = []
        self.state = {}
        self.data['agents'] = [dict(name='lead/tools', sessionId='claude-successor', state='working', status='busy')]
        self.assertFalse(self.rule('handover late'))
        self.data['agents'] = []
        self.data['unit/lead/tools'] = False
        self.assertFalse(self.rule('handover late'))

    def test_successful_remedy_escalates_only_after_thirty_minutes(self):
        self.live()
        self.mail(11)
        candidates = self.judge()
        candidates['deaf\tlead/tools']['remedy'] = dict(kind='resume')
        calls = []
        def action(kind, to, candidate):
            calls.append((kind, to))
            return dict(success=True) if kind == 'remedy' else 0
        for tick in (0, 120, 1800):
            API['reconcile'](self.state, candidates, {}, self.config, NOW+tick, action)
        self.assertEqual(calls, [('remedy', 'lead/tools')])
        API['reconcile'](self.state, candidates, {}, self.config, NOW+1801, action)
        self.assertEqual(calls[-1], ('send', 's/default'))


class Repairs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, HOME=str(self.home)).start()
        self.sid = '01234567-1234-1234-1234-123456789abc'
        self.cwd = str(self.home)
        self.agent = dict(sessionId=self.sid, cwd=self.cwd, state='done', status='idle')
        self.saved = self.home/'.claude/jobs/01234567/state.json'
        self.saved.parent.mkdir(parents=True)
        self.saved.write_text(json.dumps(dict(self.agent, respawnFlags=['--permission-mode','bypassPermissions'])))
        self.calls = []
        self.stopped = False
        self.resume_id = self.sid
        self.fail_dry = False
        self.pending = 1
        self.timeout = False
        def fake(argv, **kw):
            self.calls.append((argv, kw))
            stdout = ''
            rc = 0
            if argv[:2] == ['claude', 'agents']:
                if '--all' in argv:
                    self.pending -= 1
                    state = 'stopped' if self.stopped and self.pending < 0 and not self.timeout else 'blocked'
                    stdout = json.dumps([dict(self.agent, state=state)])
                else:
                    stdout = json.dumps([self.agent])
            elif argv[:2] == ['claude', 'stop']:
                self.stopped = True
            elif '--resume' in argv:
                self.assertLess(self.pending, 0)
                stdout = json.dumps(dict(session_id=self.resume_id))
            elif '--dry-run' in argv and self.fail_dry:
                rc = 1
            return subprocess.CompletedProcess(argv, rc, stdout, '')
        patch.dict(API['repair'].__globals__, command=fake).start()
        patch('time.sleep').start()
        self.plan = dict(kind='resume', session=self.sid, cwd=self.cwd, owner='lead/tools')

    def repair(self):
        return API['repair'](self.plan, dict(stop_timeout_seconds=60, stop_poll_seconds=1), 'session-start')

    def test_stop_waits_then_resumes_exact_id_and_argv(self):
        self.assertTrue(self.repair()['success'])
        argv, kw = self.calls[-1]
        self.assertEqual(argv, ['claude','--bg','--resume',self.sid,
            'Restart your post wait lead/tools in the background, post read lead/tools, and carry on.'])
        self.assertEqual(kw['cwd'], self.cwd)
        stop = next(kw for argv, kw in self.calls if argv[:2] == ['claude','stop'])
        self.assertEqual(stop['cwd'], self.cwd)
        self.assertEqual(sum('--all' in argv for argv, _ in self.calls), 2)

    def test_busy_or_unknown_bypass_never_stops(self):
        self.agent['status'] = 'busy'
        self.assertFalse(self.repair()['attempted'])
        self.agent['status'] = 'idle'
        self.saved.unlink()
        self.assertFalse(self.repair()['attempted'])
        self.assertFalse(any(argv[1:2] == ['stop'] for argv, _ in self.calls))

    def test_copy_is_stopped_and_failed_result_records_copy(self):
        self.resume_id = 'copy-session'
        result = self.repair()
        self.assertFalse(result['success'])
        self.assertEqual(result['copy_session'], 'copy-session')
        self.assertEqual(self.calls[-1][0], ['claude','stop','copy-session'])

    def test_stop_timeout_never_resumes(self):
        self.timeout = True
        with patch('time.monotonic', side_effect=[0, 0, 0, 61]):
            result = self.repair()
        self.assertFalse(result['success'])
        self.assertFalse(any('--resume' in argv for argv, _ in self.calls))

    def test_copy_waiter_cleanup_rechecks_other_reader_before_signal(self):
        self.agent['name'] = 'lead/tools'
        original_command = API['repair'].__globals__['command']
        records = [f'lead/tools 201 alive copy-session', f'lead/tools 202 alive {self.sid}']
        def command(argv, **kw):
            if argv == ['post','waiters']:
                return subprocess.CompletedProcess(argv,0,'\n'.join(records),'')
            return original_command(argv, **kw)
        def process(pid):
            return dict(alive=True,verified=True,start=str(pid),argv=['post','wait','lead/tools'])
        plan = dict(kind='kill',pid=201,start='201',owner='lead/tools',identity={})
        with patch.dict(API['repair'].__globals__, command=command, waiter_process=process), patch('os.kill') as kill:
            self.assertTrue(API['repair'](plan,{},'session-start')['success'])
            kill.assert_called_once_with(201,15)
            records.pop()
            kill.reset_mock()
            self.assertFalse(API['repair'](plan,{},'session-start')['attempted'])
            kill.assert_not_called()

    def test_saved_bypass_conflicts_and_identity_mismatch_refuse(self):
        for fields in (dict(respawnFlags=['--permission-mode','default']),
                       dict(respawnFlags=['--permission-mode','bypassPermissions','--permission-mode','default']),
                       dict(respawnFlags=['--model','opus']), dict(sessionId='wrong-id')):
            row = dict(self.agent,respawnFlags=['--dangerously-skip-permissions'])
            row.update(fields)
            self.saved.write_text(json.dumps(row))
            self.assertFalse(self.repair()['attempted'])
        self.assertFalse(any(argv[:2] == ['claude','stop'] for argv,_ in self.calls))

    def test_current_turn_metadata_is_correlated_with_completion_ledger(self):
        directory = self.home/'owner'
        directory.mkdir()
        (directory/'events.jsonl').write_text('\n'.join(json.dumps(row) for row in [
            dict(type='thread.started',thread_id='thread',ts=ISO(NOW-100)),
            dict(type='turn.started',ts=ISO(NOW-100))])+'\n')
        ledger = directory/'turns.tsv'
        ledger.write_text(f'{ISO(NOW-400)}\t{ISO(NOW-200)}\t0\t1\n')
        row = API['owner_turn'](dict(owner_state=str(directory)), 'ops')
        self.assertEqual(row['started'], NOW-100)
        self.assertEqual(row['thread'], 'thread')
        ledger.write_text(f'{ISO(NOW-100)}\t{ISO(NOW)}\t0\t1\n')
        self.assertIsNone(API['owner_turn'](dict(owner_state=str(directory)), 'ops')['started'])

    def test_gone_failed_dry_run_never_starts(self):
        self.fail_dry = True
        result = API['repair'](dict(kind='launch', argv=['coordinator','q']), {}, 'session-start')
        self.assertFalse(result['success'])
        self.assertEqual([argv for argv, _ in self.calls], [['session-start','coordinator','q','--dry-run']])


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


class Integration(RecordsSeed, unittest.TestCase):
    seed_files = dict(RecordsSeed.seed_files, **{
        f'events/{source}/README.md': '# Synthetic\n'
        for source in ('queue', 'heavy', 'sessions', 'post', 'post-sent')})

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
        self.copy_records_seed()
        self.tmp = self.home / 'src/rust/tmp'
        self.write(self.tmp / 'post/machines', 'hel8 local\nbuilder fake.invalid\n')
        (self.tmp / 'codex-run').mkdir(parents=True)
        self.write(self.tmp / 'heavy/state.json', '{"tasks":{}}')
        inventory = subprocess.run([str(TOOL.parents[1] / 'session/start'), 'names', '--json'],
                                   env=dict(os.environ, RECORDS_REPO=str(self.home/'records')),
                                   text=True, capture_output=True)
        self.assertEqual(inventory.returncode, 0, inventory.stderr)
        # Exercise Codex owners explicitly, independent of active registry choices.
        rows = json.loads(inventory.stdout)
        for row in rows:
            if row.get('role') == 'lead' and row.get('handle') == 'u':
                row.update(kind='codex', unit='codex-owner-lead-u-' + row['area'],
                           owner_state=str(self.tmp / 'owners' / row['area'] / 'codex'))
                row.pop('start_dir', None)
        self.write(self.home / 'names.json', json.dumps(rows))
        self.write(self.home / 'agents.json', '[]')
        self.write(self.home / 'refs', '')
        self.write(self.home / 'claims', '')
        self.write(self.home / 'waiters', '')
        self.write(self.home / 'leases', '[]')
        self.write(self.home / 'remote', json.dumps(dict(runs=[], heavy=[], errors=[], spools={s: [] for s in API['EVENT_SOURCES']})))
        self.env = dict(os.environ, PATH=str(self.bin)+os.pathsep+os.environ['PATH'],
                        RECORDS_REPO=str(self.home / 'records'), RECORDS_ORIGIN=str(self.origin))
        self.fake('systemctl', "import os, sys\nassert sys.argv[1:4] == ['--user', 'is-active', '--quiet']\nsys.exit(int(os.environ.get('UNIT_EXIT', '3')))\n")
        self.fake('post', """from pathlib import Path
import os,sys
home=Path(os.environ['HOME'])
if sys.argv[1]=='waiters': print((home/'waiters').read_text(),end='')
else:
 with (home/'post.log').open('a') as out: out.write(__import__('json').dumps(sys.argv[1:])+'\\n')
 if sys.argv[1]=='send':
  with (home/'bodies.log').open('a') as out: out.write(__import__('json').dumps(sys.stdin.read())+'\\n')
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
            suffix = """rows=__import__('json').loads((Path(os.environ['HOME'])/'agents.json').read_text())
rows.append(dict(name='director',sessionId='fixture-director',state='working',status='busy'))
print(__import__('json').dumps(rows))
""" if name == 'claude' else f"print((Path(os.environ['HOME'])/{file!r}).read_text(),end='')\n"
            self.fake(name, f"import os,sys\nfrom pathlib import Path\nif os.environ.get('FAIL_INPUT')=={name!r}: sys.exit(2)\n" + suffix)
        self.fake('git', f"import os,sys\nfrom pathlib import Path\nif sys.argv[1]=='ls-remote' and sys.argv[-1]=='refs/heads/ready/*': print((Path(os.environ['HOME'])/'refs').read_text(),end='')\nelse: os.execv({self.real_git!r}, [{self.real_git!r}]+sys.argv[1:])\n")
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
            'post = true', 'post = true' if post else 'post = false'))
        wrapper = ("import runpy,sys\nfrom unittest.mock import patch\nsys.argv=sys.argv[1:]\n"
                   f"with patch('time.time', return_value={NOW}):\n api=runpy.run_path(sys.argv[0])\n sys.exit(api['main']())")
        result = subprocess.run(['python3', '-I', '-B', '-c', wrapper, str(TOOL), '--once', '--config', str(config)] + (['--dry-run'] if dry else []),
                                env=dict(self.env, **env), capture_output=True, text=True)
        self.assertEqual(result.returncode, code, result.stdout+result.stderr)
        return result
    def mail(self):
        self.write(self.home/'agents.json', '[{"name":"lead/jig","sessionId":"session","status":"busy"}]')
        path = self.write(self.tmp/'post/lead+jig/new/synthetic.md',
                          'Id: synthetic\nFrom: test@hel8\nTo: lead/jig@hel8\nSubject: synthetic\n\nPRIVATE BODY MUST NEVER APPEAR\n')
        old = NOW-660
        os.utime(path, (old, old))
        return path
    def state(self):
        return json.loads((self.home/'.local/state/watch/state.json').read_text())
    def events(self):
        return [json.loads(line) for path in (self.home/'src/fabrig/events/watch').glob('*.jsonl') for line in path.read_text().splitlines()]


    def test_dry_run_no_state_no_posts_no_append_no_clone(self):
        self.mail()
        before = self.git('--git-dir', str(self.origin), 'rev-parse', 'main')
        result = self.invoke(dry=True)
        self.assertIn("would post send --as watch lead/jig", result.stdout)
        self.assertIn('"kind": "alert-open"', result.stdout)
        self.assertNotIn('PRIVATE BODY', result.stdout)
        self.assertFalse((self.home/'.local').exists())
        self.assertFalse((self.home/'records').exists())
        self.assertFalse((self.home/'post.log').exists())
        self.assertEqual(self.git('--git-dir', str(self.origin), 'rev-parse', 'main'), before)


    def test_spool_failure_retains_outbox_without_repeating_wake(self):
        self.mail()
        spool = self.home/'src/fabrig/events/watch'
        spool.parent.mkdir(parents=True, exist_ok=True)
        spool.write_text('block the source directory')
        self.assertIn('spool failed', self.invoke(code=2).stderr)
        saved = {e['id'] for e in self.state()['pending']}
        self.assertTrue(saved)
        spool.unlink()
        self.invoke()
        self.assertFalse(self.state()['pending'])
        self.assertTrue(saved <= {e['id'] for e in self.events()})
        self.assertEqual((self.home/'post.log').read_text().count('send'), 1)


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
        self.assertEqual(API['waiters']('lead/jig 123 dead session')['lead/jig']['alive'], False)
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


if __name__ == '__main__':
    unittest.main()
