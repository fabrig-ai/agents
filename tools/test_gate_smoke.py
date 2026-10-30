"""Fast declaration smoke: gate ownership, selectors and installed paths exist."""
from pathlib import Path
import tomllib
import unittest

ROOT = Path(__file__).resolve().parent.parent


class Smoke(unittest.TestCase):
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
