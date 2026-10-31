"""Rust digest scans use hand-written trees; commands use the fake runner (fab.md, 8)."""

from __future__ import annotations

import io
import tarfile
import unittest
from dataclasses import replace
from pathlib import Path

from fab import atomic, rust_digest as digest
from fab.calls import Signature
from fab.digest import Change, Function
from fab.plan import Task
from fab.sh import Failed, Result
from fab.tests.support import FakeRunner, tmp_home

TASK = Task("draft/rust", "part", "feature", "fabrig", (), ("skein/**",),
            "high", 60, "Build Rust.", "task.md")


def function(name: str, lines: int) -> str:
    return f"pub fn {name}() {{\n" + "".join(f"    call_{index}();\n" for index in range(lines - 2)) + "}\n"


def summary(root: Path, changes=(), counts=()) -> digest.Digest:
    return digest.build(TASK, "draft/rust-1", "draft/rust", "b" * 40, "a" * 40,
                        changes, root / "base", root / "tip", counts)


class PublicTest(unittest.TestCase):
    def test_public_declarations_modifiers_and_private_items(self):
        text = '''/// Build it.
#[inline]
pub async unsafe fn make<'a>(value: &'a str) -> usize {
    1
}
pub struct Shape;
pub enum Choice { A }
pub unsafe trait Read { fn read(); }
pub type Name = String;
pub const LIMIT: usize = 1;
pub mod api;
pub(crate) fn inside() {}
fn private() {}
// pub fn comment() {}
const TEXT: &str = "pub fn string() {}";
/* pub struct Hidden; */
pub extern "C" fn exported() {}
pub const fn constant() -> usize { 1 }
'''
        items = digest.public_items("skein/src/lib.rs", text)
        self.assertEqual([entry.name for entry in items],
                         ["make", "Shape", "Choice", "Read", "Name", "LIMIT", "api", "exported", "constant"])
        self.assertEqual(items[0], Signature("skein/src/lib.rs", "make",
                                             "pub async unsafe fn make<'a>(value: &'a str) -> usize", "Build it."))
        self.assertEqual(items[-2].text, 'pub extern "C" fn exported()')

    def test_items_added_removed_signature_change_and_unchanged_file(self):
        with tmp_home() as root:
            path = "skein/src/lib.rs"
            atomic.write(root / "base" / path, "pub fn removed() {}\npub fn changed(x: u8) {}\npub struct Kept;\n")
            atomic.write(root / "tip" / path, "pub fn added() {}\npub fn changed(x: u16) {}\npub struct Kept;\n")
            atomic.write(root / "tip/skein/src/untouched.rs", "pub fn absent_from_digest() {}\n")
            result = summary(root, [Change(path, "production", 2, 2)])
            self.assertEqual([entry.name for entry in result.added], ["added", "changed"])
            self.assertEqual([entry.name for entry in result.removed], ["removed", "changed"])
            self.assertEqual(result.outside, ())

    def test_inventory_selected_crates_sorted_deduplicated_without_tests(self):
        with tmp_home() as root:
            atomic.write(root / "skein/crates/z/src/lib.rs", "pub mod z;\n")
            atomic.write(root / "skein/crates/a/src/lib.rs", '''pub struct A;
#[cfg(test)]
mod tests {
    pub fn test_only() {}
}
''')
            atomic.write(root / "skein/crates/a/tests/api.rs", "pub fn integration() {}\n")
            atomic.write(root / "skein/crates/a/src/unit_tests.rs", "pub fn unit() {}\n")
            items = digest.inventory(root, ["skein/crates/z", "missing", "skein/crates/a", "skein/crates"])
            self.assertEqual([(entry.module, entry.name) for entry in items],
                             [("skein/crates/a/src/lib.rs", "A"), ("skein/crates/z/src/lib.rs", "z")])

    def test_added_and_deleted_rust_files(self):
        with tmp_home() as root:
            atomic.write(root / "base/skein/old.rs", "pub enum Gone {}\n")
            atomic.write(root / "tip/skein/new.rs", "pub struct New;\n")
            result = summary(root, [Change("skein/old.rs", "production", 0, 1),
                                    Change("skein/new.rs", "production", 1, 0)])
            self.assertEqual([entry.name for entry in result.added], ["New"])
            self.assertEqual([entry.name for entry in result.removed], ["Gone"])
            self.assertEqual([entry.path for entry in result.changes], ["skein/new.rs", "skein/old.rs"])


