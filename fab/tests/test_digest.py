"""The digest core reads small trees, without git (docs/design/fab.md, 4; fab-gates.md, 2)."""

from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch
from pathlib import Path

from fab import digest
from fab.calls import Signature
from fab.plan import Task
from fab.sh import Failed, Result
from fab.tests.support import FakeRunner, git, git_pair, tmp_home


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sibling = path.with_name(path.name + ".tmp")
    sibling.write_text(text, encoding="utf-8")
    sibling.replace(path)


def function(name: str, lines: int) -> str:
    return f"def {name}():\n" + "".join(f"    {name}_{index} = {index}\n" for index in range(lines - 1))


class PathsTest(unittest.TestCase):
    def test_classify_tests_win_over_docs(self):
        for path, kind in (
            ("fab/run.py", "production"),
            ("fab/tests/helpers.py", "tests"),
            ("elsewhere/test_api.py", "tests"),
            ("fab/roles/reader.md", "docs"),
            ("docs/example.py", "docs"),
            ("bin/fab", "production"),
            ("fab/hosts.toml", "production"),
            ("fab/tests/notes.md", "tests"),
            ("docs/test_example.md", "tests"),
            ("fab/tests_extra/api.py", "production"),
        ):
            with self.subTest(path=path):
                self.assertEqual(digest.classify(path), kind)

    def test_outside_exact_and_component_globs(self):
        paths = ["fab/nested/api.py", "fab/z.py", "docs/guide.md", "fab/a.py", "bin/fab"]
        self.assertEqual(digest.outside(paths, ["bin/fab", "fab/*.py"]),
                         ["docs/guide.md", "fab/nested/api.py"])
        self.assertEqual(digest.outside(paths, ["fab/**/*.py"]), ["bin/fab", "docs/guide.md"])
        self.assertEqual(digest.outside(paths, ["**"]), [])
        self.assertEqual(digest.outside(paths, []), sorted(paths))
        self.assertEqual(digest.outside([], ["fab/*.py"]), [])


class ItemsTest(unittest.TestCase):
    def test_added_removed_changed_method_and_docstring_only(self):
        with tmp_home() as root:
            base, tip = root / "base", root / "tip"
            write(base / "fab/a.py", '''class Gone:
    """Removed class."""

class Kept:
    """Old description."""

def update(value: int) -> int:
    """Old function doc."""
    return value

def documented():
    """Old doc."""
    pass
''')
            write(tip / "fab/a.py", '''class Kept:
    """New description."""
    def method(self, value):
        """New method."""
        return value

def update(value: str) -> str:
    """New function doc."""
    return value

def documented():
    """New doc."""
    pass

def added():
    """New function."""
    pass
''')
            added, removed, changed = digest.items(base, tip)
            self.assertEqual(added, [Signature("fab/a.py", "Kept.method", "def method(self, value)", "New method."),
                                     Signature("fab/a.py", "added", "def added()", "New function.")])
            self.assertEqual(removed, [Signature("fab/a.py", "Gone", "class Gone", "Removed class.")])
            self.assertEqual(changed, [(Signature("fab/a.py", "update", "def update(value: int) -> int", "Old function doc."),
                                        Signature("fab/a.py", "update", "def update(value: str) -> str", "New function doc."))])

    def test_first_duplicate_key_and_inventory_order(self):
        with tmp_home() as root:
            base, tip = root / "base", root / "tip"
            write(base / "fab/a.py", "def first(x): pass\ndef first(y): pass\ndef removed_z(): pass\ndef removed_a(): pass\n")
            write(tip / "fab/a.py", "def new_z(): pass\ndef first(x): pass\ndef first(z): pass\ndef new_a(): pass\n")
            write(tip / "fab/z.py", "def last(): pass\n")
            added, removed, changed = digest.items(base, tip)
            self.assertEqual([entry.name for entry in added], ["new_z", "new_a", "last"])
            self.assertEqual([entry.name for entry in removed], ["removed_z", "removed_a"])
            self.assertEqual(changed, [])

    def test_missing_package_on_either_side(self):
        with tmp_home() as root:
            empty, tree = root / "empty", root / "tree"
            write(tree / "fab/api.py", "def added(): pass\n")
            entry = Signature("fab/api.py", "added", "def added()", "")
            self.assertEqual(digest.items(empty, empty), ([], [], []))
            self.assertEqual(digest.items(empty, tree), ([entry], [], []))
            self.assertEqual(digest.items(tree, empty), ([], [entry], []))

    def test_invalid_python_propagates(self):
        with tmp_home() as root:
            write(root / "tip/fab/api.py", "def broken(\n")
            with self.assertRaises(SyntaxError):
                digest.items(root / "base", root / "tip")


