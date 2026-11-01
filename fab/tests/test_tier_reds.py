"""Red lifecycle decisions over records; acting shells use temporary homes and fakes."""

import shlex
import unittest
from dataclasses import FrozenInstanceError, replace
from unittest.mock import patch

from fab import atomic, foreman, log, tier_reds as reds
from fab.hosts import Host
from fab.plan import Plan, Task
from fab.sh import Result
from fab.tests.support import FakeRunner, tmp_home

PLAN = Plan("demo", "fabrig", (), 1, 2, {}, (), landing="queue")
TASK = Task("demo/a", "core", "feature", "fabrig", (), ("fab/a.py",), "high", 20, "body", "a.md")
HOST = Host("tiers", "worker@tiers.invalid", ("builder", "after-landing"))
BUILDER = Host("builder", "worker@builder.invalid", ("builder",), places=0)
KEY = "default::binary::test"
FOREMAN = "demo/red-1/foreman-1"


def event(ev, **fields):
    return dict(ev=ev, ts="2026-11-01T00:00:00Z", **fields)


def tier(key=KEY, tip="tip", branches=("demo/a",), **fields):
    return event(reds.TIERS_RED, key=key, tip=tip, branches=list(branches), profile="default",
                 binary="binary", test=key, state="new", error="assertion", log="/tier/log",
                 rerun=f"/tier/{key}", **fields)


def checked(keys=(KEY,), tip="tip", **fields):
    return event(reds.TIERS_RUN, **(dict(tip=tip, reds=list(keys), starved=0, unobserved=0) | fields))


def opened(**fields):
    return event(reds.OPENED, **(dict(red="red-1", tip="tip", keys=[KEY], suspects=["demo/a"],
                                    tasks=["demo/a"], draft="demo", route="foreman", reason="") | fields))


def foreman_run(outcome=None):
    records = [event("run.started", run=FOREMAN, task="demo/red-1/foreman", kind=foreman.KIND,
                     red="red-1", tip="tip")]
    if outcome is not None:
        records += [event("run.ended", run=FOREMAN, outcome=outcome, report="/report.md")]
    return records


def settled(verdict="fix", **fields):
    return event(reds.SETTLED, **(dict(red="red-1", run=FOREMAN, verdict=verdict,
                                     reason="why", owner="demo/a", section="## Repair\n\nfix it\n") | fields))


def repair_events():
    return [opened(), *foreman_run("done"), settled()]


def command(call):
    return shlex.split(shlex.split(call.argv[-1])[2])


