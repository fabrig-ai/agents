import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fab import atomic, call_review as review, calls, designer, log, run
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
                           _event("question.answered", task=CHAIN.subject))
        self.assertEqual(chain.state, "review")
        self.assertEqual(chain.calls, (CHAIN.root, "amend-1"))
        self.assertEqual(chain.latest, "amend-1")
        self.assertEqual(chain.refusals, ("review-1", "review-2"))

    def test_refusal_after_reset_allows_amendment_again(self):
        chain = self.chain(*_review_events(), *_amend_events(), *_review_events("review-2"),
                           _event("call.parked", call=CHAIN.root),
                           _event("question.answered", task=CHAIN.subject),
                           *_review_events("review-3"))
        self.assertEqual(chain.state, "amend")
        self.assertEqual(chain.refusals, ("review-1", "review-2", "review-3"))

    def test_reset_restarts_infra_count(self):
        events = [event for n in range(review.INFRA_LIMIT)
                  for event in _review_events(f"review-{n}", "infra")]
        chain = self.chain(*events, _event("call.parked", call=CHAIN.root),
                           _event("question.answered", task=CHAIN.subject),
                           *_review_events("retry", "infra"))
        self.assertEqual(chain.state, "review")

    def test_answer_before_park_or_for_other_subject_does_not_reset(self):
        chain = self.chain(_event("question.answered", task=CHAIN.subject),
                           _event("call.parked", call=CHAIN.root),
                           _event("question.answered", task="other"))
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
                           _event("question.answered", task=CHAIN.subject),
                           *_review_events(),
                           _event("question.answered", task=CHAIN.subject))
        self.assertEqual(chain.state, "review")
        self.assertEqual(chain.refusals, ("review-1",))

    def test_in_flight_review_takes_precedence_over_reset(self):
        chain = self.chain(*_review_events(outcome=None),
                           _event("call.parked", call=CHAIN.root),
                           _event("question.answered", task=CHAIN.subject))
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
                  _event("question.answered"), _event("run.started", task=CHAIN.root, kind="review"),
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


class BriefTest(unittest.TestCase):
    def brief(self, chain=CHAIN, diff="+short\n", *, designs=()):
        """Use distinctive facts and optional changed designs for exact assertions."""
        return review.brief(chain, run_id="run-1", base="base", tip="tip", stat="file | 1 +\n",
                            diff=diff, report="/reports/run-1.md", designs=designs)

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


class StartTest(unittest.TestCase):
    def test_git_snapshot_detached_checkout_and_review_launch(self):
        with tmp_home() as home:
            fake = _review_runner()
            events = [_event("run.started", task=CHAIN.root), _event("run.started", task="other")]
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
            self.assertEqual(fake.calls[8].argv, ssh(HOST.ssh,
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
