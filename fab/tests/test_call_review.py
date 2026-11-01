import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fab import atomic, call_review as review, calls, channel, designer, log, run
from fab.hosts import Host
from fab.sh import Failed, Result, ssh
from fab.tests.support import FakeRunner, tmp_home


HOST = Host("builder", "worker@builder.invalid", ("builder",))
ROOT = Path("/home/worker/src/fabrig/fab")
CHAIN = review.Chain("skeleton-1", "skeleton", "draft/part", "calls/skeleton-1",
                     ("skeleton-1",), "skeleton-1", (), "review")


def _event(ev, **fields):
    """Keep every timestamp equal to exercise log position ordering."""
    return {"ev": ev, "ts": "2026-10-30T12:00:00.000Z", **fields}


def _root_events(call=CHAIN.root, role=CHAIN.role, outcome="done"):
    """A root call with its complete start and ending."""
    return [_event("call.started", call=call, role=role, subject=CHAIN.subject,
                   branch="calls/" + call), _event("call.ended", call=call, outcome=outcome)]


def _review_events(run_id="review-1", outcome="failed"):
    """A review run and optionally its ending."""
    events = [_event("run.started", run=run_id, kind=review.KIND, task=CHAIN.root)]
    if outcome is not None:
        events.append(_event("run.ended", run=run_id, outcome=outcome))
    return events


def _amend_events(call="amend-1", outcome="done", root=CHAIN.root):
    """An amendment naming a root and optionally ending."""
    events = [_event("call.started", call=call, role=review.AMEND, amends=root)]
    if outcome is not None:
        events.append(_event("call.ended", call=call, outcome=outcome))
    return events


def _review_runner():
    """Answer local git and the remote launcher without running services."""
    fake = FakeRunner()
    for argv, output in [(["git", "rev-parse"], "tip-sha\n"),
                         (["git", "merge-base"], "base-sha\n"),
                         (["git", "diff", "--stat"], " file | 1 +\n"),
                         (["git", "diff"], "+change\n")]:
        fake.on(argv, Result(0, output))
    launcher = ssh(HOST.ssh, ["fab", "codex", "start", "--effort", "medium", "--model", run.MODEL, "--read-only",
                             str(ROOT / "runs/skeleton-1-1/brief.md"),
                             str(ROOT / "wt/skeleton-1-1"),
                             str(ROOT / "runs/skeleton-1-1/report.md")])
    return fake.on(launcher, Result(0, "codex-1 /state/codex-1\n"))


class LandRefusalTest(unittest.TestCase):
    def test_only_land_steps_without_queue_timestamp_are_land_refusals(self):
        record = _event("branch.rejected", branch=CHAIN.branch, step="rebase", log="CONFLICT in x")
        with tmp_home():
            for step in ("fetch", "rebase", "paths", "test", "push"):
                with self.subTest(step=step):
                    rejection = dict(record, step=step)
                    self.assertEqual(review.land_refusal("queue:" + json.dumps(rejection)), rejection)
            for rejection in (dict(record, queue_ts="queued"), dict(record, queue_ts=None),
                              dict(record, step="merge"), dict(record, step="catch-up"),
                              dict(record, step="gate:shape"), dict(record, ev="branch.landed")):
                with self.subTest(rejection=rejection):
                    self.assertIsNone(review.land_refusal("queue:" + json.dumps(rejection)))
            for refusal in ("review-1", "queue:broken", "queue:[]", "queue:null", "queue:{}"):
                with self.subTest(refusal=refusal):
                    self.assertIsNone(review.land_refusal(refusal))

    def test_land_tries_counts_refusals_by_branch_and_step_never_tip(self):
        with tmp_home():
            first = _event("branch.rejected", branch=CHAIN.branch, step="fetch", tip="same")
            second = dict(first, tip="new")
            ignored = [dict(first, branch="calls/other"), dict(first, step="push"),
                       dict(first, queue_ts="queued"), dict(first, queue_ts=None),
                       dict(first, ev="branch.landed"), _event("branch.rejected")]
            events = [*_root_events(), first, second, first, *ignored]
            self.assertEqual(review.land_tries(CHAIN, iter(events), "fetch"), [first, second, first])
            self.assertEqual(review.land_tries(CHAIN, events, "push"), [ignored[1]])

    def test_land_tries_starts_after_later_latest_ending_or_reset(self):
        refusal = _event("branch.rejected", branch=CHAIN.branch, step="push", tip="tip")
        latest = replace(CHAIN, latest="amend-1", calls=(CHAIN.root, "amend-1"))
        resets = [_event(channel.ANSWERED, subject=CHAIN.subject),
                  _event("chain.settled", call=CHAIN.root, subject=CHAIN.subject,
                         settle="settle-1", verdict="amend", text="Try again.")]
        with tmp_home():
            for reset in resets:
                for end_first in (False, True):
                    with self.subTest(reset=reset["ev"], end_first=end_first):
                        ending = _event("call.ended", call=latest.latest, outcome="done")
                        boundaries = [ending, reset] if end_first else [reset, ending]
                        events = [*_root_events(), refusal, boundaries[0], refusal, boundaries[1], refusal]
                        self.assertEqual(review.land_tries(latest, events, "push"), [refusal])

    def test_land_tries_ignores_unrelated_answers_endings_and_land_settlements(self):
        refusal = _event("branch.rejected", branch=CHAIN.branch, step="push")
        ignored = [_event(channel.ANSWERED, subject="other"),
                   _event("question.answered", subject=CHAIN.subject),
                   _event("call.ended", call="other", outcome="done"),
                   _event("chain.settled", call="other", verdict="amend"),
                   _event("chain.settled", call=CHAIN.root, verdict="land")]
        with tmp_home():
            self.assertEqual(review.land_tries(CHAIN, [*_root_events(), refusal, *ignored], "push"),
                             [refusal])


