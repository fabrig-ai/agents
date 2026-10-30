"""Fast declaration smoke: gate ownership, selectors and installed paths exist."""
from pathlib import Path
import importlib.util
import tomllib
import unittest

ROOT = Path(__file__).resolve().parent.parent


class Smoke(unittest.TestCase):
    def test_fleet_changes_select_landing_and_periodic_declaration_coverage(self):
        spec = importlib.util.spec_from_file_location('gate_fleet_selection', ROOT / 'tools/gate.py')
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        config = gate.configuration(ROOT)
        readers = {str(path.relative_to(ROOT)) for path in (ROOT / 'tools').rglob('test_*.py')
                   if any(name in path.read_text() for name in ('fleet/hosts.toml', 'fleet/units/'))}
        readers.update({'tools/test_land.py', 'tools/test_periodic.py'})
        for change in ('fleet/hosts.toml', 'fleet/units/agents-periodic.service'):
            for tier in ('gate', 'periodic'):
                with self.subTest(change=change, tier=tier):
                    expected = readers & set(gate.discover(ROOT, tier))
                    self.assertLessEqual(expected, set(gate.select(ROOT, config, [change], tier)))

    def test_gate_and_installed_declarations(self):
        config = tomllib.loads((ROOT / 'tools/gate.toml').read_text())
        files = {p.relative_to(ROOT).as_posix() for p in (ROOT / 'tools').rglob('test_*.py')}
        self.assertEqual(files, set(config['files']))
        for name, row in config['files'].items():
            self.assertTrue(row['owner'], name)
        for tests in config['select'].values():
            self.assertTrue(tests == ['*'] or set(tests) <= files)
        for line in (ROOT / 'tools/installed').read_text().splitlines():
            parts = line.split()
            if parts and not line.startswith('#'):
                self.assertTrue((ROOT / 'tools' / parts[-1]).is_file(), line)


if __name__ == '__main__':
    unittest.main()
