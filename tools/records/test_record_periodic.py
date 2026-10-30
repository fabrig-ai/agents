"""Full CLI/lifecycle matrices; isolated periodic coverage."""
from test_record import *


class PeriodicRecordTests(RecordTests):
    def run_record(self, *args, **kwargs):
        return super().run_record(*args, cli=True, **kwargs)

    def test_rewritten_history_guard_reset_archives_and_keeps_untracked(self):
        path = self.seed / 'events/queue/hel8/2026-10-29.jsonl'
        path.parent.mkdir(parents=True)
        path.write_bytes(self.event().replace(b'after-landing', b'queue'))
        self.seed_commit('old collector')
        self.prepare()
        (self.clone / 'AGENTS.md').write_text('# Unpublished local judgement\n')
        self.git(self.clone, 'add', '.')
        self.git(self.clone, 'commit', '-m', 'local judgement')
        old = self.git(self.clone, 'rev-parse', 'HEAD')
        new = self.rewrite_origin()
        refused = self.run_record('pull', code=1)
        self.assertIn(b'records history was rewritten upstream; run `record reset`', refused.stderr)
        self.assertEqual(self.git(self.clone, 'rev-parse', 'HEAD'), old)
        (self.clone / 'scratch.txt').write_bytes(b'keep this untracked file')
        reset = self.run_record('reset')
        self.assertIn(old.encode() + b' -> ' + new.encode(), reset.stdout)
        self.assertIn(b'saved 3 local-only commits', reset.stdout)
        archive_root = self.home / 'src/fabrig/archive'
        archive, = archive_root.iterdir()
        patches = sorted(archive.glob('*.patch'))
        self.assertEqual(len(patches), 3)
        self.assertEqual((archive / 'commits.txt').read_text().splitlines()[-1], old)
        # The patches restore all original bytes, including the unpublished judgement.
        restored = self.home / 'restored'
        self.git(self.home, 'init', str(restored))
        self.git(restored, 'am', *(str(p) for p in patches))
        self.assertEqual(self.git(restored, 'rev-parse', 'HEAD^{tree}'),
                         self.git(self.clone, 'rev-parse', old + '^{tree}'))
        self.assertEqual((self.clone / 'scratch.txt').read_bytes(), b'keep this untracked file')
        self.assertFalse((self.clone / 'events').exists())
        self.assertEqual(self.git(self.clone, 'rev-parse', 'HEAD'), new)
        again = self.run_record('reset')
        self.assertIn(b'saved 0 local-only commits', again.stdout)
        self.assertIn(new.encode() + b' -> ' + new.encode(), again.stdout)
        self.assertEqual(len(list(archive_root.iterdir())), 2)
        (self.clone / 'scratch.txt').unlink()
        self.run_record('write', '--as', 'ops', 'README.md', data=b'# Normal push after reset\n')
        self.assert_clean()


    def test_history_guard_threshold_and_durable_events_exception(self):
        self.prepare()
        for _ in range(20):
            self.git(self.clone, 'commit', '--allow-empty', '-m', 'local')
        refused = self.run_record('pull', code=1)
        self.assertIn(b'unpublished/divergent', refused.stderr)
        self.git(self.clone, 'commit', '--allow-empty', '-m', 'one too many')
        refused = self.run_record('pull', code=1)
        self.assertIn(b'history was rewritten upstream', refused.stderr)
        self.run_record('reset')
        path = self.clone / 'events/after-landing/hel8/2026-10-29.jsonl'
        path.parent.mkdir(parents=True)
        path.write_bytes(self.event())
        self.git(self.clone, 'add', '.')
        self.git(self.clone, 'commit', '-m', 'durable verdict')
        refused = self.run_record('pull', code=1)
        self.assertIn(b'unpublished/divergent', refused.stderr)
        self.git(self.clone, 'mv', 'events/after-landing', 'events/raw')
        self.git(self.clone, 'commit', '-m', 'rename to raw')
        self.assertIn(b'history was rewritten upstream', self.run_record('pull', code=1).stderr)


    def test_reset_archives_merge_empty_and_binary_commits(self):
        self.prepare()
        self.git(self.clone, 'checkout', '-b', 'side')
        (self.clone / 'binary.dat').write_bytes(b'\x00\xff\x01')
        self.git(self.clone, 'add', '.')
        self.git(self.clone, 'commit', '-m', 'binary')
        self.git(self.clone, 'checkout', 'main')
        self.git(self.clone, 'commit', '--allow-empty', '-m', 'empty local commit')
        self.git(self.clone, 'merge', '--no-ff', 'side', '-m', 'local merge')
        saved = self.run_record('reset')
        self.assertIn(b'saved 3 local-only commits', saved.stdout)
        archive, = (self.home / 'src/fabrig/archive').iterdir()
        patches = list(archive.glob('*.patch'))
        self.assertEqual(len(patches), 3)
        self.assertTrue(all(p.stat().st_size > 0 for p in patches))
        self.assertTrue(any(b'GIT binary patch' in p.read_bytes() for p in patches))
        self.assertTrue(any(b'local merge' in p.read_bytes() for p in patches))
        for patch_file in patches:
            sha = patch_file.stem.split('-', 1)[1]
            self.assertTrue(patch_file.read_bytes().startswith(f'From {sha} '.encode()))


    def test_push_guard_never_replays_old_events_after_force_push(self):
        path = self.seed / 'events/queue/hel8/2026-10-29.jsonl'
        path.parent.mkdir(parents=True)
        path.write_bytes(self.event().replace(b'after-landing', b'queue'))
        self.seed_commit('old collector')
        self.prepare()
        # Prepare a new root but postpone the force-push until record's pre-push hook.
        self.git(self.seed, 'checkout', '--orphan', 'rewritten')
        self.git(self.seed, 'rm', '-rf', '.')
        (self.seed / 'README.md').write_text('# New root\n')
        self.git(self.seed, 'add', '.')
        self.git(self.seed, 'commit', '-m', 'rewritten')
        self.hook(self.clone,
                  f'git -C {shlex.quote(str(self.seed))} push --force origin HEAD:main >&2\n')
        refused = self.run_record('write', '--as', 'ops', 'README.md', data=b'# Pending input\n', code=1)
        self.assertIn(b'history was rewritten upstream', refused.stderr)
        self.assertEqual(self.git(self.origin, 'rev-list', '--count', 'main'), '1')
        self.assertTrue((self.clone / 'events').is_dir())
        self.assertEqual((self.clone / 'README.md').read_bytes(), b'# Pending input\n')
        self.run_record('reset')
        self.assert_clean()


    def test_automatic_append_retries_twice_then_succeeds(self):
        self.prepare()
        for writer in ('after-landing',):
            with self.subTest(writer=writer):
                counter = self.home / (writer + '-attempts')
                self.hook(self.clone,
                    f'echo attempt >> {shlex.quote(str(counter))}\n'
                    f'if test "$(wc -l < {shlex.quote(str(counter))})" -le 2; then\n'
                    f'git -C {shlex.quote(str(self.seed))} pull --ff-only origin main >&2\n'
                    f'cp {shlex.quote(str(counter))} {shlex.quote(str(self.seed / "AGENTS.md"))}\n'
                    f'git -C {shlex.quote(str(self.seed))} add AGENTS.md\n'
                    f'git -C {shlex.quote(str(self.seed))} commit -m "advance origin" >&2\n'
                    f'git -C {shlex.quote(str(self.seed))} push origin main >&2\nfi\n')
                source = 'after-landing'
                data = self.event(writer).replace(b'after-landing', source.encode())
                self.run_record('append', '--as', writer, source, 'hel8', data=data, wait=False)
                self.assertEqual(len(counter.read_text().splitlines()), 3)
                self.assertEqual((self.clone / f'events/{source}/hel8/2026-10-29.jsonl').read_bytes(), data)
                self.assert_clean()

    def test_lost_acknowledgement_replays_ids_without_duplicates(self):
        self.prepare()
        for writer in ('after-landing',):
            for rejected in (0, 4):
                with self.subTest(writer=writer, rejected=rejected):
                    counter = self.home / f'{writer}-{rejected}-attempts'
                    self.hook(self.clone,
                        f'echo attempt >> {shlex.quote(str(counter))}\n'
                        f'if test "$(wc -l < {shlex.quote(str(counter))})" -le {rejected}; then\n'
                        f'git -C {shlex.quote(str(self.seed))} pull --ff-only origin main >&2\n'
                        f'cp {shlex.quote(str(counter))} {shlex.quote(str(self.seed / "AGENTS.md"))}\n'
                        f'git -C {shlex.quote(str(self.seed))} add AGENTS.md\n'
                        f'git -C {shlex.quote(str(self.seed))} commit -m "advance origin" >&2\n'
                        f'git -C {shlex.quote(str(self.seed))} push origin main >&2\nfi\n')
                    source = 'after-landing'
                    identities = [f'{writer}-{rejected}-{n}' for n in range(2)]
                    data = b''.join(self.event(identity).replace(b'after-landing', source.encode()) for identity in identities)
                    with self.push_transport('lost-ack'):
                        self.run_record('append', '--as', writer, source, 'hel8', data=data + data, wait=False)
                    self.assertEqual(len(counter.read_text().splitlines()), rejected + 1)
                    rows = self.git(self.origin, 'show', f'main:events/{source}/hel8/2026-10-29.jsonl').splitlines()
                    ids = [json.loads(row)['id'] for row in rows]
                    for identity in identities:
                        self.assertEqual(ids.count(identity), 1)
                    self.assert_clean()

    def test_two_concurrent_appends_one_clone_hold_lock_through_retry_and_reset(self):
        self.prepare()
        (self.seed / 'AGENTS.md').write_text('# Racing writer\n')
        self.git(self.seed, 'add', 'AGENTS.md')
        self.git(self.seed, 'commit', '-m', 'racing writer')
        ready, release = self.home / 'ready', self.home / 'release'
        self.hook(self.clone,
            f'if test ! -e {shlex.quote(str(ready))}; then\n'
            f'touch {shlex.quote(str(ready))}\n'
            'i=0\n'
            f'while test ! -e {shlex.quote(str(release))}; do\n'
            'i=$((i + 1)); test "$i" -lt 1000 || exit 1; sleep 0.01\ndone\n'
            f'git -C {shlex.quote(str(self.seed))} push origin main >&2\nfi\n')
        processes = []
        def start(identity):
            process = subprocess.Popen([str(TOOL), 'append', '--as', 'after-landing', 'after-landing', 'hel8'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
            processes.append(process)
            process.stdin.write(self.event(identity))
            process.stdin.close()
            process.stdin = None
            return process
        try:
            start('first')
            deadline = time.monotonic() + 10
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(ready.exists(), 'first writer did not reach its push barrier')
            with (self.clone / '.git/record.lock').open('a') as lock:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            second = start('second')
            with self.assertRaises(subprocess.TimeoutExpired):
                second.wait(timeout=0.1)
            release.touch()
            for process in processes:
                stdout, stderr = process.communicate(timeout=30)
                self.assertEqual(process.returncode, 0, stdout.decode() + stderr.decode())
        finally:
            release.touch()
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        rows = self.git(self.origin, 'show', 'main:events/after-landing/hel8/2026-10-29.jsonl').splitlines()
        self.assertCountEqual([json.loads(row)['id'] for row in rows], ['first', 'second'])
        self.assert_clean()

    def test_malformed_declaration_refuses_every_append(self):
        for declaration in (None, b'broken = [', b'\xff', b'', b'writer = "after-landing"',
                            b'[writer]\nsources = "after-landing"', b'[writer]\nsources = []',
                            b'[writer]\nsources = [1]', b'[writer]\nsources = ["../after-landing"]',
                            b'[writer]\nsources = ["after-landing"]\nextra = true',
                            b'["bad writer"]\nsources = ["after-landing"]'):
            with self.subTest(declaration=declaration), self.writer_declaration(declaration):
                for writer in ('ops', 'after-landing', 'watch', 'after-landing'):
                    self.run_record('append', '--as', writer, 'after-landing', 'hel8', data=self.event(), code=2)
        self.assertFalse(self.clone.exists())

    def test_push_race_retries_and_rebase_conflict_recovers_input(self):
        self.prepare()
        # A second writer advances origin after the first writer's fetch/commit.
        marker = self.home / 'injected'
        self.hook(self.clone,
                  f'if test ! -e {shlex.quote(str(marker))}; then\n'
                  f'  touch {shlex.quote(str(marker))}\n'
                  f'  git -C {shlex.quote(str(self.seed))} push origin main >&2\nfi\n')
        (self.seed / 'AGENTS.md').write_text('# Remote rules\n')
        self.git(self.seed, 'add', 'AGENTS.md')
        self.git(self.seed, 'commit', '-m', 'other writer')
        self.run_record('write', '--as', 'ops', 'README.md', data=b'# Local\n')
        self.assertEqual((self.clone / 'AGENTS.md').read_text(), '# Remote rules\n')
        self.assert_clean()
        self.git(self.seed, 'pull', '--ff-only', 'origin', 'main')
        (self.seed / 'README.md').write_text('# Conflicting remote\n')
        self.git(self.seed, 'add', 'README.md')
        self.git(self.seed, 'commit', '-m', 'conflicting writer')
        marker.unlink()
        rejected = self.run_record('write', '--as', 'ops', 'README.md', data=b'# Conflicting local\n', code=1)
        self.assertIn(b'rebase conflict', rejected.stderr)
        self.assertIn(b'# Conflicting local', rejected.stderr)
        self.assert_clean()
        self.assertEqual((self.clone / 'README.md').read_text(), '# Conflicting remote\n')

    def test_retry_limit_resets_to_origin(self):
        self.prepare()
        counter = self.home / 'attempts'
        self.hook(self.clone,
                  f'git -C {shlex.quote(str(self.seed))} pull --ff-only origin main >&2\n'
                  f'echo attempt >> {shlex.quote(str(counter))}\n'
                  f'cp {shlex.quote(str(counter))} {shlex.quote(str(self.seed / "AGENTS.md"))}\n'
                  f'git -C {shlex.quote(str(self.seed))} add AGENTS.md\n'
                  f'git -C {shlex.quote(str(self.seed))} commit -m "advance origin" >&2\n'
                  f'git -C {shlex.quote(str(self.seed))} push origin main >&2\n')
        refused = self.run_record('write', '--as', 'ops', 'README.md', data=b'# Local\n', code=1)
        self.assertIn(b'five attempts', refused.stderr)
        self.assertEqual(len(counter.read_text().splitlines()), 5)
        self.assert_clean()

    def test_automatic_retry_limit_defers_and_resets_to_origin(self):
        self.prepare()
        counter = self.home / 'attempts'
        self.hook(self.clone,
                  f'git -C {shlex.quote(str(self.seed))} pull --ff-only origin main >&2\n'
                  f'echo attempt >> {shlex.quote(str(counter))}\n'
                  f'cp {shlex.quote(str(counter))} {shlex.quote(str(self.seed / "AGENTS.md"))}\n'
                  f'git -C {shlex.quote(str(self.seed))} add AGENTS.md\n'
                  f'git -C {shlex.quote(str(self.seed))} commit -m "advance origin" >&2\n'
                  f'git -C {shlex.quote(str(self.seed))} push origin main >&2\n')
        result = self.run_record('append', '--as', 'after-landing', '--batch', 'hel8',
                                 data=self.event(), code=3, wait=False)
        self.assertIn(b'five attempts', result.stderr)
        self.assertNotIn(b'original input follows', result.stderr)
        self.assertEqual(len(counter.read_text().splitlines()), 5)
        self.assert_clean()
        self.assertFalse((self.clone / 'events').exists())

    def test_concurrent_appends_different_hosts(self):
        with self.racing_clones() as other:
            self.race(other, [('append', '--as', 'ops', 'after-landing', host) for host in ('hel8', 'hetzner8')],
                      [self.event(host=host) for host in ('hel8', 'hetzner8')])
            for host in ('hel8', 'hetzner8'):
                self.assertEqual((self.clone / f'events/after-landing/{host}/2026-10-29.jsonl').read_bytes(), self.event(host=host))

    def test_concurrent_next_decisions_and_questions(self):
        for directory, suffix, body in (('director/decisions', 'md', DECISION),
                                        ('director/questions', 'toml', QUESTION)):
            with self.subTest(directory=directory), self.racing_clones() as other:
                self.race(other, [('write', '--as', 'director', f'{directory}/next.{suffix}')] * 2,
                          [body, body.replace(b'choice', b'alternative') if suffix == 'md' else body.replace(b'What next?', b'When next?')])
                paths = list((self.clone / directory).glob(f'*.{suffix}'))
                self.assertEqual({p.stem for p in paths}, {'0001', '0002'})
                self.assertEqual(len({p.read_bytes() for p in paths}), 2)

    def test_director_draft_states_and_defaults(self):
        before = datetime.now(timezone.utc).replace(microsecond=0)
        self.draft(priority=3)
        after = datetime.now(timezone.utc)
        fields = self.fields('drafts/example/draft.toml')
        self.assertEqual((fields['state'], fields['priority']), ('queued', 3))
        updated = API['utc'](fields['updated'], 'updated')
        self.assertGreaterEqual(updated, before)
        self.assertLessEqual(updated, after)
        self.draft()
        self.assertEqual(self.fields('drafts/example/draft.toml')['priority'], 3)
        transitions = {'queued': {'queued', 'active'}, 'active': {'active', 'paused', 'done'},
                       'paused': {'paused', 'active'}, 'done': {'done'}}
        for initial, allowed in transitions.items():
            for state in transitions:
                with self.subTest(initial=initial, state=state):
                    name = initial + '-' + state
                    self.draft(name, state=initial)
                    result = self.run_record('draft', name, '--as', 'director',
                                             '--coordinator', 'multi', '--mailbox', 's/multi',
                                             '--source', 'draft.md', '--state', state,
                                             code=0 if state in allowed else 1)
                    if state not in allowed:
                        self.assertIn(b'allowed changes:', result.stderr)
                    self.assertEqual(self.fields(f'drafts/{name}/draft.toml')['state'],
                                     state if state in allowed else initial)
        for option, value in (('--state', 'invalid'), ('--state', ''), ('--priority', '0'), ('--mailbox', 'ops')):
            self.run_record('draft', 'bad', '--as', 'director', '--coordinator', 'multi',
                            '--mailbox', 's/multi', '--source', 'draft.md', option, value, code=1)
        self.run_record('check')
        self.assert_clean()

    def test_director_priorities_order_since_and_unknown(self):
        self.run_record('priority', 'show', '--as', 'director')
        for name in ('one', 'two', 'three'):
            self.draft(name)
        self.run_record('priority', 'set', '--as', 'director', 'one', 'two', 'three', '--reason', 'first')
        old = self.fields('director/priorities.toml')
        # Give since values a fixed past so moved timestamps can be distinguished.
        for entry in old['draft']:
            entry['since'] = STAMP
        body = ''.join('[[draft]]\n' + API['toml_fields'](entry) for entry in old['draft']).encode()
        self.run_record('write', '--as', 'director', 'director/priorities.toml', data=body)
        self.run_record('priority', 'set', '--as', 'director', 'one', 'three', 'two', '--reason', 'move')
        entries = self.fields('director/priorities.toml')['draft']
        self.assertEqual([e['name'] for e in entries], ['one', 'three', 'two'])
        self.assertEqual(entries[0]['since'], STAMP)
        self.assertTrue(all(e['since'] != STAMP for e in entries[1:]))
        self.assertTrue(all(e['reason'] == 'move' for e in entries))
        shown = self.run_record('priority', 'show', '--as', 'director')
        self.assertEqual(shown.stdout, (self.clone / 'director/priorities.toml').read_bytes())
        head = self.git(self.clone, 'rev-parse', 'HEAD')
        self.run_record('priority', 'set', '--as', 'director', 'missing', '--reason', 'bad', code=1)
        self.run_record('priority', 'set', '--as', 'director', 'one', 'one', '--reason', 'bad', code=1)
        self.assertEqual(head, self.git(self.clone, 'rev-parse', 'HEAD'))
        self.assert_clean()

    def test_director_ask_answer_applied_and_questions(self):
        before = datetime.now(timezone.utc).replace(microsecond=0)
        result = self.ask('What next? "quoted"\nline')
        after = datetime.now(timezone.utc)
        self.assertEqual(result.stdout.splitlines()[-1], b'0001')
        fields = self.fields('director/questions/0001.toml')
        self.assertEqual(fields['by'], 'director')
        self.assertEqual(fields['options'], ['a', 'b'])
        self.assertEqual(fields['question'], 'What next? "quoted"\nline')
        due = API['utc'](fields['deadline'], 'deadline')
        self.assertGreaterEqual(due, before + timedelta(hours=2))
        self.assertLessEqual(due, after + timedelta(hours=2))
        self.ask('Past question', '2020-01-01T00:00:00Z')
        questions = self.run_record('questions', '--as', 'ops', '--open').stdout
        self.assertIn(b'0001', questions)
        self.assertIn(b'0002', questions)
        self.assertIn(b'OVERDUE by director: Past question', questions)
        self.run_record('answer', '1', '--as', 'director', '--applied', 'commit:a', code=1)
        self.run_record('answer', '9999', '--as', 'director', '--answer', 'a', code=1)
        self.run_record('answer', '../1', '--as', 'director', '--answer', 'a', code=1)
        self.run_record('answer', '1', '--as', 'director', code=1)
        self.run_record('answer', '1', '--as', 'director', '--answer', 'a')
        answered = self.fields('director/questions/0001.toml')['answered']
        self.run_record('answer', '0001', '--as', 'ops', '--applied', 'commit:abc')
        fields = self.fields('director/questions/0001.toml')
        self.assertEqual((fields['answer'], fields['applied'], fields['answered']), ('a', 'commit:abc', answered))
        self.run_record('answer', '2', '--as', 'director', '--answer', 'b', '--applied', 'event:two')
        self.assertEqual(self.fields('director/questions/0002.toml')['applied'], 'event:two')
        self.assertEqual(self.run_record('questions', '--as', 'director', '--open').stdout, b'')
        self.assertIn(b'0001', self.run_record('questions', '--as', 'director').stdout)
        for value in ('+bad', '+0', '+999999999999999', 'tomorrow', '2020-01-01T01:00:00+01:00'):
            self.run_record('ask', '--as', 'director', '--question', 'Q', '--option', 'a',
                            '--recommendation', 'a', '--deadline', value, code=1)
        self.run_record('check')
        self.assert_clean()

    def test_director_question_numbering_concurrently(self):
        with self.racing_clones() as other:
            arguments = [('ask', '--as', 'director', '--question', question, '--option', 'a',
                          '--recommendation', 'a', '--deadline', '+1') for question in ('First?', 'Second?')]
            outputs = self.race(other, arguments, [b'', b''])
            self.assertEqual({output.splitlines()[-1] for output in outputs}, {b'0001', b'0002'})
            fields = [self.fields(f'director/questions/{n:04d}.toml') for n in (1, 2)]
            self.assertEqual({f['question'] for f in fields}, {'First?', 'Second?'})

    def test_director_decisions_files_cap_and_file_arguments(self):
        self.draft()
        incoming = self.home / 'decision.txt'
        incoming.write_text('from a file: ü\nsecond line')
        self.run_record(*self.decide_args('--draft', 'example', context='@' + str(incoming)))
        path = 'drafts/example/decisions/0001.md'
        API['validate'](self.clone, path, (self.clone / path).read_bytes())
        self.assertIn(incoming.read_bytes(), (self.clone / path).read_bytes())
        # Fixed-width timestamp metadata makes the exact byte cap reproducible.
        self.run_record(*self.decide_args())
        base = (self.clone / 'director/decisions/0001.md').stat().st_size
        text = 'x' * (4096 - base + len('choice'))
        self.run_record(*self.decide_args(why=text))
        exact = self.clone / 'director/decisions/0002.md'
        self.assertEqual(exact.stat().st_size, 4096)
        API['validate'](self.clone, 'director/decisions/0002.md', exact.read_bytes())
        self.run_record(*self.decide_args(why=text + 'x'), code=1)
        self.assertFalse((self.clone / 'director/decisions/0003.md').exists())
        self.run_record(*self.decide_args('--draft', 'missing'), code=1)
        for field in ('title', 'options', 'decision', 'why'):
            incoming.write_text('File choice')
            self.run_record(*self.decide_args(**{field: '@' + str(incoming)}))
        self.run_record(*self.decide_args(title='bad\nheading'), code=1)
        for content in (b'CR\r\n', b'\xff', b'sk-ant-secret'):
            incoming.write_bytes(content)
            self.run_record(*self.decide_args(context='@' + str(incoming)), code=1)
        self.run_record('check')
        self.assert_clean()

    def test_director_status_json_events_and_fresh_pull(self):
        for path in ('director/decisions/README.md', 'drafts/one/decisions/README.md'):
            target = self.seed / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('Decisions go here.\n')
        self.seed_commit('document decision directories')
        empty = json.loads(self.run_record('status', '--as', 'director', '--json').stdout)
        self.assertEqual(empty, dict(drafts=[], questions=[], decisions=[], events_last_hour={}))
        self.assertNotIn(b'Events', self.run_record('status', '--as', 'director').stdout)
        self.draft('one', state='active', priority=1)
        self.draft('two', priority=2)
        self.run_record('priority', 'set', '--as', 'director', 'two', 'one', '--reason', 'order')
        self.ask('Future question')
        self.ask('Overdue question', '2020-01-01T00:00:00Z')
        self.ask('Answered question')
        self.run_record('answer', '3', '--as', 'director', '--answer', 'a')
        # Several commits share a second: history order must still give the last five.
        for number in range(7):
            self.run_record(*self.decide_args('--director' if number % 2 else '--draft',
                                             None if number % 2 else 'one', title=f'Choice {number}'))
        without = json.loads(self.run_record('status', '--as', 'director', '--json').stdout)
        self.assertEqual([r['name'] for r in without['drafts']], ['two', 'one'])
        self.assertEqual([r['number'] for r in without['questions']], ['0002', '0001'])
        self.assertEqual([r['title'] for r in without['decisions']], [f'Choice {n}' for n in range(6, 1, -1)])
        self.assertTrue(all(r['age_seconds'] >= 0 for r in without['drafts'] + without['questions']))
        now = datetime.now(timezone.utc)
        stamps = [now, now - timedelta(minutes=30), now - timedelta(hours=2), now + timedelta(hours=2)]
        events = b''.join(self.event(str(i), stamp=t.isoformat()) for i, t in enumerate(stamps))
        self.run_record('append', '--as', 'ops', 'after-landing', 'hel8', data=events)
        run_event = json.dumps(dict(id='run1', source='after-landing', host='hel8', kind='end', time=now.isoformat())).encode()
        self.run_record('append', '--as', 'ops', 'after-landing', 'hel8', data=run_event)
        # A second clone supplies data this reader has not fetched yet.
        other = self.home / 'other-status'
        self.run_record('draft', 'fresh', '--as', 'director', '--coordinator', 'multi',
                        '--mailbox', 's/multi', '--source', 'draft.md', repo=other)
        head = self.git(self.origin, 'rev-parse', 'main')
        status = json.loads(self.run_record('status', '--as', 'director', '--json').stdout)
        self.assertEqual(status['events_last_hour'], {'after-landing': 3})
        self.assertIn('fresh', [r['name'] for r in status['drafts']])
        output = self.run_record('status', '--as', 'director').stdout
        self.assertLess(output.index(b'two queued'), output.index(b'one active'))
        self.assertLess(output.index(b'Overdue question'), output.index(b'Future question'))
        self.assertIn(b'after-landing=3', output)
        self.assertNotIn(b'Answered question', output)
        self.assertEqual(head, self.git(self.clone, 'rev-parse', 'HEAD'))
        self.assert_clean()



def load_tests(loader, tests, pattern):
    classes = (PeriodicRecordTests,)
    return unittest.TestSuite(cls(name) for cls in classes
                              for name in cls.__dict__ if name.startswith("test_"))
