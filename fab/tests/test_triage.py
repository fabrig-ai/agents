"""Pure triage rules over temporary-home log fixtures (docs/design/fab.md, 4; qa.md, 2)."""

import copy
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from unittest.mock import patch

from fab import atomic, calls, channel, dispatch, findings as qa, log, triage, wake
from fab.plan import load_plan
from fab.sh import Result
from fab.tests.ladder_plans import write_ladder
from fab.tests.qa_records import (
    STAMP, finding_merged, finding_raised, finding_triaged, walk_ended, walk_started,
)
from fab.tests.support import FakeRunner, tmp_home


def _stamp(minutes=0, seconds=0):
    return f"2026-11-01T{minutes // 60:02}:{minutes % 60:02}:{seconds:02}.000Z"


def _walk(number=1, *, verdict="pass", minutes=0, **fields):
    identifier, walk = f"finding-{number}", f"walk-{number}"
    return [walk_started(walk, "b0", draft=fields.get("draft", "ladder"), ts=_stamp(minutes)),
            finding_raised(identifier, walk, "b0", ts=_stamp(minutes), **fields),
            walk_ended(walk, verdict, (identifier,), ts=_stamp(minutes))]


def _call(outcome="done", *, call="triage-1", draft="ladder", minutes=0, role="triage"):
    fields = dict(call=call, role=role, subject=triage.subject(draft), ts=_stamp(minutes))
    return [log.record("call.started", **fields), log.record("call.ended", outcome=outcome, **fields)]


def _answer(*, subject="ladder/triage", minutes=0):
    return log.record("call.answered", ts=_stamp(minutes), subject=subject, call="triage-1",
                      by="user", question="What next?", answer="Go ahead")


def _logged(records, minutes=0):
    return [log.record(kind, ts=_stamp(minutes), **fields) for kind, fields in records]


def _ready(number, render="render", *, draft="ladder"):
    branch = f"ladder/{draft}/backlog-{number}"
    return log.record("branch.ready", ts=STAMP, task=branch, branch=branch, tip="tip", render=render)


def _rejected(number, *, draft="ladder"):
    branch = f"ladder/{draft}/backlog-{number}"
    return log.record("branch.rejected", ts=STAMP, task=branch, branch=branch, tip="tip",
                      step="gate", log="queue.log")


def _landed(task):
    return log.record("branch.landed", ts=STAMP, task=task, branch=task, tip="tip", main="main", into="")


class TriageTest(unittest.TestCase):
    def setUp(self):
        home = self.enterContext(tmp_home())
        self.plan = load_plan(write_ladder(home / "plan") / "plan.toml")


