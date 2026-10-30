"""Reconciliation uses only fixture SSH, claims, processes and private HOME."""
import json
import os
from pathlib import Path
import time
import unittest
import test_land as fixture


class ReconcileTests(fixture.LandFixture):
    def drop_run(self):
        self.env.update(WAIT_GATE='1', DROP_WAIT='1')
        self.land('--host', 'hetzner7', expected=1)
        row = self.assert_kept()
        self.assertIsInstance(row['remote_pgid'], int)
        self.assertEqual(row['sha'], self.git('rev-parse', 'HEAD'))
        self.assertTrue(Path(row['remote_dir']).is_dir())
        self.assertEqual(self.records()[0].stat().st_mode & 0o777, 0o600)
        self.assertFalse(any(call == ['remote', 'cleanup'] for call in self.calls()))
        self.env.pop('DROP_WAIT')
        return row

    def test_ssh_drop_and_live_reconcile_keep_claim_until_explicit_kill(self):
        row = self.drop_run()
        before = len(self.calls())
        self.land('--reconcile', row['id'], expected=1)
        self.assert_kept()
        self.assertEqual(self.calls()[before:], [['remote', 'inspect']])
        self.land('--reconcile', row['id'], '--kill')
        self.assert_released()
        self.assertFalse(self.records())

    def test_reconcile_ended_run_releases_after_read_only_inspection(self):
        row = self.drop_run()
        fixture.put(self.home / 'end-gate', 'finish')
        deadline = time.monotonic() + 5
        state = Path(row['remote_dir']) / 'run.json'
        while json.loads(state.read_text())['phase'] != 'finished':
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.01)
        before = len(self.calls())
        self.land('--reconcile')
        self.assertEqual(self.calls()[before], ['remote', 'inspect'])
        self.assertNotIn(['remote', 'kill'], self.calls()[before:])
        self.assert_released()
        self.assertFalse(self.records())

    def test_lost_release_ack_is_reconciled_only_after_central_free_proof(self):
        self.env['LOSE_RELEASE_REPLY'] = '1'
        self.land('--host', 'hetzner7', '--dry-run', expected=1)
        self.assertFalse((self.home / 'claim.json').exists())
        self.assertEqual(len(self.records()), 1)
        row = json.loads(self.records()[0].read_text())
        self.assertTrue(row['restored'])
        self.env.pop('LOSE_RELEASE_REPLY')
        self.land('--reconcile', row['id'])
        self.assertFalse(self.records())
        self.assertFalse((self.home / 'claim.json').exists())

    def test_missing_process_identity_never_authorizes_release(self):
        row = self.drop_run()
        status = Path(row['remote_dir']) / 'run.json'
        saved = status.read_text()
        try:
            status.unlink()
            unknown = dict(row, pgid=None, remote_pgid=None, supervisor_pid=None)
            fixture.put(self.records()[0], json.dumps(unknown))
            self.land('--reconcile', row['id'], expected=1)
            self.assert_kept()
        finally:
            fixture.put(status, saved)
            fixture.put(self.records()[0], json.dumps(row))
        self.land('--reconcile', row['id'], '--kill')
        self.assert_released()

    def test_unknown_directory_removal_keeps_claim_for_reconcile(self):
        self.env['DROP_CLEANUP'] = '1'
        self.land('--host', 'hetzner7', expected=1)
        row = self.assert_kept()
        self.assertTrue(row['exit_seen'])
        self.assertTrue(row['restoration_pending'])
        self.assertTrue(Path(row['remote_dir']).exists())
        self.env.pop('DROP_CLEANUP')
        self.land('--reconcile', row['id'])
        self.assert_released()

    def test_heavy_submission_is_a_bug_and_retains_claim(self):
        self.env['BUG_HEAVY'] = '1'
        self.land('--host', 'hetzner7', expected=1)
        row = self.assert_kept()
        self.land('--reconcile', row['id'], expected=1)
        self.assert_kept()
        fixture.put(self.home / 'src/rust/tmp/heavy/state.json', json.dumps(dict(version=1,tasks={})))
        self.land('--reconcile', row['id'])
        self.assert_released()

    def test_budget_labels_in_both_modes_and_report_only_over(self):
        for enforce, wall, label in [('false', '0.001', 'budget: REPORT-ONLY (not enforced)'),
                                     ('true', '60', 'budget: ENFORCED')]:
            fixture.put(self.source / 'tools/gate.toml', '[budget]\nenforce = ' + enforce +
                        '\nmerge_wall_s = ' + wall + '\n')
            self.git('add', '.')
            self.git('commit', '-qm', 'budget mode')
            output = self.land('--local', '--dry-run')
            self.assertIn(label, output)
            if enforce == 'false':
                self.assertIn('OVER (report-only)', output)






if __name__ == '__main__':
    unittest.main()
