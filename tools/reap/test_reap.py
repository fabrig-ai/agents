"""Offline reaper tests: disposable HOME, service fakes and proc namespace."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import copy
import fcntl
import json
import os
from pathlib import Path
import runpy
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
API = runpy.run_path(str(ROOT / 'tools/reap/reap'))
Reaper = API['Reaper']
NOW = 1800000000
DAY = 86400


def put(path, data='fixture', age=0, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    sibling = path.with_name(path.name + '.new')
    sibling.write_text(data)
    sibling.chmod(0o755 if executable else 0o600)
    sibling.replace(path)
    os.utime(path, (NOW-age, NOW-age))
    return path


class ReapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'home'
        self.home.mkdir()
        self.proc = Path(self.temp.name) / 'proc'
        self.proc.mkdir()
        self.bin = Path(self.temp.name) / 'bin'
        self.bin.mkdir()
        self.config = tomllib.loads((ROOT / 'fleet/reap.toml').read_text())
        self.env = patch.dict(os.environ, HOME=str(self.home), PATH=f'{self.bin}:/usr/bin:/bin', INVOCATION_ID='')
        self.host = patch("socket.gethostname", return_value="hel8")
        self.host.start()
        self.addCleanup(self.host.stop)
        self.env.start()
        self.addCleanup(self.env.stop)
        for tool, output in [('claude', '[]'), ('claim', ''), ('post', ''), ('systemctl', '1000000')]:
            self.fake(tool, output)

    def fake(self, name, output='', code=0):
        put(self.bin / name, '#!/usr/bin/env -S python3 -I -B\n'
            'import json, os, pathlib, sys\n'
            'home = pathlib.Path(os.environ["HOME"])\n'
            f'with (home / "{name}.calls").open("a") as f:\n'
            ' f.write(json.dumps(dict(args=sys.argv[1:], body=sys.stdin.read() if sys.argv[1:2] == ["send"] else "")) + "\\n")\n'
            f'print({output!r})\nsys.exit({code})\n', executable=True)

    def reaper(self, live=False):
        config = copy.deepcopy(self.config)
        if live:
            config['mode'] = 'live'
        return Reaper(self.home, config, self.proc, NOW)

    def run_class(self, cls, live=False):
        return self.reaper(live).execute({cls}, 'live' if live else 'dry-run')

    def old(self, relative, days=30, directory=False):
        path = self.home / relative
        if directory:
            put(path / 'payload', 'payload')
        else:
            put(path, 'payload')
        os.utime(path, (NOW-days*DAY, NOW-days*DAY))
        return path

    def final(self, path, state='landed', days=8, mtime_age=0):
        when = datetime.fromtimestamp(NOW-days*DAY, timezone.utc).isoformat().replace('+00:00', 'Z')
        return put(path / 'final.json', json.dumps(dict(state=state, time=when)), age=mtime_age)

    def record(self, event, path=None, kind='ops-scratch', identity='one', owner='lead/q/temper'):
        args = argparse.Namespace(event=event, kind=kind, owner=owner, id=identity, path=[] if path is None else [str(path)])
        self.reaper().record(args)

    def ended(self, path, kind='ops-scratch', identity='one', days=30):
        self.record('start', path, kind, identity)
        reaper = self.reaper()
        reaper.now = NOW-days*DAY
        reaper.record(argparse.Namespace(event='end', kind=kind, owner=None, id=identity, path=[]))

    def selected(self, result):
        return {Path(row['path']) for row in result['candidates'] if row['action'] in ('would delete', 'deleted')}

    def reason(self, result, reason):
        self.assertEqual(result['kept'], {reason: 1}, result)

    def git(self, path, *args):
        return subprocess.check_output(['git', '-c', 'user.email=test@example.invalid', '-c', 'user.name=Fixture', '-C', str(path), *args], stderr=subprocess.DEVNULL, text=True).strip()

    def repo(self, relative='scratch/repo', remote=True):
        path = self.home / relative
        path.mkdir(parents=True)
        self.git(path, 'init', '-b', 'main')
        put(path / 'tracked', 'original')
        self.git(path, 'add', 'tracked')
        self.git(path, 'commit', '-m', 'fixture')
        if remote:
            self.git(path, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
        self.ended(path)
        return path

    def test_claude_jobs_threshold_and_live(self):
        eligible = self.old('.claude/jobs/old', 2, True)
        self.old('.claude/jobs/new', .5, True)
        self.old('.claude/jobs/pins.json', 30)
        live = self.old('.claude/jobs/live', 2, True)
        (self.proc / '123').mkdir()
        self.fake('claude', '[{"sessionId":"live","pid":123}]')
        result = self.run_class('claude-jobs')
        self.assertEqual(self.selected(result), {eligible})
        self.reason(result, 'live session')
        self.assertTrue(live.exists())

    def test_dead_pid_eligible(self):
        eligible = self.old('.claude/jobs/dead', 2, True)
        self.fake('claude', '[{"sessionId":"dead","pid":999}]')
        self.assertEqual(self.selected(self.run_class('claude-jobs')), {eligible})

    def test_unknown_claude_inventory_keeps(self):
        self.old('.claude/jobs/old', 2, True)
        self.fake('claude', '', 1)
        self.reason(self.run_class('claude-jobs'), 'claude inventory unavailable')

    def test_codex_runs_require_explicit_old_final_time(self):
        self.fake('systemctl', 'inactive', 3)
        landed = self.old('src/rust/tmp/codex-run/landed', directory=True)
        withdrawn = self.old('src/rust/tmp/codex-run/withdrawn', directory=True)
        ended_only = self.old('src/rust/tmp/codex-run/ended-only', directory=True)
        recent = self.old('src/rust/tmp/codex-run/recent', directory=True)
        boundary = self.old('src/rust/tmp/codex-run/boundary', directory=True)
        index = self.old('src/rust/tmp/codex-run/runs.tsv')
        other = self.old('src/rust/tmp/codex-run/other-file')
        self.final(landed)  # Fresh mtime, old producer timestamp.
        self.final(withdrawn, 'withdrawn')
        self.final(recent, days=1, mtime_age=30*DAY)
        self.final(boundary, days=7, mtime_age=30*DAY)
        put(ended_only / 'ended', age=30*DAY)
        result = self.run_class('codex-runs')
        self.assertEqual(self.selected(result), {landed, withdrawn})
        self.reason(result, 'codex-run not final')
        self.assertEqual({Path(row['path']) for row in result['candidates']}, {landed, withdrawn, ended_only})
        self.assertTrue(index.exists())
        self.assertTrue(other.exists())
        calls = [json.loads(line)['args'] for line in (self.home / 'systemctl.calls').read_text().splitlines()]
        self.assertTrue(all(row[:2] == ['--user', 'is-active'] for row in calls))
        self.assertEqual({row[2] for row in calls}, {'codex-run-landed', 'codex-run-withdrawn'})

    def test_codex_unknown_final_json_kept(self):
        bad = ['not JSON', '[]', '{}', '{"state":"running","time":"2000-01-01T00:00:00Z"}',
               '{"state":"landed"}', '{"state":"landed","time":0}',
               '{"state":"landed","time":"2000-01-01"}',
               '{"state":"landed","time":"2000-01-01T00:00:00+01:00"}',
               '{"state":"landed","time":"invalid"}']
        for index, content in enumerate(bad):
            path = self.old(f'src/rust/tmp/codex-run/bad-{index}', directory=True)
            put(path / 'final.json', content)
        result = self.run_class('codex-runs', True)
        self.assertEqual(result['kept'], {'codex-run not final': len(bad)})
        self.assertFalse(self.selected(result))
        self.assertFalse((self.home / 'systemctl.calls').exists())

    def test_codex_final_time_accepts_only_utc_iso_variants(self):
        self.fake('systemctl', 'inactive', 3)
        path = self.old('src/rust/tmp/codex-run/timestamp', directory=True)
        for text in ('2000-01-01T00:00:00Z', '2000-01-01T00:00:00+00:00',
                     '2000-01-01T00:00:00.123456Z', '2000-01-01T00:00:00.123456+00:00'):
            with self.subTest(text=text):
                put(path / 'final.json', json.dumps(dict(state='landed', time=text)))
                self.assertIsNone(self.reaper().codex_finality(path)[1])
        for text in ('2000-01-01T00:00:00-00:00', '2000-01-01 00:00:00Z',
                     '20000101T000000Z', '2000-01-01T00:00:00+0000',
                     '2000-01-01T00:00:00', '2000-01-01T00:00:00,123Z',
                     '2000-01-01T00:00:00+01:00'):
            with self.subTest(text=text):
                put(path / 'final.json', json.dumps(dict(state='landed', time=text)))
                self.assertEqual(self.reaper().codex_finality(path)[1], 'codex-run not final')

    def test_codex_nonregular_final_json_kept(self):
        outside = put(Path(self.temp.name) / 'outside.json', '{"state":"landed","time":"2000-01-01T00:00:00Z"}')
        for name in ('symlink', 'directory', 'fifo'):
            path = self.old(f'src/rust/tmp/codex-run/{name}', directory=True)
            final = path / 'final.json'
            if name == 'symlink':
                final.symlink_to(outside)
            elif name == 'directory':
                final.mkdir()
            else:
                os.mkfifo(final)
        result = self.run_class('codex-runs', True)
        self.assertEqual(result['kept'], {'codex-run not final': 3})
        self.assertTrue(outside.exists())

    def test_codex_unreadable_final_json_kept(self):
        path = self.old('src/rust/tmp/codex-run/unreadable', directory=True)
        self.final(path)
        original = API['regular']
        @contextmanager
        def regular(target, *args, **kwargs):
            if target == path / 'final.json':
                raise PermissionError('fixture unreadable final')
            with original(target, *args, **kwargs) as fd:
                yield fd
        with patch.dict(Reaper.codex_finality.__globals__, regular=regular):
            self.reason(self.run_class('codex-runs', True), 'codex-run not final')
        self.assertTrue(path.exists())

    def test_codex_only_inactive_or_unknown_unit_is_eligible(self):
        path = self.old('src/rust/tmp/codex-run/unit', directory=True)
        self.final(path)
        for state, code, eligible in [('inactive', 3, True), ('unknown', 4, True),
                                      ('unknown', 3, True), ('active', 0, False),
                                      ('activating', 0, False), ('failed', 3, False),
                                      ('inactive', 1, False), ('unknown', 1, False), ('', 0, False)]:
            with self.subTest(state=state, code=code):
                self.fake('systemctl', state, code)
                self.assertEqual(path in self.selected(self.run_class('codex-runs')), eligible)
                self.assertTrue(path.exists())

    def test_codex_systemctl_errors_keep_run(self):
        path = self.old('src/rust/tmp/codex-run/unit', directory=True)
        self.final(path)
        for error in (FileNotFoundError('fixture systemctl absent'), subprocess.TimeoutExpired('systemctl', 30)):
            with self.subTest(error=type(error).__name__):
                with patch('subprocess.run', side_effect=error):
                    self.assertEqual(self.reaper().codex_finality(path)[1], 'codex-run unit unavailable')

    def test_codex_record_cannot_override_finality_or_remove_metadata(self):
        path = self.old('src/rust/tmp/codex-run/recorded', directory=True)
        index = self.old('src/rust/tmp/codex-run/runs.tsv')
        self.ended(path, kind='codex-run')
        self.ended(index, identity='index')
        result = self.run_class('recorded', True)
        self.assertEqual(result['kept'], {'codex-run not final': 2})
        self.assertTrue(path.exists())
        self.assertTrue(index.exists())
        self.assertFalse((path / 'final.json').exists())  # No backfill.

    def test_codex_live_removes_only_final_inactive_runs(self):
        path = self.old('src/rust/tmp/codex-run/final', directory=True)
        other = self.old('src/rust/tmp/codex-run/unknown', directory=True)
        index = self.old('src/rust/tmp/codex-run/runs.tsv')
        self.final(path)
        self.fake('systemctl', 'inactive', 3)
        self.assertEqual(self.selected(self.run_class('codex-runs', True)), {path})
        self.assertFalse(path.exists())
        self.assertTrue(other.exists())
        self.assertTrue(index.exists())

    def test_codex_finality_and_unit_rechecked_before_removal(self):
        path = self.old('src/rust/tmp/codex-run/recheck', directory=True)
        self.final(path)
        original = Reaper.snapshot
        for change in ('unit', 'final'):
            with self.subTest(change=change):
                self.final(path)
                self.fake('systemctl', 'inactive', 3)
                calls = []
                def snapshot(instance):
                    calls.append(1)
                    result = original(instance)
                    if len(calls) == 2:
                        if change == 'unit':
                            self.fake('systemctl', 'active', 0)
                        else:
                            self.final(path, state='running')
                    return result
                with patch.object(Reaper, 'snapshot', snapshot):
                    result = self.run_class('codex-runs', True)
                self.assertFalse(self.selected(result))
                self.assertTrue(path.exists())
                self.reason(result, 'codex-run unit not inactive' if change == 'unit' else 'codex-run not final')

    def test_heavy_logs_protect_history(self):
        old = self.old('src/rust/tmp/logs/old.log', 8)
        self.old('src/rust/tmp/logs/new.log', 1)
        self.old('src/rust/tmp/logs/heavy.tsv', 8)
        result = self.run_class('heavy-logs')
        self.assertEqual(self.selected(result), {old})
        self.reason(result, 'never path')

    def test_precheck_logs(self):
        old = self.old('src/fabrig/slots/1.precheck-logs/old', 4)
        self.old('src/fabrig/slots/1.precheck-logs/new', 1)
        self.old('src/fabrig/slots/1/untouched', 9)
        self.assertEqual(self.selected(self.run_class('precheck-logs')), {old})

    def test_notes_tasks_removed_and_protected_on_every_host(self):
        self.assertNotIn('notes', self.config['classes'])
        for host in ('hel8', 'hetzner3'):
            with self.subTest(host=host), patch('socket.gethostname', return_value=host):
                paths = [self.old('src/fabrig/notes/unfinished', 8), self.old('src/fabrig/tasks/unfinished', 8)]
                for i, path in enumerate(paths):
                    self.ended(path, identity=f'{host}-{i}')
                reaper = self.reaper(True)
                result = reaper.execute(set(self.config['classes']), 'live')
                self.assertTrue(all(path.exists() for path in paths))
                self.assertTrue(all(row['reason'] == 'never path' for row in result['candidates']))

    def test_codex_sessions_only_rollouts(self):
        old = self.old('.codex/sessions/2025/10/rollout.jsonl', 15)
        self.old('.codex/sessions/2026/10/new.jsonl', 1)
        self.old('.codex/sessions/metadata.json', 30)
        self.old('.codex/sessions/index.jsonl', 30)
        auth = self.old('.codex/auth.json', 30)
        self.assertEqual(self.selected(self.run_class('codex-sessions')), {old})
        self.assertTrue(auth.exists())

    def test_recorded_kind_retention(self):
        for number, (kind, seconds) in enumerate(self.config['kinds'].items()):
            with self.subTest(kind=kind):
                path = self.old(f'.claude/jobs/id{number}' if kind == 'claude-session' else f'scratch/{kind}', directory=kind == 'claude-session')
                self.ended(path, kind, f'id{number}', (seconds+1)/DAY)
        result = self.run_class('recorded')
        self.assertEqual(len(self.selected(result)), len(self.config['kinds']))

    def test_ended_claude_session_one_hour(self):
        path = self.old('.claude/jobs/one', .1, True)
        self.ended(path, 'claude-session', days=2/24)
        result = self.reaper().execute({'recorded', 'claude-jobs'}, 'dry-run')
        self.assertEqual(self.selected(result), {path})

    def test_recorded_still_live_claude_session(self):
        self.old('.claude/jobs/one', 2, True)
        self.ended(self.home / '.claude/jobs/one', 'claude-session', days=1)
        (self.proc / '123').mkdir()
        self.fake('claude', '[{"sessionId":"one","pid":123}]')
        self.reason(self.run_class('recorded'), 'live session')

    def test_recorded_too_young(self):
        path = self.old('scratch/new')
        self.ended(path, days=1)
        self.assertEqual(self.run_class('recorded')['candidates'], [])

    def test_records_merge_idempotent_append_and_malformed(self):
        first = self.home / 'scratch/one'
        second = self.home / 'scratch/two'
        self.record('start', first)
        self.record('start', first)
        self.record('start', second)
        self.record('end')
        self.record('end')
        target = self.home / '.local/state/reap/records.jsonl'
        text = target.read_text()
        self.assertEqual(len(text.splitlines()), 3)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        records = API['load_records'](text + '\nnot json\n{}\n{"kind": []}\n')
        self.assertEqual(records[('ops-scratch', 'one')]['paths'], {str(first), str(second)})
        self.assertEqual(records[('ops-scratch', 'one')]['ended'], NOW)

    def test_resume_clears_end_preserves_paths(self):
        self.record('start', self.home / 'scratch/one')
        self.record('end')
        self.record('start', self.home / 'scratch/two')
        record = self.reaper().records[('ops-scratch', 'one')]
        self.assertIsNone(record['ended'])
        self.assertEqual(len(record['paths']), 2)

    def test_first_end_retention_for_every_kind(self):
        paths = set()
        for kind, retention in self.config['kinds'].items():
            with self.subTest(kind=kind):
                identity = kind
                path = self.old(f'.claude/jobs/{identity[:8]}' if kind == 'claude-session' else f'scratch/{kind}', directory=True)
                paths.add(path)
                args = argparse.Namespace(event='start', kind=kind, owner='lead/q/temper', id=identity, path=[str(path)])
                reaper = self.reaper()
                reaper.now = NOW-4*retention
                reaper.record(args)
                args.event = 'end'
                reaper.now = NOW-2*retention
                reaper.record(args)
                reaper.now = NOW
                reaper.record(args)
                self.assertEqual(self.reaper().records[(kind, identity)]['ended'], NOW-2*retention)
                # Even a later append with an earlier timestamp uses the minimum.
                reaper.now = NOW-3*retention
                reaper.record(args)
                self.assertEqual(self.reaper().records[(kind, identity)]['ended'], NOW-3*retention)
                API['append'](reaper.state / 'records.jsonl', dict(event='end', kind=kind, id=identity,
                                                               owner='fixture', paths=[], time=NOW))
                self.assertEqual(self.reaper().records[(kind, identity)]['ended'], NOW-3*retention)
        self.assertEqual(self.selected(self.run_class('recorded')), paths)

    def test_resume_starts_new_retention_clock_for_every_kind(self):
        for kind, retention in self.config['kinds'].items():
            with self.subTest(kind=kind):
                identity = kind
                path = self.old(f'.claude/jobs/{identity[:8]}' if kind == 'claude-session' else f'scratch/{kind}', directory=True)
                args = argparse.Namespace(event='start', kind=kind, owner='coordinator/dm/stamp', id=identity, path=[str(path)])
                reaper = self.reaper()
                reaper.now = NOW-3*retention
                reaper.record(args)
                args.event = 'end'
                reaper.record(args)
                args.event = 'start'
                reaper.now = NOW
                reaper.record(args)
                self.assertIsNone(self.reaper().records[(kind, identity)]['ended'])
                self.assertNotIn(path, {Path(row['path']) for row in self.reaper().discover({'recorded'})})
                args.event = 'end'
                reaper.now = NOW+100
                reaper.record(args)
                reaper.now += 100
                reaper.record(args)
                self.assertEqual(self.reaper().records[(kind, identity)]['ended'], NOW+100)
                reaper.refresh_records()
                reaper.now = NOW+100+retention-1
                self.assertNotIn(path, {Path(row['path']) for row in reaper.discover({'recorded'})})
                reaper.now += 2
                self.assertIn(path, {Path(row['path']) for row in reaper.discover({'recorded'})})

    def test_resumed_record_retention_also_protects_generic_discovery(self):
        for kind, retention in self.config['kinds'].items():
            with self.subTest(kind=kind):
                identity = kind
                path = self.old(f'.claude/jobs/{identity[:8]}' if kind == 'claude-session'
                                else f'src/rust/tmp/logs/{kind}', directory=True)
                args = argparse.Namespace(event='start', kind=kind, owner='lead/q/temper', id=identity, path=[str(path)])
                writer = self.reaper()
                writer.now = NOW-3*retention
                writer.record(args)
                args.event = 'end'
                writer.record(args)
                args.event = 'start'
                writer.now = NOW
                writer.record(args)
                args.event = 'end'
                writer.now = NOW+10
                writer.record(args)
                cls = 'claude-jobs' if kind == 'claude-session' else 'heavy-logs'
                probe = self.reaper()
                probe.now = NOW+11
                result = probe.execute({cls}, 'dry-run')
                item = next(row for row in result['candidates'] if Path(row['path']) == path)
                self.assertEqual(item['reason'], 'record retention')
                self.assertNotIn(path, self.selected(result))
                probe.now = NOW+10+retention+1
                self.assertIn(path, self.selected(probe.execute({cls}, 'dry-run')))

    def test_active_records_protect_discovery(self):
        path = self.old('src/rust/tmp/logs/old', 8)
        self.record('start', path)
        self.reason(self.run_class('heavy-logs'), 'record active')
        self.assertEqual(self.run_class('recorded')['candidates'], [])

    def test_claude_record_cannot_name_other_paths(self):
        with self.assertRaisesRegex(ValueError, 'jobs directory'):
            self.record('start', self.home / 'scratch/one', 'claude-session')

    def test_real_session_hook_lifecycle_against_reaper(self):
        identity = '63cf764d-1df5-478f-92de-5aeb424fda12'
        path = self.old(f'.claude/jobs/{identity[:8]}', 30, True)
        (self.bin / 'reap').symlink_to(ROOT / 'tools/reap/reap')
        target = self.home / '.local/state/reap/records.jsonl'
        def hook(event):
            result = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'tools/session/reap-hook'),
                                     'lead/q/temper'], input=json.dumps(dict(
                                         hook_event_name=event, session_id=identity)),
                                    capture_output=True, text=True, timeout=5,
                                    env=dict(os.environ, SESSION_CONTEXT_STATE=str(self.home / 'hook-cache')))
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
            return [json.loads(line) for line in target.read_text().splitlines()]
        lines = hook('SessionStart')
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0]['id'], lines[0]['paths'], lines[0]['owner']),
                         (identity, [str(path)], 'lead/q/temper'))
        self.assertEqual(hook('SessionStart'), lines)  # Resume while live is idempotent.
        probe = self.reaper()
        self.reason(probe.execute({'claude-jobs'}, 'dry-run'), 'record active')
        lines = hook('SessionEnd')
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[-1]['owner'], 'lead/q/temper')
        ended = lines[-1]['time']
        self.assertEqual(hook('SessionEnd'), lines)
        probe = self.reaper()
        probe.now = ended + 3600 - .01
        self.assertEqual(probe.execute({'recorded'}, 'dry-run')['candidates'], [])
        probe.now = ended + 3600
        self.assertEqual(self.selected(probe.execute({'recorded'}, 'dry-run')), {path})
        self.assertEqual(len(hook('SessionStart')), 3)  # Resume after end is live again.
        self.assertIsNone(self.reaper().records[('claude-session', identity)]['ended'])
        self.assertEqual(len(hook('SessionEnd')), 4)
        calls = [json.loads(line)['args'] for line in (self.home / 'systemctl.calls').read_text().splitlines()]
        self.assertEqual(calls, [['--user', 'start', '--no-block', 'reap.service']] * 3)

    def test_full_session_id_only_accepts_its_short_direct_jobs_child(self):
        identity = '63cf764d-1df5-478f-92de-5aeb424fda12'
        for relative in (f'.claude/jobs/{identity}', '.claude/jobs/different',
                         f'.claude/jobs/{identity[:8]}/nested', '.claude/jobs'):
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, 'jobs directory'):
                self.record('start', self.home / relative, 'claude-session', identity)
        path = self.old(f'.claude/jobs/{identity[:8]}', 30, True)
        self.ended(path, 'claude-session', identity)
        self.fake('claude', json.dumps([dict(sessionId=identity, status='running')]))
        self.reason(self.run_class('recorded'), 'live session')

    def test_ownerless_end_inherits_start_owner_for_every_kind(self):
        for kind in self.config['kinds']:
            with self.subTest(kind=kind):
                path = self.home / (f'.claude/jobs/{kind[:8]}' if kind == 'claude-session' else f'scratch/{kind}')
                self.record('start', path, kind, kind, owner='start/owner')
                result = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'tools/reap/reap'),
                                         'record', 'end', '--kind', kind, '--id', kind],
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
                record = self.reaper().records[(kind, kind)]
                self.assertEqual(record['owner'], 'start/owner')
                self.assertIsNotNone(record['ended'])
                rows = [json.loads(line) for line in (self.home / '.local/state/reap/records.jsonl').read_text().splitlines()]
                self.assertEqual(rows[-1]['owner'], 'start/owner')

    def test_orphan_end_is_recorded_but_never_supplies_eligibility(self):
        for kind in self.config['kinds']:
            with self.subTest(kind=kind):
                path = self.old(f'.claude/jobs/{kind[:8]}' if kind == 'claude-session' else f'scratch/{kind}', directory=True)
                self.record('end', path, kind, kind, owner=None)
                ledger = self.home / '.local/state/reap/records.jsonl'
                row = json.loads(ledger.read_text().splitlines()[-1])
                self.assertEqual((row['event'], row['id'], row['owner']), ('end', kind, None))
                self.assertNotIn((kind, kind), self.reaper().records)
        self.assertEqual(self.run_class('recorded')['candidates'], [])
        # An orphan's paths cannot hitchhike on a later, unrelated start.
        self.record('start', self.home / 'scratch/new', 'ops-scratch', 'ops-scratch')
        self.assertEqual(self.reaper().records[('ops-scratch', 'ops-scratch')]['paths'],
                         {str(self.home / 'scratch/new')})

    def test_end_owner_mismatch_is_silent_success_with_one_diagnostic(self):
        path = self.home / 'scratch/run'
        self.record('start', path, 'codex-run', owner='ops/one')
        ledger = self.home / '.local/state/reap/records.jsonl'
        before = ledger.read_bytes()
        args = [sys.executable, '-I', '-B', str(ROOT / 'tools/reap/reap'),
                'record', 'end', '--kind', 'codex-run', '--id', 'one', '--owner']
        result = subprocess.run([*args, 'ops/two'], capture_output=True, text=True, timeout=5)
        self.assertEqual((result.returncode, result.stdout), (0, ''))
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertIn('owner', result.stderr)
        self.assertEqual(ledger.read_bytes(), before)
        self.assertIsNone(self.reaper().records[('codex-run', 'one')]['ended'])
        result = subprocess.run([*args, 'ops/one'], capture_output=True, text=True, timeout=5)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertIsNotNone(self.reaper().records[('codex-run', 'one')]['ended'])

    def test_start_requires_owner(self):
        result = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'tools/reap/reap'),
                                 'record', 'start', '--kind', 'ops-scratch', '--id', 'missing-owner'],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertFalse((self.home / '.local/state/reap/records.jsonl').exists())

    def test_mailbox_homes_are_never_reaped(self):
        path = self.old('src/fabrig/homes', directory=True)
        self.assertTrue(self.reaper().never(path / 'mailbox'))
        self.ended(path)
        self.reason(self.run_class('recorded', True), 'never path')
        self.assertTrue((path / 'payload').exists())

    def test_agent_login_pool_is_never_reaped(self):
        path = self.old('src/fabrig/logins', directory=True)
        reaper = self.reaper()
        for protected in (path, path.parent, path / 'payload'):
            self.assertTrue(reaper.never(protected), protected)
        self.ended(path)
        self.reason(self.run_class('recorded', True), 'never path')
        self.assertTrue((path / 'payload').exists())

    def test_fleet_scale_credential_source_is_never_reaped(self):
        path = self.old('.config/fleet-scale', directory=True)
        reaper = self.reaper()
        for protected in (path, path.parent, path / 'payload'):
            self.assertTrue(reaper.never(protected), protected)
        self.ended(path)
        self.reason(self.run_class('recorded', True), 'never path')
        self.assertTrue((path / 'payload').exists())

    def test_record_errors_never_fail_caller(self):
        result = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'tools/reap/reap'), 'record', 'start'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(result.stderr.splitlines()), 1)
        result = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'tools/reap/reap'), 'record', 'start', '--strict'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)

    def test_record_symlink_state_refused(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (self.home / '.local').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            self.record('start')
        self.assertEqual(list(outside.iterdir()), [])

    def test_cwd_kept(self):
        path = self.old('src/rust/tmp/logs/item', directory=True)
        cwd = self.proc / '42/cwd'
        cwd.parent.mkdir()
        cwd.symlink_to(path / 'child')
        self.reason(self.run_class('heavy-logs'), 'process use')

    def test_fd_kept(self):
        path = self.old('src/rust/tmp/logs/item', directory=True)
        fd = self.proc / '42/fd/3'
        fd.parent.mkdir(parents=True)
        fd.symlink_to(path / 'payload')
        self.reason(self.run_class('heavy-logs'), 'process use')

    def test_literal_deleted_suffix_in_use_file_kept(self):
        path = self.old('src/rust/tmp/logs/name (deleted)')
        fd = self.proc / '42/fd/3'
        fd.parent.mkdir(parents=True)
        fd.symlink_to(path)
        self.reason(self.run_class('heavy-logs'), 'process use')

    def test_maps_kept(self):
        path = self.old('src/rust/tmp/logs/item', directory=True)
        put(self.proc / '42/maps', f'1000-2000 r-xp 0 00:00 1 {path}/payload\n')
        self.reason(self.run_class('heavy-logs'), 'process use')

    def test_claimed_slot_and_precheck_kept(self):
        self.old('src/fabrig/slots/2.precheck-logs/item', 8)
        self.fake('claim', 'hetzner3 2 [lead/x]: lead/x: build')
        self.reason(self.run_class('precheck-logs'), 'claimed slot')
        slot = self.old('src/fabrig/slots/2', directory=True)
        self.ended(slot)
        self.reason(self.run_class('recorded'), 'claimed slot')

    def test_claim_failure_keeps_every_slot(self):
        self.old('src/fabrig/slots/2.precheck-logs/item', 8)
        self.fake('claim', '', 1)
        self.reason(self.run_class('precheck-logs'), 'claim unavailable')

    def test_claim_malformed_keeps_slots(self):
        self.old('src/fabrig/slots/2.precheck-logs/item', 8)
        self.fake('claim', 'bad output')
        self.reason(self.run_class('precheck-logs'), 'claim unavailable')

    def test_builder_claims_use_authority_and_filter_host(self):
        self.old('src/fabrig/slots/2.precheck-logs/item', 8)
        self.fake('ssh', 'hetzner6 2 [pool]: other: build\nhetzner3 2 [pool]: free')
        self.fake('claim', 'bad local inventory', 1)
        for host in ('hetzner3', 'debian-16gb-hel1-3.example'):
            with self.subTest(host=host), patch('socket.gethostname', return_value=host):
                self.assertEqual(len(self.selected(self.run_class('precheck-logs'))), 1)
        self.assertFalse((self.home / 'claim.calls').exists())
        calls = [json.loads(line)['args'] for line in (self.home / 'ssh.calls').read_text().splitlines()]
        self.assertTrue(all(call == ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
                                    'free@204.168.210.29', "bash -lc 'claim list'"] for call in calls))
        self.fake('ssh', 'hetzner3 2 [pool]: owner: live')
        with patch('socket.gethostname', return_value='hetzner3'):
            self.reason(self.run_class('precheck-logs'), 'claimed slot')

    def test_builder_failed_unknown_or_missing_authority_keeps_slots(self):
        self.old('src/fabrig/slots/2.precheck-logs/item', 8)
        for output, code in (('', 1), ('invalid', 0), ('hetzner6 2 [pool]: free', 0), ('', 0)):
            with self.subTest(output=output, code=code):
                self.fake('ssh', output, code)
                with patch('socket.gethostname', return_value='hetzner3'):
                    self.reason(self.run_class('precheck-logs'), 'claim unavailable')
        for error in (FileNotFoundError('ssh'), subprocess.TimeoutExpired('ssh', 10)):
            with patch('socket.gethostname', return_value='hetzner3'):
                with patch.dict(Reaper.claim_slots.__globals__, command=Mock(side_effect=error)):
                    self.reason(self.run_class('precheck-logs'), 'claim unavailable')
        with patch('socket.gethostname', return_value='unknown'):
            self.reason(self.run_class('precheck-logs'), 'claim unavailable')

    def test_alternates_absolute_and_relative(self):
        for relative in (False, True):
            with self.subTest(relative=relative):
                path = self.old('src/rust/tmp/logs/store', directory=True)
                alternate = self.home / 'src/borrower/.git/objects/info/alternates'
                target = path / 'objects'
                put(alternate, os.path.relpath(target, alternate.parent.parent) if relative else str(target))
                self.reason(self.run_class('heavy-logs'), 'alternates target')

    def test_quoted_alternates_fail_closed(self):
        path = self.old('src/rust/tmp/logs/store', directory=True)
        put(self.home / 'src/borrower/.git/objects/info/alternates', json.dumps(str(path / 'objects')))
        self.reason(self.run_class('heavy-logs', True), 'alternates incomplete: quoted alternates require review')
        self.assertTrue(path.exists())

    def test_alternates_under_jobs(self):
        path = self.old('src/rust/tmp/logs/store', directory=True)
        put(self.home / '.claude/jobs/job/.git/objects/info/alternates', str(path / 'objects'))
        self.reason(self.run_class('heavy-logs'), 'alternates target')

    def test_incomplete_scan_keeps(self):
        self.old('src/rust/tmp/logs/item')
        reaper = self.reaper()
        snap = dict(used=[], borrowed=[], slots=[], failures=['proc incomplete: PermissionError'])
        with patch.object(Reaper, 'snapshot', return_value=snap):
            self.reason(reaper.execute({'heavy-logs'}, 'dry-run'), snap['failures'][0])

    def test_claimed_host_named_slot(self):
        self.old('src/fabrig/slots/hetzner3-2.precheck-logs/item', 8)
        self.fake('claim', 'hetzner3 2 [lead/x]: lead/x: build')
        self.reason(self.run_class('precheck-logs'), 'claimed slot')

    def test_proc_reader_decodes_escaped_maps(self):
        path = self.old('src/rust/tmp/logs/space name', directory=True)
        mapped = str(path / 'payload').replace(' ', r'\040')
        put(self.proc / '42/maps', f'1000-2000 r-xp 0 00:00 1 {mapped}\n')
        self.reason(self.run_class('heavy-logs'), 'process use')

    def test_proc_permission_fallback_uses_only_narrow_helper(self):
        reaper = self.reaper()
        reaper.proc = Path('/proc')
        commands = []
        original = API['command']
        def command(args, **kwargs):
            if args[0] == 'sudo':
                commands.append(args)
                return '{"paths":[],"errors":[]}'
            return original(args, **kwargs)
        globals_ = Reaper.snapshot.__globals__
        with patch.dict(globals_, process_paths=lambda _: dict(paths=[], errors=['PermissionError']), command=command):
            self.assertEqual(reaper.snapshot()['failures'], [])
        self.assertEqual(commands[0][:5], ['sudo', '-n', '/usr/bin/python3', '-I', '-B'])
        self.assertEqual(Path(commands[0][-1]), ROOT / 'tools/reap/proc_paths.py')

    def test_alternates_budget_fails_closed_and_records_elapsed(self):
        path = self.old('src/rust/tmp/logs/item')
        reaper = self.reaper(True)
        with patch('time.monotonic', side_effect=[100, 121, 122]):
            scan = reaper.scan_alternates()
        with patch.object(Reaper, 'scan_alternates', return_value=scan):
            result = reaper.execute({'heavy-logs'}, 'live')
        self.reason(result, 'budget')
        self.assertTrue(path.exists())
        self.assertEqual(result['alternates_scan']['elapsed_seconds'], 22)
        self.assertFalse(result['alternates_scan']['complete'])
        reaper.save(result)
        saved = json.loads((reaper.state / 'runs.jsonl').read_text().splitlines()[-1])
        self.assertEqual(saved['alternates_scan'], result['alternates_scan'])

    def test_alternates_build_tree_timeout_shape_is_pruned(self):
        # Real hel8 failure: generic traversal spent its deadline inside deep
        # build/source output before reaching later Git metadata.
        path = self.old('src/rust/tmp/logs/store', directory=True)
        for name in ('target', 'node_modules', '.cache'):
            deep = self.home / 'src/project' / name / Path(*(['generated'] * 65))
            put(deep / '.git/objects/info/alternates', '"not Git metadata in scope"')
        put(self.home / 'src/project/.git/objects/info/alternates', str(path / 'objects'))
        reaper = self.reaper()
        with patch.object(Reaper, 'scan_alternates', wraps=reaper.scan_alternates) as scan:
            result = reaper.execute({'heavy-logs'}, 'dry-run')
        self.reason(result, 'alternates target')
        self.assertEqual(scan.call_count, 1)
        self.assertTrue(result['alternates_scan']['complete'])
        self.assertEqual(result['alternates_scan']['alternates_files'], 1)
        self.assertLess(result['alternates_scan']['directories'], 20)

    def test_alternates_bare_and_linked_commondir(self):
        path = self.old('src/rust/tmp/logs/store', directory=True)
        bare = self.home / 'src/reference.git'
        put(bare / 'objects/info/alternates', str(path / 'objects'))
        common = self.home / 'other/common'
        put(common / 'objects/info/alternates', str(path / 'objects'))
        admin = common / 'worktrees/linked'
        put(admin / 'commondir', '../..\n')
        linked = self.home / 'src/linked'
        put(linked / '.git', 'gitdir: '+str(admin)+'\n')
        reaper = self.reaper()
        result = reaper.execute({'heavy-logs'}, 'dry-run')
        self.reason(result, 'alternates target')
        self.assertEqual(result['alternates_scan']['alternates_files'], 2)
        self.assertEqual(result['alternates_scan']['git_directories'], 3)

    def test_alternates_only_git_metadata_and_no_object_walk(self):
        path = self.old('src/rust/tmp/logs/store', directory=True)
        put(self.home / 'src/plain/objects/info/alternates', '"irrelevant"')
        put(self.home / 'src/project/.git/objects/pack/deep/objects/info/alternates', '"irrelevant"')
        result = self.run_class('heavy-logs')
        self.assertEqual(self.selected(result), {path})
        self.assertTrue(result['alternates_scan']['complete'])
        self.assertEqual(result['alternates_scan']['alternates_files'], 0)

    def test_alternates_depth_six_and_explicit_tmp_root(self):
        path = self.old('src/rust/tmp/logs/store', directory=True)
        for root in ('src', '.claude/jobs', 'src/rust/tmp'):
            deep = self.home / root / Path(*(['nested'] * 6))
            put(deep / '.git/objects/info/alternates', str(path / 'objects'))
            put(deep / 'beyond/.git/objects/info/alternates', '"out of scope"')
        result = self.run_class('heavy-logs')
        self.reason(result, 'alternates target')
        self.assertEqual(result['alternates_scan']['alternates_files'], 3)
        self.assertTrue(result['alternates_scan']['complete'])

    def test_alternates_cached_even_at_final_removal_snapshot(self):
        first = self.old('src/rust/tmp/logs/first')
        second = self.old('src/rust/tmp/logs/second')
        reaper = self.reaper(True)
        with patch.object(Reaper, 'scan_alternates', wraps=reaper.scan_alternates) as scan:
            result = reaper.execute({'heavy-logs'}, 'live')
            self.assertEqual(scan.call_count, 1)
        self.assertEqual(self.selected(result), {first, second})
        self.assertFalse(first.exists())
        self.assertFalse(second.exists())

    def test_linked_worktree_gitdir_path_can_contain_newlines(self):
        path = self.old('src/rust/tmp/logs/store', directory=True)
        main = self.repo('src/primary\nwith spaces')
        linked = self.home / 'src/linked'
        self.git(main, 'worktree', 'add', '--detach', str(linked), 'HEAD')
        # Git itself produces this pointer shape. Embedded newlines belong to
        # the path, not extra metadata rows; saved h3 fixtures retained it.
        put(main / '.git/objects/info/alternates', str(path / 'objects'))
        result = self.run_class('heavy-logs')
        self.reason(result, 'alternates target')
        self.assertTrue(result['alternates_scan']['complete'])
        self.assertEqual(result['alternates_scan']['alternates_files'], 1)

    def test_archived_worktree_with_deleted_gitdir_has_no_borrower(self):
        path = self.old('src/rust/tmp/logs/item')
        # Real h3 shape: saved test evidence retains a worktree pointer to an
        # already deleted temporary fixture, including spaces in its name.
        missing = Path(self.temp.name) / 'removed-fixture/anchor with spaces/.git/worktrees/saved'
        put(self.home / 'src/fabrig/notes/ops/evidence/saved/.git', 'gitdir: '+str(missing)+'\n')
        result = self.run_class('heavy-logs')
        self.assertEqual(self.selected(result), {path})
        self.assertTrue(result['alternates_scan']['complete'])
        self.assertEqual(result['alternates_scan']['missing_git_directories'], 1)

    def test_alternates_unreadable_and_bad_git_pointers_fail_closed(self):
        path = self.old('src/rust/tmp/logs/item')
        marker = self.home / 'src/repo/.git'
        for text in ('invalid', 'gitdir: '):
            with self.subTest(text=text):
                put(marker, text)
                result = self.run_class('heavy-logs', True)
                self.assertFalse(self.selected(result))
                self.assertFalse(result['alternates_scan']['complete'])
                self.assertTrue(path.exists())
        marker.unlink()
        put(marker / 'objects/info/alternates', 'not used')
        original = API['regular']
        @contextmanager
        def regular(target, *args, **kwargs):
            if target.name == 'alternates':
                raise PermissionError('fixture')
            with original(target, *args, **kwargs) as fd:
                yield fd
        with patch.dict(Reaper.scan_alternates.__globals__, regular=regular):
            self.reason(self.run_class('heavy-logs'), 'alternates incomplete: PermissionError')

    def test_live_reloads_active_records(self):
        path = self.old('src/rust/tmp/logs/item', directory=True)
        reaper = self.reaper(True)
        original = Reaper.keep
        calls = []
        def keep(instance, candidate, snapshot, **kwargs):
            calls.append(1)
            result = original(instance, candidate, snapshot, **kwargs)
            if len(calls) == 1:
                self.record('start', path)
            return result
        with patch.object(Reaper, 'keep', keep):
            self.reason(reaper.execute({'heavy-logs'}, 'live'), 'record active')
        self.assertTrue(path.exists())

    def test_read_only_does_not_write_state_or_send(self):
        path = self.old('src/rust/tmp/logs/item')
        globals_ = API['main'].__globals__
        with patch.dict(globals_, Reaper=lambda: self.reaper()):
            with patch('builtins.print'):
                self.assertEqual(API['main'](['run', '--dry-run', '--json', '--read-only']), 0)
        self.assertFalse((self.home / '.local').exists())
        self.assertFalse((self.home / 'post.calls').exists())
        self.assertTrue(path.exists())

    def test_never_paths_and_ancestors(self):
        reaper = self.reaper()
        for path in ['src/rust/tmp/logins/a', 'src/rust/tmp/qa-focused/a', 'src/rust/tmp/qa/a',
                     'src/rust/tmp/heavy/a', 'src/rust/tmp/post/a', 'src/fabrig/claims/a',
                     'src/fabrig/events/a', 'src/fabrig/records/a', 'src/rust/records/a',
                     'src/fabrig/archive/a', 'src/rust/tmp/owners/a', 'src/fabrig/homes/a',
                     'src/fabrig/leases/a', 'src/fabrig/queue/a', 'src/fabrig/main/a', 'src/fabrig/agents/a',
                     'src/fabrig/current/a', 'src/fabrig/releases/a', '.local/state/fleet-sync/a',
                     '.local/state/fabrig/a', '.local/state/heavy/a', '.ssh/id', '.claude/.credentials.json',
                     '.claude.json', '.claude/jobs/pins.json', '.codex/auth.json', '.codex/config.toml', '.codex/history.jsonl', 'archive/a', 'src/fabrig', '.codex', '.claude']:
            with self.subTest(path=path):
                self.assertTrue(reaper.never(self.home / path))
        self.assertTrue(reaper.never(Path(self.temp.name)))
        self.assertFalse(reaper.never(self.home / 'scratch'))

    def test_collectors_archives_and_owner_state_never_reaped(self):
        paths = []
        for index, relative in enumerate(('src/fabrig/events', 'src/fabrig/records', 'src/rust/records',
                                          'src/fabrig/archive', 'src/rust/tmp/owners')):
            path = self.old(relative, directory=True)
            self.ended(path, identity=f'protected-{index}')
            paths.append(path)
        self.assertEqual(self.run_class('recorded', True)['kept'], {'never path': 5})
        for path in paths:
            self.assertTrue((path / 'payload').exists())

    def test_recorded_never_path_kept_live(self):
        path = self.old('src/rust/tmp/qa-focused/one', directory=True)
        self.ended(path)
        self.reason(self.run_class('recorded', True), 'never path')
        self.assertTrue(path.exists())

    def test_symlink_outside_kept(self):
        target = put(Path(self.temp.name) / 'outside', 'outside')
        path = self.home / 'src/rust/tmp/logs/link'
        path.parent.mkdir(parents=True)
        path.symlink_to(target)
        os.utime(path, (NOW-30*DAY, NOW-30*DAY), follow_symlinks=False)
        self.reason(self.run_class('heavy-logs', True), 'symlink')
        self.assertEqual(target.read_text(), 'outside')

    def test_symlink_parent_refused(self):
        target = Path(self.temp.name) / 'outside'
        target.mkdir()
        path = self.home / 'scratch'
        path.symlink_to(target, target_is_directory=True)
        with self.assertRaises(OSError):
            list(API['walk'](path / 'child'))

    def test_nested_symlink_never_followed_live(self):
        path = self.old('src/rust/tmp/logs/item', directory=True)
        target = put(Path(self.temp.name) / 'outside', 'outside')
        (path / 'link').symlink_to(target)
        os.utime(path, (NOW-30*DAY, NOW-30*DAY))
        self.assertEqual(self.selected(self.run_class('heavy-logs', True)), {path})
        self.assertEqual(target.read_text(), 'outside')

    def test_fifo_keeps_without_blocking(self):
        path = self.old('src/rust/tmp/logs/item', directory=True)
        os.mkfifo(path / 'pipe')
        os.utime(path, (NOW-30*DAY, NOW-30*DAY))
        self.reason(self.run_class('heavy-logs', True), 'contains special file')

    def test_dry_run_byte_identical_candidate_tree(self):
        path = self.old('src/rust/tmp/logs/item', directory=True)
        before = {str(p): (p.stat().st_mode, p.stat().st_mtime_ns, p.read_bytes()) for p in path.rglob('*') if p.is_file()}
        self.assertEqual(self.selected(self.run_class('heavy-logs')), {path})
        after = {str(p): (p.stat().st_mode, p.stat().st_mtime_ns, p.read_bytes()) for p in path.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_live_removes_exactly_eligible(self):
        old = self.old('src/rust/tmp/logs/old', 8, True)
        new = self.old('src/rust/tmp/logs/new', 1)
        result = self.run_class('heavy-logs', True)
        self.assertEqual(self.selected(result), {old})
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())
        self.assertEqual(result['classes']['heavy-logs']['bytes'], len('payload'))

    def test_recheck_new_process_use_keeps(self):
        path = self.old('src/rust/tmp/logs/item', directory=True)
        reaper = self.reaper(True)
        original = Reaper.snapshot
        calls = []
        def snapshot(instance):
            calls.append(1)
            if len(calls) == 2:
                link = self.proc / '42/cwd'
                link.parent.mkdir()
                link.symlink_to(path)
            return original(instance)
        with patch.object(Reaper, 'snapshot', snapshot):
            self.reason(reaper.execute({'heavy-logs'}, 'live'), 'process use')
        self.assertTrue(path.exists())

    def test_dirty_repo_dry_run_would_bundle(self):
        path = self.repo()
        put(path / 'tracked', 'dirty')
        self.reason(self.run_class('recorded'), 'would archive')
        self.assertFalse((self.home / 'archive').exists())

    def test_dirty_repo_live_bundle_and_worktree_verified(self):
        path = self.repo(remote=False)
        put(path / 'tracked', 'dirty')
        put(path / 'untracked', 'extra')
        result = self.run_class('recorded', True)
        self.assertEqual(self.selected(result), {path}, result)
        self.assertFalse(path.exists())
        bundles = list((self.home / 'archive/reap').rglob('*.bundle'))
        archives = list((self.home / 'archive/reap').rglob('*.tar'))
        self.assertEqual(len(bundles), 1)
        self.assertEqual(len(archives), 1)
        clone = self.home / 'restored'
        subprocess.run(['git', 'clone', str(bundles[0]), str(clone)], check=True, capture_output=True)
        self.assertEqual((clone / 'tracked').read_text(), 'original')
        import tarfile
        with tarfile.open(archives[0]) as tar:
            self.assertEqual(tar.extractfile('repo/tracked').read(), b'dirty')
            self.assertEqual(tar.extractfile('repo/untracked').read(), b'extra')

    def test_stash_bundled_live(self):
        path = self.repo()
        put(path / 'tracked', 'stashed')
        self.git(path, 'stash', 'push')
        self.reason(self.run_class('recorded'), 'would archive')
        self.assertEqual(self.selected(self.run_class('recorded', True)), {path})
        self.assertEqual(len(list((self.home / 'archive').rglob('*.bundle'))), 1)

    def test_local_only_branch_bundled_live(self):
        path = self.repo(remote=False)
        self.reason(self.run_class('recorded'), 'would archive')
        self.assertEqual(self.selected(self.run_class('recorded', True)), {path})

    def test_inherited_git_environment_cannot_redirect_inspection(self):
        path = self.repo(remote=False)
        with patch.dict(os.environ, GIT_DIR=str(self.home / 'does-not-exist'), GIT_WORK_TREE='/bad'):
            self.reason(self.run_class('recorded'), 'would archive')
        self.assertTrue(path.exists())

    def test_failed_summary_in_both_full_report_and_journal(self):
        os.environ['INVOCATION_ID'] = 'fixture'
        self.fake('post', '', 1)
        reaper = self.reaper()
        result = reaper.execute({'notes'}, 'dry-run')
        reaper.save(result)
        journal = json.loads((reaper.state / 'runs.jsonl').read_text())
        full = json.loads(Path(result['list_path']).read_text())
        self.assertIn('daily summary: post failed', journal['errors'][0])
        self.assertEqual(journal['errors'], full['errors'])

    def test_clean_remote_repo_always_has_worktree_tar(self):
        path = self.repo()
        self.assertEqual(self.selected(self.run_class('recorded', True)), {path})
        self.assertEqual(len(list((self.home / 'archive').rglob('*.tar'))), 1)
        self.assertEqual(len(list((self.home / 'archive').rglob('*.bundle'))), 0)

    def test_bundle_failure_keeps(self):
        path = self.repo(remote=False)
        with patch.object(Reaper, 'bundle', side_effect=ValueError('verify failed')):
            self.reason(self.run_class('recorded', True), 'inspection/removal error')
        self.assertTrue(path.exists())

    def test_mutation_during_bundle_keeps(self):
        path = self.repo(remote=False)
        original = Reaper.bundle
        def bundle(instance, repo, dirty):
            result = original(instance, repo, dirty)
            put(path / 'new-file', 'arrived')
            return result
        with patch.object(Reaper, 'bundle', bundle):
            self.reason(self.run_class('recorded', True), 'inspection/removal error')
        self.assertTrue(path.exists())

    def test_repository_helpers_never_execute_in_any_mode(self):
        import io
        from contextlib import redirect_stdout
        for mode in ('dry-run', 'read-only', 'live'):
            with self.subTest(mode=mode):
                path = self.repo('scratch/helper-' + mode, remote=False)
                put(path / 'process-file', 'original')
                put(path / '.gitattributes', 'tracked filter=touchclean\nprocess-file filter=touchprocess\n')
                self.git(path, 'add', '.')
                self.git(path, 'commit', '-m', 'attributes before configuring helpers')
                markers = {name: self.home / (mode+'-'+name+'.touched') for name in ('clean', 'process', 'fsmonitor', 'hook')}
                helpers = self.home / ('helpers-'+mode)
                for name in markers:
                    put(helpers / name, '#!/bin/sh\ntouch '+str(markers[name])+'\n', executable=True)
                self.git(path, 'config', 'filter.touchclean.clean', str(helpers / 'clean'))
                self.git(path, 'config', 'filter.touchprocess.process', str(helpers / 'process'))
                self.git(path, 'config', 'core.fsmonitor', str(helpers / 'fsmonitor'))
                self.git(path, 'config', 'core.hooksPath', str(helpers / 'hooks'))
                for name in ('pre-commit', 'post-checkout', 'reference-transaction', 'post-index-change', 'pre-auto-gc'):
                    put(helpers / 'hooks' / name, '#!/bin/sh\ntouch '+str(markers['hook'])+'\n', executable=True)
                # Same-length changed tracked content triggered the real review.
                put(path / 'tracked', 'changed!')
                put(path / 'process-file', 'changed!')
                if mode == 'read-only':
                    with patch.dict(API['main'].__globals__, Reaper=lambda: self.reaper()):
                        with redirect_stdout(io.StringIO()) as output:
                            self.assertEqual(API['main'](['run', '--dry-run', '--json', '--read-only', '--class', 'recorded']), 0)
                    self.assertIn('would archive', output.getvalue())
                else:
                    result = self.run_class('recorded', mode == 'live')
                    self.assertTrue(result['candidates'])
                    if mode == 'live':
                        self.assertFalse(path.exists(), result)
                self.assertFalse(any(marker.exists() for marker in markers.values()), markers)

    def test_detached_local_head_is_recoverable_from_bundle(self):
        path = self.repo()
        self.git(path, 'checkout', '--detach')
        put(path / 'tracked', 'detached work')
        self.git(path, 'commit', '-am', 'detached local commit')
        head = self.git(path, 'rev-parse', 'HEAD')
        result = self.run_class('recorded', True)
        self.assertEqual(self.selected(result), {path}, result)
        bundle = next((self.home / 'archive/reap').rglob('*.bundle'))
        restored = self.home / 'recovered-detached'
        restored.mkdir()
        self.git(restored, 'init')
        self.git(restored, 'fetch', str(bundle), 'HEAD')
        self.assertEqual(self.git(restored, 'rev-parse', 'FETCH_HEAD'), head)
        self.assertEqual(self.git(restored, 'show', 'FETCH_HEAD:tracked'), 'detached work')

    def test_worktree_tar_excludes_object_store_and_preserves_all_work(self):
        import tarfile
        path = self.repo()
        put(path / 'untracked', 'keep this')
        put(path / '.git/objects/pack/fixture.pack', 'object-store-data')
        result = self.run_class('recorded', True)
        self.assertEqual(self.selected(result), {path}, result)
        archive = next((self.home / 'archive/reap').rglob('*.tar'))
        with tarfile.open(archive) as tar:
            self.assertEqual(tar.extractfile('repo/untracked').read(), b'keep this')
            self.assertTrue(all('/.git/objects' not in name for name in tar.getnames()))

    def test_borrowed_objects_ancestors_and_descendants_are_kept(self):
        store = self.home / 'src/source/.git/objects'
        for suffix in ('pack', 'pack/fixture.pack', 'ab/object'):
            path = self.old('src/source/.git/objects/'+suffix, directory=suffix == 'pack')
            self.ended(path, identity=suffix.replace('/', '-'))
        put(self.home / 'src/borrower/.git/objects/info/alternates', str(store))
        result = self.run_class('recorded', True)
        self.assertTrue(result['candidates'])
        self.assertTrue(all(row['reason'] == 'alternates target' for row in result['candidates']), result)
        self.assertTrue((store / 'pack/fixture.pack').exists())
        self.assertTrue((store / 'ab/object').exists())

    def test_edit_during_slow_final_observation_keeps_archived_repo(self):
        path = self.repo()
        original = Reaper.snapshot
        calls = []
        def snapshot(instance):
            calls.append(1)
            result = original(instance)
            if len(calls) == 2:
                put(path / 'tracked', 'edit during claims/proc observation')
            return result
        with patch.object(Reaper, 'snapshot', snapshot):
            result = self.run_class('recorded', True)
        self.reason(result, 'inspection/removal error')
        self.assertEqual((path / 'tracked').read_text(), 'edit during claims/proc observation')
        self.assertTrue(list((self.home / 'archive').rglob('*.tar')))

    def test_each_removed_entry_must_match_its_inspected_identity(self):
        root = self.old('src/rust/tmp/logs/tree', directory=True)
        put(root / 'a', 'a')
        put(root / 'z', 'original')
        original = os.unlink
        changed = []
        def unlink(name, **kwargs):
            result = original(name, **kwargs)
            if not changed:
                changed.append(True)
                put(root / 'z', 'new owner data')
            return result
        # The root has already been opened/validated when the first unlink
        # replaces a sibling. Its new inode must never be removed.
        with patch('os.unlink', side_effect=unlink):
            self.reason(self.run_class('heavy-logs', True), 'inspection/removal error')
        self.assertEqual((root / 'z').read_text(), 'new owner data')

    def test_start_during_final_observation_prevents_removal(self):
        path = self.old('src/rust/tmp/logs/item')
        original = Reaper.snapshot
        calls = []
        def snapshot(instance):
            calls.append(1)
            if len(calls) == 2:
                self.record('start', path, identity='new-live')
            return original(instance)
        with patch.object(Reaper, 'snapshot', snapshot):
            self.reason(self.run_class('heavy-logs', True), 'record active')
        self.assertTrue(path.exists())

    def test_ledger_exclusion_bounds_writer_wait_and_next_start_retries(self):
        path = self.old('src/rust/tmp/logs/item')
        self.ended(path)
        args = [sys.executable, '-I', '-B', str(ROOT / 'tools/reap/reap'), 'record', 'start',
                '--kind', 'ops-scratch', '--owner', 'new/owner', '--id', 'next', '--path', str(path)]
        original = API['remove']
        seen = []
        def remove(path, expected, manifest, budget=None):
            started = time.monotonic()
            result = subprocess.run(args, capture_output=True, text=True, timeout=4)
            seen.append(time.monotonic()-started)
            self.assertEqual((result.returncode, result.stdout), (0, ''))
            self.assertEqual(len(result.stderr.splitlines()), 1)
            self.assertIn('retry', result.stderr)
            self.assertTrue(path.exists())
            return original(path, expected, manifest, budget)
        with patch.dict(Reaper.execute.__globals__, remove=remove):
            result = self.run_class('recorded', True)
        self.assertEqual(self.selected(result), {path}, result)
        self.assertTrue(1.8 <= seen[0] < 2.8, seen)
        result = subprocess.run(args, capture_output=True, text=True, timeout=4)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertIsNone(self.reaper().records[('ops-scratch', 'next')]['ended'])

    def test_deep_tree_1050_levels_is_iterative_and_reportable(self):
        root = self.old('src/rust/tmp/logs/deep', directory=True)
        fd = os.open(root, API['DIRECTORY'])
        try:
            for _ in range(1050):
                os.mkdir('d', dir_fd=fd)
                child = os.open('d', API['DIRECTORY'], dir_fd=fd)
                os.close(fd)
                fd = child
        finally:
            os.close(fd)
        def cleanup():
            if root.exists():
                manifest = {path.relative_to(root): API['signature'](info) for path, info in API['walk'](root)}
                info = root.stat()
                API['remove'](root, (info.st_dev, info.st_ino), manifest)
        self.addCleanup(cleanup)
        # Exercise every level independently of shared-gate wall-clock load;
        # separate tests advance the clock to verify deadline exhaustion.
        with patch.object(API['time'], 'monotonic', return_value=100):
            result = self.run_class('heavy-logs')
        self.assertEqual(self.selected(result), {root}, result)
        self.assertFalse(result['errors'])

    def test_wide_tree_budget_keeps_data_and_delivers_partial_report(self):
        os.environ['INVOCATION_ID'] = 'fixture'
        root = self.old('src/rust/tmp/logs/wide', directory=True)
        for i in range(100):
            put(root / str(i), 'wide')
        reaper = self.reaper(True)
        reaper.candidate_entries = 20
        result = reaper.execute({'heavy-logs'}, 'live')
        self.reason(result, 'budget')
        self.assertTrue((root / '99').exists())
        reaper.save(result)
        self.assertTrue(Path(result['list_path']).exists())
        body = json.loads((self.home / 'post.calls').read_text())['body']
        self.assertIn(str(root), body)
        self.assertIn('reason budget', body)
        self.assertEqual(json.loads((reaper.state / 'runs.jsonl').read_text())['kept'], {'budget': 1})

    def test_shared_run_budget_preserves_unenumerated_data_and_reports(self):
        root = self.home / 'src/rust/tmp/logs'
        for i in range(100):
            self.old('src/rust/tmp/logs/'+str(i))
        for limit in ('entries', 'time'):
            with self.subTest(limit=limit):
                reaper = self.reaper()
                if limit == 'entries':
                    reaper.run_entries = 5
                else:
                    reaper.run_seconds = 0
                result = reaper.execute({'heavy-logs'}, 'dry-run')
                self.assertTrue(result['traversal']['discovery_incomplete'])
                self.assertEqual(self.selected(result), set())
                self.assertEqual(result['kept'], {'budget': 1})
                self.assertEqual(len(list(root.iterdir())), 100)
                reaper.save(result)
                self.assertTrue((reaper.state / 'last.json').exists())

    def test_candidate_time_budget_does_not_stop_other_candidates(self):
        first = self.old('src/rust/tmp/logs/a')
        second = self.old('src/rust/tmp/logs/b')
        original = Reaper.snapshot
        calls = []
        def snapshot(instance):
            result = original(instance)
            calls.append(1)
            if len(calls) == 2:
                instance.budget.deadline = time.monotonic() - 1
            return result
        with patch.object(Reaper, 'snapshot', snapshot):
            result = self.run_class('heavy-logs', True)
        self.assertEqual(self.selected(result), {second}, result)
        self.assertEqual(result['kept'], {'budget': 1})
        self.assertTrue(first.exists())
        self.assertFalse(second.exists())

    def test_process_metadata_budget_fails_closed_without_sudo_retry(self):
        (self.proc / '42').mkdir()
        with patch('time.monotonic', side_effect=[100, 121]):
            result = API['process_paths'](self.proc)
        self.assertEqual(result['errors'], ['budget'])
        self.old('src/rust/tmp/logs/item')
        reaper = self.reaper()
        reaper.proc = Path('/proc')
        with patch.dict(Reaper.snapshot.__globals__, process_paths=lambda _: result):
            self.reason(reaper.execute({'heavy-logs'}, 'dry-run'), 'budget')

    def test_first_full_mail_groups_only_homogeneous_large_runs(self):
        os.environ['INVOCATION_ID'] = 'fixture'
        for i in range(51):
            self.old(f'src/rust/tmp/logs/log-{i:03}', days=8+i/100)
        self.old('src/rust/tmp/logs/heavy.tsv')
        reaper = self.reaper()
        result = reaper.execute({'heavy-logs'}, 'dry-run')
        reaper.save(result)
        body = json.loads((self.home / 'post.calls').read_text())['body']
        self.assertIn('Class heavy-logs:', body)
        self.assertIn('51 items; total reported bytes 357', body)
        self.assertIn('oldest mtime', body)
        self.assertIn('newest mtime', body)
        self.assertIn(str(self.home / 'src/rust/tmp/logs'), body)
        self.assertNotIn('log-000', body)
        self.assertIn('heavy.tsv', body)
        self.assertIn('reason never path', body)
        self.assertIn(datetime.fromtimestamp(NOW-8.5*DAY, timezone.utc).isoformat(), body)
        self.assertIn(datetime.fromtimestamp(NOW-8*DAY, timezone.utc).isoformat(), body)
        saved = json.loads(Path(result['list_path']).read_text())
        self.assertEqual(len(saved['candidates']), 52)

    def test_git_metadata_root_cannot_archive_outside_candidate(self):
        self.git(self.home, 'init', '-b', 'main')
        put(self.home / 'tracked', 'fixture')
        self.git(self.home, 'add', 'tracked')
        self.git(self.home, 'commit', '-m', 'fixture home repository')
        path = self.home / '.git'
        self.ended(path)
        result = self.run_class('recorded', True)
        self.reason(result, 'inspection/removal error')
        self.assertTrue(path.exists())
        self.assertFalse((self.home / 'archive').exists())

    def test_mode_locked_dry_run(self):
        self.assertEqual(self.config['mode'], 'dry-run')
        with self.assertRaisesRegex(ValueError, 'refused'):
            self.reaper().execute({'notes'}, 'live')
        result = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'tools/reap/reap'), 'run', '--live'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('refused', result.stderr)

    def test_status_summary_journal_and_private_modes(self):
        path = self.old('src/rust/tmp/logs/old')
        reaper = self.reaper()
        result = reaper.execute({'heavy-logs'}, 'dry-run')
        reaper.save(result)
        journal = reaper.state / 'runs.jsonl'
        row = json.loads(journal.read_text())
        self.assertNotIn('candidates', row)
        self.assertEqual(row['classes']['heavy-logs']['bytes'], 7)
        self.assertEqual(stat.S_IMODE(journal.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(reaper.state.stat().st_mode), 0o700)
        self.assertTrue(path.exists())
        result = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'tools/reap/reap'), 'status', '--json'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(json.loads(result.stdout)['candidates']), 1)
        self.assertFalse((self.home / 'post.calls').exists())

    def test_daily_summary_once_per_day_only_timer(self):
        os.environ['INVOCATION_ID'] = 'fixture'
        self.old('src/rust/tmp/logs/old')
        for now in (NOW, NOW+3600, NOW+DAY):
            reaper = self.reaper()
            reaper.now = now
            reaper.save(reaper.execute({'heavy-logs'}, 'dry-run'))
        calls = [json.loads(line) for line in (self.home / 'post.calls').read_text().splitlines()]
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]['args'][:5], ['send', '--as', 'reap', 'ops@hel8', f'reap {os.uname().nodename} {time.strftime("%Y-%m-%d", time.gmtime(NOW))}'])
        self.assertIn(str(self.home / 'src/rust/tmp/logs/old'), calls[0]['body'])
        self.assertIn('First complete candidate list', calls[0]['body'])
        self.assertNotIn('First complete candidate list', calls[1]['body'])
        self.assertIn('Full JSON:', calls[0]['body'])

    def test_manual_service_start_does_not_send(self):
        os.environ['INVOCATION_ID'] = 'fixture'
        self.fake('systemctl', '0')
        reaper = self.reaper()
        reaper.save(reaper.execute({'notes'}, 'dry-run'))
        self.assertFalse((self.home / 'post.calls').exists())

    def test_lock_contention_quiet_zero(self):
        lock = self.home / '.local/state/reap/lock'
        put(lock, '')
        with lock.open('r+') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            result = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'tools/reap/reap'), 'run', '--json'], capture_output=True, text=True, timeout=10)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))

    def test_overlap_counted_once(self):
        path = self.old('src/rust/tmp/logs/old', 8, True)
        self.ended(path)
        result = self.reaper().execute({'recorded', 'heavy-logs'}, 'dry-run')
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(sum(row['bytes'] for row in result['classes'].values()), 7)

    def test_units_render_every_host(self):
        fleet = runpy.run_path(str(ROOT / 'tools/fleet-sync'))
        declarations = fleet['Declarations'](ROOT, self.home)
        for host in declarations.hosts:
            self.assertTrue({'reap.service', 'reap.timer'} <= declarations.host_units(host))
        service = declarations.units['reap.service']
        self.assertIn('Nice=10', service)
        self.assertIn('IOSchedulingClass=idle', service)
        self.assertIn('"$$HOME/src/fabrig/current/tools/reap/reap" run', service)
        self.assertIn('OnActiveSec=1min', declarations.units['reap.timer'])
        self.assertIn('OnBootSec=2min', declarations.units['reap.timer'])
        self.assertIn('OnUnitActiveSec=15min', declarations.units['reap.timer'])
        self.assertIn('RandomizedDelaySec=30', declarations.units['reap.timer'])
        self.assertIn('AccuracySec=1s', declarations.units['reap.timer'])
        # Explicit task values bound activation at 60 + 30 + 1 seconds.
        timer = dict(line.split('=', 1) for line in declarations.units['reap.timer'].splitlines() if '=' in line)
        def seconds(value):
            return int(value[:-3]) * 60 if value.endswith('min') else int(value.removesuffix('s'))
        self.assertLessEqual(seconds(timer['OnActiveSec']) + seconds(timer['RandomizedDelaySec']) + seconds(timer['AccuracySec']), 91)
        self.assertLessEqual(seconds(timer['OnBootSec']) + seconds(timer['RandomizedDelaySec']) + seconds(timer['AccuracySec']), 151)


if __name__ == '__main__':
    unittest.main()