class TierRedsOpeningTest(unittest.TestCase):
    def test_unknown_commit_counts_open_with_evidence_instead_of_raising(self):
        for count in (None, "three", [], {}, True, 1.5):
            with self.subTest(commits=count), tmp_home() as home:
                events = [tier(), checked(commits=count)]
                actual = reds.open_reds(events, {TASK.id: TASK.id}, HOST, sh=FakeRunner(), log_path=home / "events")
                self.assertEqual(len(actual), 1)
                self.assertIn("unknown", reds.evidence_path("red-1").read_text())

    def test_loaded_queue_merge_opens_one_foreman(self):
        events = [tier(branches=("demo/a-r2",)), checked()]
        owners = reds.owners([(PLAN, {TASK.id: TASK})], events)
        self.assertEqual(owners["demo/a-r2"], TASK.id)
        group, = reds.openings(events, owners)
        self.assertEqual((group.tip, group.keys, group.tasks, group.draft, group.route, group.reason),
                         ("tip", (KEY,), ("demo/a",), "demo", "foreman", ""))
        with self.assertRaises(FrozenInstanceError):
            group.tip = "changed"

    def test_twelve_reds_at_one_tip_open_one_and_standing_open_none(self):
        keys = [f"test-{n}" for n in range(12)]
        events = [*(tier(key) for key in keys), checked(keys)]
        with tmp_home() as home:
            path, fake = home / "events", FakeRunner().on(["ssh"], Result(0, "rerun failed\n"))
            actual = reds.open_reds(events, {TASK.id: TASK.id}, HOST, sh=fake, log_path=path)
            self.assertEqual(len(actual), 1)
            self.assertEqual(actual[0]["keys"], keys)
            self.assertEqual(actual[0]["route"], "foreman")
            self.assertEqual(len(fake.calls), 3)
            self.assertTrue(reds.evidence_path("red-1").is_file())
            self.assertEqual(reds.openings(events + actual + [checked(keys, tip="next")],
                                           {TASK.id: TASK.id}), [])
            self.assertEqual(log.read(path), actual)
            self.assertEqual(log.read(), [])

    def test_hand_pushed_and_no_suspect_routes(self):
        for branches, reason in ((("manual/topic",), "no fab task among the suspects"),
                                 ((), "no suspects")):
            with self.subTest(branches=branches), tmp_home() as home:
                events = [tier(branches=branches), checked()]
                owners = reds.owners([(PLAN, {TASK.id: TASK})], events)
                records = reds.open_reds(events, owners, HOST, sh=FakeRunner(), log_path=home / "events")
                red, = reds.reds(records)
                self.assertEqual((red.draft, red.state, red.signal_reason), ("", "signal", reason))

    def test_group_order_and_newest_fab_suspect_owns_the_draft(self):
        events = [tier("a", branches=("old/a", "hand/x", "new/b")),
                  tier("b", branches=("old/a",)),
                  tier("c", branches=("old/a", "hand/x", "new/b")), checked(("a", "b", "c"))]
        groups = reds.openings(events, {"old/a": "old/a", "new/b": "new/b"})
        self.assertEqual([group.keys for group in groups], [("a", "c"), ("b",)])
        self.assertEqual((groups[0].tasks, groups[0].draft), (("old/a", "new/b"), "new"))

    def test_no_reds_field_newest_run_or_no_longer_red_opens_nothing(self):
        for last in (event(reds.TIERS_RUN, tip="new"), checked(())):
            self.assertEqual(reds.openings([tier(), checked(), last], {}), [])

    def test_closed_tip_key_never_reopens_but_new_tip_can(self):
        close = event(reds.CLOSED, red="red-1", reason="recovered", tip="green")
        events = [tier(), checked(), opened(), close]
        self.assertEqual(reds.openings(events, {TASK.id: TASK.id}), [])
        groups = reds.openings(events + [tier(tip="next"), checked(tip="next")], {TASK.id: TASK.id})
        self.assertEqual([group.tip for group in groups], ["next"])
        self.assertEqual(reds.openings(events[:-1] + [tier(tip="next"), checked(tip="next")], {}), [])

    def test_trunk_and_red_tasks_belong_to_loaded_plans_retired_does_not(self):
        trunk = replace(PLAN, landing="integration")
        events = repair_events() + [tier(branches=(trunk.trunk, "demo/red-1-r2", "gone/a"))]
        owners = reds.owners([(trunk, {TASK.id: TASK}),
                              (replace(PLAN, draft="gone", retired=True),
                               {"gone/a": replace(TASK, id="gone/a")})], events)
        self.assertEqual(owners[trunk.trunk], PLAN.draft)
        self.assertEqual(owners["demo/red-1-r2"], "demo/red-1")
        self.assertNotIn("gone/a", owners)

    def test_duplicate_red_records_and_key_at_another_tip_stay_single(self):
        events = [tier(), tier(), tier(tip="other"), checked()]
        groups = reds.openings(events, {TASK.id: TASK.id})
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].keys, (KEY,))

    def test_red_pass_red_imported_together_uses_last_reds_tip_and_suspects(self):
        events = [tier(tip="A", branches=("old/a",)), checked(tip="A"),
                  event(reds.RECOVERED, key=KEY, tip="B"), checked((), tip="B"),
                  tier(tip="C", branches=("new/b",)), checked(tip="C")]
        group, = reds.openings(events, {"old/a": "old/a", "new/b": "new/b"})
        self.assertEqual((group.tip, group.suspects, group.tasks, group.draft),
                         ("C", ("new/b",), ("new/b",), "new"))

    def test_run_commits_and_branches_belong_to_the_groups_tip(self):
        events = [tier(branches=("demo/integration", "manual/x"), commits=99),
                  checked(commits=2, branches=["demo/integration"]),
                  checked(commits=5, branches=["demo/integration", "demo/b", "manual/x"]),
                  checked(tip="newest", commits=40, branches=[])]
        owners = {"demo/integration": "demo"}
        group, = reds.openings(events, owners)
        self.assertEqual((group.commits, group.branches),
                         (5, ("demo/integration", "demo/b", "manual/x")))
        text = reds.evidence(group, red_id="red-1", machine="tiers", owners=owners, reruns={})
        for fragment in ("Commits with no branch: 2", "demo/integration: the trunk of plan demo",
                         "manual/x: hand-pushed"):
            self.assertIn(fragment, text)
        self.assertEqual(group.hand_pushed, ("manual/x",))
        for commits, count in ((0, "0"), (1, "0"), (None, "unknown")):
            run = checked(branches=["demo/integration"])
            if commits is not None:
                run["commits"] = commits
            group, = reds.openings([events[0], run], owners)
            text = reds.evidence(group, red_id="red-1", machine="tiers", owners=owners, reruns={})
            self.assertIn("Commits with no branch: " + count, text)

    def test_evidence_limits_counts_paths_and_rerun_tails(self):
        events = [*(tier(str(n)) for n in range(22)),
                  checked(tuple(map(str, range(22))), commits=3, branches=["demo/a"])]
        group, = reds.openings(events, {TASK.id: TASK.id})
        text = reds.evidence(group, red_id="red-1", machine="tiers", owners={TASK.id: TASK.id},
                             reruns={"/tier/0": "\n".join(f"line {n}" for n in range(45))})
        for fragment in ("`tip`", "demo/a: demo/a", "Commits with no branch: 2", "2 more reds",
                         "tiers:/tier/log", "tiers:/tier/0", "line 5\n", "line 44\n",
                         "(log unreadable: no rerun path)"):
            self.assertIn(fragment, text)
        self.assertNotIn("line 4\n", text)
        self.assertNotIn("binary 20 (new)", text)
        self.assertEqual(text.count("```text"), 3)

    def test_ssh_failures_quote_why_and_shared_rerun_is_read_once(self):
        events = [tier("a"), {**tier("b"), "rerun": "/tier/a"}, checked(("a", "b"))]
        with tmp_home() as home:
            fake = FakeRunner().on(["ssh"], Result(1, err="missing rerun"))
            records = reds.open_reds(events, {}, HOST, sh=fake, log_path=home / "events")
            self.assertEqual(len(records), 1)
            text = reds.evidence_path("red-1").read_text()
            self.assertIn("(log unreadable: missing rerun)", text)
            self.assertIn("Commits with no branch: unknown", text)
            self.assertEqual([command(call) for call in fake.calls], [["tail", "-n", "40", "--", "/tier/a"]])

    def test_ssh_oserror_and_missing_path_do_not_prevent_opening(self):
        def offline(call):
            raise OSError("offline")

        for record in (tier(), {**tier(), "rerun": ""}):
            with self.subTest(record=record), tmp_home() as home:
                fake = FakeRunner().on(["ssh"], offline)
                actual = reds.open_reds([record, checked()], {}, HOST, sh=fake, log_path=home / "events")
                self.assertEqual(len(actual), 1)
                self.assertIn("(log unreadable:", reds.evidence_path("red-1").read_text())

    def test_evidence_write_failure_notes_and_next_tick_retries(self):
        with tmp_home() as home:
            path, events = home / "events", [tier(), checked()]
            with patch.object(reds.atomic, "write", side_effect=OSError("full disk")):
                self.assertEqual(reds.open_reds(events, {}, HOST, sh=FakeRunner(), log_path=path), [])
            note, = log.read(path)
            self.assertEqual(note["ev"], "note")
            self.assertIn("full disk", note["text"])
            actual = reds.open_reds(events + [note], {}, HOST, sh=FakeRunner(), log_path=path)
            self.assertEqual(actual[0]["red"], "red-1")

    def test_number_counts_opened_in_all_drafts_including_closed(self):
        events = [opened(), event(reds.CLOSED, red="red-1", reason="cleared"),
                  tier("new", tip="new"), checked(("new",))]
        with tmp_home() as home:
            actual = reds.open_reds(events, {}, HOST, sh=FakeRunner(), log_path=home / "events")
            self.assertEqual(actual[0]["red"], "red-2")