class ChainsTest(unittest.TestCase):
    def chain(self, *events):
        """Fold one root and the events of interest."""
        return review.chains(iter([*_root_events(), *events]))[CHAIN.root]

    def test_in_flight_root_is_no_chain(self):
        self.assertEqual(review.chains(_root_events()[:1]), {})

    def test_failed_root_is_no_chain(self):
        self.assertEqual(review.chains(_root_events(outcome="failed")), {})

    def test_unreviewed_role_is_no_chain(self):
        self.assertEqual(review.chains(_root_events(role="other")), {})

    def test_done_root_needs_review(self):
        self.assertEqual(self.chain(), CHAIN)

    def test_designer_roles_start_review_chains(self):
        """Every designer call that ends done roots a chain for acceptance."""
        for role in designer.ROLES:
            with self.subTest(role=role):
                self.assertEqual(review.chains(_root_events(role=role))[CHAIN.root],
                                 replace(CHAIN, role=role))

    def test_started_review_is_reviewing(self):
        self.assertEqual(self.chain(*_review_events(outcome=None)).state, "reviewing")

    def test_done_review_approves(self):
        self.assertEqual(self.chain(*_review_events(outcome="done")).state, "approved")

    def test_refusal_needs_amendment(self):
        chain = self.chain(*_review_events())
        self.assertEqual(chain.state, "amend")
        self.assertEqual(chain.refusals, ("review-1",))

    def test_queue_refusal_amends_once_then_holds_after_second_approval(self):
        first = _event("branch.rejected", task=CHAIN.branch, branch=CHAIN.branch,
                       tip="first", step="cargo", queue_ts="queued", log="/queue/first", findings="compile error")
        history = [*_review_events(outcome="done"), first]
        chain = self.chain(*history)
        self.assertEqual(chain.state, "amend")
        self.assertEqual(len(chain.refusals), 1)
        self.assertEqual(self.chain(*history, first), chain)
        with tmp_home():
            text = review.amend_brief(chain, call_id="amend", branch=CHAIN.branch, report="/report")
        self.assertEqual(text.count("Step: cargo"), 1)
        self.assertIn("compile error", text)
        self.assertIn("Log: /queue/first", text)
        history += _amend_events() + _review_events("review-2", "done")
        self.assertEqual(self.chain(*history).state, "approved")
        second = dict(first, tip="second", step="test", log="/queue/second")
        chain = self.chain(*history, second)
        self.assertEqual((chain.state, chain.reason), ("hold", "refused after its amendment"))
        self.assertEqual(len(chain.refusals), 2)
        reset = [_event("call.parked", call=CHAIN.root),
                 _event(channel.ANSWERED, subject=CHAIN.subject)]
        self.assertEqual(self.chain(*history, second, *reset).state, "review")

    def test_land_refusal_amends_then_holds_with_land_reason(self):
        first = _event("branch.rejected", branch=CHAIN.branch, step="rebase", log="CONFLICT in x")
        with tmp_home():
            chain = self.chain(first)
            self.assertEqual((chain.state, chain.reason), ("amend", ""))
            history = [first, *_amend_events(), *_review_events(outcome="done")]
            second = dict(first, log="CONFLICT in y")
            chain = self.chain(*history, second)
            self.assertEqual((chain.state, chain.reason), ("hold", review.LAND_HOLD))
            self.assertEqual(len(chain.refusals), 2)

    def test_mechanical_land_refusals_keep_approval_and_queue_refusals_still_amend(self):
        with tmp_home():
            for step in ("fetch", "push", "rebase", "paths", "test"):
                refusal = _event("branch.rejected", branch=CHAIN.branch, step=step, log="failure")
                with self.subTest(step=step):
                    chain = self.chain(*_review_events(outcome="done"), refusal)
                    mechanical = step in ("fetch", "push")
                    self.assertEqual(chain.state, "approved" if mechanical else "amend")
                    self.assertEqual(len(chain.refusals), 0 if mechanical else 1)
                    queued = self.chain(*_review_events(outcome="done"), dict(refusal, queue_ts="queued"))
                    self.assertEqual(queued.state, "amend")
                    self.assertEqual(len(queued.refusals), 1)
            history = [_event("branch.rejected", branch=CHAIN.branch, step="test"),
                       *_amend_events(), *_review_events(outcome="done")]
            self.assertEqual(self.chain(*history, dict(refusal, step="push")).state, "approved")

    def test_last_refusal_selects_hold_reason(self):
        land = _event("branch.rejected", branch=CHAIN.branch, step="test", log="failure")
        for last in (_review_events("review-2"), [dict(land, queue_ts="queued")]):
            with self.subTest(last=last), tmp_home():
                chain = self.chain(land, *_amend_events(), *last)
                self.assertEqual((chain.state, chain.reason), ("hold", "refused after its amendment"))

    def test_queue_refusals_ignore_other_branches_and_missing_steps(self):
        events = [_event("branch.rejected", branch="calls/other", step="test"),
                  _event("branch.rejected", branch=CHAIN.branch)]
        self.assertEqual(self.chain(*_review_events(outcome="done"), *events).state, "approved")

    def test_question_review_is_a_refusal(self):
        self.assertEqual(self.chain(*_review_events(outcome="question")).state, "amend")

    def test_in_flight_amendment_is_amending(self):
        chain = self.chain(*_review_events(), *_amend_events(outcome=None))
        self.assertEqual(chain.state, "amending")
        self.assertEqual(chain.calls, (CHAIN.root, "amend-1"))
        self.assertEqual(chain.latest, CHAIN.root)

    def test_done_amendment_needs_another_review(self):
        chain = self.chain(*_review_events(), *_amend_events())
        self.assertEqual(chain.state, "review")
        self.assertEqual(chain.latest, "amend-1")
        self.assertEqual(chain.refusals, ("review-1",))

    def test_second_refusal_holds(self):
        chain = self.chain(*_review_events(), *_amend_events(), *_review_events("review-2"))
        self.assertEqual((chain.state, chain.reason), ("hold", "refused after its amendment"))
        self.assertEqual(chain.refusals, ("review-1", "review-2"))

    def test_question_amendment_holds_with_outcome(self):
        chain = self.chain(*_review_events(), *_amend_events(outcome="question"))
        self.assertEqual((chain.state, chain.reason), ("hold", "the amend call ended question"))

    def test_failed_amendment_holds_before_a_review(self):
        chain = self.chain(*_amend_events(outcome="failed"), *_review_events(outcome=None))
        self.assertEqual((chain.state, chain.reason), ("hold", "the amend call ended failed"))

    def test_infra_once_retries(self):
        chain = self.chain(*_review_events(outcome="infra"))
        self.assertEqual(chain.state, "review")
        self.assertEqual(chain.refusals, ())

    def test_infra_limit_holds(self):
        events = [event for n in range(review.INFRA_LIMIT)
                  for event in _review_events(f"review-{n}", "infra")]
        chain = self.chain(*events)
        self.assertEqual((chain.state, chain.reason),
                         ("hold", f"{review.INFRA_LIMIT} review runs ended infra"))

    def test_parked_precedes_amending(self):
        chain = self.chain(*_amend_events(outcome=None), _event("call.parked", call=CHAIN.root))
        self.assertEqual(chain.state, "parked")

    def test_answer_resets_parked_chain(self):
        chain = self.chain(*_review_events(), *_amend_events(), *_review_events("review-2"),
                           _event("call.parked", call=CHAIN.root),
                           _event(channel.ANSWERED, subject=CHAIN.subject))
        self.assertEqual(chain.state, "review")
        self.assertEqual(chain.calls, (CHAIN.root, "amend-1"))
        self.assertEqual(chain.latest, "amend-1")
        self.assertEqual(chain.refusals, ("review-1", "review-2"))

    def test_refusal_after_reset_allows_amendment_again(self):
        chain = self.chain(*_review_events(), *_amend_events(), *_review_events("review-2"),
                           _event("call.parked", call=CHAIN.root),
                           _event(channel.ANSWERED, subject=CHAIN.subject),
                           *_review_events("review-3"))
        self.assertEqual(chain.state, "amend")
        self.assertEqual(chain.refusals, ("review-1", "review-2", "review-3"))

    def test_reset_restarts_infra_count(self):
        events = [event for n in range(review.INFRA_LIMIT)
                  for event in _review_events(f"review-{n}", "infra")]
        chain = self.chain(*events, _event("call.parked", call=CHAIN.root),
                           _event(channel.ANSWERED, subject=CHAIN.subject),
                           *_review_events("retry", "infra"))
        self.assertEqual(chain.state, "review")

    def test_answer_before_park_or_for_other_subject_does_not_reset(self):
        chain = self.chain(_event(channel.ANSWERED, subject=CHAIN.subject),
                           _event("call.parked", call=CHAIN.root),
                           _event(channel.ANSWERED, subject="other"))
        self.assertEqual(chain.state, "parked")

    def test_task_answer_with_same_subject_resets_nothing(self):
        chain = self.chain(*_review_events(), _event("call.parked", call=CHAIN.root),
                           _event("question.answered", task=CHAIN.subject, subject=CHAIN.subject),
                           _event(channel.ANSWERED, task=CHAIN.subject))
        self.assertEqual(chain.state, "parked")

    def test_new_park_requires_an_answer_after_it(self):
        chain = self.chain(_event("call.parked", call=CHAIN.root),
                           _event(channel.ANSWERED, subject=CHAIN.subject),
                           _event("call.parked", call=CHAIN.root))
        self.assertEqual(chain.state, "parked")

    def test_finished_root_precedes_parked(self):
        chain = self.chain(_event("call.parked", call=CHAIN.root),
                           _event("call.finished", call=CHAIN.root, outcome="failed"))
        self.assertEqual(chain.state, "finished")

    def test_finished_amendment_finishes_chain(self):
        chain = self.chain(*_amend_events(), _event("call.finished", call="amend-1"))
        self.assertEqual(chain.state, "finished")

    def test_unknown_amendment_root_is_ignored(self):
        self.assertEqual(self.chain(*_amend_events(root="unknown")), CHAIN)

    def test_each_answer_after_the_last_park_resets_again(self):
        chain = self.chain(_event("call.parked", call=CHAIN.root),
                           _event(channel.ANSWERED, subject=CHAIN.subject),
                           *_review_events(),
                           _event(channel.ANSWERED, subject=CHAIN.subject))
        self.assertEqual(chain.state, "review")
        self.assertEqual(chain.refusals, ("review-1",))

    def test_in_flight_review_takes_precedence_over_reset(self):
        chain = self.chain(*_review_events(outcome=None),
                           _event("call.parked", call=CHAIN.root),
                           _event(channel.ANSWERED, subject=CHAIN.subject))
        self.assertEqual(chain.state, "reviewing")

    def test_review_after_amendment_can_approve(self):
        chain = self.chain(*_review_events(), *_amend_events(),
                           *_review_events("review-2", "done"))
        self.assertEqual(chain.state, "approved")
        self.assertEqual(chain.latest, "amend-1")

    def test_root_with_amends_field_is_not_a_root(self):
        events = _root_events()
        events[0]["amends"] = "unknown"
        self.assertEqual(review.chains(events), {})

    def test_chains_follow_root_end_order(self):
        first, second = _root_events("first"), _root_events("second")
        self.assertEqual(list(review.chains([first[0], *second, first[1]])), ["second", "first"])

    def test_missing_required_fields_are_skipped(self):
        events = [_event("call.started", call="bad", role="skeleton"),
                  _event("call.ended", call="bad", outcome="done"),
                  _event("call.started", role="skeleton", subject="x", branch="x"),
                  _event("call.ended"), _event("call.parked"), _event("call.finished"),
                  _event(channel.ANSWERED), _event("run.started", task=CHAIN.root, kind="review"),
                  _event("run.ended", run="review-1")]
        self.assertEqual(self.chain(*events), CHAIN)

    def test_first_review_end_wins(self):
        chain = self.chain(*_review_events(outcome="done"),
                           _event("run.ended", run="review-1", outcome="failed"))
        self.assertEqual(chain.state, "approved")
        self.assertEqual(chain.refusals, ())

    def test_other_kind_and_unknown_task_runs_are_ignored(self):
        chain = self.chain(_event("run.started", run="wrong-kind", task=CHAIN.root, kind="implement"),
                           _event("run.ended", run="wrong-kind", outcome="done"),
                           _event("run.started", run="wrong-task", task="unknown", kind="review"),
                           _event("run.ended", run="wrong-task", outcome="done"))
        self.assertEqual(chain, CHAIN)

    def test_settlement_land_overrides_each_hold_and_old_park(self):
        histories = [*_review_events(), *_amend_events(), *_review_events("review-2")]
        for verdict, state in (("land", "approved"), ("amend", "review"), ("user", "parked")):
            with self.subTest(verdict=verdict):
                chain = self.chain(*histories,
                    _event("call.parked", call=CHAIN.root, reason="refused after its amendment"),
                    _event("chain.settled", call=CHAIN.root, subject=CHAIN.subject,
                           settle="settle-1", verdict=verdict, text="Resolve the findings."))
                self.assertEqual(chain.state, state)
                self.assertEqual(chain.refusals, ("review-1", "review-2"))
        failed = [*_amend_events(outcome="failed"),
                  _event("chain.settled", call=CHAIN.root, subject=CHAIN.subject,
                         settle="settle-1", verdict="land", text="Good enough.")]
        self.assertEqual(self.chain(*failed).state, "approved")
        self.assertEqual(self.chain(*failed, _event("call.finished", call=CHAIN.root)).state, "finished")

    def test_settlement_amend_resets_infra_and_amend_counts(self):
        settle = _event("chain.settled", call=CHAIN.root, subject=CHAIN.subject,
                        settle="settle-1", verdict="amend", text="Try this.")
        infra = [event for number in range(review.INFRA_LIMIT)
                 for event in _review_events(f"infra-{number}", "infra")]
        self.assertEqual(self.chain(*infra, settle, *_review_events("retry", "infra")).state, "review")
        self.assertEqual(self.chain(*_amend_events(outcome="failed"), settle,
                                    *_review_events()).state, "amend")

    def test_old_parks_reopen_only_for_automatic_hold_reasons(self):
        history = [*_review_events(), *_amend_events(), *_review_events("review-2")]
        for reason in ("refused after its amendment", "the amend call ended failed",
                       "3 review runs ended infra", "user: choose capacity", "settle failed", ""):
            with self.subTest(reason=reason):
                parked = _event("call.parked", call=CHAIN.root, reason=reason)
                self.assertEqual(self.chain(*history, parked).state,
                                 "hold" if review.hold_reason(reason) else "parked")
                self.assertEqual(self.chain(*history, parked,
                    _event(channel.ANSWERED, subject=CHAIN.subject)).state, "review")
        settled = _event("chain.settled", call=CHAIN.root, subject=CHAIN.subject,
                         settle="settle-1", verdict="amend", text="Fix it.")
        self.assertEqual(self.chain(*history, settled,
            _event("call.parked", call=CHAIN.root, reason="refused after its amendment")).state, "parked")

    def test_attempts_survive_settlement_amend_but_user_reset_grants_more(self):
        first = _event("call.started", call="settle-1", role="settle", settles=CHAIN.root)
        second = dict(first, call="settle-2")
        settled = _event("chain.settled", call=CHAIN.root, subject=CHAIN.subject,
                         settle="settle-1", verdict="amend", text="Fix it.")
        events = [first, settled, second]
        self.assertEqual(review.settle_calls(CHAIN, iter(events)), ["settle-1", "settle-2"])
        events += [_event("call.parked", call=CHAIN.root),
                   _event(channel.ANSWERED, subject=CHAIN.subject), dict(first, call="settle-3")]
        self.assertEqual(review.settle_calls(CHAIN, events), ["settle-3"])