class LinesTest(unittest.TestCase):
    def test_added_lines_insert_replace_delete_and_new(self):
        for before, after, expected in (
            ("a\nc\n", "a\nb\nc\n", {2}),
            ("a\nb\nc\n", "a\nx\ny\nc\n", {2, 3}),
            ("a\nb\nc\n", "a\nc\n", set()),
            ("", "a\n\nb\n", {1, 2, 3}),
            ("a\nb", "a\nb", set()),
            ("", "", set()),
        ):
            with self.subTest(before=before, after=after):
                self.assertEqual(digest.added_lines(before, after), expected)

    def test_added_lines_keeps_repeated_lines_past_autojunk_threshold(self):
        before = "a\n" * 210 + "b\n" + "a\n" * 210
        after = "a\n" * 210 + "c\n" + "a\n" * 210
        self.assertEqual(digest.added_lines(before, after), {211})

    def test_functions_nested_methods_async_and_decorators(self):
        text = '''@decorate
def outer():
    @decorate
    async def nested():
        pass
    class Local:
        def method(self):
            pass

class Queue:
    @decorate
    def cycle(self):
        def take():
            pass
        return take
'''
        self.assertEqual(digest.functions("fab/api.py", text), [
            digest.Function("fab/api.py", "outer", 2, 7),
            digest.Function("fab/api.py", "outer.nested", 4, 2),
            digest.Function("fab/api.py", "outer.Local.method", 7, 2),
            digest.Function("fab/api.py", "Queue.cycle", 12, 4),
            digest.Function("fab/api.py", "Queue.cycle.take", 13, 2),
        ])
        self.assertEqual(digest.functions("fab/empty.py", "# No functions\n"), [])
        with self.assertRaises(SyntaxError):
            digest.functions("fab/bad.py", "def broken(\n")

    def test_long_functions_cap_new_untouched_changed_and_shortened(self):
        long = function("long", 61)
        short = function("short", 60)
        expected = digest.Function("fab/api.py", "long", 1, 61)
        self.assertEqual(digest.long_functions("fab/api.py", "", long), [expected])
        self.assertEqual(digest.long_functions("fab/api.py", "", short), [])
        self.assertEqual(digest.long_functions("fab/api.py", long, long), [])
        changed = long.replace("long_20 = 20", "long_20 = 100")
        # A ratchet: changed without growing passes; grown past where it was fails.
        self.assertEqual(digest.long_functions("fab/api.py", long, changed), [])
        self.assertEqual(digest.long_functions("fab/api.py", long, function("long", 62)),
                         [digest.Function("fab/api.py", "long", 1, 62)])
        self.assertEqual(digest.long_functions("fab/api.py", short, long), [expected])
        self.assertEqual(digest.long_functions("fab/api.py", function("long", 62), long), [])
        self.assertEqual(digest.long_functions("fab/api.py", "", short, cap=59),
                         [digest.Function("fab/api.py", "short", 1, 60)])

    def test_long_functions_uses_after_span_with_shift_and_boundary(self):
        long = function("long", 61)
        self.assertEqual(digest.long_functions("fab/api.py", long, "prefix = 1\n" + long), [])
        self.assertEqual(digest.long_functions("fab/api.py", long, long + "outside = 1\n"), [])
        self.assertEqual(digest.long_functions("fab/api.py", "", "@decorator\n" + long),
                         [digest.Function("fab/api.py", "long", 2, 61)])


