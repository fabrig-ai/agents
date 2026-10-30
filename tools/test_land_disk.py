"""Read-only HOME disk admission precedes central builder claiming."""
import json
from test_land import LandFixture, put


class DiskTests(LandFixture):
    def test_prefers_most_free_space(self):
        self.env['DISK_SPACES'] = json.dumps(dict(builder7=120*1024**3, builder3=100*1024**3))
        output = self.land('--dry-run')
        self.assertIn('claimed hetzner7 slot 4', output)
        self.assertIn('restored hetzner7: removed /tmp/agents-gate.', output)
        self.assert_released()

    def test_below_floor_skipped_even_when_it_has_most_space(self):
        path = self.source/'fleet/hosts.toml'
        put(path, path.read_text().replace('[hosts.hetzner7]', '[hosts.hetzner7]\nmachine_env={PLAN_MIN_DISK_GB=130}'))
        self.git('add', '.')
        self.git('commit', '-qm', 'disk floor fixture')
        self.env['DISK_SPACES'] = json.dumps(dict(builder7=120*1024**3, builder3=85*1024**3))
        output = self.land('--dry-run')
        self.assertIn('skip hetzner7: HOME available', output)
        self.assertIn('claimed hetzner3 slot 1', output)
        self.assert_released()

    def test_low_or_unknown_disk_never_claimed(self):
        self.env['DISK_SPACES'] = json.dumps(dict(builder7=84*1024**3, builder3=80*1024**3))
        self.land('--dry-run', expected=1)
        self.assertFalse(any(a[:2] == ['claim','claim'] for a in self.calls()))
        self.env['DISK_UNKNOWN'] = '1'
        self.land('--dry-run', expected=1)
        self.assertFalse(any(a[:2] == ['claim','claim'] for a in self.calls()))
