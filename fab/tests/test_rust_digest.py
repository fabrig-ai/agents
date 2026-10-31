"""fabrig's digest and gates read from Rust (docs/design/fab.md, 12)."""

from __future__ import annotations

import unittest

from fab import digest, gates, run as runs, rust_digest
from fab.tests.rust_sources import (CRATE, LIB, TASK, RustTestCase, block, commit_branch,
                                    fabrig_repo, item, line_of, long_fn, rs)
from fab.tests.support import tmp_home

CODEC = f"{CRATE}/src/codec.rs"

BASE = rs("""
    //! The wire format.

    /// A key-value store.
    pub struct Store {
        entries: Vec<(String, u64)>,
    }

    impl Store {
        /// The value at key.
        pub fn get(&self, key: &str) -> Option<u64> {
            todo!()
        }
    }

    #[cfg(test)]
    mod tests {
        #[test]
        fn get_is_empty() {}
    }
""")

TIP = (rs("""
    //! The wire format.

    mod codec;

    /// A key-value store.
    pub struct Store {
        entries: Vec<(String, u64)>,
    }

    impl Store {
        /// The value at key, or default.
        pub fn get(&self, key: &str, default: u64) -> u64 {
""") + block("sum", indent="        ") + rs("""
            sum_7 + default
        }

        pub fn helper_total(&self) -> u64 {
            0
        }
    }

""") + long_fn("rebuild", 61) + "\n" + rs("""
    #[cfg(test)]
    mod tests {
        #[test]
        fn get_is_empty() {}
    }
"""))

ENCODE = "/// Encode a value.\npub fn encode() -> u64 {\n" + block("sum") + "    sum_7\n}\n"


class ExemplarTest(RustTestCase):
    @unittest.skip("pending: agents-rebuild/rust-gates")
    def test_a_branch_that_breaks_the_skeleton_is_found_by_every_gate(self):
        with tmp_home() as home:
            _, clone, base = fabrig_repo(home, {LIB: BASE})
            tip = commit_branch(clone, "draft/task", {LIB: TIP, CODEC: ENCODE})
            found = rust_digest.gather(clone, TASK, "draft/task-1", "draft/task", base, tip,
                                       home / "gather")

        self.assertEqual([(change.path, change.kind) for change in found.changes],
                         [(CODEC, "production"), (LIB, "production")])
        self.assertEqual(found.modules, (CODEC,))
        self.assertEqual(found.removed, ())
        self.assertEqual(found.changed, ((
            item("Store.get", "pub fn get(&self, key: &str) -> Option<u64>", "The value at key."),
            item("Store.get", "pub fn get(&self, key: &str, default: u64) -> u64",
                 "The value at key, or default.")),))
        self.assertEqual([entry.name for entry in found.added],
                         ["encode", "Store.helper_total", "rebuild"])

        rebuild, block_start = line_of(TIP, "pub fn rebuild"), line_of(TIP, "let sum_0")
        self.assertFindings(found, [
            ("shape", f"`{LIB}`: `pub fn get(&self, key: &str) -> Option<u64>` changed to "
                      "`pub fn get(&self, key: &str, default: u64) -> u64`"),
            ("size", f"`{LIB}:{rebuild}` rebuild is 61 lines (cap 60)"),
            ("names", f"`{LIB}`: `Store.helper_total` uses the banned word `helper`"),
            ("docs", f"`{LIB}`: `pub fn helper_total(&self) -> u64` has no docstring"),
            ("clones", f"`{CODEC}:3-10` repeats `{LIB}:{block_start}`"),
            ("clones", f"`{LIB}:{block_start}-{block_start + 7}` repeats `{CODEC}:3`"),
        ], banned=gates.banned_names(runs.TASTE.read_text(encoding="utf-8")))
        self.assertIn(f"- `{LIB}:{rebuild}` rebuild: 61 lines\n", digest.render(found))