class ClonesTest(unittest.TestCase):
    def test_eight_lines_copied_and_longer_block_windows_merge(self):
        for length in (8, 11):
            with self.subTest(length=length):
                block = "".join(f"value_{index} = {index}\n" for index in range(length))
                texts = {"fab/source.py": "# Original\n" + block,
                         "fab/copy.py": "\n# Copy\n" + block}
                self.assertEqual(digest.clones(texts, {"fab/copy.py": set(range(3, length + 3))}),
                                 [digest.Clone("fab/copy.py", 3, length + 2, "fab/source.py", 2)])

    def test_seven_line_copy_is_not_a_clone(self):
        block = "".join(f"value_{index} = {index}\n" for index in range(7))
        self.assertEqual(digest.clones({"fab/a.py": block, "fab/b.py": block}, {"fab/b.py": {1}}), [])

    def test_overlapping_repeats_are_not_matches(self):
        self.assertEqual(digest.clones({"fab/a.py": "same = 1\n" * 15}, {"fab/a.py": set(range(1, 16))}), [])

    def test_nonoverlapping_repeat_in_same_file(self):
        block = "".join(f"value_{index} = {index}\n" for index in range(8))
        self.assertEqual(digest.clones({"fab/a.py": block + block}, {"fab/a.py": {9}}),
                         [digest.Clone("fab/a.py", 9, 16, "fab/a.py", 1)])

    def test_imports_comments_and_blanks_are_ignored_but_line_numbers_survive(self):
        first = "import alpha\n# first\n\nx = 1\nfrom beta import item\ny = 2\n"
        second = "# second\n    x = 1\n\n    y = 2\nimport gamma\n"
        self.assertEqual(digest.clones({"fab/a.py": first, "fab/b.py": second},
                                       {"fab/b.py": {2, 4}}, size=2),
                         [digest.Clone("fab/b.py", 2, 4, "fab/a.py", 4)])
        self.assertEqual(digest.clones({"fab/a.py": first, "fab/b.py": second},
                                       {"fab/b.py": {1, 3, 5}}, size=2), [])
        ignored = "import alpha\nfrom beta import item\n# comment\n\n" * 10
        self.assertEqual(digest.clones({"fab/a.py": ignored, "fab/b.py": ignored},
                                       {"fab/b.py": set(range(1, 41))}), [])

    def test_copy_wholly_in_unchanged_lines_is_not_a_clone(self):
        block = "".join(f"value_{index} = {index}\n" for index in range(9))
        texts = {"fab/a.py": block, "fab/b.py": block + "different = 1\n"}
        self.assertEqual(digest.clones(texts, {"fab/b.py": {10}}), [])
        self.assertEqual(digest.clones(texts, {"fab/b.py": set()}), [])
        self.assertEqual(digest.clones(texts, {}), [])
        self.assertEqual(digest.clones({}, {}), [])

    def test_lowest_match_and_result_order_independent_of_mapping_order(self):
        block = "x = 1\ny = 2\nz = 3\n"
        texts = {"fab/z.py": block, "fab/c.py": block, "fab/a.py": block + block,
                 "fab/b.py": block}
        changed = {"fab/z.py": {1}, "fab/c.py": {1}}
        expected = [digest.Clone("fab/c.py", 1, 3, "fab/a.py", 1),
                    digest.Clone("fab/z.py", 1, 3, "fab/a.py", 1)]
        self.assertEqual(digest.clones(texts, changed, size=3), expected)
        self.assertEqual(digest.clones(dict(reversed(list(texts.items()))), changed, size=3), expected)

    def test_windows_with_nonconsecutive_matches_do_not_merge(self):
        texts = {"fab/a.py": "x\ny\ngap\ny\nz\n", "fab/b.py": "x\ny\nz\n"}
        self.assertEqual(digest.clones(texts, {"fab/b.py": {1, 2, 3}}, size=2),
                         [digest.Clone("fab/b.py", 1, 2, "fab/a.py", 1),
                          digest.Clone("fab/b.py", 2, 3, "fab/a.py", 4)])


