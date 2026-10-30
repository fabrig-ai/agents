import unittest
from pathlib import Path
from unittest.mock import patch

from fab import atomic
from fab.tests.support import tmp_home


class AtomicTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.path = self.home / "nested" / "state.txt"

    def test_write_creates_parents_and_replaces_whole_file(self):
        atomic.write(self.path, "old content with a longer tail\n")
        atomic.write(self.path, "new café\n")
        self.assertEqual(self.path.read_bytes(), "new café\n".encode("utf-8"))
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_failed_replace_keeps_destination_and_removes_hidden_sibling(self):
        atomic.write(self.path, "old\n")
        siblings = []

        def refuse(source, destination):
            siblings.append(source)
            self.assertEqual(source.parent, self.path.parent)
            self.assertTrue(source.name.startswith(f".{self.path.name}."))
            self.assertEqual(source.read_text(encoding="utf-8"), "new\n")
            self.assertEqual(destination, self.path)
            self.assertEqual(self.path.read_text(encoding="utf-8"), "old\n")
            raise OSError("replace failed")

        with patch.object(Path, "replace", refuse):
            with self.assertRaisesRegex(OSError, "replace failed"):
                atomic.write(self.path, "new\n")
        self.assertEqual(len(siblings), 1)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "old\n")
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_failed_text_write_keeps_destination_and_removes_sibling(self):
        atomic.write(self.path, "old\n")
        with self.assertRaises(UnicodeEncodeError):
            atomic.write(self.path, "invalid \ud800")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "old\n")
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_extend_appends_utf8_text(self):
        atomic.write(self.path, "café\n")
        atomic.extend(self.path, "more\n")
        self.assertEqual(self.path.read_bytes(), "café\nmore\n".encode("utf-8"))
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_extend_creates_missing_file_and_parents(self):
        atomic.extend(self.path, "first\n")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "first\n")