class TriageDueTest(TriageTest):
    def test_constants_and_subject_match_the_call_and_answerer(self):
        self.assertEqual(triage.ROLE, "triage")
        self.assertEqual((triage.AT, triage.AFTER), (4, 30))
        self.assertEqual((triage.AT, triage.AFTER), (dispatch.ANSWER_AT, dispatch.ANSWER_AFTER))
        self.assertEqual(triage.subject("ladder"), "ladder/triage")

    def test_failed_void_and_blocking_findings_are_due_immediately(self):
        for fields in (dict(verdict="fail"), dict(verdict="void"), dict(blocking=True)):
            with self.subTest(fields=fields):
                self.assertTrue(triage.due(self.plan, _walk(**fields), STAMP))

    def test_pass_waits_for_four_new_or_thirty_minutes(self):
        events = _walk()
        self.assertFalse(triage.due(self.plan, events, _stamp(29, 59)))
        self.assertTrue(triage.due(self.plan, events, _stamp(30)))
        for number in range(2, 5):
            events += _walk(number)
            self.assertEqual(triage.due(self.plan, events, STAMP), number == 4)

    def test_age_starts_at_walk_end_not_raise_and_uses_oldest_new(self):
        events = _walk()
        events[-1]["ts"] = _stamp(20)
        events += _walk(2, minutes=40)
        self.assertFalse(triage.due(self.plan, events, _stamp(49, 59)))
        self.assertTrue(triage.due(self.plan, events, _stamp(50)))

    def test_only_new_findings_of_this_plan_count(self):
        for decision in ("backlog", "drop", "user", "path", "brief"):
            with self.subTest(decision=decision):
                events = _walk(verdict="fail") + [finding_triaged("finding-1", decision)]
                self.assertFalse(triage.due(self.plan, events, _stamp(60)))
        self.assertFalse(triage.due(self.plan, [], _stamp(60)))
        self.assertFalse(triage.due(self.plan, _walk(draft="other", verdict="fail"), _stamp(60)))
        self.assertFalse(triage.due(self.plan, _walk(verdict="fail")[:-1], _stamp(60)))
        events = _walk() + sum((_walk(number, draft="other") for number in range(2, 5)), [])
        self.assertFalse(triage.due(self.plan, events, STAMP))

    def test_flight_and_open_question_block_even_urgent_findings(self):
        events = _walk(verdict="fail")
        self.assertFalse(triage.due(self.plan, events + _call()[:1], _stamp(60)))
        events += _call("question")
        self.assertFalse(triage.due(self.plan, events, _stamp(60)))
        self.assertFalse(triage.due(self.plan, events + [_answer(subject="other/triage")], _stamp(60)))
        self.assertTrue(triage.due(self.plan, events + [_answer()], _stamp(60)))

    def test_question_requires_a_later_answer_in_log_order(self):
        events = _walk(verdict="fail") + [_answer()] + _call("question")
        events += _call(call="later")
        self.assertFalse(triage.due(self.plan, events, _stamp(60)))
        self.assertTrue(triage.due(self.plan, events + [_answer()], _stamp(60)))

    def test_other_calls_do_not_block_and_all_own_flights_must_end(self):
        events = _walk(verdict="fail") + _call("question", draft="other")
        events += _call(role="review")[:1]
        self.assertTrue(triage.due(self.plan, events, STAMP))
        events += _call(call="one")[:1] + _call(call="two")
        self.assertFalse(triage.due(self.plan, events, STAMP))
        events += _call(call="one")[1:]
        self.assertTrue(triage.due(self.plan, events, STAMP))

    def test_failed_call_waits_for_new_finding_or_thirty_minutes_from_end(self):
        events = _walk(verdict="fail") + _call("failed", minutes=10)
        self.assertFalse(triage.due(self.plan, events, _stamp(39, 59)))
        self.assertTrue(triage.due(self.plan, events, _stamp(40)))
        self.assertTrue(triage.due(self.plan, events + _walk(2, minutes=11), _stamp(11)))
        self.assertFalse(triage.due(self.plan, events + _walk(2, draft="other"), _stamp(11)))

    def test_successful_call_replaces_an_earlier_failure_cooldown(self):
        events = _walk(verdict="fail") + _call("failed") + _call(call="two", minutes=1)
        self.assertTrue(triage.due(self.plan, events, _stamp(1)))

    def test_user_answer_restarts_the_new_findings_age(self):
        events = _walk() + [finding_triaged("finding-1", "user", question="Which account?")]
        events += [_answer(subject="ladder/triage/finding-1", minutes=60)]
        self.assertFalse(triage.due(self.plan, events, _stamp(89, 59)))
        self.assertTrue(triage.due(self.plan, events, _stamp(90)))
        events += [_answer(subject="ladder/triage/finding-1", minutes=80)]
        self.assertTrue(triage.due(self.plan, events, _stamp(90)))

    def test_again_and_a_new_raise_restart_age_and_unlock_failed_call(self):
        events = _walk() + [finding_triaged("finding-1", "again", into="finding-9", ts=_stamp(60))]
        self.assertFalse(triage.due(self.plan, events, _stamp(89, 59)))
        self.assertTrue(triage.due(self.plan, events, _stamp(90)))
        events = _walk(1, verdict="fail") + _call("failed", minutes=10)
        events += [finding_triaged("finding-1", "user", question="Which account?"),
                   _answer(subject="ladder/triage/finding-1", minutes=11)]
        self.assertTrue(triage.due(self.plan, events, _stamp(11)))
        events = _walk(2, again="finding-1", minutes=60)
        self.assertFalse(triage.due(self.plan, events, _stamp(89, 59)))
        self.assertTrue(triage.due(self.plan, events, _stamp(90)))

    def test_malformed_records_and_timestamps_do_not_stop_due(self):
        events = _walk() + [{}, {"ev": "call.started", "call": []},
                            {"ev": "call.ended", "role": "triage", "subject": "ladder/triage"},
                            {"ev": "call.answered", "subject": []},
                            {"ev": "finding.triaged", "finding": "finding-1", "decision": "again"}]
        self.assertTrue(triage.due(self.plan, events, _stamp(30)))
        events[2]["ts"] = "not a timestamp"
        self.assertFalse(triage.due(self.plan, events, _stamp(30)))


