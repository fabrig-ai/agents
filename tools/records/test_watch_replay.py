#!/usr/bin/env -S python3 -I -B
"""Offline replay uses only lifecycle records under a temporary HOME."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

TOOL = Path(__file__).with_name('replay_watch.py').resolve()


class Replay(unittest.TestCase):
    def test_replay_excludes_short_runs_and_does_not_use_future_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            records = home / 'records'
            def write(source, rows):
                path = records / f'{source}/2026-10-29.jsonl'
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            def event(kind, run, time, **fields):
                return dict(kind=kind, run=run, host='hel8', effort='high', time='2026-10-29T'+time+'Z', **fields)
            rows = [event('run-start', 'short', '00:00:00'),
                    event('run-end', 'short', '00:55:00', minutes=55),
                    event('run-start', 'long', '00:00:00'),
                    event('run-end', 'long', '01:40:00', minutes=100)]
            # These five short completions must not lower the 90-minute fallback
            # before they have actually finished at 01:35.
            for i in range(5):
                rows += [event('run-start', str(i), '01:34:00'),
                         event('run-end', str(i), '01:35:00', minutes=1)]
            write('runs', rows)
            write('watch', [dict(kind='heartbeat', time='2026-10-29T00:00:00Z'),
                            dict(kind='heartbeat', time='2026-10-29T02:00:00Z')])
            before = {p: p.read_bytes() for p in records.rglob('*.jsonl')}
            result = subprocess.run(['python3', '-I', '-B', str(TOOL), str(records), '--day', '2026-10-29'],
                                    env=dict(os.environ, HOME=str(home)), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            day = json.loads(result.stdout)['days'][0]
            self.assertEqual(day['run_hung_openings_upper_bound'], 1)
            self.assertEqual(day['openings'], [dict(subject='hel8/long', time='2026-10-29T01:32:00Z')])
            self.assertEqual({p: p.read_bytes() for p in records.rglob('*.jsonl')}, before)
            self.assertFalse((home / '.local').exists())


if __name__ == '__main__':
    unittest.main()