class TierRedsFoldTest(unittest.TestCase):
    def test_covering_run_before_queue_import_proves_repair_landed(self):
        events = repair_events() + [checked((), tip="cover", branches=["demo/red-1-r2"], starved=1)]
        red, = reds.reds(events)
        self.assertEqual((red.state, red.covered), ("landed", "cover"))
        self.assertEqual(reds.closures(events), [])
        events += [event("branch.landed", task="demo/red-1")]
        self.assertEqual(reds.reds(events)[0].covered, "cover")
        events += [checked(tip="later", branches=[])]
        self.assertEqual(reds.reds(events)[0].state, "signal")
        self.assertIn("still red at later", reds.reds(events)[0].signal_reason)

    def test_states_since_report_and_frozen_record(self):
        records = [opened(), *foreman_run("done"), settled(),
                   event("run.started", task="demo/red-1", run="demo/red-1-1", kind="implement"),
                   event("branch.landed", task="demo/red-1")]
        records = [{**record, "ts": str(i)} for i, record in enumerate(records)]
        expected = [("foreman", "0"), ("deciding", "1"), ("decided", "2"),
                    ("repairing", "3"), ("repairing", "3"), ("landed", "5")]
        for length, state in enumerate(expected, 1):
            red, = reds.reds(records[:length])
            self.assertEqual((red.state, red.since), state)
        self.assertEqual((red.foreman, red.report, red.verdict, red.owner), (FOREMAN, "/report.md", "fix", TASK.id))
        with self.assertRaises(FrozenInstanceError):
            red.state = "other"

    def test_left_becomes_signal_and_no_task(self):
        events = [opened(), *foreman_run("done"), settled("left", section="", owner="")]
        red, = reds.reds(events)
        self.assertEqual((red.state, red.reason, red.signal_reason), ("signal", "why", "not the suspects': why"))
        self.assertEqual(reds.repair_tasks(PLAN, events, {}), {})

    def test_every_non_done_foreman_outcome_falls_back_without_settlement(self):
        for outcome in ("failed", "infra", "question"):
            with self.subTest(outcome=outcome):
                events = [opened(), *foreman_run(outcome)]
                red, = reds.reds(events)
                task, = reds.repair_tasks(PLAN, events, {"red-1": "the red alone"}).values()
                self.assertEqual((red.state, red.verdict, task.id), ("repairing", "", "demo/red-1"))
                self.assertIn("the red alone", task.body)
                self.assertNotIn("## Repair (", task.body)

    def test_wrong_foreman_task_tip_red_and_unrelated_question_or_refusal_do_not_count(self):
        start = foreman_run()[0]
        for changes in ({"task": "demo/a/foreman"}, {"tip": "other"}, {"red": "red-2"},
                        {"kind": "implement"}, {"red": None, "asked": "run"},
                        {"red": None, "refused": "tip"}):
            with self.subTest(changes=changes):
                self.assertEqual(reds.reds([opened(), start | changes])[0].state, "foreman")

    def test_settlement_before_end_or_wrong_run_is_ignored_and_first_end_wins(self):
        events = [opened(), *foreman_run(), settled(), foreman_run("done")[-1],
                  settled(run="wrong"), event("run.ended", run=FOREMAN, outcome="failed")]
        self.assertEqual(reds.reds(events)[0].state, "decided")
        self.assertEqual(reds.reds(events + [settled("none", section="", owner="")])[0].state, "repairing")

    def test_malformed_records_are_skipped_and_equal_timestamps_follow_order(self):
        malformed = [event(reds.OPENED, red="incomplete"), event("run.started", red="red-1"),
                     {"ts": "same"}, event("run.ended", run=FOREMAN)]
        events = [opened(), *malformed, *foreman_run("done"), settled()]
        self.assertEqual(reds.reds(events)[0].state, "repairing")

    def test_openings_require_string_fields_and_lists_of_strings(self):
        for changes in ({"tip": None}, {"keys": None}, {"keys": [None]}, {"keys": [[KEY]]},
                        {"suspects": None}, {"suspects": [7]}, {"suspects": [{"branch": "demo/a"}]},
                        {"red": []}, {"draft": None}, {"route": None}, {"tasks": [None]}):
            with self.subTest(changes=changes):
                malformed = opened(**changes)
                self.assertEqual(reds.reds([malformed]), [])
                red, = reds.reds([malformed, opened()])
                self.assertEqual((red.id, red.state), ("red-1", "foreman"))

    def test_signal_time_covers_each_route_and_survives_closure(self):
        routes = [
            [opened(route="signal", reason="no suspects")],
            [opened(), *foreman_run("done"), settled("left")],
            repair_events() + [event("branch.landed", task="demo/red-1"),
                               checked(tip="unfixed", branches=["demo/red-1-r2"])],
        ]
        for records in routes:
            with self.subTest(route=records[-1]["ev"]):
                records = [{**record, "ts": str(i)} for i, record in enumerate(records)]
                self.assertTrue(all(not red.signal_ts for red in reds.reds(records[:-1])))
                red, = reds.reds(records)
                self.assertEqual((red.state, red.signal_ts), ("signal", records[-1]["ts"]))
                records += [event(reds.CLOSED, red="red-1", reason="recovered") | {"ts": "later"}]
                red, = reds.reds(records)
                self.assertEqual((red.state, red.since, red.signal_ts),
                                 ("closed", "later", records[-2]["ts"]))

    def test_closed_is_terminal_preserves_settlement_and_opening_order(self):
        events = repair_events() + [opened(red="red-2"),
                 event(reds.CLOSED, red="red-1", reason="absent", tip="green"),
                 event("branch.landed", task="demo/red-1"), *foreman_run()]
        first, second = reds.reds(events)
        self.assertEqual((first.id, first.state, first.close_reason, first.close_tip, first.verdict),
                         ("red-1", "closed", "absent", "green", "fix"))
        self.assertEqual(second.id, "red-2")

    def test_close_while_foreman_runs_retains_its_later_report_without_creating_task(self):
        events = [opened(), *foreman_run(), event(reds.CLOSED, red="red-1", reason="recovered", tip="green")]
        for outcome in ("done", "failed"):
            with self.subTest(outcome=outcome):
                completed = events + [foreman_run(outcome)[-1], settled()]
                red, = reds.reds(completed)
                self.assertEqual((red.state, red.report, red.verdict), ("closed", "/report.md", ""))
                self.assertEqual(reds.repair_tasks(PLAN, completed, {}), {})

    def test_foreman_runs_only_once_after_done_or_fallback(self):
        for outcome in ("done", "failed"):
            events = [opened(), *foreman_run(outcome),
                      {**foreman_run()[0], "run": "demo/red-1/foreman-2"}]
            self.assertEqual(reds.reds(events)[0].foreman, FOREMAN)

    def test_covering_fault_free_run_still_red_is_unfixed(self):
        events = repair_events() + [event("branch.landed", task="demo/red-1")]
        for run in (checked(branches=["other/task"]),
                    checked(branches=["demo/red-1"], faults=["default: offline"])):
            self.assertEqual(reds.reds(events + [run])[0].state, "landed")
        events += [checked(branches=["demo/red-1"])]
        red, = reds.reds(events)
        self.assertEqual(red.state, "signal")
        self.assertEqual(red.signal_reason, "unfixed: demo/red-1 landed, still red at tip")
        self.assertEqual(red.covered, "tip")
        self.assertEqual(list(reds.repair_tasks(PLAN, events, {})), ["demo/red-1"])
        clear = event("signal.cleared", signal="red-1", text="seen", by="user")
        self.assertEqual(reds.closures(events + [clear]), [("red-1", "cleared", "")])

    def test_rebased_repair_branch_covers_and_unfixes(self):
        events = repair_events() + [event("branch.landed", task="demo/red-1"),
                                   checked(tip="rebased", branches=["demo/red-1-r2"])]
        red, = reds.reds(events)
        self.assertEqual((red.state, red.covered, red.signal_reason),
                         ("signal", "rebased", "unfixed: demo/red-1 landed, still red at rebased"))

    def test_starved_covering_run_keeps_coverage_for_a_later_run(self):
        events = repair_events() + [event("branch.landed", task="demo/red-1")]
        faulted = checked((), tip="faulted", branches=["demo/red-1-r1"], faults=["pair: offline"])
        self.assertEqual(reds.reds(events + [faulted])[0].covered, "")
        events += [faulted, checked((), tip="cover", branches=["demo/red-1-r2"], starved=1)]
        red, = reds.reds(events)
        self.assertEqual((red.state, red.covered), ("landed", "cover"))
        self.assertEqual(reds.closures(events), [])
        self.assertEqual(reds.reds(events + [checked(tip="partial", faults=["pair: offline"])])[0].state,
                         "landed")
        events += [checked(tip="still-red", branches=["other/task"])]
        red, = reds.reds(events)
        self.assertEqual((red.state, red.covered, red.signal_reason),
                         ("signal", "cover", "unfixed: demo/red-1 landed, still red at still-red"))

    def test_covering_run_with_only_unobserved_results_can_recover_later(self):
        events = repair_events() + [event("branch.landed", task="demo/red-1"),
                  checked((), tip="cover", branches=["demo/red-1-r2"], unobserved=1),
                  checked((), tip="green", branches=[])]
        self.assertEqual(reds.reds(events)[0].covered, "cover")
        self.assertEqual(reds.closures(events), [("red-1", "absent", "green")])

    def test_fold_routes_twenty_thousand_events_for_one_hundred_reds_quickly(self):
        events = []
        for n in range(100):
            identifier, task = f"red-{n + 1}", f"demo/red-{n + 1}"
            run_id = f"{task}/foreman-1"
            events += [opened(red=identifier),
                       event("run.started", red=identifier, tip="tip", run=run_id,
                             task=f"{task}/foreman", kind=foreman.KIND),
                       event("run.ended", run=run_id, outcome="failed")]
            if n % 2:
                events += [event(reds.CLOSED, red=identifier, reason="recovered", tip="green")]
            else:
                events += [event("branch.landed", task=task)]
        unrelated = [event("note", text="unrelated"),
                     event("run.started", run="other/a-1", task="other/a", kind="implement"),
                     event("run.ended", run="other/a-1", outcome="done"),
                     event("branch.landed", task="other/a")]
        events += [unrelated[n % len(unrelated)] for n in range(20000 - len(events))]
        with patch.object(reds, "_advance", wraps=reds._advance) as advance:
            folded = reds.reds(events)
        self.assertEqual(advance.call_count, 300)
        self.assertEqual(len(folded), 100)
        self.assertEqual([red.state for red in folded], ["landed", "closed"] * 50)



