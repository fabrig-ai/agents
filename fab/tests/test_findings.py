"""QA finding lifecycle over built records (docs/design/fab.md, 8 and 13.15)."""

import copy
import unittest
from dataclasses import FrozenInstanceError, replace

from fab import findings as qa, log
from fab.plan import load_plan
from fab.tests.ladder_plans import write_ladder
from fab.tests.qa_records import (
    STAMP, finding_merged, finding_raised, finding_triaged, rung_passed, walk_ended, walk_started,
)
from fab.tests.support import tmp_home


def _walk(identifier="finding-1", walk="walk-1", rung="b0", *, verdict="pass", **fields):
    return [walk_started(walk, rung, draft=fields.get("draft", "ladder")),
            finding_raised(identifier, walk, rung, **fields), walk_ended(walk, verdict, (identifier,))]


def _started(task="ladder/finding-1/foreman", run="foreman-1", kind="foreman"):
    return log.record("run.started", ts=STAMP, task=task, run=run, kind=kind,
                      host="builder", dir="checkout", branch=task, base="main")


def _ended(outcome="done", run="foreman-1", task="ladder/finding-1/foreman"):
    return log.record("run.ended", ts=STAMP, task=task, run=run, outcome=outcome,
                      report="report.md", minutes=1, tokens=10)


def _settled(verdict="fix", run="foreman-1"):
    return log.record("finding.settled", ts=STAMP, finding="finding-1", run=run,
                      verdict=verdict, reason="Survey reason", section="Repair section")


def _landed(main="landed-main", task="ladder/finding-1"):
    return log.record("branch.landed", ts=STAMP, task=task, branch=task,
                      tip="repair-tip", main=main, into="")


def _answer(text="Done", subject="ladder/triage/finding-1"):
    return log.record("call.answered", ts=STAMP, subject=subject, call="triage-1",
                      by="user", question="What next?", answer=text)


def _repair(identifier="finding-1", walk="walk-1", rung="b0", *, main="landed-main"):
    task = f"ladder/{identifier}"
    number = identifier.removeprefix("finding-")
    foreman = f"foreman-{number}"
    return [*_walk(identifier, walk, rung, blocking=True), finding_triaged(identifier, "path", owner="ctl"),
            _started(task + "/foreman", foreman), _ended(run=foreman, task=task + "/foreman"),
            {**_settled(run=foreman), "finding": identifier},
            _started(task, f"repair-{number}", "implement"), _landed(main, task)]


class FindingsTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(tmp_home())

    def test_walk_end_publishes_new_finding_and_retains_raised_fields(self):
        events = _walk(evidence=("trace.txt", "screen.png"), blocking=True)
        self.assertEqual(qa.findings(events[:-1]), {})
        finding = qa.findings(events)["finding-1"]
        self.assertEqual((finding.id, finding.state, finding.verdict, finding.raised),
                         ("finding-1", "new", "pass", STAMP))
        raised = events[1]
        for field in ("draft", "walk", "index", "rung", "backend", "commit", "edition", "title",
                      "severity", "area", "blocking", "reproduction", "expected", "seen", "again"):
            self.assertEqual(getattr(finding, field), raised[field])
        self.assertEqual(finding.evidence, ("trace.txt", "screen.png"))
        self.assertEqual((finding.into, finding.owner, finding.reason, finding.question, finding.action,
                          finding.answers, finding.sightings, finding.landed),
                         ("", "", "", "", "", (), (), ""))
        with self.assertRaises(FrozenInstanceError):
            finding.state = "fixed"

    def test_public_constants_match_walk_and_triage_vocabulary(self):
        self.assertEqual(qa.BACKENDS, {"chatgpt-forgejo": ("chatgpt",),
                                      "claude-forgejo": ("claude-box",),
                                      "chatgpt-github": ("chatgpt", "github")})
        self.assertEqual(qa.VERDICTS, ("pass", "fail", "void"))
        self.assertEqual(qa.SEVERITIES, ("low", "medium", "high"))
        self.assertEqual(qa.DECISIONS, ("path", "backlog", "user", "brief", "drop", "again"))
        self.assertEqual(qa.WALK_HOURS, 4)
        self.assertEqual(len(qa.STATES), 13)

    def test_raise_order_survives_walks_ending_in_reverse_and_includes_every_draft(self):
        first = _walk()
        second = _walk("finding-2", "walk-2", draft="other")
        events = [*first[:2], *second, first[-1]]
        found = qa.findings(events)
        self.assertEqual(list(found), ["finding-1", "finding-2"])
        self.assertEqual([finding.draft for finding in found.values()], ["ladder", "other"])
        self.assertEqual(qa.findings(iter(events)), found)

    def test_each_triage_decision_sets_its_disposition_and_requests(self):
        for decision, state in (("path", "foreman"), ("backlog", "backlog"), ("user", "asked"),
                                ("brief", "asked"), ("drop", "dropped"), ("again", "new")):
            with self.subTest(decision=decision):
                events = _walk() + [finding_triaged("finding-1", decision, owner="ctl",
                                                   question="User request", into="finding-9")]
                finding = qa.findings(events)["finding-1"]
                self.assertEqual((finding.state, finding.owner, finding.reason),
                                 (state, "ctl", "Triage reason"))
                self.assertEqual(finding.question, "User request" if state == "asked" else "")
                self.assertEqual(finding.action, "User request" if decision == "path" else "")
                self.assertEqual(finding.again, "finding-9" if decision == "again" else "")

    def test_user_answer_reopens_but_brief_answer_drops_with_answer_as_reason(self):
        for decision, state in (("user", "new"), ("brief", "dropped")):
            with self.subTest(decision=decision):
                events = _walk() + [finding_triaged("finding-1", decision, question="What next?")]
                self.assertEqual(qa.findings(events)["finding-1"].question, "What next?")
                finding = qa.findings(events + [_answer("The brief is corrected")])["finding-1"]
                self.assertEqual((finding.state, finding.question, finding.answers),
                                 (state, "", ("The brief is corrected",)))
                self.assertEqual(finding.reason, "The brief is corrected" if decision == "brief"
                                 else "Triage reason")

    def test_answers_are_kept_in_order_and_only_for_the_exact_subject(self):
        events = [_answer("Before the finding"), *_walk(),
                  finding_triaged("finding-1", "user", question="First?"),
                  _answer("First"), finding_triaged("finding-1", "user", question="Second?"),
                  _answer("Wrong draft", "other/triage/finding-1"), _answer("Second")]
        self.assertEqual(qa.findings(events)["finding-1"].answers, ("First", "Second"))

    def test_path_action_holds_after_landing_and_passing_until_a_later_answer(self):
        events = _repair()
        events[3] = finding_triaged("finding-1", "path", owner="ctl", question="Install the app")
        events += [rung_passed("b0")]
        finding = qa.findings(events)["finding-1"]
        self.assertEqual((finding.state, finding.action, finding.holds), ("fixed", "Install the app", True))
        finding = qa.findings(events + [_answer()])["finding-1"]
        self.assertEqual((finding.state, finding.action, finding.holds, finding.answers),
                         ("fixed", "", False, ("Done",)))

    def test_earlier_answer_does_not_release_a_later_path_action(self):
        events = _walk() + [_answer(), finding_triaged("finding-1", "path", question="Install")]
        self.assertEqual(qa.findings(events)["finding-1"].action, "Install")

    def test_repair_lifecycle_advances_at_each_record_and_only_a_later_rung_pass_fixes(self):
        events = _repair()
        for count, state in ((3, "new"), (4, "foreman"), (5, "deciding"), (6, "decided"),
                             (7, "repairing"), (8, "repairing"), (9, "landed")):
            with self.subTest(count=count):
                self.assertEqual(qa.findings(events[:count])["finding-1"].state, state)
        self.assertEqual(qa.findings(events)["finding-1"].landed, "landed-main")
        self.assertEqual(qa.findings(events[:-1] + [rung_passed("b0"), events[-1]])["finding-1"].state,
                         "landed")
        for passing in (rung_passed("b1"), rung_passed("b0", draft="other")):
            self.assertEqual(qa.findings(events + [passing])["finding-1"].state, "landed")
        # An edition change does not erase the finding's repair history.
        self.assertEqual(qa.findings(events + [rung_passed("b0", edition="next")])["finding-1"].state,
                         "fixed")

    def test_foreman_failure_falls_back_without_a_settlement(self):
        for outcome in ("failed", "question", "infra"):
            with self.subTest(outcome=outcome):
                events = _repair()[:5] + [_ended(outcome), _landed()]
                self.assertEqual(qa.findings(events[:-1])["finding-1"].state, "repairing")
                self.assertEqual(qa.findings(events)["finding-1"].state, "landed")

    def test_none_settlement_repairs_and_left_settlement_releases_action(self):
        for verdict, state in (("none", "repairing"), ("left", "left")):
            with self.subTest(verdict=verdict):
                events = _repair()[:6]
                events[3] = finding_triaged("finding-1", "path", question="Install")
                finding = qa.findings(events + [_settled(verdict)])["finding-1"]
                self.assertEqual((finding.state, finding.reason), (state, "Survey reason"))
                self.assertEqual(finding.holds, verdict != "left")
                self.assertEqual(finding.action, "" if verdict == "left" else "Install")

    def test_unrelated_runs_and_out_of_order_settlements_do_not_advance(self):
        events = _repair()[:4]
        irrelevant = [_ended(), _settled(), _landed(), _started(kind="implement"),
                      _started(task="other/finding-1/foreman")]
        self.assertEqual(qa.findings(events + irrelevant)["finding-1"].state, "foreman")
        events += [_started()]
        self.assertEqual(qa.findings(events + [_ended(run="another")])["finding-1"].state, "deciding")
        events += [_ended()]
        self.assertEqual(qa.findings(events + [_settled(run="another")])["finding-1"].state, "decided")

    def test_again_raise_or_triage_marks_a_landed_or_fixed_target_unfixed(self):
        for fixed in (False, True):
            for raised_again in (False, True):
                with self.subTest(fixed=fixed, raised_again=raised_again):
                    events = _repair() + ([rung_passed("b0")] if fixed else [])
                    events += _walk("finding-2", "walk-2", again="finding-1" if raised_again else "")
                    if not raised_again:
                        events += [finding_triaged("finding-2", "again", into="finding-1")]
                    found = qa.findings(events)
                    self.assertEqual((found["finding-1"].state, found["finding-1"].landed),
                                     ("unfixed", "landed-main"))
                    self.assertEqual((found["finding-2"].state, found["finding-2"].again),
                                     ("new", "finding-1"))
                    self.assertEqual(qa.findings(events + [rung_passed("b0")])["finding-1"].state,
                                     "unfixed")

    def test_again_raise_before_landing_does_not_unfix_a_later_landing(self):
        repair = _repair()
        recurrence = _walk("finding-2", "walk-2", again="finding-1")
        events = repair[:-1] + recurrence[:2] + [repair[-1], recurrence[-1]]
        found = qa.findings(events)
        self.assertEqual((found["finding-1"].state, found["finding-2"].state), ("landed", "new"))

    def test_merge_before_landing_is_not_rejudged_at_its_walk_end(self):
        repair = _repair()
        sighting = _walk("finding-2", "walk-2")
        events = repair[:-1] + sighting[:2] + [finding_merged("finding-2", "finding-1"),
                                                repair[-1], sighting[-1]]
        found = qa.findings(events)
        self.assertEqual((found["finding-1"].state, found["finding-2"].state), ("landed", "merged"))
        self.assertEqual(found["finding-1"].sightings, ("finding-2",))
        # A truncated intake contributes no sightings to the landed repair.
        self.assertEqual(qa.findings(events[:-1])["finding-1"].sightings, ())

    def test_again_of_a_dropped_or_left_target_leaves_target_disposition(self):
        for events in (_walk() + [finding_triaged("finding-1", "drop")],
                       _repair()[:6] + [_settled("left")]):
            state = qa.findings(events)["finding-1"].state
            found = qa.findings(events + _walk("finding-2", "walk-2", again="finding-1"))
            self.assertEqual(found["finding-1"].state, state)
            self.assertEqual(found["finding-2"].state, "new")

    def test_clear_drops_a_finding_and_records_the_clear_text(self):
        clear = log.record("signal.cleared", ts=STAMP, signal="finding-1", by="user", text="Setup fixed")
        events = _repair()[:4]
        events[3] = finding_triaged("finding-1", "path", question="Install")
        finding = qa.findings(events + [clear, *_repair()[4:]])["finding-1"]
        self.assertEqual((finding.state, finding.reason, finding.action, finding.holds),
                         ("dropped", "Setup fixed", "", False))

    def test_intake_merge_is_invisible_until_walk_end_and_then_adds_a_sighting_once(self):
        first = _walk()
        second = _walk("finding-2", "walk-2")
        merge = finding_merged("finding-2", "finding-1")
        events = first + second[:2] + [merge, merge]
        self.assertEqual(list(qa.findings(events)), ["finding-1"])
        self.assertEqual(qa.findings(events)["finding-1"].sightings, ())
        found = qa.findings(events + [second[-1]])
        self.assertEqual((found["finding-2"].state, found["finding-2"].into), ("merged", "finding-1"))
        self.assertEqual(found["finding-1"].sightings, ("finding-2",))

    def test_target_resolves_merge_chains_and_sightings_follow_the_target(self):
        events = _walk() + _walk("finding-2", "walk-2") + _walk("finding-3", "walk-3")
        events += [finding_merged("finding-3", "finding-2"), finding_merged("finding-2", "finding-1")]
        found = qa.findings(events)
        self.assertEqual(qa.target(found, "finding-3"), "finding-1")
        self.assertEqual(found["finding-1"].sightings, ("finding-3", "finding-2"))
        events += _walk("finding-4", "walk-4") + [finding_merged("finding-4", "finding-3")]
        found = qa.findings(events)
        self.assertEqual((found["finding-4"].into, qa.target(found, "finding-4")),
                         ("finding-3", "finding-1"))
        self.assertEqual(found["finding-1"].sightings, ("finding-3", "finding-2", "finding-4"))

    def test_target_stops_at_unknown_ids_and_before_repeating_a_cycle(self):
        finding = qa.findings(_walk())["finding-1"]
        found = {"a": replace(finding, id="a", state="merged", into="b"),
                 "b": replace(finding, id="b", state="merged", into="c")}
        self.assertEqual(qa.target(found, "a"), "c")
        self.assertEqual(qa.target(found, "unknown"), "unknown")
        found["c"] = replace(finding, id="c", state="merged", into="a")
        self.assertEqual(qa.target(found, "a"), "c")
        found["a"] = replace(found["a"], into="a")
        self.assertEqual(qa.target(found, "a"), "a")

    def test_invalid_merge_targets_and_merging_a_recurrence_are_skipped(self):
        for into in ("finding-2", "missing", "finding-1"):
            events = _walk() + _walk("finding-2", "walk-2", again="finding-1")
            found = qa.findings(events + [finding_merged("finding-2", into)])
            self.assertEqual(found["finding-2"].state, "new")
        events = _repair() + _walk("finding-2", "walk-2")
        self.assertEqual(qa.findings(events + [finding_merged("finding-2", "finding-1")])["finding-2"].state,
                         "new")

    def test_mergeable_covers_every_state(self):
        finding = qa.findings(_walk())["finding-1"]
        allowed = {"new", "asked", "backlog", "foreman", "deciding", "decided", "repairing"}
        for state in qa.STATES:
            with self.subTest(state=state):
                self.assertEqual(qa.mergeable(replace(finding, state=state)), state in allowed)

    def test_holds_covers_blocking_walk_verdict_and_every_state(self):
        active = {"new", "asked", "foreman", "deciding", "decided", "repairing"}
        for blocking, verdict in ((False, "pass"), (True, "pass"), (False, "fail"), (False, "void")):
            finding = qa.findings(_walk(blocking=blocking, verdict=verdict))["finding-1"]
            for state in qa.STATES:
                with self.subTest(blocking=blocking, verdict=verdict, state=state):
                    self.assertEqual(replace(finding, state=state).holds,
                                     (blocking or verdict != "pass") and state in active)

    def test_missing_or_wrongly_typed_raise_fields_are_skipped(self):
        events = _walk()
        for field in events[1]:
            for missing in (True, False):
                with self.subTest(field=field, missing=missing):
                    raised = dict(events[1])
                    if missing:
                        del raised[field]
                    else:
                        raised[field] = None
                    expected = not missing and field == "evidence"
                    self.assertEqual(bool(qa.findings([events[0], raised, events[2]])), expected)
        for field, value in (("index", True), ("blocking", 1), ("kind", "red"),
                             ("backend", "unknown"), ("severity", "urgent")):
            self.assertEqual(qa.findings([events[0], {**events[1], field: value}, events[2]]), {})

    def test_invalid_evidence_is_an_empty_tuple(self):
        events = _walk()
        for evidence in (None, "trace.txt", ["trace.txt", 3], ("trace.txt",), {"path": "trace.txt"}):
            with self.subTest(evidence=evidence):
                raised = {**events[1], "evidence": evidence}
                self.assertEqual(qa.findings([events[0], raised, events[2]])["finding-1"].evidence, ())

    def test_missing_or_wrongly_typed_transition_fields_are_skipped(self):
        repair = _repair()
        clear = log.record("signal.cleared", ts=STAMP, signal="finding-1", by="user", text="Clear")
        transitions = [
            (_walk(), finding_triaged("finding-1", "drop")),
            (repair[:6], _settled()),
            (_walk() + [finding_triaged("finding-1", "user", question="What next?")], _answer()),
            (repair[:4], clear), (repair[:5], _ended()), (repair[:4], _started()),
            (repair[:8], _landed()), (repair, rung_passed("b0")),
            (_walk() + _walk("finding-2", "walk-2"), finding_merged("finding-1", "finding-2")),
        ]
        required = {
            "run.started": ("ev", "ts", "run", "task", "kind"),
            "run.ended": ("ev", "ts", "run", "task", "outcome"),
        }
        for prefix, transition in transitions:
            self.assertNotEqual(qa.findings(prefix + [transition]), qa.findings(prefix))
            for field in required.get(transition["ev"], transition):
                for missing in (True, False):
                    with self.subTest(event=transition["ev"], field=field, missing=missing):
                        malformed = dict(transition)
                        if missing:
                            del malformed[field]
                        else:
                            malformed[field] = ["wrong type"]
                        self.assertEqual(qa.findings(prefix + [malformed]), qa.findings(prefix))

    def test_malformed_walk_end_does_not_publish(self):
        events = _walk()
        for field in events[-1]:
            malformed = dict(events[-1])
            del malformed[field]
            self.assertEqual(qa.findings(events[:-1] + [malformed]), {})
        for field, value in (("verdict", "unknown"), ("findings", [1]), ("findings", "finding-1")):
            self.assertEqual(qa.findings(events[:-1] + [{**events[-1], field: value}]), {})

    def test_fold_preserves_input_and_ignores_unknown_events_and_duplicate_intake(self):
        events = _repair()
        events += [events[1], events[2], log.record("future.event", ts=STAMP, count=1)]
        before = copy.deepcopy(events)
        found = qa.findings(events)
        self.assertEqual(events, before)
        self.assertEqual(found["finding-1"].state, "landed")
        self.assertEqual(len(found), 1)

    def test_log_order_controls_transitions_even_with_reversed_timestamps(self):
        events = _repair()
        events[-1]["ts"] = "2020-01-01T00:00:00.000Z"
        events += [rung_passed("b0", ts="2019-01-01T00:00:00.000Z")]
        self.assertEqual(qa.findings(events)["finding-1"].state, "fixed")


