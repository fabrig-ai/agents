"""Full CLI/lifecycle matrices; isolated periodic coverage."""
from test_record_collect import *


class PeriodicCollectTests(CollectTests):
    def run_collect(self, *sources, **kwargs):
        return self.run_collect_cli(*sources, **kwargs)

    def test_heavy_multiline_rows_keep_identity_and_replay_after_rotation(self):
        self.heavy_fixture()
        path = self.tmp / 'logs/heavy.tsv'
        normal = path.read_text()
        expected, = self.dry('heavy')
        multiline = normal.replace('example-check', 'for item in 1 2 3; do\nstep one\nstep two\ndone')
        self.write(path, multiline)
        result = self.run_collect('heavy')
        self.assertIn('heavy: skipped 0 malformed rows', result.stderr)
        self.assertEqual(self.events('heavy'), [expected])
        self.assertEqual(self.cursor('heavy')['files'][str(path)]['offset'], len(multiline.encode()))
        replacement = self.write(path.with_suffix('.new'), normal)
        replacement.replace(path)
        self.assertIn('heavy: 0 events', self.run_collect('heavy').stderr)
        self.assertEqual(self.events('heavy'), [expected])

    def test_codex_unit_lifecycle_context_and_threshold_crossings(self):
        self.codex_fixture()
        # A stale Claude row with the same name must never be measured.
        self.session_fixture('lead/u/jig')
        self.run_collect('sessions')
        start, = self.events('sessions')
        self.assertEqual(start['kind'], 'session-start')
        self.assertEqual(start['session_kind'], 'codex-owner')
        self.assertEqual(start['unit'], 'codex-owner-lead-u-jig')
        self.assertEqual(self.dry('sessions'), [])
        self.owner_reading(85, 3)
        first_preview = self.dry('sessions')
        second_preview = self.dry('sessions')
        first_hook = next(e for e in first_preview if e['kind'] == 'handover-needed')
        self.assertEqual(first_hook['id'], next(e for e in second_preview if e['kind'] == 'handover-needed')['id'])
        self.run_collect('sessions')
        hooks = lambda: [e for e in self.events('sessions') if e['kind'] == 'handover-needed']
        self.assertEqual(len(hooks()), 1)
        self.assertEqual(hooks()[0]['id'], first_hook['id'])
        self.assertEqual([e['kind'] for e in self.dry('sessions')], [])
        # The exit status, rather than rounded output, decides crossing.
        self.owner_reading(85, 0)
        self.run_collect('sessions')
        self.owner_reading(85, 3)
        self.run_collect('sessions')
        self.assertEqual(len(hooks()), 2)
        self.assertNotEqual(hooks()[0]['id'], hooks()[1]['id'])
        # A fresh owner thread above threshold begins its own crossing.
        self.owner_reading(90, 3, thread='ffffffff')
        self.run_collect('sessions')
        self.assertEqual(len(hooks()), 3)
        self.write(self.home / 'unit-exit', '3')
        self.run_collect('sessions')
        ends = [e for e in self.events('sessions') if e['kind'] == 'session-end']
        self.assertEqual(len(ends), 1)
        self.assertEqual(ends[0]['session'], start['session'])
        self.assertEqual(ends[0]['session_kind'], 'codex-owner')
        self.run_collect('sessions')
        self.assertEqual(sum(e['kind'] == 'session-end' for e in self.events('sessions')), 1)
        self.write(self.home / 'unit-exit', '0')
        self.run_collect('sessions')
        starts = [e for e in self.events('sessions') if e['kind'] == 'session-start']
        self.assertEqual(len(starts), 2)
        self.assertNotEqual(starts[0]['session'], starts[1]['session'])

    def test_optional_fired_capability_preserves_session_lifecycle(self):
        original = (self.bin / 'session-context').read_text().split('\n', 1)[1]
        for capability in ("print('hook-gating')", 'sys.exit(2)'):
            with self.subTest(capability=capability):
                self.fake('session-context', original.replace("print('fired-markers')", capability).replace(
                    "if sys.argv[1:] == ['--fired', '--json']:",
                    "if sys.argv[1:] == ['--fired', '--json']:\n raise AssertionError('must not request fired markers')"))
                self.session_fixture()
                result = self.run_collect('sessions', options=('--dry-run',))
                self.assertIn('skip sessions/fired:', result.stderr)
                self.assertEqual([json.loads(line)['kind'] for line in result.stdout.splitlines()],
                                 ['session-start'])
                self.run_collect('sessions')
                self.session_fixture('coordinator/H/next')
                self.run_collect('sessions')
                self.json(self.home / 'agents.json', [])
                self.run_collect('sessions')
                self.assertEqual([e['kind'] for e in self.events('sessions')],
                                 ['session-start', 'session-name', 'session-end'])
                # Reset only the isolated fixture for the next capability case.
                shutil.rmtree(self.fabrig / 'events/sessions')
                for path in self.state.iterdir():
                    path.unlink()

    def test_dry_run_all_sources_writes_nothing(self):
        self.runs_fixture()
        self.queue_fixture()
        self.heavy_fixture()
        self.session_fixture()
        self.lease_fixture()
        self.post_fixture()
        self.post_sent_fixture()
        events = self.dry(*API['SOURCES'])
        self.assertEqual(set(e['source'] for e in events), set(API['SOURCES']))
        self.assertFalse(self.state.exists())
        self.assertFalse(self.clone.exists())
        before = self.git(self.origin, 'rev-parse', 'main')
        self.run_collect(*API['SOURCES'])
        self.assertFalse(self.clone.exists())
        self.assertEqual(self.git(self.origin, 'rev-parse', 'main'), before)
        for source in API['SOURCES']:
            self.assertTrue(self.events(source))
        cursors = {p: p.read_bytes() for p in self.state.iterdir()}
        self.dry(*API['SOURCES'])
        self.assertEqual(cursors, {p: p.read_bytes() for p in self.state.iterdir()})

    def test_post_sent_missing_partial_retry_rotation_and_hash_only(self):
        self.assertIn('skip post-sent', self.run_collect('post-sent').stdout)
        row = self.post_sent_fixture()
        path = self.tmp / 'post/sent.jsonl'
        success = dict(row, time=END, exit=0)
        encoded = json.dumps(success)
        self.write(path, json.dumps(row) + '\n' + encoded[:20])
        self.run_collect('post-sent')
        failed, = self.events('post-sent')
        self.assertEqual((failed['kind'], failed['exit'], failed['message_id']), ('send', 2, MESSAGE))
        self.assertEqual(failed['subject_sha256'], 'a' * 64)
        self.assertNotIn('subject', failed)
        self.assertNotIn('body', failed)
        self.assertIn('post-sent: 0 events', self.run_collect('post-sent').stderr)
        self.write(path, path.read_text() + encoded[20:] + '\n')
        self.run_collect('post-sent')
        self.assertEqual([e['exit'] for e in self.events('post-sent')], [2, 0])
        replacement = path.with_name('sent.new')
        self.write(replacement, json.dumps(row) + '\n' + encoded + '\n')
        replacement.replace(path)
        self.assertIn('post-sent: 0 events', self.run_collect('post-sent').stderr)

    def test_fired_first_updates_replay_and_lead_end_ack_drive_watch(self):
        import tomllib
        watch = runpy.run_path(str(TOOL.with_name('watch')))
        config = tomllib.loads(TOOL.with_name('watch.toml').read_text())['rules']
        self.session_fixture()
        marker = dict(session_id=SESSION, name='lead/H/tools', role='lead', reason='threshold',
                      first_fired=STAMP, last_fired=STAMP)
        self.json(self.home / 'fired.json', [marker])
        self.run_collect('sessions')
        hooks = lambda: [e for e in self.events('sessions') if e['kind'] == 'handover-needed']
        first, = hooks()
        self.assertEqual(first['time'], STAMP)
        self.assertEqual(first['session'], SESSION)
        self.run_collect('sessions')
        self.assertEqual(len(hooks()), 1)
        marker['last_fired'] = END
        self.json(self.home / 'fired.json', [marker])
        self.run_collect('sessions')
        self.assertEqual(len(hooks()), 2)
        self.assertNotEqual(hooks()[0]['id'], hooks()[1]['id'])
        self.assertEqual(hooks()[1]['first_fired'], STAMP)
        data = dict(names={'lead/H/tools': dict(role='lead', supervisor='s/example')},
                    owned={'lead/H/tools': True}, **{'spool/sessions': self.events('sessions')})
        now = API['timestamp'](STAMP).timestamp() + 1300
        late = lambda: [c for c in watch['evaluate'](data, {}, config, now).values()
                        if c['rule'] == 'handover late']
        self.assertEqual(len(late()), 1)
        episodes = {}
        events = watch['reconcile'](episodes, watch['evaluate'](data, {}, config, now),
                                    {'spool/post': 'absent'}, config, now, lambda *args: 0)
        self.assertEqual([e['kind'] for e in events], ['alert-open'])
        # Replaying from a fresh cursor must not duplicate append-only hook facts.
        (self.state / 'sessions.json').unlink()
        self.run_collect('sessions')
        self.assertEqual(len(hooks()), 2)
        mail = self.post_fixture()
        self.write(mail, mail.read_text().replace('From: s/example@hel8', 'From: lead/H/tools@hel8')
                   .replace('Subject: Synthetic status', 'Subject: files current: closing complete'))
        seconds = API['timestamp'](END).timestamp()
        os.utime(mail, (seconds, seconds))
        self.run_collect('sessions')
        ack, = [e for e in self.events('sessions') if e['kind'] == 'files-current']
        self.assertEqual(ack['name'], 'lead/H/tools')
        self.assertEqual(ack['message_id'], MESSAGE)
        data['spool/sessions'] = self.events('sessions')
        self.assertFalse(late())
        self.run_collect('sessions')
        self.assertEqual(sum(e['kind'] == 'files-current' for e in self.events('sessions')), 1)



def load_tests(loader, tests, pattern):
    classes = (PeriodicCollectTests,)
    return unittest.TestSuite(cls(name) for cls in classes
                              for name in cls.__dict__ if name.startswith("test_"))