class LinesTest(unittest.TestCase):
    def test_path_kinds(self):
        for path, kind in (("skein/src/lib.rs", "production"), ("skein/tests/api.rs", "tests"),
                           ("skein/src/api_tests.rs", "tests"), ("tests/notes.md", "tests"),
                           ("skein/docs/design.md", "docs"), ("docs/example.rs", "production"),
                           ("skein/src/contests.rs", "production")):
            with self.subTest(path=path):
                self.assertEqual(digest.classify(path), kind)

    def test_inline_test_and_production_lines_split_on_both_sides(self):
        before = '''pub fn run() { old(); }
#[cfg(test)]
#[allow(dead_code)]
mod tests {
    fn works() { old(); }
}
'''
        after = before.replace("old();", "new();")
        self.assertEqual(digest.test_lines(before), {2, 3, 4, 5, 6})
        self.assertEqual(digest.line_changes("skein/src/lib.rs", before, after),
                         [Change("skein/src/lib.rs", "production", 1, 1),
                          Change("skein/src/lib.rs", "tests", 1, 1)])
        self.assertEqual(digest.line_changes("skein/src/lib.rs", before, ""),
                         [Change("skein/src/lib.rs", "production", 0, 1),
                          Change("skein/src/lib.rs", "tests", 0, 5)])

    def test_comments_and_strings_cannot_make_test_modules(self):
        text = '''// #[cfg(test)] mod tests { }
const TEXT: &str = r#"#[cfg(test)] mod fake { }"#;
pub fn run() {}
'''
        self.assertEqual(digest.test_lines(text), set())
        self.assertEqual(digest.line_changes("skein/src/lib.rs", "", text),
                         [Change("skein/src/lib.rs", "production", 3, 0)])

    def test_totals_docs_tests_and_production_with_outside_globs(self):
        with tmp_home() as root:
            atomic.write(root / "tip/skein/src/lib.rs", "pub fn run() {}\n#[cfg(test)]\nmod tests { }\n")
            result = summary(root, [Change("guide.md", "docs", 4, 1),
                                    Change("skein/src/lib.rs", "production", 3, 0),
                                    Change("skein/tests/api.rs", "tests", 0, 0)])
            self.assertEqual(result.outside, ("guide.md",))
            self.assertIn("production +1 -0, tests +2 -0, docs +4 -1", digest.render(result))
            task = replace(TASK, files=("skein/*.rs",))
            result = digest.build(task, "run", "branch", "base", "tip", result.changes[:1],
                                  root / "base", root / "tip")
            self.assertEqual(result.outside, ("guide.md",))

    def test_repeated_lines_and_zero_line_change(self):
        before = "call();\n" * 210 + "old();\n" + "call();\n" * 210
        after = before.replace("old();", "new();")
        self.assertEqual(digest.line_changes("a.rs", before, after), [Change("a.rs", "production", 1, 1)])
        self.assertEqual(digest.line_changes("a.rs", "", ""), [Change("a.rs", "production", 0, 0)])
        self.assertEqual(digest.line_changes("a.rs", "pub struct A;", "pub struct A;\n"),
                         [Change("a.rs", "production", 1, 1)])


