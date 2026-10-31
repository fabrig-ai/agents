"""The flow's event fold and builder measurements (docs/design/fab.md, 13.2 and 8)."""

import unittest
from copy import deepcopy

from fab import flow
from fab.heavy import EX_TEMPFAIL
from fab.hosts import Host
from fab.sh import Failed, Result, ssh
from fab.tests.support import FakeRunner, tmp_home


NOW = "2026-10-30T14:00:00.000Z"
QUIET = "0.20 0.30 0.40 1/100 1234\n2\n"


def event(kind, task="a", **fields):
    return {"ev": kind, "task": "draft/" + task, **fields}


def started(task="a", run=None):
    return event("run.started", task, run=run or "draft/" + task + "-1")


def ended(task="a", run=None, outcome="done"):
    return event("run.ended", task, run=run or "draft/" + task + "-1", outcome=outcome)


class TargetTest(unittest.TestCase):
    def test_start_with_no_events(self):
        self.assertEqual(flow.target("draft", iter(())), flow.START)

    def test_fresh_plan_starts_at_its_places(self):
        for places in (1, 3, 8):
            with self.subTest(places=places):
                self.assertEqual(flow.target("draft", iter(()), start=places), places)
        self.assertEqual(flow.target("draft", [], start=0), flow.FLOOR)

    def test_two_rejections_halve_eight_to_two(self):
        events = [event("branch.rejected"), event("branch.rejected", "b")]
        self.assertEqual(flow.target("draft", events[:1], start=8), 4)
        self.assertEqual(flow.target("draft", events, start=8), 2)
        self.assertEqual(flow.target("draft", events[:1], start=9), 4)

    def test_infra_halves_three_to_one_and_holds_at_floor(self):
        events = [ended("missing", outcome="infra")]
        self.assertEqual(flow.target("draft", events, start=3), 1)
        for start in (0, 1, 3):
            with self.subTest(start=start):
                self.assertEqual(flow.target("draft", events * 5, start=start), flow.FLOOR)

    def test_first_landing_grows_from_plan_places_only_with_full_window(self):
        events = [started(), started("b"), started("c"), ended(), event("branch.landed")]
        self.assertEqual(flow.target("draft", events, start=3), 4)
        self.assertEqual(flow.target("draft", events, start=4), 4)

    def test_first_landing_grows_only_if_full_at_run_end(self):
        full = [started(), started("b"), ended(), ended("b"), event("branch.landed")]
        self.assertEqual(flow.target("draft", full), flow.START + 1)
        # Filling the window after the end cannot qualify that landing.
        unused = [started(), ended(), started("b"), started("c"), event("branch.landed")]
        self.assertEqual(flow.target("draft", unused), flow.START)

    def test_each_qualifying_landing_grows_the_current_target(self):
        events = [started(), started("b"), ended(), event("branch.landed"),
                  started("c"), started("d"), ended("b"), event("branch.landed", "b")]
        self.assertEqual(flow.target("draft", events), flow.START + 2)
        events.extend([ended("c"), event("branch.landed", "c")])
        self.assertEqual(flow.target("draft", events), flow.START + 2)

    def test_second_attempt_does_not_grow(self):
        events = [started(), started("b"), ended(), started(run="draft/a-2"),
                  ended(run="draft/a-2"), event("branch.landed")]
        self.assertEqual(flow.target("draft", events), flow.START)

    def test_rejected_task_never_grows(self):
        events = [event("branch.rejected"), started(), ended(), event("branch.landed")]
        self.assertEqual(flow.target("draft", events), flow.FLOOR)

    def test_repeated_landing_is_ignored_even_when_first_could_not_grow(self):
        events = [started(), started("b"), ended(), event("branch.landed")]
        self.assertEqual(flow.target("draft", events + [event("branch.landed")]), flow.START + 1)
        events = [event("branch.landed"), started(), started("b"), ended(), event("branch.landed")]
        self.assertEqual(flow.target("draft", events), flow.START)

    def test_rejections_and_infra_halve_after_growth_and_hold_at_floor(self):
        full = [started(), started("b"), ended(), event("branch.landed")]
        for drop in (event("branch.rejected", "b"), ended("missing", outcome="infra")):
            with self.subTest(drop=drop):
                self.assertEqual(flow.target("draft", full + [drop]), flow.FLOOR)
                self.assertEqual(flow.target("draft", full + [drop] * 5), flow.FLOOR)

    def test_unmatched_end_does_not_count_as_in_flight_or_qualify_landing(self):
        events = [ended("missing"), started(), ended(), event("branch.landed")]
        self.assertEqual(flow.target("draft", events), flow.START)
        events = [started(), started("b"), ended(run="unknown"), event("branch.landed")]
        self.assertEqual(flow.target("draft", events), flow.START)

    def test_other_drafts_unknown_types_and_missing_fields_are_skipped(self):
        ignored = [{"ev": "branch.rejected", "task": name} for name in ("draft", "drafted/a", "other/a")]
        ignored += [{"ev": "run.started", "task": "other/a", "run": "other/a-1"},
                    {"ev": "run.ended", "task": "other/a", "run": "other/a-1", "outcome": "infra"},
                    {"ev": "branch.landed", "task": "other/a"}, {"ev": "branch.rejected"}, {"task": "draft/a"}, {},
                    event("run.started"), event("run.ended", outcome="infra"),
                    event("unknown"), {"ev": "run.started", "task": None, "run": "bad"}]
        self.assertEqual(flow.target("draft", ignored), flow.START)
        events = [started(), ended(), *ignored, event("branch.landed")]
        self.assertEqual(flow.target("draft", events), flow.START)

    def test_pure_repeatable_fold_accepts_a_generator(self):
        events = [started(), started("b"), ended(), event("branch.landed")]
        before = deepcopy(events)
        self.assertEqual(flow.target("draft", iter(events)), flow.target("draft", events))
        self.assertEqual(events, before)


