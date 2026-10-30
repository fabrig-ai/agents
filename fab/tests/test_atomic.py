import unittest
from pathlib import Path
from unittest.mock import patch

from fab import atomic
from fab.tests.support import tmp_home


class AtomicTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())

    def test_write_creates_parents_and_replaces_whole_file(self):
        path = self.home / "nested" / "file"
        atomic.write(path, "long old contents")
        atomic.write(path, "café\n")
        self.assertEqual(path.read_bytes(), "café\n".encode("utf-8"))
        self.assertEqual(list(path.parent.iterdir()), [path])

    def test_sibling_is_hidden_in_destination_directory(self):
        path = self.home / "file"
        replace = Path.replace

        def rename(sibling, destination):
            self.assertEqual(destination, path)
            self.assertEqual(sibling.parent, path.parent)
            self.assertTrue(sibling.name.startswith(".file."))
            self.assertEqual(sibling.read_text(encoding="utf-8"), "complete")
            return replace(sibling, destination)

        with patch("fab.atomic.Path.replace", autospec=True, side_effect=rename) as renamed:
            atomic.write(path, "complete")
        renamed.assert_called_once()

    def test_failed_rename_preserves_old_file_and_removes_sibling(self):
        path = self.home / "file"
        atomic.write(path, "old")
        with patch("fab.atomic.Path.replace", side_effect=OSError("rename failed")):
            with self.assertRaisesRegex(OSError, "rename failed"):
                atomic.write(path, "new")
        self.assertEqual(path.read_text(encoding="utf-8"), "old")
        self.assertEqual(list(self.home.iterdir()), [path])

    def test_failed_encoding_preserves_old_file_and_removes_sibling(self):
        path = self.home / "file"
        atomic.write(path, "old")
        with self.assertRaises(UnicodeEncodeError):
            atomic.write(path, "\ud800")
        self.assertEqual(path.read_text(encoding="utf-8"), "old")
        self.assertEqual(list(self.home.iterdir()), [path])

    def test_extend_appends_existing_text(self):
        path = self.home / "file"
        atomic.write(path, "café")
        atomic.extend(path, "\nmore")
        self.assertEqual(path.read_text(encoding="utf-8"), "café\nmore")
        self.assertEqual(list(self.home.iterdir()), [path])

    def test_extend_creates_missing_file_and_parents(self):
        path = self.home / "nested" / "file"
        atomic.extend(path, "new")
        self.assertEqual(path.read_text(encoding="utf-8"), "new")
        self.assertEqual(list(path.parent.iterdir()), [path])