class BuildTest(unittest.TestCase):
    def test_build_every_field_from_two_trees(self):
        with tmp_home() as root:
            base, tip = root / "base", root / "tip"
            block = "".join(f"copy_{index} = {index}\n" for index in range(10))
            before = 'class Gone: pass\ndef update(x): pass\nclass Kept:\n    """Before."""\n'
            after = 'def update(x: int): pass\nclass Kept:\n    """After."""\n    def method(self): pass\n'
            write(base / "fab/a.py", before)
            write(tip / "fab/a.py", after)
            write(base / "fab/deleted.py", "class Removed: pass\n")
            write(base / "fab/source.py", block + function("untouched", 61))
            write(tip / "fab/source.py", block + function("untouched", 61))
            write(tip / "fab/new.py", function("added", 61) + block)
            write(tip / "fab/tests/test_api.py", "invalid Python: ignored\n")
            changes = [digest.Change("fab/new.py", "production", 71, 0),
                       digest.Change("docs/guide.md", "docs", 3, 1),
                       digest.Change("fab/tests/test_api.py", "tests", 1, 0),
                       digest.Change("fab/deleted.py", "production", 0, 1),
                       digest.Change("bin/fab", "production", 1, 1),
                       digest.Change("fab/a.py", "production", 4, 4)]
            task = Task("demo/digest", "gates", "feature", "agents", (),
                        ("fab/*.py", "fab/tests/*.py", "bin/fab"), "high", 30, "", "spec.md")
            result = digest.build(task, "demo/digest-1", "agents-rebuild/digest", "a" * 40, "b" * 40,
                                  changes, base, tip)
            self.assertEqual(result, digest.Digest(
                run="demo/digest-1", task="demo/digest", kind="feature", branch="agents-rebuild/digest",
                base="a" * 40, tip="b" * 40,
                changes=tuple(sorted(changes, key=lambda change: change.path)),
                added=(Signature("fab/a.py", "Kept.method", "def method(self)", ""),
                       Signature("fab/new.py", "added", "def added()", "")),
                removed=(Signature("fab/a.py", "Gone", "class Gone", ""),
                         Signature("fab/deleted.py", "Removed", "class Removed", "")),
                changed=((Signature("fab/a.py", "update", "def update(x)", ""),
                          Signature("fab/a.py", "update", "def update(x: int)", "")),),
                modules=("fab/new.py",), outside=("docs/guide.md",),
                long=(digest.Function("fab/new.py", "added", 1, 61),),
                clones=(digest.Clone("fab/new.py", 62, 71, "fab/source.py", 1),),
            ))
            self.assertEqual(changes[0].path, "fab/new.py")

    def test_build_empty_trees_and_changes(self):
        with tmp_home() as root:
            task = Task("demo/empty", "gates", "docs", "agents", (), (), "high", 1, "", "spec.md")
            self.assertEqual(digest.build(task, "r", "b", "base", "tip", [], root / "base", root / "tip"),
                             digest.Digest("r", "demo/empty", "docs", "b", "base", "tip",
                                           (), (), (), (), (), (), (), ()))

    def test_build_long_and_clones_only_read_production_modules(self):
        with tmp_home() as root:
            base, tip = root / "base", root / "tip"
            block = "".join(f"value_{index} = {index}\n" for index in range(8))
            write(tip / "fab/api.py", block)
            write(tip / "fab/api_test.py", block)
            for path in ("fab/test_api.py", "fab/tests/helpers.py", "fab/roles/read.md", "fab/nested/api.py"):
                write(tip / path, "invalid Python\n" + block + function("excluded", 61))
            changes = [digest.Change(path, digest.classify(path), 70, 0)
                       for path in ("fab/api.py", "fab/test_api.py", "fab/tests/helpers.py",
                                    "fab/roles/read.md", "fab/nested/api.py")]
            task = Task("demo/skip", "gates", "feature", "agents", (), ("**",), "high", 1, "", "spec.md")
            result = digest.build(task, "r", "b", "base", "tip", changes, base, tip)
            self.assertEqual(result.modules, ("fab/api.py",))
            self.assertEqual(result.long, ())
            self.assertEqual(result.clones, ())
            self.assertEqual(result.changes, tuple(sorted(changes, key=lambda change: change.path)))

    def test_build_invalid_python_propagates(self):
        with tmp_home() as root:
            write(root / "tip/fab/api.py", "def broken(\n")
            task = Task("demo/bad", "gates", "feature", "agents", (), ("**",), "high", 1, "", "spec.md")
            with self.assertRaises(SyntaxError):
                digest.build(task, "r", "b", "base", "tip", [], root / "base", root / "tip")