class RungsTest(unittest.TestCase):
    def setUp(self):
        home = self.enterContext(tmp_home())
        directory = write_ladder(home / "plan", rungs={
            "b0": ("chatgpt-forgejo", ()), "b1": ("chatgpt-forgejo", ("b0",)),
        })
        self.plan = load_plan(directory / "plan.toml")
        self.editions = {"b0": "edition", "b1": "edition"}

    def states(self, events, *, now=STAMP, editions=None):
        return qa.rungs(self.plan, events, self.editions if editions is None else editions, now)

    def passes(self, events, *, editions=None):
        return qa.passes(self.plan, events, self.editions if editions is None else editions)

    def test_holds_until_landing_then_rerun_at_repair_main_and_upper_waits(self):
        events = _repair()
        for count, status in ((3, "new"), (8, "repairing")):
            with self.subTest(status=status):
                lower, upper = self.states(events[:count])
                self.assertEqual((lower.state, lower.holders), ("holding", (("finding-1", status),)))
                self.assertEqual((upper.state, upper.waits), ("waiting", ("b0",)))
        lower, upper = self.states(events)
        self.assertEqual((lower.state, lower.due, lower.at), ("due", "rerun", "landed-main"))
        self.assertEqual(upper.state, "waiting")
        events += _completed("walk-2", commit="landed-main")
        fields, = self.passes(events)
        events += [rung_passed(**fields)]
        lower, upper = self.states(events)
        self.assertEqual((lower.state, lower.walk, lower.commit),
                         ("passed", "walk-2", "landed-main"))
        self.assertEqual((upper.state, upper.due), ("due", "first walk"))
        self.assertEqual(qa.findings(events)["finding-1"].state, "fixed")

    def test_nonblocking_pass_holds_nothing_but_void_holds(self):
        for verdict, expected in (("pass", ()), ("void", ("finding-1",))):
            with self.subTest(verdict=verdict):
                found = qa.findings(_walk(verdict=verdict))
                self.assertEqual(tuple(f.id for f in qa.holders(found, "b0")), expected)
        self.assertEqual(self.states(_walk(verdict="void"))[0].state, "holding")
        self.assertEqual(self.states(_walk())[0].state, "due")

    def test_merged_sighting_uses_its_verdict_and_target_state_once(self):
        events = _walk(rung="b1") + _walk("finding-2", "walk-2", verdict="fail")
        events += _walk("finding-3", "walk-3", verdict="void")
        events += [finding_merged("finding-2", "finding-1"),
                   finding_merged("finding-3", "finding-2")]
        found = qa.findings(events)
        self.assertFalse(found["finding-1"].holds)
        self.assertEqual(qa.holders(found, "b0"), (found["finding-1"],))
        self.assertEqual(qa.holders(found, "b1"), ())
        self.assertEqual(self.states(events)[0].holders, (("finding-1", "new"),))
        for state in qa.STATES:
            with self.subTest(state=state):
                target = replace(found["finding-1"], state=state)
                changed = {**found, "finding-1": target}
                expected = (target,) if state in ("new", "asked", "foreman", "deciding", "decided",
                                                  "repairing") else ()
                self.assertEqual(qa.holders(changed, "b0"), expected)
        target = replace(found["finding-1"], state="landed", action="Reconnect")
        self.assertEqual(qa.holders({**found, "finding-1": target}, "b0"), (target,))

    def test_holder_order_is_first_sighting_raise_order_and_targets_are_unique(self):
        events = _walk("finding-1", "walk-1", rung="b1")
        events += _walk("finding-2", "walk-2", blocking=True)
        events += _walk("finding-3", "walk-3", blocking=True)
        events += _walk("finding-4", "walk-4", blocking=True)
        events += [finding_merged("finding-2", "finding-1"),
                   finding_merged("finding-4", "finding-1")]
        found = qa.findings(events)
        self.assertEqual(tuple(f.id for f in qa.holders(found, "b0")), ("finding-1", "finding-3"))
        self.assertEqual(qa.holders(found, "missing"), ())

    def test_rerun_pass_is_logged_once_and_first_pass_is_not_acceptance(self):
        events = _completed("walk-1", commit="main")
        self.assertEqual(self.passes(events), [])
        self.assertEqual((self.states(events)[0].state, self.states(events)[0].due), ("due", "rerun"))
        events += _completed("walk-2", commit="main")
        expected = {"draft": "ladder", "rung": "b0", "walk": "walk-2",
                    "edition": "edition", "commit": "main"}
        self.assertEqual(self.passes(events), [expected])
        self.assertEqual(self.passes(events + [events[-1]]), [expected])
        self.assertEqual(self.passes(events + [rung_passed(**expected)]), [])
        self.assertEqual(self.passes(events + [rung_passed("b1", draft="other", walk="walk-2")]), [expected])
        self.assertEqual(self.passes(events + [rung_passed("missing", walk="walk-2")]), [expected])

    def test_lower_pass_must_exist_at_end_or_use_the_same_commit(self):
        upper = _completed("walk-1", "b1", commit="shared")
        upper += _completed("walk-2", "b1", commit="shared")
        self.assertEqual(self.passes(upper), [])
        for commit, expected in (("shared", ["walk-4", "walk-2"]), ("other", ["walk-4"])):
            with self.subTest(commit=commit):
                events = upper + _completed("walk-3", commit=commit) + _completed("walk-4", commit=commit)
                self.assertEqual([p["walk"] for p in self.passes(events)], expected)
        for commit, expected in (("shared", ["walk-2"]), ("other", [])):
            with self.subTest(logged=commit):
                self.assertEqual([p["walk"] for p in self.passes(
                    upper + [rung_passed("b0", walk="lower", commit=commit)])], expected)
        before = [rung_passed("b0", walk="lower", commit="earlier")]
        self.assertEqual([p["walk"] for p in self.passes(before + upper)], ["walk-2"])
        self.assertEqual([p["walk"] for p in self.passes(
            before + _completed("failed-lower", verdict="fail") + upper)], [])

    def test_a_later_lower_pass_at_another_commit_keeps_the_shared_commit_pass(self):
        events = _completed("walk-1", "b1", commit="shared")
        events += _completed("walk-2", "b1", commit="shared")
        events += [rung_passed("b0", walk="lower-1", commit="shared"),
                   rung_passed("b0", walk="lower-2", commit="other")]
        self.assertEqual([p["walk"] for p in self.passes(events)], ["walk-2"])
        self.assertEqual(self.states(events)[0].commit, "other")

    def test_parallel_passes_close_bottom_up_even_with_reversed_plan_order(self):
        self.plan = replace(self.plan, rungs=dict(reversed(list(self.plan.rungs.items()))))
        events = (_completed("walk-1", "b1") + _completed("walk-2")
                  + [walk_started("walk-3", "b1"), walk_started("walk-4", "b0"),
                     walk_ended("walk-3", "pass"), walk_ended("walk-4", "pass")])
        fields = self.passes(events)
        self.assertEqual([p["rung"] for p in fields], ["b0", "b1"])
        for record in fields:
            events += [rung_passed(**record)]
        self.assertEqual(self.passes(events), [])
        self.assertEqual([(s.rung, s.state) for s in self.states(events)],
                         [("b1", "passed"), ("b0", "passed")])

    def test_void_is_not_the_earlier_walk_for_a_rerun(self):
        events = _completed("walk-1", verdict="void")
        self.assertEqual(self.states(events)[0].due, "first walk")
        self.assertEqual(self.passes(events + _completed("walk-2")), [])
        events += _completed("walk-2") + _completed("walk-3")
        self.assertEqual([p["walk"] for p in self.passes(events)], ["walk-3"])

    def test_earlier_walk_must_end_before_the_passing_walk_ends(self):
        events = [walk_started("walk-1", "b0"), walk_started("walk-2", "b0"),
                  walk_ended("walk-2", "pass"), walk_ended("walk-1", "pass")]
        self.assertEqual([p["walk"] for p in self.passes(events)], ["walk-1"])

    def test_holders_are_checked_at_walk_end_not_at_the_tick(self):
        held = _walk(blocking=True) + _completed("walk-2")
        released = held + [finding_triaged("finding-1", "drop")]
        self.assertEqual(self.passes(released), [])
        self.assertEqual([p["walk"] for p in self.passes(released + _completed("walk-3"))], ["walk-3"])
        nonblocking = _completed("walk-1") + _walk("finding-2", "walk-2")
        self.assertEqual([p["walk"] for p in self.passes(nonblocking)], ["walk-2"])
        later = nonblocking + _walk("finding-3", "walk-3", verdict="void")
        self.assertEqual([p["walk"] for p in self.passes(later)], ["walk-2"])

    def test_failed_walk_reopens_a_pass_and_disqualifies_earlier_candidates(self):
        events = _completed("walk-1") + _completed("walk-2")
        self.assertEqual([p["walk"] for p in self.passes(events)], ["walk-2"])
        events += [rung_passed("b0")] + _completed("walk-3", verdict="fail")
        self.assertEqual(self.passes(events), [])
        lower = self.states(events)[0]
        self.assertEqual((lower.state, lower.due), ("due", "rerun"))
        events += _completed("walk-4")
        self.assertEqual([p["walk"] for p in self.passes(events)], ["walk-4"])

    def test_new_edition_ignores_old_walks_and_passes_but_keeps_findings(self):
        events = _completed("walk-1") + _completed("walk-2") + [rung_passed("b0")]
        editions = {"b0": "next", "b1": "next"}
        self.assertEqual(self.passes(events, editions=editions), [])
        self.assertEqual(self.states(events, editions=editions)[0].due, "first walk")
        events += _completed("walk-3", edition="next")
        self.assertEqual(self.passes(events, editions=editions), [])
        events += _completed("walk-4", edition="next")
        self.assertEqual([p["walk"] for p in self.passes(events, editions=editions)], ["walk-4"])
        old_finding = _walk(blocking=True)
        self.assertEqual(self.states(old_finding, editions=editions)[0].state, "holding")

    def test_walking_expires_at_the_wall_cap_and_ended_walks_are_not_in_flight(self):
        events = [walk_started("walk-1", "b0")]
        for now, expected in ((STAMP, "walking"), ("2026-11-01T03:59:59.999Z", "walking"),
                              ("2026-11-01T04:00:00.000Z", "due")):
            with self.subTest(now=now):
                lower = self.states(events, now=now)[0]
                self.assertEqual(lower.state, expected)
                if expected == "walking":
                    self.assertEqual((lower.walk, lower.since), ("walk-1", STAMP))
        self.assertEqual(self.states(events + [walk_ended("walk-1", "void")])[0].state, "due")
        self.assertEqual(self.states([walk_started("old", "b0", edition="old")])[0].state, "walking")
        self.assertEqual(self.states([walk_started("bad-time", "b0", ts="broken")])[0].state, "due")
        self.assertEqual(self.states([walk_started("naive-time", "b0", ts="2026-11-01")])[0].state, "due")

    def test_multiple_live_walks_display_the_first_start_in_log_order(self):
        events = [walk_started("walk-1", "b0"),
                  walk_started("walk-2", "b0", ts="2026-10-31T23:59:00.000Z")]
        lower = self.states(events)[0]
        self.assertEqual((lower.state, lower.walk), ("walking", "walk-1"))
        lower = self.states(events, now="2026-11-01T04:00:00.000Z")[0]
        self.assertEqual((lower.state, lower.due), ("due", "first walk"))

    def test_state_priority_passed_then_walking_then_waiting_then_holding(self):
        events = _walk(blocking=True) + [walk_started("walk-2", "b0")]
        self.assertEqual(self.states(events)[0].state, "walking")
        events += [rung_passed("b0")]
        self.assertEqual(self.states(events)[0].state, "passed")
        upper = _walk(rung="b1", blocking=True)
        self.assertEqual(self.states(upper)[1].state, "waiting")
        upper += [walk_started("walk-2", "b1")]
        self.assertEqual(self.states(upper)[1].state, "walking")

    def test_unreadable_editions_and_foreign_walks_are_ignored(self):
        events = (_completed("walk-1", draft="other") + _completed("walk-2", draft="other")
                  + _completed("walk-3", "missing") + _completed("walk-4", "missing")
                  + [rung_passed("b0", draft="other"), rung_passed("missing")])
        self.assertEqual(self.passes(events), [])
        self.assertEqual(self.states(events)[0].due, "first walk")
        self.assertEqual(self.states(events, editions={}), [])
        self.assertEqual(self.passes(events + _completed("walk-5") + _completed("walk-6"), editions={}), [])
        lower, = self.states(events, editions={"b0": "edition"})
        self.assertEqual(lower.rung, "b0")
        upper, = self.states(events, editions={"b1": "edition"})
        self.assertEqual((upper.rung, upper.waits), ("b1", ("b0",)))
        self.assertEqual(self.states(_walk(draft="other", blocking=True))[0].state, "due")

    def test_malformed_starts_ends_and_passes_are_skipped(self):
        start = walk_started("walk-2", "b0")
        end = walk_ended("walk-2", "pass")
        passed = rung_passed("b0")
        for record in (start, end, passed):
            for field in record:
                for value in (None, [1]):
                    with self.subTest(kind=record["ev"], field=field, value=value):
                        malformed = {**record, field: value}
                        if record is start:
                            events = _completed("walk-1") + [malformed, end]
                        elif record is end:
                            events = _completed("walk-1") + [start, malformed]
                        else:
                            events = [malformed]
                        self.assertEqual(self.passes(events), [])
                        self.assertNotEqual(self.states(events)[0].state, "passed")
                        if record is start:
                            self.assertEqual(self.states(events)[0].state, "due")

    def test_newest_repair_main_follows_log_order_including_merged_targets(self):
        first = _repair()
        second = _repair("finding-2", "walk-2", main="newer-main")
        second[-1]["ts"] = "2000-01-01T00:00:00.000Z"
        self.assertEqual(self.states(first + second)[0].at, "newer-main")
        events = _repair()[:3] + _walk("finding-2", "walk-2", rung="b1", verdict="fail")
        events += [finding_merged("finding-1", "finding-2")]
        tail = _repair("finding-2", "walk-2", rung="b1")[3:]
        self.assertEqual(self.states(events + tail)[0].at, "landed-main")

    def test_rung_state_is_frozen_and_each_line_uses_the_shared_format(self):
        base = qa.RungState("b0", "chatgpt-forgejo", "edition", "due", due="first walk")
        prefix = "b0 (chatgpt-forgejo), edition edition: "
        cases = [(base, "due: first walk"),
                 (replace(base, due="rerun"), "due: rerun"),
                 (replace(base, due="rerun", at="123456789012more"),
                  "due: rerun at a main containing 123456789012"),
                 (replace(base, state="walking", walk="walk-2", since=STAMP),
                  f"walking: walk-2 since {STAMP}"),
                 (replace(base, state="waiting", waits=("b1", "b2")), "waiting for b1, b2"),
                 (replace(base, state="holding", holders=(("finding-3", "repairing"), ("finding-7", "new"))),
                  "holding: finding-3 repairing, finding-7 new"),
                 (replace(base, state="passed", commit="123456789012more", walk="walk-2"),
                  "passed at 123456789012 (walk-2)")]
        for state, expected in cases:
            with self.subTest(state=state):
                self.assertEqual(qa.line(state), prefix + expected)
        with self.assertRaises(FrozenInstanceError):
            base.state = "passed"

    def test_folds_leave_input_unchanged(self):
        events = _repair() + _completed("walk-2")
        before = copy.deepcopy(events)
        self.states(events)
        self.passes(events)
        self.assertEqual(events, before)


def _completed(walk, rung="b0", verdict="pass", **fields):
    return [walk_started(walk, rung, **fields), walk_ended(walk, verdict)]


if __name__ == "__main__":
    unittest.main()