class TierRedsClosingTest(unittest.TestCase):
    def test_recovered_from_any_later_tip_closes_and_logs_once(self):
        events = [event(reds.RECOVERED, key=KEY, tip="before"), opened(),
                  event(reds.RECOVERED, key=KEY, tip="green")]
        self.assertEqual(reds.closures(events), [("red-1", "recovered", "green")])
        self.assertEqual(reds.closures(events[:2]), [])
        with tmp_home() as home:
            appended = reds.close_reds(events, log_path=home / "events")
            self.assertEqual(reds.reds(events + appended)[0].state, "closed")
            self.assertEqual(reds.close_reds(events + appended, log_path=home / "events"), [])
            self.assertEqual(log.read(home / "events"), appended)

    def test_absent_requires_reds_list_no_faults_and_nothing_starved_or_unobserved(self):
        for run in (event(reds.TIERS_RUN, tip="old"), checked((), faults=["live: offline"]),
                    checked((), wall_starved=True), checked((), starved=1),
                    checked((), unobserved=1), checked((), starved=None),
                    checked((), unobserved=None),
                    event(reds.TIERS_RUN, tip="old", reds=[], unobserved=0),
                    event(reds.TIERS_RUN, tip="old", reds=[], starved=0)):
            with self.subTest(run=run):
                self.assertEqual(reds.closures([opened(), run]), [])
        self.assertEqual(reds.closures([opened(), checked((), tip="gone")]), [("red-1", "absent", "gone")])

    def test_every_key_must_close_and_last_key_supplies_reason_tip(self):
        events = [opened(keys=["a", "b"]), event(reds.RECOVERED, key="a", tip="green-a")]
        self.assertEqual(reds.closures(events), [])
        self.assertEqual(reds.closures(events + [event(reds.RECOVERED, key="b", tip="green-b")]),
                         [("red-1", "recovered", "green-b")])
        self.assertEqual(reds.closures(events + [checked((), tip="gone")]), [("red-1", "absent", "gone")])

    def test_clear_closes_signal_only_and_all_keys_at_once(self):
        clear = event("signal.cleared", signal="red-1", text="seen", by="user")
        self.assertEqual(reds.closures([opened(), clear]), [])
        self.assertEqual(reds.closures([opened(route="signal", reason="no fab task among the suspects",
                                              keys=["a", "b"]), clear]), [("red-1", "cleared", "")])
        self.assertEqual(reds.closures([opened(), *foreman_run("done"), settled("left"), clear]),
                         [("red-1", "cleared", "")])

    def test_clear_before_signal_does_not_close_even_with_equal_timestamps(self):
        clear = event("signal.cleared", signal="red-1")
        events = [opened(), *foreman_run("done"), clear, settled("left")]
        self.assertEqual(reds.closures(events), [])
        self.assertEqual(reds.closures(events + [clear]), [("red-1", "cleared", "")])

    def test_partial_closures_are_remembered_and_last_key_uses_log_order(self):
        events = [opened(keys=["a", "b"]), checked(("a",), tip="b-absent"),
                  event(reds.RECOVERED, key="b", tip="duplicate-b"),
                  event(reds.RECOVERED, key="a", tip="a-recovered")]
        self.assertEqual(reds.closures(events), [("red-1", "recovered", "a-recovered")])

    def test_malformed_opening_does_not_start_a_future_reds_closure(self):
        events = [event(reds.OPENED, red="red-1"), checked((), tip="before"), opened()]
        self.assertEqual(reds.closures(events), [])

    def test_recovery_before_open_or_other_red_clear_cannot_close(self):
        self.assertEqual(reds.closures([event(reds.RECOVERED, key=KEY, tip="before"), opened(),
                                       event("signal.cleared", signal="red-2")]), [])