class FunctionsTest(unittest.TestCase):
    def test_new_grown_untouched_shortened_and_same_length(self):
        long = function("work", 61)
        short = function("work", 60)
        expected = Function("a.rs", "work", 1, 61)
        self.assertEqual(digest.long_functions("a.rs", "", long), [expected])
        self.assertEqual(digest.long_functions("a.rs", "", short), [])
        self.assertEqual(digest.long_functions("a.rs", short, long), [expected])
        self.assertEqual(digest.long_functions("a.rs", long, function("work", 62)),
                         [Function("a.rs", "work", 1, 62)])
        for before, after in ((long, long), (long, long.replace("call_1()", "other()")),
                              (function("work", 62), long), (long, "// prefix\n" + long),
                              (long, long + "pub struct After;\n")):
            self.assertEqual(digest.long_functions("a.rs", before, after), [])

    def test_nested_braces_comments_literals_lifetimes_and_trait_declarations(self):
        text = '''trait Read {
    fn read(&self);
    fn defaulted(&self) {
        if true { call(); }
        // } fn fake() {
        /* { /* } */ fn hidden() {} */
        let raw = br###" } { // fn fake() {} "###;
        let string = "\\"}\\"";
        let character = '}';
        let borrowed: &'static str = "{";
    }
}
impl Read for A {
    fn read(&self) {}
}
impl Read for B {
    fn read(&self) {}
}
'''
        self.assertEqual(digest.functions("a.rs", text),
                         [Function("a.rs", "trait Read::defaulted", 3, 9),
                          Function("a.rs", "impl Read for A::read", 14, 1),
                          Function("a.rs", "impl Read for B::read", 17, 1)])

    def test_test_functions_do_not_flag(self):
        with tmp_home() as root:
            inline = "#[cfg(test)]\nmod tests {\n" + function("work", 61) + "}\n"
            self.assertEqual(digest.long_functions("a.rs", "", inline), [])
            atomic.write(root / "tip/skein/tests/a.rs", function("work", 61))
            result = summary(root, [Change("skein/tests/a.rs", "tests", 61, 0)])
            self.assertEqual(result.long, ())

    def test_array_signatures_do_not_end_at_the_array_semicolon(self):
        text = function("work", 61).replace("work()", "work(input: [u8; 16]) -> [u8; 16]")
        self.assertEqual(digest.long_functions("a.rs", "", text), [Function("a.rs", "work", 1, 61)])
        self.assertEqual(digest.public_items("a.rs", text)[0].text,
                         "pub fn work(input: [u8; 16]) -> [u8; 16]")

    def test_unclosed_body_cannot_be_measured(self):
        with self.assertRaisesRegex(ValueError, "unclosed Rust block"):
            digest.functions("a.rs", "fn work() {\n")


