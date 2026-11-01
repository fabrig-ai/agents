"""Brief editions use ordered main-branch bytes through the runner (docs/design/fab-qa.md, 2)."""

import io
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import patch

from fab import atomic, cli, findings, log, walks, wake
from fab.plan import load_plan
from fab.sh import Failed, Result
from fab.tests.ladder_plans import write_ladder
from fab.tests.qa_records import finding_merged, finding_raised, finding_triaged, walk_ended, walk_started
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


# One complete table keeps parser and intake fixtures in the walker's TOML format.
_FINDING = dict(title="The story stalled", severity="high", area="ctl", blocking=True,
                reproduction="Run the story", expected="It completes", seen="It stalls",
                evidence=["box:/walk/evidence.txt"], same="")


def _result_text(verdict="fail", entries=None, **changes):
    """Render result.toml with complete fields and optional per-test overrides."""
    entries = [{**_FINDING, **changes}] if entries is None else entries
    lines = [f"verdict = {json.dumps(verdict)}", 'reason = "Story stopped"']
    for entry in entries:
        lines += ["[[finding]]", *[f"{key} = {json.dumps(value)}" for key, value in entry.items()]]
    return "\n".join(lines) + "\n"


def _append(*events, path=None):
    """Write complete shared QA fixtures through the real log primitive."""
    for event in events:
        fields = {key: value for key, value in event.items() if key not in ("ev", "ts")}
        log.append(event["ev"], ts=event["ts"], path=path, **fields)


def _landed(identifier="finding-1", rung="b0", draft="ladder"):
    """A finding's repair lifecycle, ending at landed main repair-main."""
    task = f"{draft}/{identifier}"
    return [walk_started("walk-1", rung, draft=draft),
            finding_raised(identifier, "walk-1", rung, draft=draft),
            walk_ended("walk-1", "fail", (identifier,)),
            finding_triaged(identifier, "path", owner="ctl"),
            log.record("run.started", run="foreman-1", task=task + "/foreman", kind="foreman"),
            log.record("run.ended", run="foreman-1", task=task + "/foreman", outcome="done"),
            log.record("finding.settled", finding=identifier, run="foreman-1", verdict="fix",
                       reason="Repair the story", section="ctl"),
            log.record("branch.landed", task=task, branch="repair", tip="tip", main="repair-main", into="main")]


class ParseTest(unittest.TestCase):
    def test_result_fields_and_verdicts(self):
        parsed = walks.parse(_result_text())
        self.assertIsInstance(parsed, walks.Result)
        self.assertEqual((parsed.verdict, parsed.reason), ("fail", "Story stopped"))
        for key, value in _FINDING.items():
            self.assertEqual(getattr(parsed.findings[0], key), tuple(value) if key == "evidence" else value)
        for verdict in ("pass", "void"):
            self.assertEqual(walks.parse(_result_text(verdict, [])).findings, ())
        self.assertEqual(walks.parse(_result_text("pass", blocking=False)).verdict, "pass")
        self.assertEqual(walks.parse(_result_text("void")).verdict, "void")
        without_same = dict(_FINDING)
        del without_same["same"]
        self.assertEqual(walks.parse(_result_text(entries=[without_same])).findings[0].same, "")

    def test_semantic_refusals_name_the_field(self):
        for text, field in ((_result_text("maybe"), "verdict"),
                            (_result_text("pass"), "blocking"),
                            (_result_text("fail", []), "finding"),
                            (_result_text(severity="critical"), "severity"),
                            (_result_text(entries=[_FINDING] * 31), "finding")):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                walks.parse(text)

    def test_character_limits_include_unicode_and_accept_the_boundary(self):
        for field, limit in (("title", 200), ("reproduction", 4000), ("expected", 4000), ("seen", 4000)):
            with self.subTest(field=field):
                self.assertEqual(getattr(walks.parse(_result_text(**{field: "é" * limit})).findings[0], field),
                                 "é" * limit)
                with self.assertRaisesRegex(ValueError, field):
                    walks.parse(_result_text(**{field: "é" * (limit + 1)}))
        self.assertEqual(len(walks.parse(_result_text(entries=[_FINDING] * 30)).findings), 30)

    def test_malformed_toml_and_field_types_are_named(self):
        for text, field in (("[", "result.toml"), ('verdict = "pass"\n', "reason"),
                            (_result_text(blocking="true"), "blocking"),
                            (_result_text(evidence="path"), "evidence"),
                            (_result_text(evidence=[1]), "evidence"),
                            (_result_text(same=4), "same"),
                            (_result_text(title=4), "title"),
                            ('verdict = "void"\nreason = "setup"\nfinding = "bad"', "finding")):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, field):
                walks.parse(text)