class TierRedsTaskTest(unittest.TestCase):
    def test_refusal_fix_folds_into_the_red_task_body(self):
        events = repair_events() + [event("refusal.settled", task="demo/red-1", verdict="fix",
                                         section="## Repair (refusal)\n\nFix its regression test.\n"),
                                   event("refusal.settled", task="other/red-1", verdict="fix", section="foreign")]
        body = reds.repair_tasks(PLAN, events, {})["demo/red-1"].body
        self.assertIn("## Repair (refusal)\n\nFix its regression test.\n", body)
        self.assertNotIn("foreign", body)

    def test_fix_makes_specless_task_with_evidence_section_owner_and_acceptance(self):
        task, = reds.repair_tasks(PLAN, repair_events(), {"red-1": "confirmed red"}).values()
        self.assertEqual((task.id, task.kind, task.part, task.repo, task.needs, task.files,
                          task.effort, task.minutes, task.path),
                         ("demo/red-1", "red", "after-landing", "fabrig", (), ("**",), "high", 20, ""))
        for fragment in ("# Repair a red after landing (red-1)", "`tip` (main)", "demo/a",
                         "Owner: demo/a", "confirmed red", "## Repair", "Reproduce first",
                         "lowest tier", "default", "heavy", "every red test", "precheck --onto origin/main",
                         "live pair", "logins", "next after-landing run"):
            self.assertIn(fragment, task.body)
        self.assertEqual(reds.repair_tasks(replace(PLAN, draft="other"), repair_events(), {}), {})

    def test_none_creates_task_without_a_section(self):
        events = [opened(), *foreman_run("done"), settled("none", owner="", section="")]
        body = reds.repair_tasks(PLAN, events, {})["demo/red-1"].body
        self.assertNotIn("## Repair", body)
        self.assertIn("(evidence unreadable:", body)

    def test_closing_before_first_task_run_drops_only_unstarted_task(self):
        close = event(reds.CLOSED, red="red-1", reason="recovered", tip="green")
        start = event("run.started", task="demo/red-1", kind="implement", run="demo/red-1-1")
        self.assertEqual(reds.repair_tasks(PLAN, repair_events() + [close], {}), {})
        self.assertEqual(reds.repair_tasks(PLAN, repair_events() + [close, start], {}), {})
        self.assertEqual(len(reds.repair_tasks(PLAN, repair_events() + [start, close], {})), 1)

    def test_answers_fold_in_log_order_and_reading_variant_marks_unreadable(self):
        events = repair_events() + [event("question.answered", task="demo/red-1", answer="First."),
                  event("question.answered", task="other/red-1", answer="Foreign."),
                  event("question.answered", task="demo/red-1", answer="Second.")]
        with tmp_home():
            body = reds.tasks(PLAN, events)["demo/red-1"].body
            self.assertIn("(evidence unreadable:", body)
            self.assertTrue(body.endswith("## Answers\n\n- First.\n- Second.\n"))
            self.assertNotIn("Foreign.", body)
            atomic.write(reds.evidence_path("red-1"), "evidence from disk")
            self.assertIn("evidence from disk", reds.tasks(PLAN, events)["demo/red-1"].body)

    def test_answers_for_several_reds_keep_their_own_log_order(self):
        second = "demo/red-2/foreman-1"
        events = repair_events() + [opened(red="red-2"),
                  event("run.started", run=second, task="demo/red-2/foreman", kind=foreman.KIND,
                        red="red-2", tip="tip"), event("run.ended", run=second, outcome="done"),
                  settled(red="red-2", run=second)]
        events += [event("question.answered", task=task, answer=answer) for task, answer in
                   (("demo/red-1", "First."), ("demo/red-2", "Second."),
                    ("demo/red-1", "Third."), ("demo/red-2", "Fourth."))]
        tasks = reds.repair_tasks(PLAN, events, {})
        self.assertTrue(tasks["demo/red-1"].body.endswith("## Answers\n\n- First.\n- Third.\n"))
        self.assertTrue(tasks["demo/red-2"].body.endswith("## Answers\n\n- Second.\n- Fourth.\n"))

    def test_prefolded_snapshot_is_reused_by_all_decisions_and_reading_tasks(self):
        events = repair_events() + [tier("new", branches=("demo/red-1-r2",)),
                  event("question.answered", task="demo/red-1", answer="Use the unit test."),
                  checked((KEY, "new"))]
        folded = reds.reds(events)
        with tmp_home(), patch.object(reds, "reds", side_effect=AssertionError("folded again")):
            owners = reds.owners([(PLAN, {TASK.id: TASK})], events, folded=folded)
            self.assertEqual(owners["demo/red-1-r2"], "demo/red-1")
            group, = reds.openings(events, owners, folded=folded)
            self.assertEqual(group.tasks, ("demo/red-1",))
            self.assertEqual(reds.closures(events, folded=folded), [])
            task, = reds.repair_tasks(PLAN, events, {}, folded=folded).values()
            self.assertIn("Use the unit test.", task.body)
            self.assertIn("Use the unit test.", reds.tasks(PLAN, events, folded=folded)[task.id].body)