class BriefTest(unittest.TestCase):
    def brief(self, chain=CHAIN, diff="+short\n", *, designs=(), answers=""):
        """Use distinctive facts and optional changed designs for exact assertions."""
        return review.brief(chain, run_id="run-1", base="base", tip="tip", stat="file | 1 +\n",
                            diff=diff, report="/reports/run-1.md", designs=designs, answers=answers)

    def test_sections_facts_findings_and_original_brief_in_order(self):
        with tmp_home() as home:
            original = "# Task\n\nKeep this verbatim.\n\n"
            atomic.write(home / "fab/calls" / CHAIN.root / "brief.md", original)
            for run_id in ("refusal-1", "refusal-2"):
                atomic.write(home / "fab/runs" / run_id / "report.md",
                             "\n".join(f"{run_id} line {n}" for n in range(review.FINDINGS_LINES + 1)))
            chain = replace(CHAIN, calls=(CHAIN.root, "amend-1"), latest="amend-1",
                            refusals=("refusal-1", "refusal-2"))
            text = self.brief(chain)
            sections = [review.ROLE.read_text().rstrip("\n"), "# Your review", "# Earlier findings",
                        "## refusal-1", "## refusal-2", "# The diff", "# The call's brief"]
            self.assertEqual([text.index(section) for section in sections],
                             sorted(text.index(section) for section in sections))
            self.assertIn("- Run: run-1\n- Call: skeleton-1 (skeleton)\n- Amended by: amend-1\n"
                          "- Subject: draft/part\n- Branch: `calls/skeleton-1`\n- Base: `base`\n"
                          "- Tip: `tip`\n- Report: write it to `/reports/run-1.md`\n", text)
            self.assertIn("Your checkout is the tip, read-only; `git diff base tip` is the change.", text)
            self.assertIn("refusal-1 line 39", text)
            self.assertNotIn("refusal-1 line 40", text)
            self.assertTrue(text.endswith("What the call was asked, verbatim, to the end of this brief:\n\n" + original))

    def test_retire_brief_uses_consistency_and_lists_designs_after_facts(self):
        """Retirement replaces the reviewer role and inserts designs before findings."""
        chain = replace(CHAIN, role="retire", subject="draft/retire", refusals=("refused",))
        for designs in ((), ("docs/design/a.md", "docs/design/b.md")):
            with self.subTest(designs=designs), tmp_home():
                text = self.brief(chain, designs=designs)
                role = review.CONSISTENCY.read_text().rstrip("\n")
                self.assertTrue(text.startswith(role + "\n\n# Your review\n"))
                expected = "\n".join(f"- `{path}`" for path in designs) or "(none)"
                sections = ["# Your review", "# Designs changed since the plan started\n\n" + expected,
                            "# Earlier findings", "# The diff", "# The call's brief"]
                positions = [text.index(section) for section in sections]
                self.assertEqual(positions, sorted(positions))
                self.assertNotIn(review.ROLE.read_text().rstrip("\n"), text)

    def test_other_roles_ignore_changed_designs(self):
        """A designs argument leaves every non-retire review brief unchanged."""
        with tmp_home():
            for role in review.REVIEWED:
                if role == "retire":
                    continue
                with self.subTest(role=role):
                    chain = replace(CHAIN, role=role)
                    self.assertEqual(self.brief(chain, designs=("docs/design/a.md",)), self.brief(chain))
                    self.assertTrue(self.brief(chain).startswith(review.ROLE.read_text().rstrip("\n")))

    def test_missing_brief_and_report_have_markers(self):
        with tmp_home() as home:
            text = self.brief(replace(CHAIN, refusals=("lost",)))
            self.assertIn("## lost\n\n(report missing)", text)
            self.assertIn(f"(brief missing: {home}/fab/calls/{CHAIN.root}/brief.md)", text)
            self.assertTrue(text.endswith("\n"))

    def test_no_findings_or_amended_by_for_unamended_root(self):
        with tmp_home():
            text = self.brief()
            self.assertNotIn("# Earlier findings", text)
            self.assertNotIn("Amended by", text)

    def test_answers_follow_findings_or_review_facts_and_precede_diff(self):
        with tmp_home():
            for refusals in ((), ("refusal-1",)):
                with self.subTest(refusals=refusals):
                    chain = replace(CHAIN, refusals=refusals)
                    plain = self.brief(chain)
                    self.assertNotIn(channel.SECTION, plain)
                    self.assertEqual(self.brief(chain, answers=""), plain)
                    text = self.brief(chain, answers="Question: Capacity?\nAnswer (user): Buy it")
                    earlier = "# Earlier findings" if refusals else "# Your review"
                    self.assertLess(text.index(earlier), text.index(channel.SECTION))
                    self.assertLess(text.index(channel.SECTION), text.index("# The diff"))
                    self.assertEqual(text.replace(channel.SECTION +
                                     "\n\nQuestion: Capacity?\nAnswer (user): Buy it\n\n", ""), plain)

    def test_short_diff_is_whole_including_trailing_blank_lines(self):
        with tmp_home():
            text = self.brief(diff="+first\n+last\n\n")
            self.assertIn("```text\nfile | 1 +\n```\n\n```diff\n+first\n+last\n\n```", text)
            self.assertNotIn("The diff is cut", text)

    def test_long_diff_cuts_at_last_newline(self):
        with tmp_home():
            prefix = "+first\n"
            text = self.brief(diff=prefix + "x" * review.DIFF_LIMIT)
            self.assertIn("```diff\n+first\n```", text)
            self.assertNotIn("xxxxx", text)
            self.assertIn(f"The diff is cut at {review.DIFF_LIMIT} characters; read the rest with "
                          "`git diff base tip`.", text)

    def test_diff_limit_is_inclusive_and_no_newline_can_yield_empty_excerpt(self):
        with tmp_home(), patch.object(review, "DIFF_LIMIT", 7):
            self.assertNotIn("The diff is cut", self.brief(diff="1234567"))
            self.assertIn("```diff\n1234567\n```", self.brief(diff="1234567\nrest"))
            self.assertIn("```diff\n\n```", self.brief(diff="12345678"))

    def test_amend_brief_sections_facts_and_earlier_amendments(self):
        with tmp_home() as home:
            chain = replace(CHAIN, calls=(CHAIN.root, "amend-1", "amend-2"),
                            refusals=("refusal-1", "refusal-2"))
            atomic.write(home / "fab/runs/refusal-1/report.md", "Failed: fix this\n")
            text = review.amend_brief(chain, call_id="new-call", branch="new-branch", report="/report")
            self.assertEqual([line for line in text.splitlines() if line.startswith("# ")],
                             ["# Role", "# You are the amender", "# Call facts", "# The call you amend", "# Findings"])
            self.assertIn("# Role\n\n" + review.AMENDER.read_text().rstrip("\n"), text)
            self.assertIn("# Call facts\n\n" + calls._facts("new-call", "new-branch", "/report"), text)
            self.assertIn(f"- Its brief: `{home}/fab/calls/{CHAIN.root}/brief.md`", text)
            for call in chain.calls[1:]:
                self.assertIn(f"- Amended by: {call} (report `{home}/fab/calls/{call}/report.md`)", text)
            self.assertIn("Read its brief first: it is the task you are finishing.", text)
            self.assertIn("## refusal-1\n\nFailed: fix this\n\n## refusal-2\n\n(report missing)", text)

    def test_land_amend_brief_names_step_quotes_conflict_and_lists_design_status(self):
        record = _event("branch.rejected", branch=CHAIN.branch, step="rebase",
                        log="Rebasing (1/1)\nCONFLICT (content): Merge conflict in docs/design/x.status.md")
        chain = replace(CHAIN, role="retire", refusals=("queue:" + json.dumps(record),))
        with tmp_home():
            options = dict(call_id="id", branch=chain.branch, report="report")
            plain = review.amend_brief(chain, **options)
            text = review.amend_brief(chain, designs=("docs/design/x.md",), **options)
            findings = ("## `fab land` refused at rebase\n\nStep: rebase\nLog:\n" + record["log"])
            self.assertIn(findings, plain)
            self.assertNotIn("## Queue rejection", plain)
            self.assertNotIn("# Designs main changed since your branch", plain)
            section = ("# Designs main changed since your branch\n\n"
                       "- `docs/design/x.md` (status `docs/design/x.status.md`)\n\n"
                       "Main changed these designs after your branch's tip: check each one's status file "
                       "against what your branch writes.\n")
            self.assertEqual(text, plain + "\n" + section)
            queue = replace(chain, refusals=("queue:" + json.dumps(dict(record, queue_ts="queued")),))
            self.assertIn("## Queue rejection\n\nStep: rebase", review.amend_brief(queue, **options))

    def test_test_refusal_brief_names_rebase_outcome_in_findings(self):
        refusal = _event("branch.rejected", branch=CHAIN.branch, step="test", log="test failed")
        chain = replace(CHAIN, refusals=("queue:" + json.dumps(refusal),))
        with tmp_home():
            for outcome, phrase in (("rebased", "was rebased onto origin/main and pushed"),
                                    ("conflicted", "conflicted and was aborted; nothing was pushed"),
                                    ("pending", "would be rebased onto origin/main and pushed")):
                with self.subTest(outcome=outcome):
                    text = review.amend_brief(chain, call_id="id", branch=chain.branch,
                                              report="report", rebase=outcome)
                    findings = text.split("# Findings\n\n", 1)[1]
                    self.assertIn("## `fab land` refused at test", findings)
                    self.assertIn("test failed", findings)
                    self.assertIn(phrase, findings)

    def test_amend_brief_without_refusals(self):
        with tmp_home():
            text = review.amend_brief(CHAIN, call_id="id", branch="branch", report="report")
            self.assertTrue(text.endswith("# Findings\n\n(none)\n"))
            self.assertNotIn("- Amended by:", text)

    def test_amend_brief_uses_calls_size_limit(self):
        with tmp_home(), patch.object(calls, "BRIEF_LIMIT", 20):
            with self.assertRaisesRegex(ValueError, "BRIEF_LIMIT"):
                review.amend_brief(CHAIN, call_id="id", branch="branch", report="report")

    def test_calls_start_rebinds_amend_facts_only(self):
        with tmp_home():
            text = review.amend_brief(CHAIN, call_id="placeholder", branch="placeholder", report="placeholder")
            fake = FakeRunner().on(["claude"], Result(0, "{}"))
            result = calls.start("review", "subject", Path("/checkout"), text, sh=fake)
            rebound = (log.home() / "calls" / result["call"] / "brief.md").read_text()
            self.assertIn(calls._facts(result["call"], result["branch"], result["report"]), rebound)
            self.assertNotIn("placeholder", rebound)
            self.assertEqual(rebound.split("# The call you amend", 1)[1],
                             text.split("# The call you amend", 1)[1])

    def test_land_hold_settle_permits_amend_or_user_then_user_only(self):
        record = _event("branch.rejected", branch=CHAIN.branch, step="rebase", log="CONFLICT in x")
        chain = replace(CHAIN, state="hold", reason=review.LAND_HOLD,
                        refusals=("queue:" + json.dumps(record),))
        attempt = _event("call.started", call="settle-1", role="settle", settles=chain.root)
        choices = (([], "A land verdict would land the tip fab land just refused "
                       "(refused again at rebase, paths or test): choose amend or user."),
                   ([attempt], "Amend is no longer an option, and land would land the tip "
                               "fab land refused: user only."))
        for events, restriction in choices:
            with self.subTest(events=events), tmp_home():
                text = review.settle_brief(chain, Path("/checkout"), events, call_id="settle",
                                           branch="", report="/report", sh=_review_runner())
                self.assertIn(restriction, text)
                self.assertIn("- Hold: " + review.LAND_HOLD, text)
                self.assertIn("## `fab land` refused at rebase\n\nStep: rebase\nLog:\nCONFLICT in x", text)
                self.assertNotIn("## Queue rejection", text)

    def test_settle_brief_has_chain_evidence_diff_and_restricted_second_choice(self):
        with tmp_home() as home:
            chain = replace(CHAIN, calls=(CHAIN.root, "amend-1"), latest="amend-1",
                            refusals=("review-1", "review-2"), state="hold", reason="refused after its amendment")
            atomic.write(home / "fab/calls/amend-1/report.md", "Done: amended\nCovered blocks.\n")
            for run_id in chain.refusals:
                atomic.write(home / "fab/runs" / run_id / "report.md", f"Failed: {run_id} findings\n")
            fake = _review_runner()
            options = dict(call_id="settle", branch="", report="/report", sh=fake)
            first = review.settle_brief(chain, Path("/checkout"), [], **options)
            attempt = _event("call.started", call="settle-1", role="settle", settles=chain.root)
            second = review.settle_brief(chain, Path("/checkout"), [attempt], **options)
            self.assertIn("Choose land, amend or user.", first)
            self.assertIn("Amend is no longer an option: land or user only.", second)
            for text in (first, second):
                for expected in (str(home / "fab/calls/skeleton-1/brief.md"),
                                 "- Hold: refused after its amendment", "- Base: `base-sha`", "- Tip: `tip-sha`",
                                 "Failed: review-1 findings", "Failed: review-2 findings", "Covered blocks.",
                                 str(home / "fab/calls/amend-1/report.md"), "+change"):
                    self.assertIn(expected, text)
            self.assertTrue(all(call.cwd == "/checkout" for call in fake.calls))
            self.assertEqual(fake.argvs()[:5], [["git", "fetch", "origin"],
                ["git", "rev-parse", "--verify", "refs/remotes/origin/calls/skeleton-1^{commit}"],
                ["git", "merge-base", "refs/remotes/origin/main", "tip-sha"],
                ["git", "diff", "--stat", "base-sha", "tip-sha"], ["git", "diff", "base-sha", "tip-sha"]])