class RenderTest(unittest.TestCase):
    def small(self):
        return digest.Digest(
            "demo/digest-1", "demo/digest", "feature", "topic", "a" * 40, "b" * 40,
            (digest.Change("fab/a.py", "production", 4, 2),
             digest.Change("fab/tests/test_a.py", "tests", 3, 1),
             digest.Change("README.md", "docs", 2, 0)),
            (Signature("fab/a.py", "new", "def new()", "A new function."),
             Signature("fab/a.py", "bare", "def bare()", "")),
            (Signature("fab/a.py", "old", "def old()", ""),),
            ((Signature("fab/a.py", "update", "def update(x)", ""),
              Signature("fab/a.py", "update", "def update(x: int)", "")),),
            ("fab/a.py",), ("README.md",),
            (digest.Function("fab/a.py", "new", 10, 61),),
            (digest.Clone("fab/a.py", 20, 27, "fab/b.py", 3),))

    def test_render_exact_every_section_and_deterministic(self):
        expected = """# Digest: demo/digest-1

- Task: demo/digest (feature)
- Branch: `topic`
- Base: `aaaaaaaaaaaa`; tip: `bbbbbbbbbbbb`
- Lines: production +4 -2, tests +3 -1, docs +2 -0

## Changed paths
- `fab/a.py` production +4 -2
- `fab/tests/test_a.py` tests +3 -1
- `README.md` docs +2 -0

## Public items
- module added `fab/a.py`
- added `def new()` (fab/a.py) — A new function.
- added `def bare()` (fab/a.py) — no docstring
- removed `def old()` (fab/a.py)
- changed `def update(x)` -> `def update(x: int)` (fab/a.py)

## Outside the task's files
- `README.md`

## Functions over 60 lines
- `fab/a.py:10` new: 61 lines

## Repeated blocks
- `fab/a.py:20-27` repeats `fab/b.py:3`
"""
        self.assertEqual(digest.render(self.small()), expected)
        self.assertEqual(digest.render(self.small()), digest.render(self.small()))

    def test_render_empty_sections(self):
        empty = digest.Digest("r", "t", "docs", "b", "base", "tip",
                              (), (), (), (), (), (), (), ())
        self.assertEqual(digest.render(empty), """# Digest: r

- Task: t (docs)
- Branch: `b`
- Base: `base`; tip: `tip`
- Lines: production +0 -0, tests +0 -0, docs +0 -0

## Changed paths
- none

## Public items
- none

## Outside the task's files
- none

## Functions over 60 lines
- none

## Repeated blocks
- none
""")

    def test_render_list_and_line_caps(self):
        paths = tuple(f"fab/{index}.py" for index in range(digest.LIST_CAP + 2))
        result = digest.render(replace(self.small(), outside=paths))
        section = result.split("## Outside the task's files\n")[1].split("\n\n")[0]
        self.assertEqual(section.splitlines(),
                         [f"- `{path}`" for path in paths[:digest.LIST_CAP]] + ["- ... and 2 more"])
        for length in (digest.LINE_CAP - 1, digest.LINE_CAP, digest.LINE_CAP + 1):
            with self.subTest(length=length):
                path = "x" * (length - len("- ``"))
                result = digest.render(replace(self.small(), outside=(path,)))
                line = result.split("## Outside the task's files\n")[1].splitlines()[0]
                entry = f"- `{path}`"
                self.assertEqual(line, entry if length <= digest.LINE_CAP
                                 else entry[:digest.LINE_CAP - 3] + "...")

    def test_render_digest_limit_keeps_maximum_whole_lines(self):
        paths = tuple(f"fab/{index}/" + "x" * 150 for index in range(digest.LIST_CAP + 2))
        large = replace(self.small(), outside=paths, modules=paths,
                        changes=tuple(digest.Change(path, "production", 1, 0) for path in paths))
        with patch.object(digest, "DIGEST_LIMIT", 100_000):
            full = digest.render(large)
        self.assertGreater(len(full), digest.DIGEST_LIMIT)
        result = digest.render(large)
        cut = f"(cut at {digest.DIGEST_LIMIT} characters)\n"
        self.assertTrue(result.endswith(cut))
        self.assertLessEqual(len(result), digest.DIGEST_LIMIT)
        prefix = result[:-len(cut)]
        self.assertTrue(prefix.endswith("\n"))
        self.assertTrue(full.startswith(prefix))
        next_line = full[len(prefix):].splitlines(keepends=True)[0]
        self.assertGreater(len(result) + len(next_line), digest.DIGEST_LIMIT)
        self.assertEqual(result, digest.render(large))