class RatchetsTest(unittest.TestCase):
    def test_sparse_diagnostics_override_baseline_including_unwritten_falls(self):
        baseline = "# comment\nmax_out 5\nJournalRoom 2\ntakes 0\n"
        output = ("max_out: count 1, baseline 5; lower with `python3 -I -B scripts/old_forms.py --write`\n"
                  "takes: count 3, baseline 0\nUses of the old forms may only fall.\n")
        self.assertEqual(digest.parse_counts(baseline, output), {"max_out": 1, "JournalRoom": 2, "takes": 3})

    def test_invalid_baselines_and_inconsistent_diagnostics_raise(self):
        for baseline, output in (("", ""), ("form -1", ""), ("form 1\nform 2", ""),
                                 ("form nope", ""), ("form 1 extra", ""),
                                 ("form 1", "other: count 0, baseline 1"),
                                 ("form 1", "form: count 0, baseline 9"),
                                 ("form 1", "form: count nope, baseline 1"),
                                 ("form 1", "form: count 0, baseline 1\nform: count 0, baseline 1")):
            with self.subTest(baseline=baseline, output=output), self.assertRaises(ValueError):
                digest.parse_counts(baseline, output)

    def test_touched_trees_run_both_sides_in_isolated_indexes_and_compare_actual_counts(self):
        with tmp_home() as root:
            for side in ("base", "tip"):
                for tree in ("skein", "other", "untouched"):
                    atomic.write(root / side / tree / "scripts/old_forms.py", "# fake script\n")
                    atomic.write(root / side / tree / "scripts/old-forms.txt", "form 5\nkept 0\n")
            fake = FakeRunner().on(["python3"], lambda call: Result(
                1, err=f"form: count {2 if '/base/' in call.cwd else 3}, baseline 0\n"))
            result = digest.ratchets(root / "base", root / "tip",
                                     ["skein/src/a.rs", "skein/src/b.rs", "other/guide.md", "README.md"], sh=fake)
            self.assertEqual(result, [digest.Ratchet("other", "form", 2, 3), digest.Ratchet("other", "kept", 0, 0),
                                      digest.Ratchet("skein", "form", 2, 3), digest.Ratchet("skein", "kept", 0, 0)])
            self.assertEqual(len(fake.calls), 12)
            for index, (tree, side) in enumerate((tree, side) for tree in ("other", "skein") for side in ("base", "tip")):
                path = root / side / tree
                self.assertEqual((path / "scripts/old-forms.txt").read_text(), "form 5\nkept 0\n")
                calls = fake.calls[index * 3:index * 3 + 3]
                self.assertEqual([call.argv for call in calls],
                                 [["git", "init", "-q", str(path)], ["git", "add", "--all", "--force"],
                                  ["python3", "-I", "-B", "scripts/old_forms.py"]])
                self.assertEqual([call.cwd for call in calls], [None, str(path), str(path)])

    def test_zero_baseline_reports_mixed_rise_and_fall_on_the_same_tree(self):
        with tmp_home() as root:
            baseline = "above 1\nbelow 10\nzero 0\n"
            for side in ("base", "tip"):
                atomic.write(root / side / "skein/scripts/old_forms.py", "# fake\n")
                atomic.write(root / side / "skein/scripts/old-forms.txt", baseline)

            def count(call):
                path = Path(call.cwd) / "scripts/old-forms.txt"
                self.assertEqual(path.read_text(), "above 0\nbelow 0\nzero 0\n")
                above, below = (2, 4) if "/base/" in call.cwd else (3, 1)
                return Result(1, err=f"above: count {above}, baseline 0\nbelow: count {below}, baseline 0\n")

            fake = FakeRunner().on(["python3"], count)
            self.assertEqual(digest.ratchets(root / "base", root / "tip", ["skein/a.rs"], sh=fake),
                             [digest.Ratchet("skein", "above", 2, 3),
                              digest.Ratchet("skein", "below", 4, 1),
                              digest.Ratchet("skein", "zero", 0, 0)])
            for side in ("base", "tip"):
                self.assertEqual((root / side / "skein/scripts/old-forms.txt").read_text(), baseline)

    def test_new_tree_counts_start_at_zero_and_raised_script_result_is_a_count(self):
        with tmp_home() as root:
            atomic.write(root / "tip/new/scripts/old_forms.py", "# fake\n")
            atomic.write(root / "tip/new/scripts/old-forms.txt", "form 0\n")
            fake = FakeRunner().on(["python3"], Result(1, err="form: count 1, baseline 0\nRule.\n"))
            self.assertEqual(digest.ratchets(root / "base", root / "tip", ["new/a.rs"], sh=fake),
                             [digest.Ratchet("new", "form", 0, 1)])

    def test_missing_baseline_removed_script_and_command_failures_raise(self):
        with tmp_home() as root:
            atomic.write(root / "base/skein/scripts/old_forms.py", "# fake\n")
            atomic.write(root / "tip/skein/src/a.rs", "pub struct A;\n")
            with self.assertRaisesRegex(ValueError, "old_forms.py removed"):
                digest.ratchets(root / "base", root / "tip", ["skein/a.rs"], sh=FakeRunner())
            atomic.write(root / "tip/skein/scripts/old_forms.py", "# fake\n")
            with self.assertRaises(FileNotFoundError):
                digest.ratchets(root / "base", root / "tip", ["skein/a.rs"], sh=FakeRunner())
            for side in ("base", "tip"):
                atomic.write(root / side / "skein/scripts/old-forms.txt", "form 0\n")
            for command in (["git", "init"], ["git", "add"], ["python3"]):
                fake = FakeRunner().on(command, Result(1, err="broken command"))
                with self.subTest(command=command), self.assertRaises(Failed):
                    digest.ratchets(root / "base", root / "tip", ["skein/a.rs"], sh=fake)
                self.assertEqual((root / "base/skein/scripts/old-forms.txt").read_text(), "form 0\n")
            self.assertEqual(digest.ratchets(root / "base", root / "tip", ["no-script/a.rs"], sh=FakeRunner()), [])


