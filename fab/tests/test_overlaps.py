"""Pure overlap decisions over plans and records (docs/design/fab.md, 4; fab-integration.md, 4)."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch
from dataclasses import replace

from fab import atomic, log, overlaps
from fab.plan import Plan
from fab.sh import Failed, Result
from fab.tests.support import FakeRunner, tmp_home

PLAN = Plan("a", "agents", (), 1, 2, {}, ())
TREE = "0123456789abcdef" * 2 + "01234567"


def record(pair=("a", "b"), files=("shared.py",), more=0, tips=("a-tip", "b-tip"), reason="probe"):
    return dict(ev="trunks.overlap", drafts=list(pair), tips=list(tips), files=list(files),
                more=more, reason=reason)


class OverlapsTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(tmp_home())

    def test_probe_plans_excludes_queue_replay_retired_and_landed_trunks(self):
        plans = [replace(PLAN, draft="z"), replace(PLAN, draft="queue", landing="queue"),
                 replace(PLAN, draft="replay", ready=False), replace(PLAN, draft="retired", retired=True),
                 replace(PLAN, draft="landed"), PLAN]
        events = [dict(ev="branch.landed", task="landed/integration", queue_ts="landed"),
                  dict(ev="branch.landed", task="a/integration", into="a/integration"),
                  dict(ev="branch.landed", task="z/task", queue_ts="task-landed")]
        selected = overlaps.probe_plans(plans, events)
        self.assertEqual(selected, [PLAN, plans[0]])
        self.assertEqual([plan.draft for plan in plans], ["z", "queue", "replay", "retired", "landed", "a"])
        self.assertEqual(overlaps.probe_plans([], events), [])

    def test_pairs_are_name_ordered_and_within_one_repo(self):
        plans = [replace(PLAN, draft="c"), replace(PLAN, draft="foreign", repo="fabrig"),
                 replace(PLAN, draft="b"), PLAN]
        self.assertEqual(overlaps.pairs(plans), [("a", "b"), ("a", "c"), ("b", "c")])
        self.assertEqual(overlaps.pairs([]), [])
        self.assertEqual(overlaps.pairs([PLAN]), [])

    def test_catch_up_parse_distinguishes_tree_conflict_and_failure(self):
        for tree in (TREE, "A" * 40, "f" * 64):
            with self.subTest(tree=tree):
                self.assertEqual(overlaps.parse_catch_up(0, tree + "\n"), ("clean", tree))
                self.assertEqual(overlaps.parse_catch_up(0, tree), ("clean", tree))
                self.assertEqual(overlaps.parse_catch_up(1, tree + "\nconflicted path\n"), ("conflict", None))
        for code, stdout in ((1, ""), (1, "fatal: missing ref\n"), (128, TREE + "\n"),
                             (2, TREE), (0, ""), (0, "garbage"), (1, "garbage"),
                             (0, "a" * 39), (0, "g" * 40), (0, " " + TREE),
                             (0, TREE + "\0"), (0, "warning\n" + TREE)):
            with self.subTest(code=code, stdout=stdout):
                self.assertEqual(overlaps.parse_catch_up(code, stdout), ("failure", None))

    def test_pair_parse_clean_is_empty(self):
        for stdout in ("", TREE + "\0", "unused on success"):
            with self.subTest(stdout=stdout):
                self.assertEqual(overlaps.parse_pair(0, stdout), ([], 0))

    def test_pair_parse_keeps_spaces_newlines_and_path_order(self):
        paths = ["z.py", "a space and\na newline.py", 'literal "quote" and \\ slash.py', "a.py"]
        stdout = TREE + "\0\0" + "\0".join(paths) + "\0\0"
        self.assertEqual(overlaps.parse_pair(1, stdout), (paths, 0))
        self.assertEqual(overlaps.parse_pair(1, "f" * 64 + "\0"), ([], 0))
        self.assertEqual(overlaps.parse_pair(1, TREE), ([], 0))

    def test_pair_parse_bounds_paths_at_forty(self):
        paths = [f"file-{number:02}.py" for number in range(45)]
        self.assertEqual(overlaps.FILES, 40)
        self.assertEqual(overlaps.parse_pair(1, TREE + "\0" + "\0".join(paths) + "\0"),
                         (paths[:40], 5))
        self.assertEqual(overlaps.parse_pair(1, TREE + "\0" + "\0".join(paths[:40]) + "\0"),
                         (paths[:40], 0))

    def test_pair_parse_rejects_failure_and_missing_or_garbage_id(self):
        for code, stdout in ((1, ""), (1, "fatal: missing ref"), (128, TREE + "\0path\0"),
                             (2, TREE + "\0path\0"), (1, "garbage\0path\0"),
                             (1, "a" * 39 + "\0path\0"), (1, "g" * 40 + "\0path\0"),
                             (1, TREE + "\npath\n"), (1, "\0" + TREE + "\0path\0")):
            with self.subTest(code=code, stdout=stdout):
                self.assertIsNone(overlaps.parse_pair(code, stdout))

    def test_news_compares_only_last_files_and_more(self):
        pair = ("a", "b")
        self.assertFalse(overlaps.is_news(pair, [], 0, []))
        self.assertTrue(overlaps.is_news(pair, ["shared.py"], 0, []))
        events = [record(), record(("a", "c"), files=("other.py",)),
                  dict(ev="note", drafts=list(pair), files=[])]
        self.assertFalse(overlaps.is_news(pair, ["shared.py"], 0, events))
        self.assertTrue(overlaps.is_news(pair, ["changed.py"], 0, events))
        self.assertTrue(overlaps.is_news(pair, ["shared.py"], 1, events))
        self.assertTrue(overlaps.is_news(pair, [], 0, events))
        events.append(record(files=(), tips=("new-a", "new-b")))
        self.assertFalse(overlaps.is_news(pair, [], 0, events))
        self.assertTrue(overlaps.is_news(pair, ["shared.py"], 0, events))

    def test_news_preserves_merge_tree_order(self):
        self.assertTrue(overlaps.is_news(("a", "b"), ["b", "a"], 0, [record(files=("a", "b"))]))

    def test_open_pairs_uses_last_record_and_returns_name_order(self):
        later_pair = record(("b", "c"))
        earlier_pair = record(("a", "c"))
        reopened = record(tips=("new-a", "new-b"), files=("new.py",))
        events = [later_pair, record(), record(files=()), earlier_pair, reopened]
        self.assertEqual(list(overlaps.open_pairs(events)), [("a", "b"), ("a", "c"), ("b", "c")])
        self.assertIs(overlaps.open_pairs(events)[("a", "b")], reopened)
        self.assertEqual(overlaps.open_pairs([record(), record(files=())]), {})
        self.assertEqual(overlaps.open_pairs([]), {})

    def test_open_pairs_skips_malformed_drafts_and_unrelated_events(self):
        events = [record()]
        for drafts in (None, "a b", ("a", "b"), [], ["a"], ["a", "b", "c"], ["a", 1], [[], "b"]):
            events.append(dict(ev="trunks.overlap", drafts=drafts, files=["bad.py"]))
        events.extend([dict(ev="trunks.overlap", files=["bad.py"]), dict(record(files=()), ev="note")])
        self.assertEqual(overlaps.open_pairs(events), {("a", "b"): events[0]})

    def test_gone_pairs_closes_only_absent_open_pairs_with_last_tips(self):
        events = [record(), record(tips=("new-a", "new-b")), record(("a", "c")),
                  record(("b", "c")), record(("b", "c"), files=())]
        self.assertEqual(overlaps.gone_pairs([("a", "c")], events),
                         [dict(drafts=["a", "b"], tips=["new-a", "new-b"], files=[], more=0, reason="gone")])
        self.assertEqual(events[1]["files"], ["shared.py"])
        self.assertEqual(overlaps.gone_pairs([("a", "b"), ("a", "c")], events), [])
        self.assertEqual(overlaps.gone_pairs([], []), [])
        self.assertEqual([fields["drafts"] for fields in overlaps.gone_pairs([], events)],
                         [["a", "b"], ["a", "c"]])

    def test_failure_prefix_names_one_trunk_or_one_pair(self):
        self.assertEqual(overlaps.failure_prefix(("draft",)), "trunks.overlap draft: ")
        self.assertEqual(overlaps.failure_prefix(("a", "b")), "trunks.overlap a b: ")

    def test_failure_notes_are_news_only_when_the_last_text_changes(self):
        for drafts in (("a",), ("a", "b")):
            with self.subTest(drafts=drafts):
                prefix = overlaps.failure_prefix(drafts)
                text = prefix + "exit 128: missing ref"
                self.assertTrue(overlaps.failure_is_news(prefix, text, []))
                events = [dict(ev="note", text=text), dict(ev="note", text="trunks.overlap a c: other"),
                          dict(ev="note"), dict(ev="note", text=4), dict(ev="other", text=prefix + "other")]
                self.assertFalse(overlaps.failure_is_news(prefix, text, events))
                changed = prefix + "exit 1: unreadable output"
                self.assertTrue(overlaps.failure_is_news(prefix, changed, events))
                events.append(dict(ev="note", text=changed))
                self.assertFalse(overlaps.failure_is_news(prefix, changed, events))
                self.assertTrue(overlaps.failure_is_news(prefix, text, events))

    def test_overlap_fields_are_flat_and_own_their_lists(self):
        tips, files = ["a-tip", "b-tip"], ["a.py", "b.py"]
        fields = overlaps.overlap_fields(("a", "b"), tips, files, 5)
        self.assertEqual(fields, dict(drafts=["a", "b"], tips=tips, files=files, more=5, reason="probe"))
        tips.append("changed")
        files.clear()
        self.assertEqual(fields["tips"], ["a-tip", "b-tip"])
        self.assertEqual(fields["files"], ["a.py", "b.py"])
        self.assertEqual(overlaps.overlap_fields(("a", "b"), (), (), 0, reason="gone")["reason"], "gone")


class OverlapProbeTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.path = self.home / "probe.jsonl"
        self.cache_path = log.home() / "overlaps.json"
        self.main = "1" * 40
        self.tips = {"a": "a" * 40, "b": "b" * 40, "c": "c" * 40, "d": "d" * 40}
        self.trees = {draft: str(number) * 40 for number, draft in enumerate(self.tips, 2)}
        self.catch_results = {}
        self.pair_result = Result(1, TREE + "\0shared.py\0")
        self.fake = FakeRunner().on(["git", "rev-parse", "--verify"], self.revision)
        self.fake.on(["git", "merge-tree"], self.merge)
        self.loaded = [self.entry("b"), self.entry("a")]

    def entry(self, draft, repo="agents"):
        checkout = self.home / repo / draft
        return replace(PLAN, draft=draft, repo=repo), {}, checkout / "plan", checkout

    def revision(self, call):
        ref = call.argv[-1]
        if ref == "origin/main":
            return Result(0, self.main + "\n")
        tip = self.tips.get(ref.split("/")[1])
        return Result(0, tip + "\n") if tip else Result(128, err="missing ref")

    def merge(self, call):
        if "--name-only" in call.argv:
            return self.pair_result
        draft = call.argv[-1].split("/")[1]
        return self.catch_results.get(draft, Result(0, self.trees[draft] + "\n"))

    def probe(self, *, all_loaded=True):
        return overlaps.probe(self.loaded, log.read(self.path), all_loaded,
                              sh=self.fake, log_path=self.path)

    def merges(self):
        return [call for call in self.fake.calls if call.argv[:2] == ["git", "merge-tree"]]

    def events(self, kind):
        return [event for event in log.read(self.path) if event["ev"] == kind]

    def test_overlap_probe_caches_news_and_reprobes_a_new_tip(self):
        paths = [f"path-{number}" for number in range(43)]
        self.pair_result = Result(1, TREE + "\0" + "\0".join(paths) + "\0")
        self.assertEqual(self.probe(), ["overlap a b 43"])
        first = self.events("trunks.overlap")[0]
        self.assertEqual({key: first[key] for key in ("drafts", "tips", "files", "more", "reason")},
                         dict(drafts=["a", "b"], tips=[self.tips["a"], self.tips["b"]],
                              files=paths[:40], more=3, reason="probe"))
        self.assertEqual(len(self.merges()), 3)
        self.assertTrue(all(call.cwd == str(self.home / "agents/a") for call in self.fake.calls))
        self.assertEqual(self.probe(), [])
        self.assertEqual(len(self.events("trunks.overlap")), 1)
        self.assertEqual(len(self.merges()), 3)
        self.tips["a"] = "e" * 40
        self.assertEqual(self.probe(), [])
        self.assertEqual(len(self.merges()), 5)
        self.assertEqual(len(self.events("trunks.overlap")), 1)
        self.pair_result = Result(0)
        self.main = "f" * 40
        self.assertEqual(self.probe(), ["overlap a b 0"])
        self.assertEqual(self.events("trunks.overlap")[-1]["files"], [])
        self.assertEqual(len(self.merges()), 8)

    def test_overlap_probe_merges_main_then_compares_caught_up_trees(self):
        self.probe()
        self.assertEqual([call.argv for call in self.merges()], [
            ["git", "merge-tree", "--write-tree", "--no-messages", "origin/main", "origin/a/integration"],
            ["git", "merge-tree", "--write-tree", "--no-messages", "origin/main", "origin/b/integration"],
            ["git", "merge-tree", "--write-tree", "--name-only", "--no-messages", "-z",
             "--merge-base=origin/main", self.trees["a"], self.trees["b"]]])
        self.assertEqual([call.argv for call in self.fake.calls[:3]], [
            ["git", "rev-parse", "--verify", "origin/main"],
            ["git", "rev-parse", "--verify", "origin/a/integration"],
            ["git", "rev-parse", "--verify", "origin/b/integration"]])

    def test_overlap_probe_catch_up_conflict_keeps_pairs_open_and_is_cached(self):
        self.probe()
        self.tips["a"] = "e" * 40
        self.catch_results["a"] = Result(1, TREE + "\n")
        self.assertEqual(self.probe(), [])
        self.assertEqual(len(self.merges()), 4)
        with patch.object(atomic, "write") as write:
            self.assertEqual(self.probe(), [])
        write.assert_not_called()
        self.assertEqual(len(self.events("trunks.overlap")), 1)
        self.assertEqual(self.events("note"), [])
        self.assertEqual(len(self.merges()), 4)
        cache = json.loads(self.cache_path.read_text())
        self.assertFalse(any(self.tips["a"] in key for key in cache["trees"]))
        self.assertEqual(cache["pairs"], {})
        self.assertEqual(list(cache["conflicts"].values()), [True])
        self.assertIn(self.tips["a"], next(iter(cache["conflicts"])))

    def test_overlap_probe_catch_up_failure_prints_each_tick_and_notes_changes(self):
        self.catch_results["a"] = Result(128, err="missing object\nsecond line")
        for _ in range(2):
            self.assertEqual(self.probe(), ["trunks.overlap a: exit 128: missing object"])
        self.assertEqual(len(self.events("note")), 1)
        self.assertEqual(self.events("trunks.overlap"), [])
        self.catch_results["a"] = Result(1, "no tree")
        self.assertEqual(self.probe(), ["trunks.overlap a: exit 1: unreadable merge-tree output"])
        self.assertEqual(len(self.events("note")), 2)

    def test_overlap_probe_pair_failure_retries_and_drops_cached_trees(self):
        self.probe()
        self.pair_result = Result(128, err="missing tree\nsecond line")
        # A lost pair answer must also invalidate the trees that fail when reused.
        cache = json.loads(self.cache_path.read_text())
        cache["pairs"] = {}
        atomic.write(self.cache_path, json.dumps(cache))
        self.fake.calls.clear()
        for number in range(2):
            self.assertEqual(self.probe(), ["trunks.overlap a b: exit 128: missing tree"])
            cache = json.loads(self.cache_path.read_text())
            self.assertEqual(cache, {"trees": {}, "pairs": {}, "conflicts": {}})
            self.assertEqual(len(self.merges()), 1 + 3 * number)
        self.assertEqual(len(self.events("note")), 1)
        self.assertEqual(len(self.events("trunks.overlap")), 1)

    def test_overlap_probe_merge_exceptions_leave_other_pairs_running(self):
        self.loaded.append(self.entry("c"))
        original = self.merge
        for error in (OSError("unreadable tree"), ValueError("unreadable tree"),
                      Failed(["git", "merge-tree"], Result(128, err="unreadable tree"))):
            with self.subTest(error=type(error).__name__):
                def merge(call):
                    if "--name-only" in call.argv and call.argv[-2:] == [self.trees["a"], self.trees["b"]]:
                        raise error
                    return original(call)
                self.fake.rules[-1] = (["git", "merge-tree"], merge)
                self.cache_path.unlink(missing_ok=True)
                lines = self.probe()
                self.assertIn("unreadable tree", lines[0])
                self.assertEqual(len(self.events("trunks.overlap")), 2)
                cache = json.loads(self.cache_path.read_text())
                self.assertEqual(list(cache["trees"].values()), [self.trees["c"]])

    def test_overlap_probe_repositories_never_share_pairs_or_checkouts(self):
        self.loaded = [self.entry("d", "other"), self.entry("b"),
                       self.entry("c", "other"), self.entry("a")]
        self.assertEqual(self.probe(), ["overlap a b 1", "overlap c d 1"])
        self.assertEqual([event["drafts"] for event in self.events("trunks.overlap")],
                         [["a", "b"], ["c", "d"]])
        for call in self.fake.calls:
            self.assertIn(call.cwd, [str(self.home / "agents/a"), str(self.home / "other/c")])
        self.assertEqual(len(self.merges()), 6)
        for call in self.merges():
            if "--name-only" in call.argv:
                drafts = ("a", "b") if call.cwd == str(self.home / "agents/a") else ("c", "d")
                self.assertEqual(call.argv[-2:], [self.trees[draft] for draft in drafts])

    def test_overlap_probe_closes_landed_pair_unless_a_load_failed(self):
        self.probe()
        log.append("branch.landed", path=self.path, task="a/integration", queue_ts="001")
        self.assertEqual(self.probe(all_loaded=False), [])
        self.assertEqual(len(self.events("trunks.overlap")), 1)
        self.assertEqual(self.probe(), ["overlap a b gone"])
        last = self.events("trunks.overlap")[-1]
        self.assertEqual((last["files"], last["more"], last["reason"], last["tips"]),
                         ([], 0, "gone", [self.tips["a"], self.tips["b"]]))
        self.assertEqual(self.probe(), [])

    def test_overlap_probe_closes_unlisted_retired_and_unready_pairs(self):
        for cause in ("unlisted", "retired", "unready"):
            with self.subTest(cause=cause):
                self.loaded = [self.entry("a"), self.entry("b")]
                self.probe()
                if cause == "unlisted":
                    self.loaded = []
                else:
                    plan, tasks, directory, checkout = self.loaded[0]
                    self.loaded[0] = (replace(plan, **({"retired": True} if cause == "retired"
                                                       else {"ready": False})), tasks, directory, checkout)
                self.assertEqual(self.probe(), ["overlap a b gone"])

    def test_overlap_probe_missing_origin_trunk_forms_no_pair(self):
        self.probe()
        self.tips.pop("a")
        self.fake.calls.clear()
        self.assertEqual(self.probe(), ["overlap a b gone"])
        self.assertEqual(self.merges(), [])

    def test_overlap_probe_clean_first_pair_and_single_trunk_log_nothing(self):
        self.pair_result = Result(0)
        self.assertEqual(self.probe(), [])
        self.assertEqual(log.read(self.path), [])
        self.loaded = self.loaded[:1]
        self.fake.calls.clear()
        self.assertEqual(self.probe(), [])
        self.assertEqual(self.fake.calls, [])

    def test_overlap_probe_missing_corrupt_or_unreadable_cache_only_costs_merges(self):
        self.probe()
        for text in (None, "not json", "[]", '{"trees": [], "pairs": {}}',
                     '{"trees": {}, "pairs": {"bad": {"files": 1, "more": 0}}}',
                     '{"trees": {"bad": "not a tree"}, "pairs": {}}', "\udcff"):
            with self.subTest(text=repr(text)):
                if text is None:
                    self.cache_path.unlink()
                elif text == "\udcff":
                    sibling = self.cache_path.with_name("broken-cache")
                    sibling.write_bytes(b"\xff")
                    sibling.replace(self.cache_path)
                else:
                    atomic.write(self.cache_path, text)
                before = len(self.merges())
                self.assertEqual(self.probe(), [])
                self.assertEqual(len(self.merges()) - before, 3)
                self.assertEqual(len(self.events("trunks.overlap")), 1)
        with patch.object(Path, "read_text", side_effect=PermissionError("unreadable cache")):
            before = len(self.merges())
            self.assertEqual(overlaps.probe(self.loaded, log.read(self.path), True,
                                           sh=self.fake, log_path=self.path), [])
            self.assertEqual(len(self.merges()) - before, 3)

    def test_overlap_probe_checkout_change_does_not_reuse_foreign_tree_ids(self):
        self.probe()
        self.loaded = [(plan, tasks, directory, checkout / "new")
                       for plan, tasks, directory, checkout in self.loaded]
        before = len(self.merges())
        self.assertEqual(self.probe(), [])
        self.assertEqual(len(self.merges()) - before, 3)


    def test_overlap_probe_unchanged_results_only_resolve_refs_and_never_write(self):
        self.probe()
        self.fake.calls.clear()
        before = self.cache_path.stat().st_mtime_ns
        with patch.object(atomic, "write") as write:
            self.assertEqual(self.probe(), [])
        write.assert_not_called()
        self.assertEqual(self.cache_path.stat().st_mtime_ns, before)
        self.assertEqual(self.fake.argvs(), [
            ["git", "rev-parse", "--verify", "origin/main"],
            ["git", "rev-parse", "--verify", "origin/a/integration"],
            ["git", "rev-parse", "--verify", "origin/b/integration"]])

    def test_overlap_probe_empty_missing_cache_needs_no_write(self):
        self.loaded = []
        with patch.object(atomic, "write") as write:
            self.assertEqual(self.probe(), [])
        write.assert_not_called()
        self.assertFalse(self.cache_path.exists())
        self.assertEqual(self.fake.calls, [])

    def test_overlap_probe_conflicts_retry_only_when_tip_or_main_moves(self):
        self.catch_results["a"] = Result(1, TREE + "\n")
        self.assertEqual(self.probe(), [])
        self.assertEqual(len(self.merges()), 2)
        self.fake.calls.clear()
        self.assertEqual(self.probe(), [])
        self.assertEqual(self.merges(), [])
        old_tip = self.tips["a"]
        self.tips["a"] = "e" * 40
        self.assertEqual(self.probe(), [])
        self.assertEqual(len(self.merges()), 1)
        cache = json.loads(self.cache_path.read_text())
        self.assertFalse(any(old_tip in key for answers in cache.values() for key in answers))
        old_main = self.main
        self.main = "f" * 40
        self.assertEqual(self.probe(), [])
        self.assertEqual(len(self.merges()), 3)
        cache = json.loads(self.cache_path.read_text())
        self.assertFalse(any(old_main in key for answers in cache.values() for key in answers))
        self.assertEqual(list(cache["conflicts"].values()), [True])
        self.catch_results.clear()
        self.tips["a"] = "9" * 40
        self.assertEqual(self.probe(), ["overlap a b 1"])
        self.assertEqual(json.loads(self.cache_path.read_text())["conflicts"], {})

    def test_overlap_probe_prunes_old_tip_and_departed_pair_keys(self):
        self.loaded.append(self.entry("c"))
        self.probe()
        old_tip = self.tips["b"]
        self.tips["b"] = "e" * 40
        self.assertEqual(self.probe(), [])
        cache = json.loads(self.cache_path.read_text())
        self.assertFalse(any(old_tip in key for answers in cache.values() for key in answers))
        self.assertEqual(len(cache["trees"]), 3)
        self.assertEqual(len(cache["pairs"]), 3)
        self.loaded.pop()
        self.fake.calls.clear()
        self.assertEqual(self.probe(), ["overlap a c gone", "overlap b c gone"])
        cache = json.loads(self.cache_path.read_text())
        self.assertFalse(any(self.tips["c"] in key for answers in cache.values() for key in answers))
        self.assertEqual(len(cache["trees"]), 2)
        self.assertEqual(len(cache["pairs"]), 1)
        self.assertEqual(self.merges(), [])
        self.loaded.clear()
        self.assertEqual(self.probe(), ["overlap a b gone"])
        self.assertEqual(json.loads(self.cache_path.read_text()),
                         {"trees": {}, "pairs": {}, "conflicts": {}})

    def test_overlap_probe_prunes_conflicts_after_a_pair_leaves(self):
        self.catch_results["a"] = Result(1, TREE + "\n")
        self.probe()
        self.loaded.pop()
        self.assertEqual(self.probe(), [])
        self.assertEqual(json.loads(self.cache_path.read_text()),
                         {"trees": {}, "pairs": {}, "conflicts": {}})

    def test_overlap_probe_reads_first_format_without_rewriting_it(self):
        self.probe()
        cache = json.loads(self.cache_path.read_text())
        cache.pop("conflicts")
        atomic.write(self.cache_path, json.dumps(cache))
        self.fake.calls.clear()
        with patch.object(atomic, "write") as write:
            self.assertEqual(self.probe(), [])
        write.assert_not_called()
        self.assertEqual(self.merges(), [])
        cache["pairs"] = {}
        atomic.write(self.cache_path, json.dumps(cache))
        self.assertEqual(self.probe(), [])
        self.assertEqual(len(self.merges()), 1)
        self.assertIn("--name-only", self.merges()[0].argv)
        self.assertEqual(json.loads(self.cache_path.read_text())["conflicts"], {})

    def test_overlap_probe_malformed_conflicts_discards_other_cached_results(self):
        self.probe()
        cache = json.loads(self.cache_path.read_text())
        for conflicts in (None, [], True, "bad", {"key": False}, {"key": 1},
                          {"key": "true"}, {"key": {}}):
            with self.subTest(conflicts=conflicts):
                cache["conflicts"] = conflicts
                atomic.write(self.cache_path, json.dumps(cache))
                self.fake.calls.clear()
                self.assertEqual(self.probe(), [])
                self.assertEqual(len(self.merges()), 3)
                self.assertEqual(json.loads(self.cache_path.read_text())["conflicts"], {})
