"""Atomic retention and probe packaging, isolated from host state."""
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPOOL = runpy.run_path(str(Path(__file__).with_name('event_spool.py')))
NOW = datetime(2026, 10, 30, 0, 30, tzinfo=timezone.utc).timestamp()


def event(identity, seconds, source='runs'):
    return dict(id=identity, source=source, host='hel8', kind='run-start',
                time=datetime.fromtimestamp(NOW-seconds, timezone.utc).isoformat())


class Spool(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.env = patch.dict(os.environ, HOME=str(self.home))
        self.env.start()
        self.addCleanup(self.env.stop)
        self.root = self.home/'src/fabrig/events'

    def append(self, rows, source='runs'):
        SPOOL['append'](source, rows, NOW)

    def test_two_hour_cut_across_midnight_empty_days_removed_and_dedup(self):
        self.append([event('keep', 119*60), event('drop', 121*60), event('edge', 120*60),
                     event('today', 0), event('old-day', 48*3600)])
        self.assertEqual({r['id'] for r in SPOOL['read'](self.root, 'runs', NOW)}, {'keep', 'edge', 'today'})
        self.assertEqual(sorted(p.name for p in (self.root/'runs').glob('*.jsonl')),
                         ['2026-10-29.jsonl', '2026-10-30.jsonl'])
        self.append([event('keep', 119*60)])
        self.assertEqual(len(SPOOL['read'](self.root, 'runs', NOW)), 3)
        SPOOL['append']('runs', [], NOW+7201)
        self.assertEqual(list((self.root/'runs').glob('*.jsonl')), [])

    def test_atomic_rewrite_failure_keeps_original_and_source_lock(self):
        self.append([event('one', 0)])
        path = self.root/'runs/2026-10-30.jsonl'
        original = path.read_bytes()
        real_replace = os.replace
        calls = []
        def observe(sibling, destination):
            self.assertEqual(Path(sibling).parent, path.parent)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(Path(sibling).stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(Path(sibling).read_text().splitlines()), 2)
            with (path.parent/'.lock').open('rb') as lock:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            calls.append(destination)
            real_replace(sibling, destination)
        with patch('os.replace', side_effect=observe):
            self.append([event('two', 0)])
        self.assertEqual(calls, [path])
        complete = path.read_bytes()
        with patch('os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.append([event('three', 0)])
        self.assertEqual(path.read_bytes(), complete)
        self.assertEqual(list(path.parent.glob('.'+path.name+'.*')), [])
        self.assertEqual((path.parent/'.lock').stat().st_mode & 0o777, 0o600)

    def test_malformed_timestamps_fail_as_input_errors(self):
        for value in (None, 42, 'invalid', '2026-10-30T00:30:00'):
            with self.subTest(time=value), self.assertRaises(ValueError):
                self.append([event('bad', 0) | {'time': value}])

    def test_context_outbox_migration_drops_samples(self):
        context = event('context', 0, 'sessions') | {'kind': 'context'}
        self.append([context, event('start', 0, 'sessions')], 'sessions')
        rows = SPOOL['read'](self.root, 'sessions', NOW)
        self.assertEqual([r['id'] for r in rows], ['start'])

    def test_real_stdin_probes_include_the_shared_reader(self):
        # Execute shipped sources with only fake capacity/subscription commands.
        self.append([event('fresh', 60), event('expired', 7260)])
        self.append([event('queue', 60, 'queue')], 'queue')
        for name, argument in (('watch', '--probe'), ('status-page', 'collect')):
            with self.subTest(probe=name):
                tool = Path(__file__).with_name(name)
                source = SPOOL['probe_source'](tool)
                env = dict(os.environ, PATH='/usr/bin:/bin', STATUS_NOW=str(NOW),
                           STATUS_PROBE_TIMEOUT='0.1')
                if name == 'status-page':
                    for function in ('part_machine', 'part_claude_usage', 'part_codex_usage'):
                        source = source.replace(', ' + function + ')', ', lambda *args: {})')
                # Freeze the probe clock before its own imports/main.
                source = f'import time\ntime.time = lambda: {NOW}\n' + source
                result = subprocess.run(['python3', '-I', '-B', '-', argument], input=source,
                                        text=True, capture_output=True, env=env, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(result.stdout)
                self.assertIn('spools', data)
                self.assertEqual([r['id'] for r in data['spools']['queue']], ['queue'])
                if name == 'status-page':
                    self.assertEqual([r['id'] for r in data['spools']['runs']], ['fresh'])


if __name__ == '__main__':
    unittest.main()