class StartTest(unittest.TestCase):
    def test_git_snapshot_detached_checkout_and_review_launch(self):
        with tmp_home() as home:
            fake = _review_runner()
            events = [_event("run.started", task=CHAIN.root), _event("run.started", task="other"),
                      _event(channel.ANSWERED, subject=CHAIN.subject, answer="Buy capacity"),
                      _event(channel.ANSWERED, subject="other", answer="Ignore other subject"),
                      _event("question.answered", task=CHAIN.subject, answer="Ignore task answer")]
            # The fake accepts the numbered launch while all commands remain observable.
            fake.on(["ssh"], Result(0, "codex-2 /state/codex-2\n"))
            path = home / "custom/log.jsonl"
            chain = replace(CHAIN, latest="amend-1")
            run_id = review.start(chain, "agents", Path("/checkout"), HOST, iter(events), sh=fake,
                                  log_path=path)
            self.assertEqual(run_id, "skeleton-1-2")
            self.assertEqual([call.argv for call in fake.calls[:5]], [
                ["git", "fetch", "origin"],
                ["git", "rev-parse", "--verify", "refs/remotes/origin/calls/skeleton-1^{commit}"],
                ["git", "merge-base", "refs/remotes/origin/main", "tip-sha"],
                ["git", "diff", "--stat", "base-sha", "tip-sha"],
                ["git", "diff", "base-sha", "tip-sha"]])
            self.assertTrue(all(call.cwd == "/checkout" for call in fake.calls[:5]))
            self.assertEqual(fake.calls[5].argv, ["git", "show", "tip-sha:docs/plan/draft/plan.toml"])
            self.assertEqual(fake.calls[5].cwd, "/checkout")
            self.assertEqual(fake.calls[9].argv, ssh(HOST.ssh,
                ["git", "-C", str(ROOT / "repos/agents"), "worktree", "add", "--detach",
                 str(ROOT / "wt" / run_id), "tip-sha"]))
            directory = ROOT / "runs" / run_id
            self.assertEqual(fake.calls[-1].argv, ssh(HOST.ssh,
                ["fab", "codex", "start", "--effort", "medium", "--model", run.MODEL, "--read-only",
                 str(directory / "brief.md"), str(ROOT / "wt" / run_id), str(directory / "report.md")]))
            record, = log.read(path)
            self.assertEqual({key: value for key, value in record.items() if key != "ts"},
                             {"ev": "run.started", "run": run_id, "task": CHAIN.root,
                              "kind": "review", "host": HOST.name, "dir": str(ROOT / "wt" / run_id),
                              "branch": CHAIN.branch, "base": "base-sha", "codex": "codex-2",
                              "state": "/state/codex-2", "report": str(directory / "report.md"),
                              "call": "amend-1", "tip": "tip-sha"})
            self.assertEqual(log.read(), [])
            text = (home / "fab/runs" / run_id / "brief.md").read_text()
            self.assertEqual(fake.calls[-2].input, text)
            self.assertIn("- Amended by: amend-1", text)
            self.assertIn("+change", text)
            self.assertIn(channel.SECTION, text)
            self.assertIn("Answer (-): Buy capacity", text)
            self.assertNotIn("Ignore", text)

    def test_fabrig_review_reads_the_nested_plan_at_the_tip(self):
        with tmp_home():
            fake = _review_runner()
            fake.on(["git", "ls-tree"], Result(0, "README.md\nskein/docs/plan/draft/plan.toml\n"))
            fake.on(["git", "show", "tip-sha:skein/docs/plan/draft/plan.toml"],
                    Result(0, 'sources = ["skein/docs/draft.md"]'))
            fake.on(["git", "show", "tip-sha:skein/docs/draft.md"], Result(0, "Rust draft."))
            with patch.object(run, "launch_detached", return_value="review-id") as launch:
                review.start(CHAIN, "fabrig", Path("/checkout"), HOST, (), sh=fake)
            self.assertEqual(launch.call_args.args[2], "fabrig")
            self.assertIn("Rust draft.", launch.call_args.kwargs["brief"])
            self.assertNotIn(["git", "show", "tip-sha:docs/plan/draft/plan.toml"], fake.argvs())

    def test_fabrig_review_refuses_missing_or_ambiguous_plan_paths(self):
        for paths in ("README.md\n", "one/docs/plan/draft/plan.toml\ntwo/docs/plan/draft/plan.toml\n"):
            with self.subTest(paths=paths), tmp_home():
                fake = _review_runner().on(["git", "ls-tree"], Result(0, paths))
                with patch.object(run, "launch_detached") as launch, self.assertRaisesRegex(ValueError, "expected one plan"):
                    review.start(CHAIN, "fabrig", Path("/checkout"), HOST, (), sh=fake)
                launch.assert_not_called()

    def test_start_carries_whole_drafts_at_tip_independently_of_call_excerpts(self):
        sources = ("docs/draft/code.md", "docs/draft/landing.md", "docs/draft/execution.md")
        drafts = {source: f"# {source}\n\n## Cited\nCited words.\n\n## Other\nUncited {source}.\n"
                  for source in sources}
        subjects = {"skeleton": "draft/nested/part", "contract": "draft/nested/part",
                    "answer": "draft/nested", "review": "draft/nested/review", "cut": "draft/nested/cut",
                    "decision": "draft/nested/part/decision", "retire": "draft/nested/retire"}
        for role, subject in subjects.items():
            with self.subTest(role=role), tmp_home() as home:
                original = "# The user's drafts\n\n## Cited\nCited words.\n"
                atomic.write(home / "fab/calls" / CHAIN.root / "brief.md", original)
                fake = _review_runner().on(["git", "show", "tip-sha:docs/plan/draft/nested/plan.toml"],
                                           Result(0, "sources = " + json.dumps(sources)))
                for source, draft in drafts.items():
                    fake.on(["git", "show", f"tip-sha:{source}"], Result(0, draft))
                chain = replace(CHAIN, role=role, subject=subject)
                with patch.object(designer, "changed_designs", return_value=[]), \
                     patch.object(run, "launch_detached", return_value="review-id") as launch:
                    self.assertEqual(review.start(chain, "agents", Path("/checkout"), HOST, (), sh=fake),
                                     "review-id")
                text = launch.call_args.kwargs["brief"]
                whole = text.split("# The user's drafts\n\n", 1)[1].split("# The call's brief\n\n", 1)[0]
                for source, draft in drafts.items():
                    self.assertIn(f"## {source}\n\n{draft}", whole)
                self.assertTrue(text.endswith(original))
                self.assertIn(["git", "show", "tip-sha:docs/plan/draft/nested/plan.toml"], fake.argvs())
                self.assertTrue(all(call.cwd == "/checkout" for call in fake.calls))

    def test_start_has_whole_drafts_even_when_call_brief_is_missing(self):
        with tmp_home():
            fake = _review_runner().on(["git", "show", "tip-sha:docs/plan/draft/plan.toml"],
                                       Result(0, 'sources = ["docs/draft.md", "elsewhere", "/external", "../outside"]'))
            fake.on(["git", "show", "tip-sha:docs/draft.md"], Result(0, "Whole draft.\n"))
            fake.on(["git", "show", "tip-sha:elsewhere"], Result(128, err="not in tree"))
            with patch.object(run, "launch_detached", return_value="review-id") as launch:
                review.start(CHAIN, "agents", Path("/checkout"), HOST, (), sh=fake)
            text = launch.call_args.kwargs["brief"]
            self.assertIn("# The user's drafts\n\n## docs/draft.md\n\nWhole draft.\n", text)
            for source in ("elsewhere", "/external", "../outside"):
                self.assertIn(f"## {source}\n\n(not a file in this repository)", text)
            self.assertIn("(brief missing:", text)
            self.assertNotIn(["git", "show", "tip-sha:/external"], fake.argvs())
            self.assertNotIn(["git", "show", "tip-sha:../outside"], fake.argvs())

    def test_unreadable_or_malformed_plan_starts_nothing(self):
        for result, error in ((Result(128, err="missing plan"), Failed),
                              (Result(0, "not TOML"), ValueError)):
            with self.subTest(result=result), tmp_home():
                fake = _review_runner().on(["git", "show", "tip-sha:docs/plan/draft/plan.toml"], result)
                with patch.object(run, "launch_detached") as launch, self.assertRaises(error):
                    review.start(CHAIN, "agents", Path("/checkout"), HOST, (), sh=fake)
                launch.assert_not_called()
                self.assertEqual(log.read(), [])
                self.assertTrue(all(argv[0] == "git" for argv in fake.argvs()))

    def test_retire_start_passes_changed_designs_at_the_reviewed_tip(self):
        """Consistency reviews list designs from the plan history at this branch's tip."""
        with tmp_home():
            fake = _review_runner()
            chain = replace(CHAIN, role="retire", subject="draft/nested/retire")
            designs = ["docs/design/a.md", "docs/design/b.md"]
            with patch.object(designer, "changed_designs", return_value=designs) as changed, \
                 patch.object(review, "brief", wraps=review.brief) as brief, \
                 patch.object(run, "launch_detached", return_value="review-id") as launch:
                self.assertEqual(review.start(chain, "agents", Path("/checkout"), HOST, (), sh=fake),
                                 "review-id")
            changed.assert_called_once_with(Path("/checkout"), "draft/nested", rev="tip-sha", sh=fake)
            self.assertEqual(brief.call_args.kwargs["designs"], designs)
            text = launch.call_args.kwargs["brief"]
            self.assertIn("# Designs changed since the plan started\n\n- `docs/design/a.md`\n"
                          "- `docs/design/b.md`", text)
            self.assertTrue(text.startswith(review.CONSISTENCY.read_text().rstrip("\n")))

    def test_failed_changed_designs_starts_nothing(self):
        """Missing history and git failures prevent any builder launch or run record."""
        failures = (ValueError("no plan history"), Failed(["git", "log"], Result(1, err="git failed")))
        for failure in failures:
            with self.subTest(failure=failure), tmp_home():
                fake = _review_runner()
                chain = replace(CHAIN, role="retire", subject="draft/retire")
                with patch.object(designer, "changed_designs", side_effect=failure), \
                     patch.object(run, "launch_detached") as launch, self.assertRaises(type(failure)):
                    review.start(chain, "agents", Path("/checkout"), HOST, (), sh=fake)
                launch.assert_not_called()
                self.assertTrue(all(argv[0] == "git" for argv in fake.argvs()))
                self.assertEqual(log.read(), [])

    def test_failed_launch_removes_worktree_and_reraises(self):
        with tmp_home():
            fake = _review_runner()
            launcher = fake.rules[-1][0]
            fake.rules[-1] = (launcher, Result(2, err="launch refused"))
            cleanup = ssh(HOST.ssh, ["git", "-C", str(ROOT / "repos/agents"), "worktree", "remove",
                                     "--force", str(ROOT / "wt/skeleton-1-1")])
            fake.on(cleanup, Result(1, err="cleanup also failed"))
            with self.assertRaisesRegex(Failed, "launch refused"):
                review.start(CHAIN, "agents", Path("/checkout"), HOST, (), sh=fake)
            self.assertEqual(fake.calls[-1].argv, cleanup)
            self.assertEqual(log.read(), [])

    def test_failed_fetch_does_not_contact_builder(self):
        with tmp_home():
            fake = FakeRunner().on(["git", "fetch"], Result(1, err="fetch failed"))
            with self.assertRaises(Failed):
                review.start(CHAIN, "agents", Path("/checkout"), HOST, (), sh=fake)
            self.assertEqual(fake.argvs(), [["git", "fetch", "origin"]])
            self.assertEqual(log.read(), [])

    def test_failed_worktree_add_does_not_launch_or_remove(self):
        with tmp_home():
            fake = _review_runner()
            add = ssh(HOST.ssh, ["git", "-C", str(ROOT / "repos/agents"), "worktree", "add",
                                "--detach", str(ROOT / "wt/skeleton-1-1"), "tip-sha"])
            fake.on(add, Result(1, err="cannot add"))
            with self.assertRaisesRegex(Failed, "cannot add"):
                review.start(CHAIN, "agents", Path("/checkout"), HOST, (), sh=fake)
            self.assertEqual(fake.calls[-1].argv, add)
            self.assertEqual(log.read(), [])


