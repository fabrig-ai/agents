"""Upstream race policy with disposable remotes and fake claimed builders."""
import unittest
import fcntl
import json
from pathlib import Path
import signal
import subprocess
import time
import test_land as fixture


class LandRaceTests(fixture.LandFixture):
    def test_local_gate_uses_pinned_snapshot_despite_uncommitted_live_edit(self):
        self.env.update(WAIT_GATE='1', SNAPSHOT_PROBE='1')
        candidate = self.git('rev-parse', 'HEAD')
        child = subprocess.Popen(['python3', '-I', '-B', 'tools/land', '--local', '--keep-branch'],
                                 cwd=self.source, env=self.env, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 10
            while not (self.home / 'ready').exists():
                self.assertIsNone(child.poll())
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
            fixture.put(self.source / 'a/change', 'uncommitted live edit')
            fixture.put(self.home / 'end-gate', 'finish')
            out, err = child.communicate(timeout=10)
            self.assertEqual(child.returncode, 0, out + err)
            tested = json.loads((self.home / 'tested-snapshot.json').read_text())
            self.assertEqual(tested['sha'], candidate)
            self.assertEqual(tested['value'], 'feature')
            self.assertNotEqual(Path(tested['root']), self.source)
            self.assertFalse(Path(tested['root']).exists())
            self.assertEqual(self.tip(), tested['sha'])
            self.assertEqual((self.source / 'a/change').read_text(), 'uncommitted live edit')
        finally:
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
                child.communicate(timeout=10)

    def test_local_checkout_lock_stays_held_while_waiting_for_host_gate(self):
        host_lock = self.home / '.local/state/agents-gate.lock'
        host_lock.parent.mkdir(parents=True, exist_ok=True)
        with host_lock.open('a') as lock, (self.home / 'local-output').open('w') as output:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            child = subprocess.Popen(['python3', '-I', '-B', 'tools/land', '--local', '--dry-run'],
                                     cwd=self.source, env=self.env, stdout=output, stderr=output)
            try:
                deadline = time.monotonic() + 5
                while 'waiting for another agents gate' not in (self.home / 'local-output').read_text():
                    self.assertIsNone(child.poll())
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(.01)
                # Let the re-exec, if any, reach its blocked host-lock acquisition.
                time.sleep(.1)
                with (self.source / '.git/agents-land.lock').open('a') as checkout:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(checkout, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                child.send_signal(signal.SIGINT)
                child.wait(timeout=5)
        self.assertFalse((self.home / 'ssh.log').exists())
        self.assertEqual(self.tip(), self.original)

    def test_checkout_lock_refuses_another_lander_before_remote_work(self):
        with (self.source / '.git/agents-land.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.land('--host', 'hetzner7', expected=1)
            self.assertIn('agents-land.lock', self.last_result.stderr)
            self.assertFalse((self.home / 'ssh.log').exists())
            self.assertEqual(self.tip(), self.original)

    def test_local_head_advance_during_remote_gate_refuses_push(self):
        self.env['WAIT_GATE'] = '1'
        child = subprocess.Popen(['python3', '-I', '-B', 'tools/land', '--host', 'hetzner7',
                                  '--inventory', str(self.inventory)], cwd=self.source,
                                 env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 10
            while not (self.home / 'ready').exists():
                self.assertIsNone(child.poll())
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
            checked = self.git('rev-parse', 'HEAD')
            fixture.put(self.source / 'a/unchecked', 'concurrent commit')
            self.git('add', '.')
            self.git('commit', '-qm', 'unchecked descendant')
            fixture.put(self.home / 'end-gate', 'finish')
            out, err = child.communicate(timeout=10)
            self.assertNotEqual(child.returncode, 0, out + err)
            self.assertIn('HEAD moved', err)
            self.assertEqual(self.tip(), self.original)
            self.assertNotEqual(checked, self.git('rev-parse', 'HEAD'))
            self.assert_released()
        finally:
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
                child.communicate(timeout=10)

    def test_races_disjoint_once_overlapping_twice_second_refused(self):
        self.env['RACE_PATH']='b/upstream'
        self.land('--host','hetzner7')
        self.assertEqual((self.home/'gates').read_text(),'1')
        self.assertEqual(self.tip(),self.git('rev-parse','HEAD'))
        self.assert_released()

    def test_overlapping_race_checks_twice(self):
        self.env['RACE_PATH']='a/upstream'
        self.land('--host','hetzner7')
        self.assertEqual((self.home/'gates').read_text(),'2')
        self.assert_released()

    def test_second_race_never_pushes_candidate(self):
        self.env.update(RACE_PATH='a/upstream',SECOND_RACE='1')
        self.land('--host','hetzner7',expected=1)
        self.assertNotEqual(self.tip(),self.git('rev-parse','HEAD'))
        self.assert_released()


if __name__ == "__main__":
    unittest.main()