class TierRedsRemedyTest(unittest.TestCase):
    def red(self):
        return reds.reds([opened(), *foreman_run("done")])[0]

    def test_fix_reason_owner_and_section(self):
        actual = reds.remedy(self.red(), "Done: fix: fix test\nOwner: demo/a\nwhere  \n\n")
        self.assertEqual(actual, ("fix", "fix test", "demo/a",
                         f"## Repair (2026-11-01, after landing red-1, foreman {FOREMAN})\n\nfix test\nwhere\n"))

    def test_optional_owner_invalid_owner_and_thirty_lines(self):
        for owner in ("", "Owner: foreign/task\n", "Owner: demo/no-such-task\n"):
            report = "Done : fix : fix test\n" + owner + "\n".join(f"line {n}  " for n in range(35))
            verdict, reason, assigned, section = reds.remedy(self.red(), report, day="today")
            self.assertEqual((verdict, reason, assigned), ("fix", "fix test", ""))
            self.assertIn("(today, after landing", section)
            self.assertTrue(section.endswith("line 29\n"))
            self.assertNotIn("Owner:", section)

    def test_suspect_trunk_owner_must_be_a_loaded_plan_task(self):
        red = replace(self.red(), tasks=("demo",), suspects=("demo/integration",))
        report = "Done: fix: fix test\nOwner: demo/a\nwhere"
        self.assertEqual(reds.remedy(red, report, plan_tasks={TASK.id: TASK})[2], TASK.id)
        self.assertEqual(reds.remedy(red, report)[2], "")
        self.assertEqual(reds.remedy(red, report.replace("demo/a", "demo/missing"),
                                    plan_tasks={TASK.id: TASK})[2], "")

    def test_retry_is_left_and_bad_forms_are_none(self):
        self.assertEqual(reds.remedy(self.red(), "\n Done : retry : login expired\nevidence"),
                         ("left", "login expired", "", ""))
        for report in ("Failed: cannot say", "", "Done: fix:", "Done: retry: ", "Question: what",
                       "Done: accept: yes", "x" * 200, "bad first\nDone: fix: next"):
            with self.subTest(report=report):
                first = next((line.strip() for line in report.splitlines() if line.strip()), "")
                self.assertEqual(reds.remedy(self.red(), report), ("none", "no verdict: " + first[:120], "", ""))

    def test_acting_settlement_logs_only_and_tasks_quote_section(self):
        events = [opened(), *foreman_run("done")]
        with tmp_home() as home:
            actual = reds.settle(self.red(), "Done: fix: fix test\nOwner: demo/a\nwhere", log_path=home / "events")
            self.assertEqual(log.read(home / "events"), [actual])
            self.assertIn(actual["section"], reds.tasks(PLAN, events + [actual])["demo/red-1"].body)
            self.assertEqual(log.read(), [])