class TriageDecisionsTest(TriageTest):
    def decide(self, events, text, **kwargs):
        return triage.decisions(self.plan, events + _call(**kwargs), {kwargs.get("call", "triage-1"): text})

    def test_every_report_line_form_has_exact_flat_fields_and_logs_once(self):
        events = sum((_walk(number) for number in range(1, 9)), []) + _call()
        report = """Done: 7 decisions
finding-1: path ctl: The story needs it
finding-2: path forge: Restore access; user: Reinstall the app
finding-3: backlog: After v0.1.0
finding-4: user: Which account?
finding-5: brief b0: The step is wrong
finding-6: merge finding-8: Same cause
finding-7: drop: A machine fault
"""
        records = triage.decisions(self.plan, events, {"triage-1": report})
        expected = [
            ("finding.triaged", dict(finding="finding-1", decision="path", owner="ctl",
                                    reason="The story needs it", question="", into="", call="triage-1")),
            ("finding.triaged", dict(finding="finding-2", decision="path", owner="forge",
                                    reason="Restore access", question="Reinstall the app", into="", call="triage-1")),
            ("finding.triaged", dict(finding="finding-3", decision="backlog", owner="",
                                    reason="After v0.1.0", question="", into="", call="triage-1")),
            ("finding.triaged", dict(finding="finding-4", decision="user", owner="",
                                    reason="", question="Which account?", into="", call="triage-1")),
            ("finding.triaged", dict(finding="finding-5", decision="brief", owner="b0",
                                    reason="", question="The step is wrong", into="", call="triage-1")),
            ("finding.merged", dict(finding="finding-6", into="finding-8", by="triage-1", reason="Same cause")),
            ("finding.triaged", dict(finding="finding-7", decision="drop", owner="",
                                    reason="A machine fault", question="", into="", call="triage-1")),
        ]
        self.assertEqual(records, expected)
        self.assertEqual(triage.decisions(self.plan, events + _logged(records), {"triage-1": report}), [])

    def test_only_done_own_triage_calls_with_available_reports_are_consumed(self):
        for kwargs in (dict(outcome="failed"), dict(outcome="question"), dict(draft="other"),
                       dict(role="review")):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.decide(_walk(), "finding-1: drop: Out of scope", **kwargs), [])
        events = _walk() + _call()
        self.assertEqual(triage.decisions(self.plan, events, {}), [])
        self.assertEqual(len(triage.decisions(self.plan, events, {"triage-1": "finding-1: drop: Out of scope"})), 1)

    def test_any_logged_decision_merge_or_note_consumes_the_call(self):
        for recorded in (finding_triaged("finding-1", "backlog"),
                         finding_merged("finding-2", "finding-1", by="triage-1"),
                         log.record("note", ts=STAMP, call="triage-1", text="triage triage-1: no decisions")):
            with self.subTest(recorded=recorded):
                self.assertEqual(self.decide(_walk() + [recorded], "finding-1: path ctl: Needed"), [])

    def test_prose_only_or_empty_report_logs_one_note_and_repeats_nothing(self):
        for report in ("Done: 0 decisions\nNo decisions today.", "", "finding-1: dance: Unknown"):
            with self.subTest(report=report):
                events = _walk() + _call()
                records = triage.decisions(self.plan, events, {"triage-1": report})
                self.assertEqual(records, [("note", dict(call="triage-1", text="triage triage-1: no decisions"))])
                self.assertEqual(triage.decisions(self.plan, events + _logged(records), {"triage-1": report}), [])

    def test_skips_non_new_foreign_unknown_and_second_lines_but_redecides_backlog(self):
        events = sum((_walk(number) for number in range(1, 5)), []) + _walk(5, draft="other")
        events += [finding_triaged("finding-1", "path", call="old"),
                   finding_triaged("finding-2", "backlog", call="old")]
        records = self.decide(events, """finding-1: drop: Already on path
finding-2: path ctl: Promote
finding-3: drop: First decision
finding-3: backlog: Second decision
finding-5: drop: Foreign
finding-99: drop: Unknown
""")
        self.assertEqual([(kind, fields["finding"], fields["decision"]) for kind, fields in records],
                         [("finding.triaged", "finding-2", "path"), ("finding.triaged", "finding-3", "drop")])

    def test_list_markers_whitespace_and_colons_in_text_are_accepted(self):
        records = self.decide(_walk() + _walk(2),
                              "- finding-1: path ctl: Reason: needed; user: Set login: yes  \n"
                              "* finding-2: backlog: Later: after launch\n")
        self.assertEqual(records[0][1]["reason"], "Reason: needed")
        self.assertEqual(records[0][1]["question"], "Set login: yes")
        self.assertEqual(records[1][1]["reason"], "Later: after launch")

    def test_invalid_syntax_is_ignored_without_using_the_findings_turn(self):
        for line in (" finding-1: drop: Indented", "finding-1: drop:", "finding-1: path: Missing owner",
                     "finding-1: path two owners: Reason",
                     "finding-1: brief two rungs: Reason", "finding-1: merge other: Reason",
                     "finding-1: path ctl: ; user: Install", "finding-1: path ctl: Why; user: ",
                     "finding-1: again finding-2: Not a report decision", "finding-1: dance: Unknown"):
            with self.subTest(line=line):
                records = self.decide(_walk(), line + "\nfinding-1: drop: Valid")
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0][1]["reason"], "Valid")

    def test_merges_resolve_targets_and_skip_self_unknown_foreign_or_again_targets(self):
        events = _walk() + _walk(2) + _walk(3, again="finding-1") + _walk(4, draft="other")
        events += [finding_merged("finding-2", "finding-1")]
        for target in ("finding-3", "finding-99", "finding-4", "finding-1", "finding-2"):
            with self.subTest(target=target):
                records = self.decide(events, f"finding-3: merge {target}: Duplicate\nfinding-3: drop: Valid")
                self.assertEqual(records[0][1]["decision"], "drop")
        records = self.decide(events + _walk(5), "finding-5: merge finding-2: Duplicate")
        self.assertEqual(records, [("finding.merged", dict(finding="finding-5", into="finding-2",
                                                          by="triage-1", reason="Duplicate"))])
        folded = qa.findings(events + _walk(5) + _logged(records))
        self.assertEqual(folded["finding-1"].sightings, ("finding-2", "finding-5"))

    def test_merge_into_landed_target_logs_again_and_is_not_merged(self):
        task = "ladder/finding-1"
        events = _walk() + [finding_triaged("finding-1", "path", call="old"),
                           log.record("run.started", ts=STAMP, run="foreman", task=task + "/foreman", kind="foreman"),
                           log.record("run.ended", ts=STAMP, run="foreman", task=task + "/foreman", outcome="done"),
                           log.record("finding.settled", ts=STAMP, finding="finding-1", run="foreman", verdict="fix",
                                      reason="Repair it", section="Repair"), _landed(task)] + _walk(2)
        self.assertEqual(qa.findings(events)["finding-1"].state, "landed")
        records = self.decide(events, "finding-2: merge finding-1: Still broken")
        self.assertEqual(records, [("finding.triaged", dict(finding="finding-2", decision="again",
                                                          owner="", reason="Still broken", question="",
                                                          into="finding-1", call="triage-1"))])
        folded = qa.findings(events + _logged(records))
        self.assertEqual((folded["finding-1"].state, folded["finding-2"].state), ("unfixed", "new"))
        self.assertEqual(folded["finding-2"].again, "finding-1")
        records = self.decide(events + _logged(records), "finding-2: merge finding-1: Again", call="next")
        self.assertEqual(records[0][0], "note")

    def test_merge_into_dropped_target_logs_again(self):
        events = _walk() + _walk(2) + [finding_triaged("finding-1", "drop", call="old")]
        records = self.decide(events, "finding-2: merge finding-1: Drop was wrong")
        self.assertEqual((records[0][1]["decision"], records[0][1]["into"]), ("again", "finding-1"))

    def test_report_order_prevents_merge_cycles_and_applies_target_decisions(self):
        events = _walk() + _walk(2)
        records = self.decide(events, "finding-1: merge finding-2: Same\nfinding-2: merge finding-1: Cycle")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0][0], "finding.merged")
        records = self.decide(events, "finding-1: drop: Wrong\nfinding-2: merge finding-1: Recurred")
        self.assertEqual([fields["decision"] for kind, fields in records], ["drop", "again"])

    def test_multiple_calls_use_prior_decisions_and_duplicate_ends_are_consumed_once(self):
        events = _walk() + _call() + _call(call="two") + _call(call="two")[1:]
        reports = {"triage-1": "finding-1: backlog: Later", "two": "finding-1: path ctl: Needed"}
        records = triage.decisions(self.plan, events, reports)
        self.assertEqual([fields["decision"] for kind, fields in records], ["backlog", "path"])
        self.assertEqual(triage.decisions(self.plan, events + _logged(records), reports), [])

    def test_malformed_call_and_marker_records_are_skipped(self):
        events = _walk() + [{"ev": "call.ended", "role": "triage", "subject": "ladder/triage",
                             "outcome": "done", "call": []},
                            {"ev": "finding.triaged", "call": []},
                            {"ev": "finding.merged", "by": []}, {"ev": "note", "call": []}]
        records = self.decide(events, "finding-1: drop: Valid")
        self.assertEqual(records[0][1]["reason"], "Valid")

    def test_readers_leave_events_and_reports_unchanged(self):
        events = _walk() + _call()
        reports = {"triage-1": "finding-1: backlog: Later"}
        before = copy.deepcopy((events, reports))
        triage.decisions(self.plan, events, reports)
        triage.due(self.plan, events, _stamp(30))
        triage.backlog_text(self.plan, events)
        triage.backlog_held(self.plan, events, "render")
        self.assertEqual((events, reports), before)