class TaskSourceTest(unittest.TestCase):
    def setUp(self):
        from fab.plan import Task
        self.task = Task("draft/task", "part", "feature", "agents", (), (), "high", 25, "", "task.md")
        self.checked = _event("call.checked", call=CHAIN.root, root=CHAIN.root,
                              subject=CHAIN.subject, tip="skeleton-tip", outcome="green", tasks=[self.task.id])
        self.events = [*_root_events(), self.checked]
        self.started = _event("run.started", task=self.task.id, run="task-1", kind="implement",
                              branch=self.task.id, base="skeleton-tip")

    def test_fresh_tasks_use_only_green_checks_for_their_part_and_id(self):
        source = review.task_source(self.task, iter(self.events))
        self.assertEqual((source[0], source[1].root), (self.checked, CHAIN.root))
        for changes in ({"outcome": "red"}, {"subject": "draft/elsewhere"}, {"tasks": ["draft/other"]}):
            with self.subTest(changes=changes):
                self.assertIsNone(review.task_source(self.task, [*_root_events(), {**self.checked, **changes}]))

    def test_first_run_base_preserves_origin_across_later_checks_and_runs(self):
        events = [*self.events, self.started,
                  {**self.checked, "call": "amend-1", "tip": "amended-tip"},
                  _event("run.started", task=self.task.id, run="task-2", kind="rebase", base="origin/main")]
        self.assertEqual(review.task_source(self.task, events)[0]["tip"], "skeleton-tip")
        self.assertIsNone(review.task_source(self.task, [*self.events, {**self.started, "base": "origin/main"}]))

    def test_new_tasks_after_landing_use_main(self):
        events = [*self.events, _event("call.finished", call=CHAIN.root, outcome="done", tip="skeleton-tip")]
        self.assertIsNone(review.task_source(self.task, events))
        events[-1] = {**events[-1], "outcome": "failed"}
        self.assertEqual(review.task_source(self.task, events)[0]["tip"], "skeleton-tip")

    def test_same_tip_and_failed_finishes_need_no_amendment_rebase(self):
        for outcome, tip in (("done", "skeleton-tip"), ("failed", "amended-tip")):
            with self.subTest(outcome=outcome):
                events = [*self.events, self.started, _event("call.finished", call=CHAIN.root, outcome=outcome, tip=tip)]
                self.assertIsNone(review.task_rebase(self.task, events))

    def test_integration_amendment_is_consumed_only_by_a_done_rebase_onto_its_trunk(self):
        trunk = "draft/integration"
        for base, outcome, consumed in ((f"origin/{trunk}", "done", True),
                                       ("origin/main", "done", False),
                                       (f"origin/{trunk}", "infra", False),
                                       (f"origin/{trunk}", "failed", False)):
            with self.subTest(base=base, outcome=outcome):
                events = [*self.events, self.started, *_amend_events(),
                          _event("call.finished", call="amend-1", outcome="done", tip="amended-tip"),
                          _event("run.started", task=self.task.id, run="rebase", kind="rebase", base=base),
                          _event("run.ended", run="rebase", outcome=outcome)]
                context = review.task_rebase(self.task, iter(events), trunk=trunk)
                self.assertEqual(context is None, consumed)

    def test_amendment_rebase_consumed_only_by_a_rebase_after_landing(self):
        events = [*self.events, self.started, *_amend_events(),
                  _event("run.started", task=self.task.id, run="early-rebase", kind="rebase", base="origin/main"),
                  _event("call.finished", call="amend-1", outcome="done", tip="amended-tip")]
        context = review.task_rebase(self.task, events)
        self.assertEqual((context["old_tip"], context["tip"], context["step"]),
                         ("skeleton-tip", "amended-tip", "rebase"))
        events.append(_event("run.started", task=self.task.id, run="repair", kind="repair", base="skeleton-tip"))
        self.assertIsNotNone(review.task_rebase(self.task, events))
        events.append(_event("run.started", task=self.task.id, run="rebase", kind="rebase", base="origin/main"))
        self.assertIsNotNone(review.task_rebase(self.task, events))
        events.append(_event("run.ended", run="rebase", outcome="infra"))
        self.assertIsNotNone(review.task_rebase(self.task, events))
        events.append(_event("run.started", task=self.task.id, run="rebase-2", kind="rebase", base="origin/main"))
        events.append(_event("run.ended", run="rebase-2", outcome="done"))
        self.assertIsNone(review.task_rebase(self.task, events))