class TierRedsForemanTest(unittest.TestCase):
    def test_brief_sections_and_each_suspect_kind(self):
        red = reds.reds([opened(suspects=["demo/a-r2", "other/integration", "manual/x"],
                               tasks=["demo/a", "other"])])[0]
        other = replace(TASK, id="other/b", files=("fab/b.py",))
        text = reds.brief(red, run_id=FOREMAN, report="/report", evidence="confirmed red",
                          plan_tasks={TASK.id: TASK, other.id: other}, specs={TASK.id: "whole spec"}, role="role\n")
        headings = ("role", "# The red", "# The evidence", "# The suspects' specs")
        self.assertEqual(sorted(headings, key=text.index), list(headings))
        for fragment in ("- Run: " + FOREMAN, "red-1 at `tip` on main", "demo/a-r2: task demo/a, spec `a.md`",
                         "other/integration: the trunk of plan other", "manual/x: hand-pushed, no fab task",
                         "other/b: fab/b.py", "whole spec", "confirmed red", "- Report: write it to `/report`",
                         "Your checkout is fabrig at tip, read-only."):
            self.assertIn(fragment, text)
        self.assertTrue(text.endswith("\n"))

    def test_red_task_suspect_has_no_spec_and_hand_pushed_branches_are_exposed(self):
        red, = reds.reds([opened(suspects=["demo/red-2-r1", "demo/integration", "manual/x"],
                                tasks=["demo/red-2", "demo"])])
        self.assertEqual(red.hand_pushed, ("manual/x",))
        repair = replace(TASK, id="demo/red-2", path="", kind="red")
        text = reds.brief(red, run_id=FOREMAN, report="/report", evidence="red", role="role",
                          plan_tasks={repair.id: repair}, specs={repair.id: repair.body})
        self.assertIn("demo/red-2-r1: task demo/red-2, (no spec)", text)
        self.assertNotIn("spec ``", text)
        self.assertIn("manual/x: hand-pushed, no fab task", text)

    def test_brief_quotes_newest_five_specs_then_only_ids(self):
        tasks = {f"demo/t{n}": replace(TASK, id=f"demo/t{n}") for n in range(7)}
        red = reds.reds([opened(suspects=list(tasks), tasks=list(tasks))])[0]
        specs = {identifier: f"SPEC {identifier}" for identifier in tasks}
        text = reds.brief(red, run_id=FOREMAN, report="/report", evidence="red", plan_tasks=tasks, specs=specs, role="role")
        self.assertIn("## demo/t0", text)
        self.assertNotIn("SPEC demo/t0", text)
        self.assertNotIn("SPEC demo/t1", text)
        self.assertEqual(text.count("SPEC "), 5)
        self.assertLess(text.index("SPEC demo/t6"), text.index("SPEC demo/t2"))

    def test_start_detaches_at_tip_uses_foreman_numbering_and_logs_red_fields(self):
        def answer(call):
            if command(call)[:3] == ["fab", "codex", "start"]:
                return Result(0, "codex-red /state/red\n")
            return Result(0)
        with tmp_home() as home:
            task = replace(TASK, path=str(home / "task.md"))
            atomic.write(home / "task.md", "the suspect spec")
            atomic.write(reds.evidence_path("red-1"), "the evidence")
            red, = reds.reds([opened()])
            fake, path = FakeRunner().on(["ssh"], answer), home / "events"
            previous = [event("run.started", task=foreman.task_field(red.task), run="old")]
            run_id = reds.start(red, BUILDER, previous, plan_tasks={task.id: task}, sh=fake, log_path=path)
            self.assertEqual(run_id, "demo/red-1/foreman-2")
            started, = log.read(path)
            self.assertEqual((started["task"], started["kind"], started["red"], started["tip"], started["base"]),
                             ("demo/red-1/foreman", "foreman", "red-1", "tip", "tip"))
            self.assertNotIn("asked", started)
            self.assertNotIn("refused", started)
            commands = [command(call) for call in fake.calls]
            self.assertTrue(any("--detach" in argv and argv[-1] == "tip" for argv in commands))
            launcher = next(argv for argv in commands if argv[:3] == ["fab", "codex", "start"])
            self.assertIn("--read-only", launcher)
            self.assertEqual(launcher[launcher.index("--effort") + 1], foreman.EFFORT)
            brief = (log.home() / "runs" / run_id / "brief.md").read_text()
            self.assertIn("the suspect spec", brief)
            self.assertIn("the evidence", brief)
            self.assertIn("the suspects'", brief)
            self.assertEqual(log.read(), [])

    def test_unreadable_evidence_quoted_but_unreadable_spec_starts_nothing(self):
        red, = reds.reds([opened()])
        with tmp_home() as home:
            fake = FakeRunner()
            with self.assertRaises(OSError):
                reds.start(red, BUILDER, [], plan_tasks={TASK.id: replace(TASK, path=str(home / "missing"))}, sh=fake)
            self.assertEqual(fake.calls, [])
            with patch.object(reds.runs, "launch_detached", return_value=FOREMAN) as launch:
                reds.start(red, BUILDER, [], plan_tasks={TASK.id: TASK}, specs={TASK.id: "spec"}, sh=fake)
                self.assertIn("(evidence unreadable:", launch.call_args.kwargs["brief"])


if __name__ == "__main__":
    unittest.main()