class TriageBacklogTest(TriageTest):
    def test_backlog_renders_every_field_in_raise_order_with_sightings(self):
        first = _walk(8, title="Unicode café", reproduction="First step\nSecond step", expected="Success",
                      seen="Failure", area="forge", severity="high", commit="walked-sha")
        second = _walk(2, title="Second raised")
        events = first[:2] + second + first[2:] + _walk(9) + _walk(3, draft="other")
        events += [finding_triaged("finding-2", "backlog", reason="Second reason"),
                   finding_triaged("finding-8", "backlog", reason="Off the happy path"),
                   finding_triaged("finding-3", "backlog", reason="Foreign"),
                   finding_merged("finding-9", "finding-8")]
        text = triage.backlog_text(self.plan, events)
        for fragment in ("# ladder backlog", "from its log", "Do not edit by hand",
                         "## finding-8: Unicode café", "- Rung: b0", "- Walk: walk-8",
                         "- Backend: chatgpt-forgejo", "- Commit: walked-sha", "- Area: forge",
                         "- Severity: high", "- Sightings: finding-9", "### Reproduction\n\nFirst step\nSecond step",
                         "### Expected\n\nSuccess", "### Seen\n\nFailure", "### Triage reason\n\nOff the happy path"):
            self.assertIn(fragment, text)
        self.assertLess(text.index("## finding-8:"), text.index("## finding-2:"))
        self.assertNotIn("## finding-3:", text)
        self.assertNotIn("## finding-9:", text)
        self.assertTrue(text.endswith("\n"))
        self.assertFalse(text.endswith("\n\n"))

    def test_promoted_and_merged_findings_leave_backlog(self):
        events = sum((_walk(number) for number in range(1, 4)), [])
        events += [finding_triaged(f"finding-{number}", "backlog", call="old") for number in range(1, 4)]
        records = triage.decisions(self.plan, events + _call(), {"triage-1":
                                  "finding-1: path ctl: Needed\nfinding-2: merge finding-3: Same"})
        text = triage.backlog_text(self.plan, events + _logged(records))
        self.assertNotIn("## finding-1:", text)
        self.assertNotIn("## finding-2:", text)
        self.assertIn("## finding-3:", text)
        self.assertIn("- Sightings: finding-2", text)

    def test_empty_backlog_still_has_a_header_and_final_newline(self):
        text = triage.backlog_text(self.plan, _walk())
        self.assertIn("ladder", text)
        self.assertNotIn("## finding-", text)
        self.assertTrue(text.endswith("\n"))

    def test_render_key_is_full_sha256_of_exact_utf8_text(self):
        self.assertEqual(triage.render_key(""), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
        self.assertEqual(triage.render_key("café\n"), "7b49b9e063bd91a4f9252b413261f5557b9c570aa61516989499f64a62dbcdd6")
        self.assertNotEqual(triage.render_key("text"), triage.render_key("text\n"))

    def test_two_rejections_hold_only_their_render_and_return_latest_record(self):
        events = [_ready(1), _rejected(1)]
        self.assertIsNone(triage.backlog_held(self.plan, events, "render"))
        events += [_ready(2), _rejected(2)]
        self.assertIs(triage.backlog_held(self.plan, events, "render"), events[-1])
        self.assertIsNone(triage.backlog_held(self.plan, events, "changed"))
        events += [_ready(3), _rejected(3)]
        self.assertIs(triage.backlog_held(self.plan, events, "render"), events[-1])

    def test_clear_or_any_backlog_landing_resets_rejections_in_log_order(self):
        prefix = [_ready(1), _rejected(1), _ready(2), _rejected(2)]
        clear = log.record("signal.cleared", ts=STAMP, signal="backlog:ladder", by="user", text="Try again")
        for reset in (clear, _landed("ladder/ladder/backlog-9")):
            with self.subTest(reset=reset):
                events = prefix + [reset]
                self.assertIsNone(triage.backlog_held(self.plan, events, "render"))
                events += [_ready(3), _rejected(3)]
                self.assertIsNone(triage.backlog_held(self.plan, events, "render"))
                events += [_ready(4), _rejected(4)]
                self.assertIs(triage.backlog_held(self.plan, events, "render"), events[-1])

    def test_foreign_branches_renders_and_signals_neither_count_nor_reset(self):
        events = [_ready(1), _rejected(1), _ready(1, draft="other"), _rejected(1, draft="other"),
                  _ready(2, "different"), _rejected(2), _rejected(99)]
        self.assertIsNone(triage.backlog_held(self.plan, events, "render"))
        events += [_ready(3), _rejected(3)]
        latest = events[-1]
        events += [_landed("ladder/other/backlog-1"), _landed("ladder/finding-1"),
                   log.record("signal.cleared", ts=STAMP, signal="backlog:other", by="user", text="Clear")]
        self.assertIs(triage.backlog_held(self.plan, events, "render"), latest)

    def test_malformed_records_cannot_hold_or_reset_a_backlog(self):
        events = [_ready(1), _rejected(1)]
        for field in ("ts", "task", "branch", "tip", "step", "log"):
            rejection = _rejected(1)
            rejection[field] = []
            self.assertIsNone(triage.backlog_held(self.plan, events + [rejection], "render"))
        events += [_ready(2), _rejected(2)]
        latest = events[-1]
        events += [{"ev": "signal.cleared", "signal": "backlog:ladder"},
                   {"ev": "branch.landed", "branch": "ladder/ladder/backlog-9"},
                   {"ev": "branch.ready", "branch": [], "render": "render"}]
        self.assertIs(triage.backlog_held(self.plan, events, "render"), latest)
        events = [_ready(1), _rejected(1), {**_ready(2), "tip": []}, _rejected(2)]
        self.assertIsNone(triage.backlog_held(self.plan, events, "render"))

    def test_rejection_needs_a_preceding_ready_for_an_exact_backlog_branch(self):
        events = [_rejected(1), _ready(1), _ready(2), _rejected(2)]
        for branch in ("ladder/ladder/backlog-2/extra", "ladder/ladder/backlog-no", "ladder/ladder/backlog-0"):
            events += [{**_ready(3), "branch": branch}, {**_rejected(3), "branch": branch}]
        self.assertIsNone(triage.backlog_held(self.plan, events, "render"))


class TriageMainTest(TriageTest):
    def test_triage_uses_main_after_own_trunk_lands_and_shares_brief_snapshot(self):
        root = log.home().parent
        fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(root)))
        plan = replace(self.plan, landing="integration")
        for landed in (False, True):
            if landed:
                log.append("branch.landed", task="ladder/integration", queue_ts="001")
            events = log.read()
            with self.subTest(landed=landed), patch.object(triage, "load_plan", return_value=plan), \
                 patch.object(calls, "run", fake), patch.object(triage.walks, "editions", return_value={}), \
                 patch.object(triage.log, "read", return_value=events) as read, \
                 patch.object(triage, "brief", return_value="Triage brief.") as brief, \
                 patch.object(calls, "start", return_value={"outcome": "done"}) as start, \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(triage.main(["--plan", str(root / "plan")]), 0)
            read.assert_called_once_with()
            self.assertIs(brief.call_args.args[1], events)
            self.assertEqual(start.call_args.kwargs["base"], "main" if landed else plan.trunk)
            self.assertTrue(start.call_args.kwargs["report_only"])

    def test_tick_brief_failure_parks_with_empty_report_and_wakes(self):
        root = log.home().parent
        fake = FakeRunner().on(["git", "rev-parse"], Result(0, str(root)))
        atomic.write(root / "docs/design/draft/path.md", "## 2. Story\nStory.\n## 4. Bar\nBar.\n")
        with patch.object(calls, "run", fake), patch.object(calls, "BRIEF_LIMIT", 10), \
             patch.object(triage.walks, "editions", return_value={}), redirect_stderr(io.StringIO()):
            for flags in ((), ("--tick", "--brief-only")):
                self.assertEqual(triage.main(["--plan", str(root / "plan"), *flags]), 1)
                self.assertEqual(log.read(), [])
                self.assertFalse(wake.want_path().exists())
            self.assertEqual(triage.main(["--plan", str(root / "plan"), "--tick"]), 1)
        record, = log.read()
        self.assertEqual((record["ev"], record["subject"], record["role"], record["call"], record["report"]),
                         ("call.parked", "ladder/triage", "triage", "", ""))
        self.assertTrue(record["reason"].startswith("brief failed: brief exceeds BRIEF_LIMIT"))
        self.assertEqual(wake.want_path().read_text(), "park ladder/triage\n")

    def test_tick_unreadable_triage_input_parks_its_first_error_line(self):
        root = log.home().parent
        runner = FakeRunner().on(["git", "rev-parse"], Result(0, str(root)))
        with patch.object(calls, "run", runner), patch.object(triage.walks, "editions", return_value={}), \
             patch.object(triage, "brief", side_effect=OSError("report unreadable\nmore detail")), \
             redirect_stderr(io.StringIO()):
            self.assertEqual(triage.main(["--plan", str(root / "plan"), "--tick"]), 1)
        record, = log.read()
        self.assertEqual(record["reason"], "brief failed: report unreadable")
        self.assertEqual(wake.want_path().read_text(), "park ladder/triage\n")

    def test_tick_plan_without_rungs_or_ladder_never_parks(self):
        for plan in (replace(self.plan, rungs=()), replace(self.plan, ladder=None)):
            with self.subTest(plan=plan), patch.object(triage, "load_plan", return_value=plan), \
                 patch.object(calls, "start") as start, redirect_stderr(io.StringIO()):
                self.assertEqual(triage.main(["--plan", str(log.home().parent / "plan"), "--tick"]), 1)
            start.assert_not_called()
            self.assertEqual(log.read(), [])
            self.assertFalse(wake.want_path().exists())


