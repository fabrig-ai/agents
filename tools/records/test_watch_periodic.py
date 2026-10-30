"""Full CLI/lifecycle matrices; isolated periodic coverage."""
from test_watch import *
import test_watch as fixture


class PeriodicIntegration(Integration):
    def test_gone_part_lifecycle_for_claude_and_codex(self):
        draft = self.seed / 'drafts/experiment'
        for kind, name, handle, coordinator in (
                ('claude', 'lead/jig', 'dm', 's/dynamic-memory'),
                ('codex', 'lead/u/jig', 'u', 's/upgrades')):
            with self.subTest(kind=kind):
                self.write(draft / 'draft.toml',
                           f'mailbox="{coordinator}"\ncoordinator="{handle}"\nstate="active"\n')
                part = draft / 'parts/jig-parser'
                brief = part / 'brief.md'
                closing = part / 'closing.toml'
                brief.unlink(missing_ok=True)
                closing.unlink(missing_ok=True)
                post_events = self.home / 'src/fabrig/events/post/2026-10-29.jsonl'
                post_events.unlink(missing_ok=True)
                scratch = self.home / 'src/fabrig/leads' / ('jig' if kind == 'claude' else 'u-jig')

                def publish():
                    self.git('-C', str(self.seed), 'add', '.')
                    self.git('-C', str(self.seed), 'commit', '-m', 'synthetic part state')
                    self.git('-C', str(self.seed), 'push', 'origin', 'main')

                def gone():
                    result = self.invoke(dry=True, UNIT_EXIT='3')
                    return [row for line in result.stdout.splitlines() if line.startswith('{')
                            and (row := json.loads(line)).get('rule') == 'gone' and row.get('owner') == name]

                # Registered but never started: neither a scratch brief nor a part brief.
                publish()
                self.assertFalse((scratch / 'brief.md').exists())
                self.assertEqual(gone(), [])
                # An unfinished records part expects a running lead of either kind.
                self.write(brief, 'Synthetic unfinished jig part.\n')
                self.write(scratch / 'brief.md', 'Work on jig-parser.\n')
                self.write(scratch / 'state.md', 'Part jig-parser is in progress.\n')
                publish()
                self.assertTrue(gone())
                # Files current with a handed-over/open part still needs a successor.
                self.write(post_events, json.dumps(dict(id='synthetic-ack', source='post', host='hel8', kind='mail', time=ISO(NOW),
                           subject='files current', **{'from': name+'@hel8', 'to': coordinator+'@hel8'}))+'\n')
                self.write(closing, 'outcome="handed-over"\nopen=["remaining work"]\n')
                publish()
                self.assertTrue(gone())
                # Completion is authoritative even while inherited scratch files remain.
                self.write(closing, 'outcome="done"\nopen=[]\n')
                self.write(scratch / 'state.md', 'Part jig-parser is done; files current posted.\n')
                publish()
                self.assertTrue((scratch / 'brief.md').exists())
                self.assertEqual(gone(), [])

    def test_codex_cli_reads_unit_and_sends_deaf_to_owner(self):
        path = self.write(self.tmp/'post/lead+u+jig/new/owner-mail.md',
                          'Id: owner-mail\nFrom: test@hel8\nTo: lead/u/jig@hel8\nSubject: synthetic\n\n')
        old = NOW-660
        os.utime(path, (old, old))
        # Unit liveness is independent of Claude availability.
        active = self.invoke(dry=True, UNIT_EXIT='0', FAIL_INPUT='claude')
        self.assertNotIn('deaf lead/u/jig', active.stdout)
        inactive = self.invoke(dry=True, UNIT_EXIT='3', FAIL_INPUT='claude')
        self.assertIn("would post send --as watch lead/u/jig 'watch: deaf lead/u/jig'", inactive.stdout)
        self.assertNotIn('post wake lead/u/jig', inactive.stdout)
        failed = self.invoke(dry=True, UNIT_EXIT='1')
        self.assertNotIn('watch: deaf lead/u/jig', failed.stdout)
        heartbeat = next(json.loads(line) for line in failed.stdout.splitlines()
                         if line.startswith('{') and json.loads(line).get('kind') == 'heartbeat')
        self.assertIn('unit/lead/u/jig', heartbeat['inputs_failed'])

    def test_cli_events_state_modes_dedup_close_and_recurrence(self):
        mail = self.mail()
        self.invoke()
        self.invoke()
        events = self.events()
        self.assertEqual(sum(e['kind']=='alert-open' for e in events), 1)
        self.assertEqual(sum(e['kind']=='heartbeat' for e in events), 1)
        self.assertEqual(json.loads((self.home/'post.log').read_text()), ['send', '--as', 'watch', 'lead/jig', 'watch: deaf lead/jig'])
        state = self.home/'.local/state/watch/state.json'
        self.assertEqual(state.stat().st_mode & 0o777, 0o600)
        self.assertTrue(next(iter(self.state()['episodes'].values()))['notified'])
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
        self.assertTrue(tomllib.loads(TOOL.with_suffix('.toml').read_text())['alerts']['post'])
        self.mail()
        self.write(self.home/'remote', json.dumps({'runs': [dict(
            run='hung', owner='lead/jig', cwd='/synthetic/slots/1', started=0, changed=0, effort='high', ended=False)], 'heavy': [], 'errors': [], 'spools': {s: [] for s in API['EVENT_SOURCES']}}))
        result = self.invoke(post=False)
        self.assertIn('would post send --as watch lead/jig', result.stdout)
        self.assertIn('would post send --as watch lead/jig', result.stdout)
        self.assertNotIn('PRIVATE BODY', result.stdout)
        self.assertFalse((self.home/'post.log').exists())
        events = self.events()
        self.assertTrue(any(e['kind'] == 'alert-open' for e in events))
        self.assertEqual(events[-1]['kind'], 'heartbeat')
        self.assertFalse(next(e for e in events if e.get('rule') == 'deaf').get('remedy_attempts', 0))
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

    def test_cli_open_and_escalation_destinations_evidence_and_dedup(self):
        owners = ['lead/jig', 's/qa', 'ops', 's/deploy']
        self.write(self.home/'remote', json.dumps({'runs': [dict(
            run=owner.replace('/', '-'), owner=owner, cwd='/synthetic', started=0,
            changed=0, effort='high', ended=False) for owner in owners], 'heavy': [], 'errors': [], 'spools': {s: [] for s in API['EVENT_SOURCES']}}))
        self.invoke()
        sends = [json.loads(line) for line in (self.home/'post.log').read_text().splitlines()]
        self.assertEqual({a[3] for a in sends}, set(owners))
        self.assertTrue(all(a[:3] == ['send', '--as', 'watch'] for a in sends))
        state = self.state()
        for episode in state['episodes'].values():
            episode['opened'] -= 1800
        self.write(self.home/'.local/state/watch/state.json', json.dumps(state))
        self.invoke()
        self.invoke()
        sends = [json.loads(line) for line in (self.home/'post.log').read_text().splitlines()]
        self.assertEqual(len(sends), 8)
        expected = {e['subject']: e['supervisor'] for e in self.events() if e['kind'] == 'alert-escalate'}
        self.assertEqual(len(expected), 4)
        bodies = [json.loads(line) for line in (self.home/'bodies.log').read_text().splitlines()]
        for argv, body in zip(sends[4:], bodies[4:]):
            subject = argv[4].removeprefix('watch: run hung ')
            self.assertEqual(argv[3], expected[subject])
            self.assertLessEqual(len(body.splitlines()), 6)
            self.assertIn('output unchanged since', body)
            self.assertIn('elapsed_s=', body)

    def test_cli_silent_to_live_catchup_is_marked_and_not_repeated(self):
        mail = self.mail()
        self.write(self.home/'remote', json.dumps({'runs': [dict(
            run='hung', owner='s/deploy', cwd='/synthetic', started=0, changed=0,
            effort='high', ended=False)], 'heavy': [], 'errors': [], 'spools': {s: [] for s in API['EVENT_SOURCES']}}))
        self.invoke(post=False)
        state = self.state()
        for episode in state['episodes'].values():
            episode['opened'] -= 3600
            # Simulate the already deployed silent state schema.
            episode.pop('silent_since')
            episode['escalated'] = True
        state.pop('posts_enabled')
        self.write(self.home/'.local/state/watch/state.json', json.dumps(state))
        mail.unlink()
        self.invoke()
        self.invoke()
        sends = [json.loads(line) for line in (self.home/'post.log').read_text().splitlines()]
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0][3], 'director')
        self.assertEqual(sends[0][4], 'watch: run hung builder/hung')
        body = json.loads((self.home/'bodies.log').read_text())
        self.assertIn('(was silent since ', body)
        self.assertFalse(any(e['rule'] == 'deaf' for e in self.state()['episodes'].values()))

    def test_alerts_and_heartbeat_leave_records_remote_untouched(self):
        before = self.git('--git-dir', str(self.origin), 'rev-parse', 'main')
        mail = self.mail()
        self.invoke()
        self.assertTrue(self.events())
        mail.unlink()
        self.invoke()
        self.invoke()
        self.assertTrue(any(e['kind'] == 'alert-close' for e in self.events()))
        self.assertEqual(self.git('--git-dir', str(self.origin), 'rev-parse', 'main'), before)

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

    def test_local_and_remote_spools_and_named_probe_failure(self):
        local = dict(id='local', source='queue', host='hel8', kind='batch', time=ISO(NOW-60))
        remote = dict(id='remote', source='queue', host='builder', kind='attempt', time=ISO(NOW-30))
        self.write(self.home/'src/fabrig/events/queue/2026-10-29.jsonl', json.dumps(local)+'\n')
        reply = dict(runs=[], heavy=[], errors=[], spools={s: [] for s in API['EVENT_SOURCES']})
        reply['spools']['queue'] = [remote, dict(remote, id='expired', time=ISO(NOW-7260))]
        self.write(self.home/'remote', json.dumps(reply))
        with patch.dict(os.environ, self.env), patch('time.time', return_value=NOW):
            inputs = API['Inputs'](False).collect(self.home/'records')
        self.assertEqual([r['id'] for r in inputs.data['spool/queue']], ['local', 'remote'])
        reply['spools']['queue'] = [dict(remote, time='invalid')]
        self.write(self.home/'remote', json.dumps(reply))
        with patch.dict(os.environ, self.env), patch('time.time', return_value=NOW):
            inputs = API['Inputs'](False).collect(self.home/'records')
        self.assertIn('spool/queue/builder', inputs.errors)
        self.assertIn('spool/heavy', inputs.data)
        self.invoke(FAIL_INPUT='ssh')
        failed = self.events()[-1]['inputs_failed']
        self.assertIn('spool/queue/builder', failed)
        self.assertIn('builder', failed['spool/queue'])

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

    def test_sibling_resolution_and_heartbeat_paths(self):
        original_tool = fixture.TOOL
        self.env['PATH'] = str(self.bin) + os.pathsep + '/usr/bin:/bin'
        release = self.home / 'release/tools'
        helper = release / 'session/session_lib.py'
        helper.parent.mkdir(parents=True)
        shutil.copy2(TOOL.parents[1] / 'session/session_lib.py', helper)
        for name in ('watch', 'record', 'watch.toml', 'event_spool.py'):
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
            fixture.TOOL = release / 'records/watch'
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
                    self.assertEqual({key: heartbeat['inputs'][key] for key in expected}, expected)
                    self.assertFalse(heartbeat['inputs_failed'])
                    self.assertIn('would post send --as watch lead/jig', result.stdout)
            calls = [json.loads(line) for line in (self.home / 'launcher.log').read_text().splitlines()]
            self.assertIn(['names', '--json'], calls)
            self.assertIn(['owns', 'lead/jig'], calls)
        finally:
            fixture.TOOL = original_tool

    def test_records_fetch_only_when_main_changes_and_all_git_uses_multiplexing(self):
        self.fake('git', f"""import json,os,sys
from pathlib import Path
home=Path(os.environ['HOME'])
with (home/'git.log').open('a') as out:
 out.write(json.dumps(dict(argv=sys.argv[1:],ssh=os.environ.get('GIT_SSH_COMMAND')))+'\\n')
if sys.argv[1]=='ls-remote' and sys.argv[-1]=='refs/heads/ready/*':
 print((home/'refs').read_text(),end='')
else: os.execv({self.real_git!r}, [{self.real_git!r}]+sys.argv[1:])
""")
        self.invoke()
        def fetches():
            return [r for line in (self.home/'git.log').read_text().splitlines()
                    if 'fetch' in (r := json.loads(line))['argv']]
        first = len(fetches())
        self.assertGreater(first, 0)
        self.invoke()
        self.assertEqual(len(fetches()), first)
        self.write(self.seed/'README.md', '# Changed synthetic records\n')
        self.git('-C',str(self.seed),'add','README.md')
        self.git('-C',str(self.seed),'commit','-m','synthetic main moved')
        self.git('-C',str(self.seed),'push','origin','main')
        self.invoke()
        self.assertEqual(len(fetches()), first+1)
        network = [json.loads(line) for line in (self.home/'git.log').read_text().splitlines()
                   if any(arg in ('ls-remote','fetch','clone') for arg in json.loads(line)['argv'])]
        self.assertTrue(network)
        for row in network:
            for option in ('ControlMaster=auto','ControlPersist=600',str(self.home/'.local/state/watch/ssh-%C')):
                self.assertIn(option,row['ssh'])

    def test_cli_deaf_stop_then_resume_without_permission_flags_and_same_cwd(self):
        self.mail()
        sid = '01234567-1234-1234-1234-123456789abc'
        agent = dict(name='lead/jig',sessionId=sid,cwd=str(self.home),state='done',status='idle')
        self.write(self.home/'agents.json', json.dumps([agent]))
        self.write(self.home/'.claude/jobs/01234567/state.json',json.dumps(agent))
        self.fake('claude', """import json,os,sys
from pathlib import Path
home=Path(os.environ['HOME'])
agent=json.loads((home/'agents.json').read_text())[0]
with (home/'claude.log').open('a') as out:
 out.write(json.dumps(dict(argv=sys.argv[1:],cwd=os.getcwd()))+'\\n')
if sys.argv[1]=='agents':
 if '--all' in sys.argv and (home/'stopped').exists(): agent['state']='stopped'
 print(json.dumps([agent,dict(name='director',sessionId='fixture-director',state='working',status='busy')]))
elif sys.argv[1]=='stop': (home/'stopped').touch()
elif sys.argv[1:3]==['--bg','--resume']:
 assert (home/'stopped').exists()
 print(json.dumps(dict(session_id=agent['sessionId'])))
else: sys.exit(2)
""")
        self.invoke()
        self.invoke()
        rows = [json.loads(line) for line in (self.home/'claude.log').read_text().splitlines()]
        actions = [r for r in rows if r['argv'][0] != 'agents']
        self.assertEqual([r['argv'][:3] for r in actions], [['stop',sid],['--bg','--resume',sid]])
        self.assertTrue(all(r['cwd'] == str(self.home) for r in actions))
        self.assertEqual(sum(e['kind']=='remedy' for e in self.events()),1)
        self.assertFalse((self.home/'post.log').exists())


    def test_writer_watch_append_only(self):
        record = TOOL.with_name('record')
        row = dict(id='synthetic', time=ISO(NOW), source='watch', host='hel8', kind='heartbeat')
        result = subprocess.run([str(record),'append','--as','watch','watch','hel8'], input=json.dumps(row)+'\n',
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        result = subprocess.run([str(record),'write','--as','watch','README.md'], input='# Refused\n',
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('invalid writer', result.stderr)



def load_tests(loader, tests, pattern):
    classes = (PeriodicIntegration,)
    return unittest.TestSuite(cls(name) for cls in classes
                              for name in cls.__dict__ if name.startswith("test_"))
