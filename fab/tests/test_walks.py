"""Brief editions use ordered main-branch bytes through the runner (docs/design/fab.md, 13.15)."""

import unittest
from dataclasses import replace

from fab import walks
from fab.plan import load_plan
from fab.sh import Failed, Result
from fab.tests.ladder_plans import write_ladder
from fab.tests.support import FakeRunner, tmp_home


class EditionTest(unittest.TestCase):
    def test_edition_is_stable_twelve_hex_from_ordered_utf8_paths_and_texts(self):
        files = [("briefs/kit.md", "Kit.\n"), ("briefs/b0.md", "Walk.\n")]
        self.assertEqual(walks.edition(files), "03fd74b72fa3")
        self.assertEqual(walks.edition(tuple(files)), walks.edition(files))
        self.assertRegex(walks.edition([]), r"^[0-9a-f]{12}$")
        self.assertNotEqual(walks.edition([("briefs/é.md", "Marche.\n")]),
                            walks.edition([("briefs/e.md", "Marche.\n")]))

    def test_path_text_order_and_file_boundaries_change_the_edition(self):
        files = [("kit", "shared"), ("brief", "walk")]
        for changed in ([("kit", "changed"), files[1]], [files[0], ("brief", "changed")],
                        [("renamed", "shared"), files[1]], list(reversed(files)), files[:1],
                        [("kitshared", ""), files[1]], [("kit", "sharedbriefwalk")]):
            with self.subTest(changed=changed):
                self.assertNotEqual(walks.edition(changed), walks.edition(files))
        self.assertNotEqual(walks.edition([("ab", "c")]), walks.edition([("a", "bc")]))


class EditionsTest(unittest.TestCase):
    def setUp(self):
        self.root = self.enterContext(tmp_home()) / "checkout"
        self.directory = write_ladder(self.root / "nested/docs/plan/ladder", rungs={
            "b1": ("claude-forgejo", ("b0",)), "b0": ("claude-forgejo", ())})
        self.plan = load_plan(self.directory / "plan.toml")
        self.prefix = "origin/main:nested/docs/plan/ladder/"
        self.texts = {"briefs/kit.md": "Main kit.\n", "briefs/b0.md": "Main b0.\n",
                      "briefs/b1.md": "Main b1.\n"}
        self.fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"], Result(0, str(self.root) + "\n"))
        self.fake.on(["git", "show"], lambda call: Result(0, self.texts[call.argv[2].removeprefix(self.prefix)]))

    def test_editions_read_main_through_runner_in_plan_and_brief_order(self):
        result = walks.editions(self.plan, self.directory, sh=self.fake)
        self.assertEqual(list(result), ["b1", "b0"])
        for identifier, rung in self.plan.rungs.items():
            self.assertEqual(result[identifier], walks.edition([(path, self.texts[path]) for path in rung.brief]))
        self.assertEqual(self.fake.argvs(), [["git", "rev-parse", "--show-toplevel"],
                         *[["git", "show", self.prefix + path] for path in (
                             "briefs/kit.md", "briefs/b1.md", "briefs/kit.md", "briefs/b0.md")]])
        self.assertEqual(self.fake.calls[0].cwd, str(self.directory))
        self.assertEqual([call.cwd for call in self.fake.calls[1:]], [str(self.root)] * 4)

    def test_hash_uses_path_spelled_in_plan_even_when_git_path_is_normalized(self):
        rung = replace(self.plan.rungs["b0"], brief=("./briefs/b0.md",))
        plan = replace(self.plan, rungs={"b0": rung})
        result = walks.editions(plan, self.directory, sh=self.fake)
        self.assertEqual(result, {"b0": walks.edition([("./briefs/b0.md", self.texts["briefs/b0.md"])])})

    def test_missing_main_brief_names_rung_and_file_even_when_local_file_exists(self):
        for path in ("briefs/kit.md", "briefs/b1.md", "briefs/b0.md"):
            with self.subTest(path=path):
                fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(self.root)))
                fake.on(["git", "show", self.prefix + path], Result(128, err="not in main"))
                self.assertTrue((self.directory / path).is_file())
                with self.assertRaises(ValueError) as raised:
                    walks.editions(self.plan, self.directory, sh=fake)
                rung = "b0" if path == "briefs/b0.md" else "b1"
                self.assertIn(rung, str(raised.exception))
                self.assertIn(path, str(raised.exception))

    def test_checkout_lookup_failure_propagates(self):
        fake = FakeRunner().on(["git", "rev-parse"], Result(128, err="not a checkout"))
        with self.assertRaises(Failed):
            walks.editions(self.plan, self.directory, sh=fake)
        self.assertEqual(fake.argvs(), [["git", "rev-parse", "--show-toplevel"]])

    def test_no_rungs_needs_no_git_commands(self):
        plan = replace(self.plan, rungs={})
        self.assertEqual(walks.editions(plan, self.directory, sh=self.fake), {})
        self.assertEqual(self.fake.calls, [])