class TriageBriefTest(TriageTest):
    def setUp(self):
        super().setUp()
        self.root = log.home().parent
        self.directory = self.root / "plan"
        atomic.write(self.root / "docs/design/draft/path.md",
                     "# Path\n\n## 1. Outside\nUncited setup.\n\n## 2. Story\nHappy story.\n"
                     "\n## 3. Aside\nUncited aside.\n\n## 4. Acceptance\nHappy bar.\n")
        self.editions = {"b0": "first-edition", "b1": "second-edition"}

    def compile(self, events):
        return triage.brief(self.plan, events, self.root, self.directory, self.editions,
                            call_id="triage-preview", branch="", report="/report.md", now=STAMP)

    def test_sections_new_fields_answers_and_only_affected_rung_briefs(self):
        whole = "First step.\n\n## Nested detail\nLast step, café.\n"
        atomic.write(self.directory / "briefs/b0.md", whole)
        events = _walk(verdict="fail", title="A café stalls", blocking=True, index=7,
                       commit="walked-sha", edition="walked-edition", severity="high", area="forge",
                       reproduction="First step\nSecond step", expected="Success", seen="Failure",
                       evidence=("log:first\ncontinued", "screenshot:second"))
        events += [finding_triaged("finding-1", "user", question="Which login?"),
                   log.record(channel.ANSWERED, ts=STAMP, subject="ladder/triage/finding-1",
                              call="asked-1", by="owner", question="Which login?", answer="Use café\nThen retry.")]
        events += _walk(2, verdict="void", again="finding-9") + _walk(3, draft="other")
        before = copy.deepcopy(events)
        text = self.compile(events)
        headings = ["Role", "Call facts", "The happy path", "The rungs", "New findings", "Open findings"]
        positions = [text.index(f"# {name}\n\n") for name in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertIn(calls.ROLES["triage"].read_text(), text)
        self.assertIn(calls._facts("triage-preview", "", "/report.md"), text)
        self.assertIn("Happy story.", text)
        self.assertIn("Happy bar.", text)
        self.assertNotIn("Uncited", text)
        for state in qa.rungs(self.plan, events, self.editions, STAMP):
            self.assertIn(qa.line(state), text)
        self.assertIn(whole, text)
        self.assertEqual(text.count("## b0: briefs/b0.md"), 1)
        self.assertIn("The walk kit.\n", text)
        self.assertNotIn("Walk b1.", text)
        self.assertNotIn("## b1: briefs/b1.md", text)
        for fragment in ("- Id: finding-1", "- Kind: qa", "- Draft: ladder", "- Walk: walk-1",
                         "- Index: 7", "- Rung: b0", "- Backend: chatgpt-forgejo", "- Commit: walked-sha",
                         "- Edition: walked-edition", "- Title: A café stalls", "- Severity: high",
                         "- Area: forge", "- Blocking: True", "- Reproduction: First step\nSecond step",
                         "- Expected: Success", "- Seen: Failure", "log:first\ncontinued", "screenshot:second",
                         f"- Raised: {STAMP}", "- Verdict: fail", "- Verdict: void", "- Again: finding-9"):
            self.assertIn(fragment, text)
        first = text.split("# New findings\n\n", 1)[1].split("## finding-2:", 1)[0]
        self.assertNotIn("- Again:", first)
        self.assertIn(channel.answers_text("ladder/triage/finding-1", events), first)
        self.assertNotIn("## finding-3:", text)
        self.assertEqual(events, before)

    def test_each_affected_rung_includes_its_files_in_plan_order(self):
        events = _walk() + [walk_started("walk-2", "b1"), finding_raised("finding-2", "walk-2", "b1"),
                            walk_ended("walk-2", "pass", ("finding-2",))]
        text = self.compile(events)
        self.assertIn("Walk b1.\n", text)
        self.assertLess(text.index("## b0: briefs/kit.md"), text.index("## b0: briefs/b0.md"))
        self.assertLess(text.index("## b0: briefs/b0.md"), text.index("## b1: briefs/kit.md"))
        self.assertLess(text.index("## b1: briefs/kit.md"), text.index("## b1: briefs/b1.md"))

    def test_open_lines_cover_asked_routed_landed_and_backlog_with_sightings(self):
        states = ("asked", "foreman", "deciding", "decided", "repairing", "landed", "backlog")
        events = []
        for number, state in enumerate(states, 1):
            identifier, task, run = f"finding-{number}", f"ladder/finding-{number}", f"foreman-{number}"
            events += _walk(number, title=f"Open {state}\ncontinued", area="forge\napi")
            decision = {"asked": "user", "backlog": "backlog"}.get(state, "path")
            events += [finding_triaged(identifier, decision)]
            if state in ("deciding", "decided", "repairing", "landed"):
                events += [log.record("run.started", ts=STAMP, task=task + "/foreman", run=run, kind="foreman")]
            if state in ("decided", "repairing", "landed"):
                events += [log.record("run.ended", ts=STAMP, task=task + "/foreman", run=run, outcome="done")]
            if state in ("repairing", "landed"):
                events += [log.record("finding.settled", ts=STAMP, finding=identifier, run=run, verdict="fix",
                                      reason="Repair", section="Fix")]
            if state == "landed":
                events += [_landed(task)]
        events += _walk(8) + [finding_merged("finding-8", "finding-1")]
        events += _walk(9) + [finding_triaged("finding-9", "drop")]
        events += _walk(10, draft="other") + [finding_triaged("finding-10", "backlog")]
        events += _walk(11)
        text = self.compile(events).split("# Open findings\n\n", 1)[1]
        lines = text.splitlines()
        self.assertEqual(len(lines), len(states))
        for number, state in enumerate(states, 1):
            sightings = "finding-8" if number == 1 else "(none)"
            self.assertEqual(lines[number - 1], f"- finding-{number}: {state}; rung b0; area forge api; "
                             f"Open {state} continued; sightings: {sightings}")

    def test_empty_findings_keep_sections_without_rung_brief_files(self):
        (self.directory / "briefs/b0.md").unlink()
        text = self.compile([])
        self.assertIn("# New findings\n\n", text)
        self.assertIn("# Open findings\n\n", text)
        self.assertNotIn("The walk kit.", text)

    def test_oversize_brief_raises_without_trimming(self):
        with patch.object(calls, "BRIEF_LIMIT", len(self.compile(_walk())) - 1):
            with self.assertRaisesRegex(ValueError, "brief exceeds BRIEF_LIMIT"):
                self.compile(_walk())


if __name__ == "__main__":
    unittest.main()
