"""Pure overlap decisions over plans and records (docs/design/fab.md, 8 and 13.17)."""

import unittest
from dataclasses import replace

from fab import overlaps
from fab.plan import Plan
from fab.tests.support import tmp_home

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