class CalmTest(unittest.TestCase):
    def test_calm_without_heavy_records(self):
        self.assertTrue(flow.calm(QUIET, NOW))
        self.assertTrue(flow.calm(QUIET + '{"ev":"heavy","ts":"2026-10-30T13:45:00.000Z",'
                                  '"lane_wait":30,"disk_wait":60,"code":0}\n', NOW))

    def test_five_minute_load_per_cpu_strictly_below_threshold(self):
        self.assertTrue(flow.calm("9.0 1.39 9.0\n2\n", NOW))
        self.assertFalse(flow.calm("0.0 1.4 0.0\n2\n", NOW))
        self.assertFalse(flow.calm("0.0 1.41 0.0\n2\n", NOW))

    def test_lane_and_disk_waits_summed_across_records_in_minutes(self):
        records = ('{"ev":"heavy","ts":"2026-10-30T13:45:00.000Z","lane_wait":120}\n'
                   '{"ev":"heavy","ts":"2026-10-30T13:46:00.000Z","disk_wait":180}\n')
        self.assertFalse(flow.calm(QUIET + records, NOW))
        self.assertTrue(flow.calm(QUIET + records.replace('180', '179'), NOW))
        self.assertFalse(flow.calm(QUIET + records.replace('180', '181'), NOW))

    def test_disk_refusal_blocks_even_without_waits(self):
        refusal = ('{"ev":"heavy","ts":"2026-10-30T13:45:00.000Z","code":'
                   + str(EX_TEMPFAIL) + '}\n')
        self.assertFalse(flow.calm(QUIET + refusal, NOW))

    def test_window_includes_start_and_excludes_end_and_old_records(self):
        refusal = '{"ev":"heavy","ts":"2026-10-30T13:29:59.999Z","code":75}\n'
        self.assertTrue(flow.calm(QUIET + refusal, NOW))
        self.assertFalse(flow.calm(QUIET + refusal.replace('13:29:59.999', '13:30:00.000'), NOW))
        self.assertTrue(flow.calm(QUIET + refusal.replace('13:29:59.999', '14:00:00.000'), NOW))

    def test_torn_non_object_missing_ts_and_other_events_skipped(self):
        records = ('{"ev":"heavy",\n[]\nnull\n{"ev":"heavy"}\n{"ts":123}\n'
                   '{"ev":"note","ts":"2026-10-30T13:45:00.000Z","code":75}\n')
        self.assertTrue(flow.calm(QUIET + records, NOW))

    def test_bad_load_count_or_timestamp_never_raises(self):
        for output in ("", "0.0", "0.1 bad 0.2\n2", "0.1 0.2 0.3\nbad", "0 0 0\n0",
                       "0 0 0\n-1", "0 0 0\n1.5", "0 nan 0\n2", "0 inf 0\n2"):
            with self.subTest(output=output):
                self.assertFalse(flow.calm(output, NOW))
        self.assertFalse(flow.calm(QUIET, "not a timestamp"))
        self.assertFalse(flow.calm(QUIET + '{"ev":"heavy","ts":"2026-10-30T13:45:00.000Z",'
                                             '"lane_wait":"bad"}\n', NOW))


class MeasureTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(tmp_home())
        self.hosts = {"z": Host("z", "bob@z", ("builder",)),
                      "gate": Host("gate", "gate@gate", ("gate",)),
                      "a": Host("a", "alice@a", ("builder", "dispatcher"))}
        self.commands = [ssh("alice@a", flow.PROBE + ["/home/alice/src/fabrig/fab/heavy.jsonl"]),
                         ssh("bob@z", flow.PROBE + ["/home/bob/src/fabrig/fab/heavy.jsonl"])]

    def test_builders_in_name_order_one_exact_probe_each(self):
        fake = FakeRunner().on(self.commands[0], Result(0, QUIET)).on(self.commands[1], Result(0, QUIET))
        result = flow.measure(self.hosts, NOW, sh=fake)
        self.assertEqual(list(result), ["a", "z"])
        self.assertEqual(result, {"a": True, "z": True})
        self.assertEqual(fake.argvs(), self.commands)

    def test_failed_ssh_false_while_next_builder_is_measured(self):
        fake = FakeRunner().on(self.commands[0], Result(255, err="offline"))
        fake.on(self.commands[1], Result(0, QUIET))
        self.assertEqual(flow.measure(self.hosts, NOW, sh=fake), {"a": False, "z": True})
        self.assertEqual(fake.argvs(), self.commands)

    def test_remote_exceptions_do_not_stop_the_next_builder(self):
        for error in (OSError("offline"), Failed(self.commands[0], Result(255))):
            with self.subTest(error=error):
                def fail(call):
                    raise error
                fake = FakeRunner().on(self.commands[0], fail).on(self.commands[1], Result(0, QUIET))
                self.assertEqual(flow.measure(self.hosts, NOW, sh=fake), {"a": False, "z": True})
                self.assertEqual(fake.argvs(), self.commands)

    def test_no_builders_measures_nothing(self):
        fake = FakeRunner()
        self.assertEqual(flow.measure({"gate": self.hosts["gate"]}, NOW, sh=fake), {})
        self.assertEqual(fake.calls, [])


class ConflictRefusalTest(unittest.TestCase):
    def test_a_conflict_refusal_leaves_the_target(self):
        start = 8
        for step, expected in (("rebase", start), ("merge", start), ("test", start // 2)):
            events = [{"ev": "branch.rejected", "task": "d/a", "step": step, "ts": "t"}]
            self.assertEqual(flow.target("d", events, start=start), expected, step)