class BriefTest(unittest.TestCase):
    def test_brief_preserves_texts_and_lists_each_finding_on_one_line(self):
        events = [walk_started("walk-1", "b0"),
                  finding_raised("finding-1", "walk-1", "b0", title="Line one\nline two"),
                  walk_ended("walk-1", "fail", ("finding-1",))]
        texts = ["Kit with trailing spaces.  \n", "Rung without a final newline."]
        directory = Path("/walks/walk-2")
        text = walks.brief_text(texts, directory, findings.findings(events).values())
        self.assertTrue(text.startswith("\n\n".join(texts)))
        self.assertEqual(text.split("# Open findings\n\n", 1)[1].splitlines(),
                         ["finding-1 new b0 ctl Line one line two"])
        for filename in ("report.md", "result.toml"):
            self.assertIn(str(directory / filename), text)
        self.assertEqual(walks.parse(text.split("```toml\n")[1].split("```")[0]).verdict, "fail")
        self.assertEqual(texts, ["Kit with trailing spaces.  \n", "Rung without a final newline."])

    def test_empty_briefs_and_findings_still_have_reporting_sections(self):
        text = walks.brief_text([], Path("/walks/walk-1"), [])
        self.assertTrue(text.startswith("# Reporting to fab\n"))
        self.assertTrue(text.endswith("# Open findings\n\n\n"))


class IntakeTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.path = self.home / "elsewhere/log.jsonl"
        self.directory = self.home / "walker"
        self.destination = log.home() / walks.WALKS / "walk-2"
        _append(walk_started("walk-1", "b0"), finding_raised("finding-1", "walk-1", "b0"),
                walk_ended("walk-1", "fail", ("finding-1",)), walk_started("walk-2", "b1"), path=self.path)
        self.text = _result_text(entries=[{**_FINDING, "same": "finding-1"},
                                          {**_FINDING, "title": "A second cause"}])
        atomic.write(self.directory / "result.toml", self.text)
        atomic.write(self.directory / "report.md", "Walk report.\n")

    def test_cli_result_raises_then_merges_then_ends_and_wakes_once(self):
        with patch.object(log, "default_path", return_value=self.path):
            self.assertEqual(cli.main(["qa", "result", "walk-2", str(self.directory)]), 0)
        events = log.read(self.path)[4:]
        self.assertEqual([event["ev"] for event in events],
                         ["finding.raised", "finding.raised", "finding.merged", "walk.ended"])
        for index, event in enumerate(events[:2], 1):
            self.assertEqual(event["finding"], f"finding-{index + 1}")
            self.assertEqual(event["index"], index)
            for field in ("draft", "walk", "rung", "backend", "commit", "edition"):
                self.assertEqual(event[field], walk_started("walk-2", "b1")[field])
            self.assertEqual((event["kind"], event["again"]), ("qa", ""))
            self.assertEqual(event["evidence"], _FINDING["evidence"])
        self.assertEqual((events[2]["finding"], events[2]["into"], events[2]["by"]),
                         ("finding-2", "finding-1", "walk-2"))
        self.assertEqual(events[-1]["findings"], ["finding-2", "finding-3"])
        self.assertEqual(events[-1]["report"], str(self.destination / "report.md"))
        self.assertEqual((self.destination / "report.md").read_text(), "Walk report.\n")
        self.assertEqual((self.destination / "result.toml").read_text(), self.text)
        self.assertEqual(wake.want_path(self.path).read_text(), "qa walk-2\n")
        found = findings.findings(log.read(self.path))
        self.assertEqual(found["finding-2"].state, "merged")
        self.assertEqual(found["finding-1"].sightings, ("finding-2",))

    def test_interrupted_intake_reuses_indices_and_merges(self):
        append = log.append
        for cut in (1, 3):
            with self.subTest(cut=cut):
                path = self.home / f"cut-{cut}/log.jsonl"
                _append(*log.read(self.path), path=path)
                count = 0

                def interrupted(ev, **fields):
                    nonlocal count
                    if count == cut:
                        raise OSError("intake interrupted")
                    count += 1
                    return append(ev, **fields)

                with patch.object(log, "append", side_effect=interrupted), self.assertRaisesRegex(OSError, "interrupted"):
                    walks.result("walk-2", self.directory, log_path=path)
                partial = log.read(path)
                self.assertEqual(len(partial), 4 + cut)
                self.assertEqual(list(findings.findings(partial)), ["finding-1"])
                self.assertFalse(wake.want_path(path).exists())
                resumed = walks.result("walk-2", log_path=path)
                self.assertEqual(len(resumed), 4 - cut)
                events = log.read(path)
                self.assertEqual([e["ev"] for e in events[4:]],
                                 ["finding.raised", "finding.raised", "finding.merged", "walk.ended"])
                self.assertEqual(events[-1]["findings"], ["finding-2", "finding-3"])
                with self.assertRaisesRegex(ValueError, "ended"):
                    walks.result("walk-2", log_path=path)
                self.assertEqual(log.read(path), events)
                self.assertEqual(wake.want_path(path).read_text(), "qa walk-2\n")

    def test_same_resolves_a_merge_chain(self):
        _append(walk_started("walk-3", "b0"), finding_raised("finding-2", "walk-3", "b0"),
                finding_merged("finding-2", "finding-1", by="walk-3"),
                walk_ended("walk-3", "fail", ("finding-2",)), path=self.path)
        atomic.write(self.directory / "result.toml", _result_text(same="finding-2"))
        events = walks.result("walk-2", self.directory, log_path=self.path)
        self.assertEqual(events[1]["into"], "finding-1")
        self.assertEqual(events[0]["again"], "")

    def test_same_landed_or_closed_is_filed_again(self):
        histories = [_landed(), [walk_started("walk-1", "b0"),
                     finding_raised("finding-1", "walk-1", "b0"),
                     walk_ended("walk-1", "fail", ("finding-1",)), finding_triaged("finding-1", "drop")]]
        for index, history in enumerate(histories):
            with self.subTest(index=index):
                path = self.home / f"closed-{index}/log.jsonl"
                _append(*history, walk_started("walk-2", "b1"), path=path)
                events = walks.result("walk-2", self.directory, log_path=path)
                self.assertEqual([e["ev"] for e in events], ["finding.raised", "finding.raised", "walk.ended"])
                self.assertEqual(events[0]["again"], "finding-1")

    def test_refusals_leave_log_and_artifacts_untouched(self):
        _append(walk_started("walk-3", "b0", draft="other"),
                finding_raised("finding-2", "walk-3", "b0", draft="other"),
                walk_ended("walk-3", "fail", ("finding-2",)), path=self.path)
        before = self.path.read_text()
        refusals = [(_result_text("pass"), "blocking"), (_result_text("fail", []), "finding"),
                    (_result_text(same="finding-999"), "same"), (_result_text(same="finding-2"), "same"),
                    (_result_text("wrong"), "verdict"), (_result_text(severity="urgent"), "severity"),
                    (_result_text(title="x" * 201), "title"), (_result_text(seen="x" * 4001), "seen")]
        for text, field in refusals:
            with self.subTest(field=field):
                atomic.write(self.directory / "result.toml", text)
                with self.assertRaisesRegex(ValueError, field):
                    walks.result("walk-2", self.directory, log_path=self.path)
                self.assertEqual(self.path.read_text(), before)
                self.assertFalse(self.destination.exists())
                self.assertFalse(wake.want_path(self.path).exists())
        for identifier, reason in (("walk-999", "unknown"), ("walk-1", "ended")):
            with self.assertRaisesRegex(ValueError, reason):
                walks.result(identifier, self.directory, log_path=self.path)
        self.assertEqual(self.path.read_text(), before)

    def test_default_directory_and_missing_report(self):
        atomic.write(self.destination / "result.toml", _result_text("void", []))
        events = walks.result("walk-2", log_path=self.path)
        self.assertEqual([e["ev"] for e in events], ["walk.ended"])
        self.assertEqual((events[0]["verdict"], events[0]["findings"], events[0]["report"]), ("void", [], ""))

    def test_cli_refusal_exits_two_and_names_field(self):
        atomic.write(self.directory / "result.toml", _result_text("pass"))
        err = io.StringIO()
        with patch.object(log, "default_path", return_value=self.path), redirect_stderr(err):
            self.assertEqual(cli.main(["qa", "result", "walk-2", str(self.directory)]), 2)
        self.assertIn("blocking", err.getvalue())
        self.assertEqual(len(log.read(self.path)), 4)

    def test_concurrent_intakes_count_ids_only_after_acquiring_the_lock(self):
        _append(walk_started("walk-3", "b0"), path=self.path)
        atomic.write(self.directory / "result.toml", _result_text())
        first_read, second_attempt = Event(), Event()
        read, flock = log.read, walks.fcntl.flock

        def locked(descriptor, operation):
            if first_read.is_set():
                second_attempt.set()
            return flock(descriptor, operation)

        def reading(path):
            if not first_read.is_set():
                first_read.set()
                if not second_attempt.wait(2):
                    raise AssertionError("second intake never attempted qa.lock")
            return read(path)

        with patch.object(walks.fcntl, "flock", side_effect=locked), patch.object(log, "read", side_effect=reading):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(walks.result, "walk-2", self.directory, log_path=self.path)
                self.assertTrue(first_read.wait(2))
                second = pool.submit(walks.result, "walk-3", self.directory, log_path=self.path)
                self.assertEqual(first.result()[0]["finding"], "finding-2")
                self.assertEqual(second.result()[0]["finding"], "finding-3")
        self.assertEqual(wake.want_path(self.path).read_text().splitlines(), ["qa walk-2", "qa walk-3"])


class WalkTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.root = self.home / "checkout"
        self.directory = write_ladder(self.root / "docs/plan/ladder")
        self.plan = load_plan(self.directory / "plan.toml")
        self.texts = {"briefs/kit.md": "Main kit.\n", "briefs/b0.md": "Main b0.\n",
                      "briefs/b1.md": "Main b1.\n"}
        self.fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(self.root)))
        self.fake.on(["git", "show"], lambda call: Result(0, self.texts[
            call.argv[2].removeprefix("origin/main:docs/plan/ladder/")]))

    def test_walk_writes_main_brief_open_findings_and_reporting_outside_edition(self):
        _append(walk_started("walk-1", "b1"), finding_raised("finding-1", "walk-1", "b1"),
                walk_ended("walk-1", "fail", ("finding-1",)),
                walk_started("walk-2", "b0", draft="other"),
                finding_raised("finding-2", "walk-2", "b0", draft="other"),
                walk_ended("walk-2", "fail", ("finding-2",)))
        out = io.StringIO()
        with patch.object(walks, "run", self.fake), redirect_stdout(out):
            self.assertEqual(cli.main(["qa", "walk", str(self.directory), "b0", "--commit", "walked"]), 0)
        identifier, printed = out.getvalue().splitlines()
        self.assertEqual(identifier, "walk-3")
        brief = Path(printed).read_text()
        self.assertTrue(brief.startswith("Main kit.\n\n\nMain b0.\n"))
        self.assertIn("finding-1 new b1 ctl The story stalled", brief)
        self.assertNotIn("finding-2", brief)
        self.assertIn("# Reporting to fab", brief)
        self.assertIn(str(Path(printed).parent / "report.md"), brief)
        self.assertIn(str(Path(printed).parent / "result.toml"), brief)
        self.assertLess(brief.index("# Reporting to fab"), brief.index("# Open findings"))
        example = brief.split("```toml\n", 1)[1].split("```", 1)[0]
        self.assertEqual(walks.parse(example).verdict, "fail")
        event = log.read()[-1]
        self.assertEqual(event["by"], "session")
        self.assertEqual((event["ev"], event["walk"], event["commit"]), ("walk.started", identifier, "walked"))
        self.assertEqual(event["edition"], walks.edition([(p, self.texts[p]) for p in self.plan.rungs["b0"].brief]))
        self.assertEqual(self.fake.argvs()[0], ["git", "fetch", "origin"])
        self.assertEqual(self.fake.calls[0].cwd, str(self.directory))
        self.assertFalse(wake.want_path().exists())

    def test_walk_refuses_missing_landed_repair_including_merged_target_on_other_rung(self):
        _append(*_landed(rung="b1"))
        # The merge predates landing, so its target can later carry the repair.
        events = log.read()
        before_landing = events[:3] + [walk_started("walk-2", "b0"),
            finding_raised("finding-2", "walk-2", "b0"),
            finding_merged("finding-2", "finding-1", by="walk-2"),
            walk_ended("walk-2", "fail", ("finding-2",))] + events[3:]
        path = self.home / "merged/log.jsonl"
        _append(*before_landing, path=path)
        self.fake.on(["git", "merge-base"], Result(1))
        before = log.read(path)
        with self.assertRaisesRegex(ValueError, "finding-1.*repair-main"):
            walks.walk(self.directory, "b0", "old-commit", sh=self.fake, log_path=path)
        self.assertEqual(log.read(path), before)
        err = io.StringIO()
        with patch.object(log, "default_path", return_value=path), \
                patch.object(walks, "run", self.fake), redirect_stderr(err):
            self.assertEqual(cli.main(["qa", "walk", str(self.directory), "b0", "--commit", "old-commit"]), 2)
        self.assertIn("finding-1", err.getvalue())
        self.assertEqual(log.read(path), before)
        call = self.fake.calls[-1]
        self.assertEqual(call.argv, ["git", "merge-base", "--is-ancestor", "repair-main", "old-commit"])
        self.assertEqual(call.cwd, str(log.home() / "repos/fabrig"))
        self.assertFalse((log.home() / walks.WALKS).exists())

    def test_walk_accepts_commit_containing_repair_and_explicit_by(self):
        _append(*_landed())
        identifier, path = walks.walk(self.directory, "b0", "new-commit", by="reviewer", sh=self.fake)
        self.assertEqual(identifier, "walk-2")
        self.assertTrue(path.is_file())
        self.assertEqual(log.read()[-1]["by"], "reviewer")
        self.assertIn("finding-1 landed b0 ctl", path.read_text())
        self.assertEqual(self.fake.argvs()[-1], ["git", "merge-base", "--is-ancestor", "repair-main", "new-commit"])

    def test_unknown_rung_fetch_failure_or_missing_brief_logs_nothing(self):
        with self.assertRaisesRegex(ValueError, "rung"):
            walks.walk(self.directory, "missing", "commit", sh=self.fake)
        self.assertEqual(self.fake.calls, [])
        failed_fetch = FakeRunner().on(["git", "fetch"], Result(1, err="fetch failed"))
        with self.assertRaises(Failed):
            walks.walk(self.directory, "b0", "commit", sh=failed_fetch)
        missing = FakeRunner().on(["git", "rev-parse"], Result(0, str(self.root)))
        missing.on(["git", "show"], Result(1))
        with self.assertRaisesRegex(ValueError, "b0.*briefs/kit.md"):
            walks.walk(self.directory, "b0", "commit", sh=missing)
        self.assertEqual(log.read(), [])

    def test_rungs_prints_one_shared_line_per_rung_with_explicit_or_default_plans(self):
        expected = [findings.line(state) for state in findings.rungs(
            self.plan, [], walks.editions(self.plan, self.directory, sh=self.fake), log.now())]
        for arguments in ([str(self.directory)], []):
            with self.subTest(arguments=arguments):
                out = io.StringIO()
                with patch.object(walks, "run", self.fake), \
                        patch.object(walks.channel, "plan_dirs", return_value=[self.directory]) as defaults, \
                        redirect_stdout(out):
                    self.assertEqual(cli.main(["qa", "rungs", *arguments]), 0)
                self.assertEqual(out.getvalue().splitlines(), expected)
                self.assertEqual(defaults.call_count, 0 if arguments else 1)