class ChangesTest(unittest.TestCase):
    def test_changes_numstat_nul_records_and_binary_counts(self):
        sh = FakeRunner().on(["git", "diff"], Result(
            0, "4\t2\tfab/a\tfile.py\0-\t-\timage.png\0" "3\t1\tfab/tests/test_a.py\0"
            "2\t0\tdocs/guide.md\0"))
        with tmp_home() as root:
            result = digest.changes(root, "base", "tip", sh=sh)
            self.assertEqual(sh.argvs(), [["git", "diff", "--numstat", "-z", "--no-renames",
                                          "base", "tip", "--"]])
            self.assertEqual(sh.calls[0].cwd, str(root))
        self.assertEqual(result, [digest.Change("fab/a\tfile.py", "production", 4, 2),
                                  digest.Change("image.png", "production", 0, 0),
                                  digest.Change("fab/tests/test_a.py", "tests", 3, 1),
                                  digest.Change("docs/guide.md", "docs", 2, 0)])

    def test_changes_empty_and_failed_diff(self):
        with tmp_home() as root:
            self.assertEqual(digest.changes(root, "base", "tip", sh=FakeRunner()), [])
            sh = FakeRunner().on(["git", "diff"], Result(1, err="diff failed"))
            with self.assertRaises(Failed):
                digest.changes(root, "base", "tip", sh=sh)


class ArchiveTest(unittest.TestCase):
    def test_archive_only_package_and_missing_package_fails(self):
        with tmp_home() as root:
            _, repo = git_pair(root)
            before = git(repo, "rev-parse", "HEAD")
            write(repo / "fab/x.py", "def x(): pass\n")
            git(repo, "add", "fab/x.py")
            git(repo, "commit", "-q", "-m", "Add package")
            dest = root / "tree"
            self.assertEqual(digest.archive(repo, "HEAD", dest), dest)
            self.assertEqual((dest / "fab/x.py").read_text(), "def x(): pass\n")
            self.assertEqual(sorted(path.relative_to(dest).as_posix() for path in dest.rglob("*")),
                             ["fab", "fab/x.py"])
            self.assertFalse(Path(str(dest) + ".tar").exists())
            with self.assertRaises(FileExistsError):
                digest.archive(repo, "HEAD", dest)
            missing = root / "missing"
            with self.assertRaises(Failed):
                digest.archive(repo, before, missing)
            self.assertFalse(Path(str(missing) + ".tar").exists())