class ShellAndRenderTest(unittest.TestCase):
    def test_numstat_binary_counts_and_unusual_paths(self):
        with tmp_home() as root:
            fake = FakeRunner().on(["git", "diff"], Result(0, "2\t3\tskein/src/a.rs\0-\t-\timage.png\0"
                                                       "1\t0\tskein/tests/tab\tline\n.rs\0"))
            self.assertEqual(digest.changes(root, "base", "tip", sh=fake),
                             [Change("skein/src/a.rs", "production", 2, 3), Change("image.png", "production", 0, 0),
                              Change("skein/tests/tab\tline\n.rs", "tests", 1, 0)])
            self.assertEqual(fake.argvs(), [["git", "diff", "--numstat", "-z", "--no-renames", "base", "tip", "--"]])

    def test_archive_extracts_full_tree_and_cleans_tar_on_failure(self):
        with tmp_home() as root:
            def archive(call):
                with tarfile.open(call.argv[call.argv.index("-o") + 1], "w") as tree:
                    content = b"pub struct A;\n"
                    entry = tarfile.TarInfo("skein/src/lib.rs")
                    entry.size = len(content)
                    tree.addfile(entry, io.BytesIO(content))
                return Result(0)

            fake = FakeRunner().on(["git", "archive"], archive)
            dest = root / "tree"
            self.assertEqual(digest.archive(root, "tip", dest, sh=fake), dest)
            self.assertEqual((dest / "skein/src/lib.rs").read_text(), "pub struct A;\n")
            self.assertFalse(Path(str(dest) + ".tar").exists())
            self.assertEqual(fake.argvs()[0], ["git", "archive", "--format=tar", "-o", str(dest) + ".tar", "tip"])
            fake = FakeRunner().on(["git", "archive"], Result(1, err="archive failed"))
            with self.assertRaises(Failed):
                digest.archive(root, "bad", root / "failed", sh=fake)
            self.assertFalse((root / "failed.tar").exists())

    def test_render_deterministic_bounded_and_includes_flags_and_ratchet_deltas(self):
        with tmp_home() as root:
            result = replace(summary(root), changes=(Change("skein/a.rs", "production", 2, 1),),
                             long=(Function("skein/a.rs", "work", 1, 61),),
                             ratchets=(digest.Ratchet("skein", "form", 2, 1),))
            rendered = digest.render(result)
            self.assertEqual(rendered, digest.render(result))
            self.assertIn("Functions over 60 lines (flag)", rendered)
            self.assertIn("`skein` `form`: 2 -> 1 (-1)", rendered)
            self.assertTrue(rendered.endswith("\n"))
            many = tuple(Change(f"skein/{index:03}-" + "x" * 200 + ".rs", "production", 1, 0) for index in range(100))
            huge = replace(result, changes=many, outside=tuple(entry.path for entry in many),
                           added=tuple(Signature(entry.path, "name", "pub fn " + "x" * 200, "") for entry in many))
            rendered = digest.render(huge)
            self.assertLessEqual(len(rendered), 8_000)
            self.assertIn("... and 70 more", rendered)
            self.assertTrue(rendered.endswith("(cut at 8000 characters)\n"))
            self.assertLessEqual(len(digest.render(replace(result, run="x" * 9_000))), 8_000)
