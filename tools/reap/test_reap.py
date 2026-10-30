"""Offline reaper tests: disposable HOME, service fakes and proc namespace."""
import argparse
from contextlib import contextmanager
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
from unittest.mock import patch

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

    def record(self, event, path=None, kind='ops-scratch', identity='one', owner='lead/q/temper'):
        args = argparse.Namespace(event=event, kind=kind, owner=owner, id=identity, path=[] if path is None else [str(path)])
        self.reaper().record(args)

    def ended(self, path, kind='ops-scratch', identity='one', days=30):
        self.record('start', path, kind, identity)
        reaper = self.reaper()
        reaper.now = NOW-days*DAY
        reaper.record(argparse.Namespace(event='end', kind=kind, owner='coordinator/dm/stamp', id=identity, path=[]))

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

    def test_codex_runs_require_old_ended_file(self):
        old = self.old('src/rust/tmp/codex-run/old', directory=True)
        self.old('src/rust/tmp/codex-run/active', directory=True)
        new = self.old('src/rust/tmp/codex-run/new', directory=True)
        self.old('src/rust/tmp/codex-run/runs.tsv')
        put(old / 'ended', age=8*DAY)
        put(new / 'ended', age=DAY)
        self.assertEqual(self.selected(self.run_class('codex-runs')), {old})

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

    def test_notes_and_tasks_recursive(self):
        old = {self.old('src/fabrig/notes/nested/old', 8), self.old('src/fabrig/tasks/old', 8)}
        self.old('src/fabrig/notes/new', 1)
        self.old('src/fabrig/notes/nested/queue.jsonl', 8)
        self.old('src/fabrig/tasks/queue.out', 8)
        result = self.run_class('notes')
        self.assertEqual(self.selected(result), old)
        self.assertEqual(result['kept'], {'never path': 2})

    def test_codex_sessions_only_rollouts(self):
        old = self.old('.codex/sessions/2025/10/rollout.jsonl', 15)
        self.old('.codex/sessions/2026/10/new.jsonl', 1)
        auth = self.old('.codex/auth.json', 30)
        self.assertEqual(self.selected(self.run_class('codex-sessions')), {old})
        self.assertTrue(auth.exists())

    def test_recorded_kind_retention(self):
        for number, (kind, seconds) in enumerate(self.config['kinds'].items()):
            with self.subTest(kind=kind):
                path = self.old(f'.claude/jobs/id{number}' if kind == 'claude-session' else f'scratch/{kind}')
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

    def test_active_records_protect_discovery(self):
        path = self.old('src/rust/tmp/logs/old', 8)
        self.record('start', path)
        self.reason(self.run_class('heavy-logs'), 'record active')
        self.assertEqual(self.run_class('recorded')['candidates'], [])

    def test_claude_record_cannot_name_other_paths(self):
        with self.assertRaisesRegex(ValueError, 'jobs directory'):
            self.record('start', self.home / 'scratch/one', 'claude-session')

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

    def test_alternates_absolute_and_relative(self):
        for relative in (False, True):
            with self.subTest(relative=relative):
                path = self.old('src/rust/tmp/logs/store', directory=True)
                alternate = self.home / 'src/borrower/.git/objects/info/alternates'
                target = path / 'objects'
                put(alternate, os.path.relpath(target, alternate.parent.parent) if relative else str(target))
                self.reason(self.run_class('heavy-logs'), 'alternates target')

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

    def test_alternates_limit_fails_closed(self):
        self.old('src/rust/tmp/logs/item')
        deep = self.home / 'src' / Path(*(['deep'] * 65))
        deep.mkdir(parents=True)
        self.reason(self.run_class('heavy-logs'), 'alternates incomplete: ValueError')

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
                     'src/fabrig/leases/a', 'src/fabrig/queue/a', 'src/fabrig/main/a', 'src/fabrig/agents/a',
                     'src/fabrig/current/a', 'src/fabrig/releases/a', '.local/state/fleet-sync/a',
                     '.local/state/fabrig/a', '.local/state/heavy/a', '.ssh/id', '.claude/.credentials.json',
                     '.claude.json', '.codex/auth.json', 'archive/a', 'src/fabrig', '.codex', '.claude']:
            with self.subTest(path=path):
                self.assertTrue(reaper.never(self.home / path))
        self.assertTrue(reaper.never(Path(self.temp.name)))
        self.assertFalse(reaper.never(self.home / 'scratch'))

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
        self.reason(self.run_class('recorded'), 'would bundle')
        self.assertFalse((self.home / 'archive').exists())

    def test_dirty_repo_live_bundle_and_worktree_verified(self):
        path = self.repo()
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
        self.reason(self.run_class('recorded'), 'would bundle')
        self.assertEqual(self.selected(self.run_class('recorded', True)), {path})
        self.assertEqual(len(list((self.home / 'archive').rglob('*.bundle'))), 1)

    def test_local_only_branch_bundled_live(self):
        path = self.repo(remote=False)
        self.reason(self.run_class('recorded'), 'would bundle')
        self.assertEqual(self.selected(self.run_class('recorded', True)), {path})

    def test_clean_remote_repo_no_bundle(self):
        path = self.repo()
        self.assertEqual(self.selected(self.run_class('recorded', True)), {path})
        self.assertFalse((self.home / 'archive').exists())

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
        self.assertLess(len(calls[0]['body'].splitlines()), 15)
        self.assertIn('Full list:', calls[0]['body'])

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
        self.assertIn('OnBootSec=5min', declarations.units['reap.timer'])
        self.assertIn('OnUnitActiveSec=15min', declarations.units['reap.timer'])
        self.assertIn('RandomizedDelaySec=120', declarations.units['reap.timer'])


if __name__ == '__main__':
    unittest.main()
