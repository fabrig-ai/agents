import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from fab import channel, cli, code_report, findings, landing_report, log, report, tier_reds, triage, walks
from fab.plan import Plan, Question
from fab.sh import Result
from fab.tests import qa_records as qa
from fab.tests.ladder_plans import write_ladder
from fab.tests.support import FakeRunner, tmp_home


def ts(minute):
    return f"2026-10-30T12:{minute:02}:00.000Z"


def event(minute, ev, **fields):
    return {"ts": ts(minute), "ev": ev, **fields}


def red_opened(minute=1, identifier="red-1", route="signal", **fields):
    return event(minute, "red.opened", **{
        "red": identifier, "tip": "abcdef1234567890", "keys": ['["browser-jig","pkg::bin","case"]'],
        "suspects": [], "tasks": [], "draft": "", "route": route,
        "reason": "no suspects" if route == "signal" else "", **fields,
    })


def foreman_events(verdict="left"):
    return [red_opened(route="foreman", draft="demo", suspects=["demo/a"], tasks=["demo/a"]),
            event(2, "run.started", red="red-1", tip="abcdef1234567890", kind="foreman",
                  task="demo/red-1/foreman", run="foreman-1"),
            event(3, "run.ended", run="foreman-1", outcome="done", report="/runs/foreman/report.md"),
            event(4, "red.settled", red="red-1", run="foreman-1", verdict=verdict,
                  reason="the tier needs a login")]


def question(minute, subject="demo/core", call="cut-1"):
    return event(minute, "call.ended", subject=subject, call=call, outcome="question")


def parked(minute, subject="demo/core", call="root-1", **fields):
    return event(minute, "call.parked", subject=subject, call=call,
                 reason="Choose capacity", **fields)


def finding_events(decision="user", question="Which account?", **fields):
    return [qa.walk_started("walk-1", "b0", ts=ts(0)),
            qa.finding_raised("finding-1", "walk-1", "b0", ts=ts(0), **fields),
            qa.walk_ended("walk-1", "fail", ("finding-1",), ts=ts(1)),
            qa.finding_triaged("finding-1", decision, question=question, ts=ts(2))]


def plan(draft="demo", questions=()):
    return Plan(draft, "agents", (), 1.0, 2.0, {}, (), questions=questions)


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    sibling = path.with_name("." + path.name + ".new")
    sibling.write_text(text, encoding="utf-8")
    sibling.replace(path)
    return path


class ChannelTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.fab_home = log.home()
        self.fab_home.mkdir()

    def test_settlement_closes_only_earlier_parked_ask_for_subject(self):
        events = [question(0), parked(1), parked(2, subject="other/core")]
        settled = event(3, "chain.settled", call="root-1", subject="demo/core", settle="settle-1",
                        verdict="land", text="Good enough.")
        self.assertEqual([(ask.kind, ask.subject) for ask in channel.asks((), iter([*events, settled]))],
                         [("call", "demo/core"), ("parked", "other/core")])
        self.assertEqual([ask.kind for ask in channel.asks((), [settled, parked(4)])], ["parked"])

    def test_settle_guidance_joins_user_answers_in_log_order(self):
        events = [event(1, channel.ANSWERED, subject="demo/core", answer="Use blocks."),
                  event(2, "chain.settled", subject="demo/core", call="root", settle="settle-1",
                        verdict="amend", text="Include extern blocks.\nKeep the parser."),
                  event(3, "chain.settled", subject="other", verdict="amend", text="Elsewhere."),
                  event(4, "chain.settled", subject="demo/core", verdict="land", text="Later work.")]
        text = channel.answers_text("demo/core", iter(events))
        self.assertIn("Settlement (settle-1): Include extern blocks.\nKeep the parser.", text)
        self.assertLess(text.index("Use blocks."), text.index("Include extern blocks."))
        self.assertNotIn("Elsewhere.", text)
        self.assertNotIn("Later work.", text)

    def test_amend_and_settle_questions_wait_for_chain_judgement(self):
        for role in ("amend", "settle"):
            for explicit in (False, True):
                with self.subTest(role=role, explicit=explicit):
                    started = event(0, "call.started", call="call-1", role=role)
                    ended = question(1, call="call-1")
                    if explicit:
                        ended["role"] = role
                    self.assertEqual(channel.asks((), [started, ended]), [])

    def rejection(self, minute=1, branch="hand/pushed", tip="tip", **fields):
        return event(minute, "queue.rejected", branch=branch, tip=tip, step="default",
                     log="/queue/check.log", gate="gate-host", queue_ts=ts(minute), **fields)

    def test_finding_questions_show_context_and_answer_closes_each_decision(self):
        reproduction = "\n".join(f"step {n}" for n in range(channel.QUESTION_LINES + 2))
        subject = "ladder/triage/finding-1"
        for decision in ("user", "brief", "path"):
            with self.subTest(decision=decision):
                events = finding_events(decision, title="Connect stalls", reproduction=reproduction)
                ask, = channel.asks((), iter(events))
                walk_report = self.fab_home / "walks/walk-1/report.md"
                self.assertEqual(ask, channel.Ask("finding", "ladder", subject, "Which account?",
                                                ts(2), call="triage-1", report=str(walk_report)))
                page = channel.compose([], events, ts(3))
                expected = (f"### {subject}, asked {ts(2)}\n\nConnect stalls\n\nRung: b0\n\n"
                            + "\n".join(reproduction.splitlines()[:channel.QUESTION_LINES])
                            + f"\n\nWhich account?\n\n- Read: `{walk_report}`\n"
                            + f"- Answer: `fab page answer {subject} TEXT`")
                self.assertIn(expected, page)
                self.assertNotIn(f"step {channel.QUESTION_LINES}\n", page)
                record = channel.answer(subject, "  Use the team account  ", events)
                self.assertEqual((record["subject"], record["call"], record["question"], record["answer"]),
                                 (subject, "triage-1", "Which account?", "Use the team account"))
                self.assertEqual(channel.asks((), [*events, record]), [])
                self.assertNotIn("Connect stalls", channel.compose([], [*events, record], ts(4)))
                self.assertIn(f"answer {subject}\n", (self.fab_home / "tick.want").read_text())

    def test_finding_asks_require_ended_walk_known_finding_and_question_decision(self):
        for decision in ("drop", "backlog", "again"):
            with self.subTest(decision=decision):
                self.assertEqual(channel.asks((), finding_events(decision)), [])
        for text in ("", " ", None, 4, []):
            with self.subTest(text=text):
                self.assertEqual(channel.asks((), finding_events("path", question=text)), [])
        events = finding_events()
        self.assertEqual(channel.asks((), [events[0], events[1], events[3]]), [])
        self.assertEqual(channel.asks((), [dict(events[-1], finding="missing")]), [])
        for key in ("finding", "question", "call", "ts"):
            record = dict(events[-1])
            del record[key]
            self.assertEqual(channel.asks((), [*events[:-1], record]), [])

    def test_finding_asks_keep_log_order_replace_and_reopen_after_answer(self):
        events = finding_events()
        subject = "ladder/triage/finding-1"
        events += [question(3), qa.finding_triaged("finding-1", "brief", question="Change the brief?",
                                                 call="triage-2", ts=ts(2))]
        opened = channel.asks((), events)
        self.assertEqual([ask.kind for ask in opened], ["call", "finding"])
        self.assertEqual((opened[-1].call, opened[-1].text), ("triage-2", "Change the brief?"))
        events.append(event(4, "call.answered", subject=subject))
        self.assertEqual([ask.kind for ask in channel.asks((), events)], ["call"])
        events.append(qa.finding_triaged("finding-1", "user", question="Now which?", ts=ts(4)))
        self.assertEqual([ask.kind for ask in channel.asks((), events)], ["call", "finding"])

    def test_compose_ladders_use_main_editions_and_show_backlog_count_after_landing(self):
        directories = [write_ladder(self.home / name, draft=name) for name in ("ladder", "other")]
        loaded = [channel.plan.load_plan(directory / "plan.toml") for directory in directories]
        edition = walks.edition([("briefs/kit.md", "The committed brief.\n"),
                                 ("briefs/b0.md", "The committed brief.\n")])
        events = finding_events("backlog", question="", edition=edition)
        events[0] = dict(events[0], edition=edition)
        events += [event(3, "tiers.run", tip="main", verdict="green")]
        sh = FakeRunner().on(["git", "rev-parse"], Result(0, str(self.home)))
        sh.on(["git", "show"], Result(0, "The committed brief.\n"))
        read_editions = walks.editions
        with patch.object(channel, "read_editions", side_effect=lambda plan, directory:
                          read_editions(plan, directory, sh=sh)):
            with patch.object(walks, "editions", wraps=read_editions) as shared_editions:
                page = channel.compose(directories, events, ts(4))
        shared_editions.assert_not_called()
        self.assertLess(page.index("## After landing"), page.index("## The ladder"))
        for plan in loaded:
            editions = {rung.id: walks.edition([(path, "The committed brief.\n")
                                               for path in rung.brief])
                        for rung in plan.rungs.values()}
            expected = [f"- {findings.line(state)}"
                        for state in findings.rungs(plan, events, editions, ts(4))]
            count = 1 if plan.draft == "ladder" else 0
            self.assertIn(f"### {plan.draft}\n\n" + "\n".join(expected)
                          + f"\n- Backlog: {count} findings in `docs/design/debt/ladder.md`", page)
        self.assertEqual(sh.argvs(), [command for name in ("ladder", "other") for command in [
            ["git", "rev-parse", "--show-toplevel"],
            ["git", "show", f"origin/main:{name}/briefs/kit.md"],
            ["git", "show", f"origin/main:{name}/briefs/b0.md"],
            ["git", "show", f"origin/main:{name}/briefs/kit.md"],
            ["git", "show", f"origin/main:{name}/briefs/b1.md"]]])
        self.assertIn("due: rerun", page)
        self.assertNotIn("## Unread", page)

    def test_compose_unreadable_editions_list_the_plan_and_keep_other_ladders(self):
        directories = [write_ladder(self.home / name, draft=name)
                       for name in ("outside", "missing-brief", "readable")]
        sh = FakeRunner().on(["git", "rev-parse"], lambda call:
                            Result(128, err="not a checkout") if call.cwd == str(directories[0])
                            else Result(0, str(self.home)))
        sh.on(["git", "show", "origin/main:missing-brief/briefs/kit.md"], Result(1))
        sh.on(["git", "show"], Result(0, "brief\n"))
        read_editions = walks.editions
        with patch.object(channel, "read_editions", side_effect=lambda plan, directory:
                          read_editions(plan, directory, sh=sh)):
            page = channel.compose(directories, [], ts(4))
        self.assertLess(page.index("## The ladder"), page.index("## Unread"))
        self.assertIn("### readable", page)
        self.assertNotIn("### outside", page)
        self.assertNotIn("### missing-brief", page)
        self.assertIn(f"- {directories[0]}: git rev-parse --show-toplevel exited 128   not a checkout", page)
        self.assertIn(f"- {directories[1]}: rung b0: cannot read brief briefs/kit.md at origin/main", page)

    def test_backlog_signal_requires_two_current_render_rejections_and_clear_rewrites(self):
        directory = write_ladder(self.home / "ladder")
        _write(self.fab_home / channel.PLANS, str(directory) + "\n")
        plan = channel.plan.load_plan(directory / "plan.toml")
        events = finding_events("backlog", question="")
        render = triage.render_key(triage.backlog_text(plan, events))
        for n in (1, 2):
            branch = f"ladder/ladder/backlog-{n}"
            events += [event(3, "branch.ready", task=branch, branch=branch, tip=f"tip-{n}", render=render),
                       event(n + 3, "branch.rejected", task=branch, branch=branch, tip=f"tip-{n}",
                             step="gate", gate="gate-host", log=f"/queue/{n}.log")]
        sh = FakeRunner().on(["git", "rev-parse"], Result(0, str(self.home)))
        sh.on(["git", "show"], Result(0, "brief\n"))
        read_editions = walks.editions
        with patch.object(channel, "read_editions", side_effect=lambda plan, directory:
                          read_editions(plan, directory, sh=sh)):
            self.assertNotIn("### backlog:ladder,", channel.compose([directory], events[:-2], ts(6)))
            page = channel.compose([directory], events, ts(6))
            self.assertIn(f"### backlog:ladder, backlog rejected twice, since {ts(5)}", page)
            self.assertIn("- Branch: `ladder/ladder/backlog-2`\n- Step: `gate`\n"
                          "- Read: `gate-host:/queue/2.log`\n"
                          "- Clear: `fab page clear backlog:ladder TEXT`", page)
            changed = [*events, qa.finding_triaged("finding-1", "drop", ts=ts(6))]
            self.assertNotIn("### backlog:ladder,", channel.compose([directory], changed, ts(6)))
            landed = [*events, event(6, "branch.landed", task=branch, branch=branch,
                                     tip="tip-2", main="main", into="")]
            self.assertNotIn("### backlog:ladder,", channel.compose([directory], landed, ts(6)))
            for record in events:
                log.append(**record)
            with redirect_stdout(io.StringIO()), patch("fab.log.now", return_value=ts(6)):
                self.assertEqual(cli.main(["page", "clear", "backlog:ladder", "Retry", "--by", "free"]), 0)
            self.assertEqual(log.read()[-1], event(6, "signal.cleared", signal="backlog:ladder",
                                                   by="free", text="Retry"))
            self.assertNotIn("### backlog:ladder,", (self.fab_home / channel.PAGE).read_text())
            self.assertIn("clear backlog:ladder\n", (self.fab_home / "tick.want").read_text())
            with self.assertRaisesRegex(ValueError, "no open signal"):
                channel.clear("backlog:ladder", "Again", log.read())

    def test_queue_signal_facts_and_oldest_first_from_an_iterator(self):
        events = [dict(self.rejection(3, tests=["pkg::a", "pkg::b"]), ts=ts(8)),
                  dict(self.rejection(1, branch="hand/older"), ts=ts(9))]
        self.assertEqual(channel.signals(iter(events)), [
            channel.Signal("queue:hand/older", "rejected hand/older", ts(1),
                           ("- Tip: `tip`", "- Step: `default`", "- Tests: (see the log)"),
                           "gate-host:/queue/check.log", True),
            channel.Signal("queue:hand/pushed", "rejected hand/pushed", ts(3),
                           ("- Tip: `tip`", "- Step: `default`", "- Tests: pkg::a, pkg::b"),
                           "gate-host:/queue/check.log", True),
        ])

    def test_queue_signal_tests_ignore_malformed_values(self):
        for tests, expected in ((None, "(see the log)"), ("pkg::wrong-shape", "(see the log)"),
                                ([None, 3, {}, "pkg::valid"], "pkg::valid")):
            with self.subTest(tests=tests):
                signal, = channel.signals([self.rejection(tests=tests)])
                self.assertEqual(signal.facts[-1], "- Tests: " + expected)

    def test_queue_landing_closes_its_branch_only_even_at_another_tip(self):
        events = [self.rejection(), self.rejection(2, branch="other"),
                  event(3, "queue.landed", branch="hand/pushed", tip="merged")]
        self.assertEqual([signal.id for signal in channel.signals(events)], ["queue:other"])

    def test_queue_new_tip_replaces_rejection_and_collateral_only_closes_another_tip(self):
        events = [self.rejection(), self.rejection(2, tip="new")]
        self.assertEqual([(signal.since, signal.facts[0]) for signal in channel.signals(events)],
                         [(ts(2), "- Tip: `new`")])
        events.append(event(3, "queue.collateral", branch="hand/pushed", tip="new"))
        self.assertEqual(len(channel.signals(events)), 1)
        events.append(event(4, "queue.collateral", branch="hand/pushed", tip="newer"))
        self.assertEqual(channel.signals(events), [])

    def test_queue_collateral_and_task_rejection_never_open_signals(self):
        events = [event(1, "queue.collateral", branch="hand/pushed", tip="tip"),
                  event(2, "branch.rejected", branch="draft/task", tip="task-tip"),
                  event(3, "red.opened", red="red-1"),
                  event(4, "tiers.run", faults=["profile failed"])]
        self.assertEqual(channel.signals(events), [])
        self.assertEqual(channel.signals([{}, event(1, "queue.rejected"),
                                         event(2, "queue.rejected", branch=3)]), [])

    def test_queue_clear_closes_its_signal_and_later_rejection_opens_again(self):
        events = [self.rejection(), self.rejection(2, branch="other"),
                  event(3, "signal.cleared", signal="queue:hand/pushed", text="settled")]
        self.assertEqual([signal.id for signal in channel.signals(events)], ["queue:other"])
        events.append(self.rejection(4))
        self.assertEqual([(signal.id, signal.since) for signal in channel.signals(events)],
                         [("queue:other", ts(2)), ("queue:hand/pushed", ts(4))])

    def test_clear_logs_stripped_text_and_wakes_beside_explicit_log(self):
        path = self.home / "custom/events.jsonl"
        events = [self.rejection()]
        record = channel.clear("queue:hand/pushed", "  settled  ", events, by="free", log_path=path)
        self.assertEqual({key: value for key, value in record.items() if key != "ts"},
                         dict(ev="signal.cleared", signal="queue:hand/pushed", by="free", text="settled"))
        self.assertEqual(log.read(path), [record])
        self.assertEqual(channel.signals(events + [record]), [])
        self.assertEqual((path.parent / "tick.want").read_text(), "clear queue:hand/pushed\n")
        self.assertFalse((self.fab_home / "tick.want").exists())
        self.assertEqual(log.read(), [])

    def test_clear_refuses_unknown_closed_and_blank_without_logging_or_waking(self):
        rejection = self.rejection()
        closed = [rejection, event(2, "signal.cleared", signal="queue:hand/pushed")]
        for identifier, text, events in (("missing", "yes", [rejection]),
                                         ("queue:hand/pushed", "yes", closed),
                                         ("queue:hand/pushed", "  ", [rejection])):
            with self.subTest(identifier=identifier, text=text), self.assertRaises(ValueError):
                channel.clear(identifier, text, events)
        self.assertEqual(log.read(), [])
        self.assertFalse((self.fab_home / "tick.want").exists())

    def test_red_signal_at_opening_has_evidence_and_reason(self):
        signal, = channel.signals(iter([red_opened()]))
        self.assertEqual(signal, channel.Signal("red-1", "after-landing red", ts(1), (
            "- Tip: `abcdef1234567890`", "- Why: no suspects",
            "- Tests: browser-jig pkg::bin case", "- Suspects: (none)",
        ), str(self.fab_home / "reds/red-1.md"), True))
        page = channel.compose([], [red_opened()], ts(2))
        self.assertIn(f"### red-1, after-landing red, since {ts(1)}", page)
        self.assertIn("- Clear: `fab page clear red-1 TEXT`", page)
        self.assertNotIn("## After landing", page)

    def test_red_signal_limits_tests_and_marks_only_hand_pushed_suspects(self):
        keys = [json.dumps(["browser-jig", "pkg::bin", f"case-{i}"]) for i in range(12)]
        signal, = channel.signals([red_opened(keys=keys, draft="demo", tasks=["demo/a", "demo"],
            suspects=["demo/a-r2", "hand/pushed", "demo/integration"],
            reason="no fab task among the suspects")])
        self.assertIn("- Why: no fab task among the suspects", signal.facts)
        self.assertIn("case-9, and 2 more", signal.facts[2])
        self.assertNotIn("case-10", signal.facts[2])
        self.assertEqual(signal.facts[3],
                         "- Suspects: demo/a-r2, hand/pushed (hand-pushed), demo/integration")
        self.assertEqual(channel.signals([red_opened(keys=["legacy-key"])])[0].facts[2],
                         "- Tests: legacy-key")

    def test_left_red_signal_keeps_foreman_reason_report_and_transition_time(self):
        events = foreman_events()
        signal, = channel.signals(events)
        self.assertEqual(signal.since, ts(4))
        self.assertIn("- Why: not the suspects': the tier needs a login", signal.facts)
        page = channel.compose([], events, ts(5))
        self.assertIn(f"- Read: `{self.fab_home / 'reds/red-1.md'}`, `/runs/foreman/report.md`", page)
        self.assertNotIn("red-1 (demo/red-1)", page)

    def test_repairing_red_is_an_after_landing_line_and_not_a_signal(self):
        for verdict in ("fix", "none"):
            with self.subTest(verdict=verdict):
                events = foreman_events(verdict)
                self.assertEqual(channel.signals(events), [])
                self.assertEqual(channel.landing_lines(iter(events)), [
                    f"red-1 (demo/red-1): repairing, 1 tests at `abcdef123456`, since {ts(4)}"])
                page = channel.compose([], events, ts(5))
                self.assertIn("## Open signals\n\n(none)", page)
                self.assertIn("## After landing\n\n- red-1 (demo/red-1): repairing", page)
                events.append(event(5, "tiers.run", tip="latest-tip", verdict="red", faults=[]))
                self.assertEqual(channel.landing_lines(events), [
                    f"red at `latest-tip`, {ts(5)}: new 0, standing 0, unattributed 0, flakes 0",
                    f"red-1 (demo/red-1): repairing, 1 tests at `abcdef123456`, since {ts(4)}"])

    def test_unfixed_red_signal_shows_why_and_red_closed_removes_it(self):
        events = foreman_events("fix") + [event(5, "branch.landed", task="demo/red-1"),
                  event(6, "tiers.run", tip="unfixed-tip", branches=["demo/red-1-r2"],
                        faults=[], reds=['["browser-jig","pkg::bin","case"]'])]
        signal, = channel.signals(events)
        self.assertEqual(signal.since, ts(6))
        self.assertIn("- Why: unfixed: demo/red-1 landed, still red at unfixed-tip", signal.facts)
        self.assertFalse(any("red-1 (demo/red-1)" in line for line in channel.landing_lines(events)))
        events.append(event(7, "red.closed", red="red-1", reason="recovered", tip="green"))
        self.assertEqual(channel.signals(events), [])
        self.assertFalse(any("red-1 (demo/red-1)" in line for line in channel.landing_lines(events)))

    def test_red_clear_command_hides_signal_until_tick_closes_it_without_returning(self):
        for record in foreman_events():
            log.append(**record)
        output = io.StringIO()
        with patch("fab.log.now", return_value=ts(4)), redirect_stdout(output):
            self.assertEqual(cli.main(["page", "clear", "red-1", "Investigated", "--by", "free"]), 0)
        cleared = event(4, "signal.cleared", signal="red-1", by="free", text="Investigated")
        self.assertEqual(log.read()[-1], cleared)
        self.assertIn("cleared red-1", output.getvalue())
        self.assertIn("## Open signals\n\n(none)", (self.fab_home / channel.PAGE).read_text())
        self.assertEqual((self.fab_home / "tick.want").read_text(), "clear red-1\n")
        self.assertEqual(tier_reds.closures(log.read()), [("red-1", "cleared", "")])
        closed, = tier_reds.close_reds(log.read())
        self.assertEqual((closed["ev"], closed["reason"]), ("red.closed", "cleared"))
        log.append("tiers.run", tip="still-red", reds=['["browser-jig","pkg::bin","case"]'], faults=[])
        self.assertEqual(channel.signals(log.read()), [])
        self.assertEqual(channel.landing_lines(log.read())[1:], [])

    def test_red_clear_before_signal_transition_does_not_hide_a_later_raise(self):
        events = foreman_events()
        events.insert(1, event(1, "signal.cleared", signal="red-1"))
        self.assertEqual([signal.id for signal in channel.signals(events)], ["red-1"])

    def test_pending_red_closures_hide_signals_and_refuse_repeated_clears(self):
        key = red_opened()["keys"][0]
        for closing in (event(2, "tiers.recovered", key=key, tip="green"),
                        event(2, "tiers.run", tip="absent", faults=[], reds=[],
                              starved=0, unobserved=0),
                        event(2, "signal.cleared", signal="red-1")):
            with self.subTest(closing=closing["ev"]):
                events = [red_opened(), closing]
                self.assertEqual(channel.signals(events), [])
                self.assertNotIn("### red-1,", channel.compose([], events, ts(3)))
                for _ in range(2):
                    with self.assertRaisesRegex(ValueError, "no open signal"):
                        channel.clear("red-1", "seen", events)
                self.assertEqual(log.read(), [])
                self.assertFalse((self.fab_home / "tick.want").exists())

    def test_pending_repair_closures_hide_after_landing_lines(self):
        events = foreman_events("fix")
        for closing in (event(5, "tiers.recovered", key=events[0]["keys"][0], tip="green"),
                        event(5, "tiers.run", tip="absent", faults=[], reds=[],
                              starved=0, unobserved=0)):
            with self.subTest(closing=closing["ev"]):
                page = channel.compose([], [*events, closing], ts(6))
                self.assertNotIn("red-1 (demo/red-1)", page)
                self.assertNotIn("### red-1,", page)

    def test_compose_folds_reds_once_and_consumers_reuse_an_explicit_fold(self):
        events = [*foreman_events("fix"), red_opened(5, "red-2")]
        folded = tier_reds.reds(events)
        with patch.object(tier_reds, "reds", wraps=tier_reds.reds) as fold:
            page = channel.compose([], events, ts(6))
        fold.assert_called_once_with(events)
        self.assertIn("red-1 (demo/red-1): repairing", page)
        self.assertIn("### red-2,", page)
        with patch.object(tier_reds, "reds", side_effect=AssertionError("fold repeated")):
            self.assertEqual([signal.id for signal in channel.signals(events, folded=folded)], ["red-2"])
            self.assertEqual(len(channel.landing_lines(events, folded=folded)), 1)
            self.assertEqual(channel.signals(events, folded=[]), [])
            self.assertEqual(channel.landing_lines(events, folded=[]), [])

    def test_page_skips_malformed_red_openings_and_prints_non_string_facts(self):
        for changes in ({"tip": None}, {"keys": None}, {"keys": [1]},
                        {"suspects": [None]}, {"suspects": [{"branch": "hand/pushed"}]}):
            for route in ("signal", "foreman"):
                with self.subTest(changes=changes, route=route):
                    events = [red_opened(route=route, **changes)]
                    self.assertEqual(channel.signals(events), [])
                    self.assertEqual(channel.landing_lines(events), [])
                    self.assertIn("## Open signals\n\n(none)", channel.compose([], events, ts(2)))
        events = foreman_events()
        events[2]["report"] = 123
        events += [event(5, "tiers.run", tip=None, faults=[7], budget=[8],
                         over_budget=[9], possible_hangs=[10]),
                   event(5, "tiers.red", tip=None, profile=11, test=12, branches=[13])]
        page = channel.compose([], events, ts(6))
        for text in ("`, `123`", "faults: 7", "budget: 8", "over budget: 9", "possible hang: 10",
                     "new red: 11 12, since 13"):
            self.assertIn(text, page)

    def test_fault_signals_count_runs_keep_first_time_and_latest_text_and_log(self):
        events = [event(1, "tiers.run", faults=["live-temper: exit 4", "browser-jig: exit 75"],
                        log="/al/first.log"),
                  event(2, "signal.cleared", signal="fault:live-temper"),
                  self.rejection(3),
                  event(4, "tiers.run", faults=["live-temper: no login", "live-temper: no login"],
                        log="/al/newest.log")]
        self.assertEqual(channel.signals(iter(events)), [
            channel.Signal("fault:live-temper", "after-landing pair cannot run", ts(1),
                           ("- Fault: live-temper: no login", "- Runs: 2"),
                           "after-landing:/al/newest.log", False),
            channel.signals([self.rejection(3)])[0]])
        page = channel.compose([], events, ts(5))
        self.assertNotIn("fab page clear fault:", page)
        events.append(event(5, "tiers.run", faults=[]))
        self.assertEqual([signal.id for signal in channel.signals(events)], ["queue:hand/pushed"])
        events.append(event(6, "tiers.run", faults=["live-temper: exit 4"], log="/al/reopened.log"))
        signal = next(signal for signal in channel.signals(events) if signal.id.startswith("fault:"))
        self.assertEqual((signal.since, signal.facts[-1]), (ts(6), "- Runs: 1"))
        events.append(event(7, "tiers.run"))
        self.assertEqual([signal.id for signal in channel.signals(events)], ["queue:hand/pushed"])

    def test_fault_signal_reads_the_newest_runs_machine_and_log(self):
        events = [event(1, "tiers.run", faults=["live-temper: exit 4"],
                        host="first", log="/al/first.log"),
                  event(2, "tiers.run", faults=["live-temper: no login"],
                        host="tiers-box", log="/al/newest.log")]
        signal, = channel.signals(events)
        self.assertEqual((signal.since, signal.read), (ts(1), "tiers-box:/al/newest.log"))
        self.assertIn("- Read: `tiers-box:/al/newest.log`", channel.compose([], events, ts(3)))
        del events[-1]["host"]
        self.assertEqual(channel.signals(events)[0].read, "after-landing:/al/newest.log")

    def test_fault_signal_skips_malformed_fault_fields(self):
        for faults in (None, "live-temper: exit 4", [None, 3, {}, "missing separator", ": no profile"]):
            with self.subTest(faults=faults):
                self.assertEqual(channel.signals([event(1, "tiers.run", faults=faults)]), [])
        self.assertEqual(channel.signals([{"ev": "tiers.run", "faults": ["p: exit 4"]}]), [])

    def test_fault_clear_command_is_refused_without_writing_or_waking(self):
        log.append(**event(1, "tiers.run", faults=["live-temper: exit 4"], log="/al/run.log"))
        before = log.read()
        with redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(cli.main(["page", "clear", "fault:live-temper", "done"]), 1)
        self.assertIn("cannot be cleared", errors.getvalue())
        self.assertEqual(log.read(), before)
        self.assertFalse((self.fab_home / channel.PAGE).exists())
        self.assertFalse((self.fab_home / "tick.want").exists())

    def test_asks_plans_first_in_given_order_and_whitespace_answer_open(self):
        first = plan(questions=(Question("budget", "How much?", ("core", "ui")),
                                Question("host", "Which host?", (), "hel8"),
                                Question("limit", "Which limit?", (), "   ")))
        second = plan("other", (Question("machine", "Buy one?", ("build",)),))
        first_path, second_path = self.home / "plan.toml", self.home / "other/plan.toml"
        result = channel.asks([(first, first_path), (second, second_path)], [question(1)])
        self.assertEqual(result[:3], [
            channel.Ask("plan", "demo", "budget", "How much?", "",
                        report=str(first_path), parts=("core", "ui")),
            channel.Ask("plan", "demo", "limit", "Which limit?", "", report=str(first_path)),
            channel.Ask("plan", "other", "machine", "Buy one?", "",
                        report=str(second_path), parts=("build",)),
        ])
        self.assertEqual(result[3].kind, "call")

    def test_asks_reopening_moves_key_to_end_and_kinds_coexist(self):
        events = [question(1), question(2, "other", "other-1"),
                  parked(3, report=str(self.fab_home / "runs/review-1/report.md")),
                  question(4, call="cut-2")]
        result = channel.asks((), iter(events))
        self.assertEqual(result, [
            channel.Ask("call", "other", "other", "", ts(2), call="other-1",
                        report=str(self.fab_home / "calls/other-1/report.md")),
            channel.Ask("parked", "demo", "demo/core", "Choose capacity", ts(3),
                        call="root-1", report=str(self.fab_home / "runs/review-1/report.md")),
            channel.Ask("call", "demo", "demo/core", "", ts(4), call="cut-2",
                        report=str(self.fab_home / "calls/cut-2/report.md")),
        ])

    def test_asks_parked_reopening_moves_to_end_and_report_defaults_empty(self):
        result = channel.asks((), [parked(1), question(2, "other"), parked(3, call="root-2")])
        self.assertEqual([(ask.kind, ask.subject, ask.since) for ask in result],
                         [("call", "other", ts(2)), ("parked", "demo/core", ts(3))])
        self.assertEqual(result[-1].call, "root-2")
        self.assertEqual(result[-1].report, "")

    def test_asks_answer_closes_both_kinds_only_for_its_subject(self):
        events = [question(1), parked(2), question(3, "other"),
                  event(4, channel.ANSWERED, subject="demo/core")]
        self.assertEqual([ask.subject for ask in channel.asks((), events)], ["other"])
        self.assertEqual([ask.subject for ask in channel.asks((), events + [question(5)])],
                         ["other", "demo/core"])

    def test_asks_done_closes_call_only_and_task_answer_closes_nothing(self):
        events = [question(1), parked(2),
                  event(3, "question.answered", task="demo/core", subject="demo/core")]
        self.assertEqual([ask.kind for ask in channel.asks((), events)], ["call", "parked"])
        events += [event(4, "call.ended", subject="other", outcome="done"),
                   event(5, "call.ended", subject="demo/core", call="later", outcome="done")]
        self.assertEqual([ask.kind for ask in channel.asks((), events)], ["parked"])

    def test_asks_finished_closes_matching_parked_chain_only(self):
        events = [question(1, call="root-1"), parked(2), parked(3, "other", "other-1"),
                  event(4, "call.finished", call="unrelated"),
                  event(5, "call.finished", call="root-1")]
        self.assertEqual([(ask.kind, ask.subject) for ask in channel.asks((), events)],
                         [("call", "demo/core"), ("parked", "other")])

    def test_asks_missing_fields_are_skipped_without_replacing_open_asks(self):
        events = [question(1), parked(2)]
        malformed = [{}, {"ev": channel.ANSWERED}, {"ev": "call.finished"},
                     event(3, "call.ended", subject="demo/core"),
                     event(3, "call.ended", outcome="done"),
                     event(3, "call.parked", reason="missing subject")]
        for opening, required in ((question(3), ("subject", "call", "ts", "outcome")),
                                  (parked(3), ("subject", "call", "ts", "reason"))):
            malformed.extend({key: value for key, value in opening.items() if key != field}
                             for field in required)
        self.assertEqual(channel.asks((), iter(events + malformed)), channel.asks((), events))
        self.assertEqual(channel.asks((), [event(1, "call.ended", subject="demo", outcome="failed")]), [])

    def test_plan_dirs_missing_file_and_uncreated_given_directory(self):
        given = self.home / "not-cut-yet"
        self.assertEqual(channel.plan_dirs(), [])
        self.assertEqual(channel.plan_dirs([given]), [given.resolve()])

    def test_plan_dirs_lines_resolve_and_keep_first_occurrence(self):
        first, second, third = (self.home / name for name in ("first", "second", "third"))
        _write(self.fab_home / channel.PLANS, f"  {first}  \n\n{second}\n{first}/../first\n")
        self.assertEqual(channel.plan_dirs([second, third, first]), [first, second, third])

    def test_plan_dirs_relative_paths_resolve_against_working_directory(self):
        _write(self.fab_home / channel.PLANS, "plans/../draft\n\n")
        with patch("os.getcwd", return_value=str(self.home)):
            self.assertEqual(channel.plan_dirs([Path("draft"), Path("next")]),
                             [self.home / "draft", self.home / "next"])

    def test_signal_section_matches_both_standing_reports(self):
        sources = report.Sources([], [], {})
        window = report.Window(ts(0), ts(30))
        texts = [code_report.render(plan(), {}, sources, {}, window),
                 landing_report.render(sources, {}, window)]
        for text in texts:
            with self.subTest(heading=text.splitlines()[0]):
                self.assertEqual(channel.signal_section(text), ("- none",))

    def test_signal_section_exact_heading_stops_at_next_section_and_drops_blanks(self):
        self.assertEqual(channel.signal_section("# Report\n## Other\nnone\n"), ())
        self.assertEqual(channel.signal_section("## Signals extra\n- ignored\n"), ())
        self.assertEqual(channel.signal_section(
            "## Signals\n\n- first  \n   \n### Detail\n second\t\n## Next\n- ignored"),
            ("- first", "### Detail", " second"))
        self.assertEqual(channel.signal_section("## Signals\n- last  \n\n"), ("- last",))

    def test_latest_reports_greatest_valid_day_hidden_siblings_and_landing_last(self):
        directory = self.fab_home / "reports"
        _write(directory / "demo/2026-10-29.md", "## Signals\n- old\n")
        latest = _write(directory / "demo/2026-10-30.md", "## Signals\n- latest  \n")
        for name in ("notes.md", "2026-02-30.md", "20261031.md", "2026-W44-6.md",
                     "2026-1-31.md", "2026-12-01.txt", ".2026-12-01.md.new"):
            _write(directory / "demo" / name, "## Signals\n- stray\n")
        (directory / "demo/2026-12-01.md").mkdir()
        landing = _write(directory / "landing/2026-10-29.md", "No signals")
        zed = _write(directory / "zed/2026-10-30.md", "## Signals\n- zed\n")
        _write(directory / ".demo.new/2026-10-30.md", "hidden")
        _write(directory / ".sibling", "hidden")
        _write(directory / "stray.md", "stray")
        (directory / "empty").mkdir()
        self.assertEqual(channel.latest_reports(directory), [
            channel.Report("demo", "2026-10-30", latest, ("- latest",)),
            channel.Report("zed", "2026-10-30", zed, ("- zed",)),
            channel.Report("landing", "2026-10-29", landing, ()),
        ])

    def test_latest_reports_missing_directory(self):
        self.assertEqual(channel.latest_reports(self.fab_home / "missing"), [])

    @unittest.skipIf(os.geteuid() == 0, "root can read mode 000 files")
    def test_latest_reports_unreadable_day_stays_listed(self):
        directory = self.fab_home / "reports"
        path = _write(directory / "demo/2026-10-30.md", "unreadable")
        path.chmod(0)
        try:
            found = channel.latest_reports(directory)
        finally:
            path.chmod(0o600)
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].name, found[0].day, found[0].path),
                         ("demo", "2026-10-30", path))
        self.assertTrue(found[0].signals[0].startswith("(unreadable: "))
        self.assertTrue(found[0].signals[0].endswith(")"))

    def test_excerpt_cut_at_question_lines_and_trim_trailing_blanks(self):
        path = _write(self.home / "question.md", "\n".join(f"line {n}  " for n in range(20)))
        self.assertEqual(channel.excerpt(path), "\n".join(f"line {n}" for n in range(channel.QUESTION_LINES)))
        _write(path, "first  \n\n second\t\n  \n\n")
        self.assertEqual(channel.excerpt(path), "first\n\n second")
        self.assertEqual(channel.excerpt(path, 2), "first")

    def test_excerpt_missing_empty_and_blank(self):
        path = self.home / "report.md"
        self.assertEqual(channel.excerpt(path), "(report missing)")
        _write(path, "")
        self.assertEqual(channel.excerpt(path), "(empty report)")
        _write(path, " \n\t\n")
        self.assertEqual(channel.excerpt(path), "(empty report)")

    def test_answers_text_keeps_subject_answers_in_log_order_and_multiline(self):
        events = [event(1, channel.ANSWERED, subject="demo/core", call="cut-1",
                        question="Which host?", by="user", answer="hel8\nthen hel9"),
                  event(2, channel.ANSWERED, subject="other", answer="ignored"),
                  event(3, "question.answered", subject="demo/core", answer="ignored"),
                  event(4, channel.ANSWERED, subject="demo/core", call="cut-2",
                        question="Budget?", by="free", answer="100")]
        self.assertEqual(channel.answers_text("demo/core", iter(events)),
                         f"### {ts(1)}, to cut-1\nQuestion: Which host?\n"
                         f"Answer (user): hel8\nthen hel9\n\n### {ts(4)}, to cut-2\n"
                         "Question: Budget?\nAnswer (free): 100")

    def test_answers_text_missing_fields_and_none(self):
        self.assertEqual(channel.answers_text("demo", [{"ev": channel.ANSWERED, "subject": "demo"}]),
                         "### -, to -\nQuestion: -\nAnswer (-): -")
        self.assertEqual(channel.answers_text("demo", [{"ev": channel.ANSWERED}]), "")
        self.assertEqual(channel.answers_text("demo", []), "")

    def test_render_all_question_kinds_quote_bodies_and_report_user_signals(self):
        entries = [
            (channel.Ask("plan", "demo", "budget", "Budget?", "", report="plan.toml",
                         parts=("core", "ui")), "**Budget?**\nkeep `Markdown`"),
            (channel.Ask("call", "demo", "demo/core", "", ts(1), report="calls/cut/report.md"),
             "Question: choose a host\n\n> quoted"),
            (channel.Ask("parked", "demo", "demo/ui", "refused", ts(2), report="review.md"),
             "refused\n\nFailed: scope"),
            (channel.Ask("parked", "other", "other", "capacity", ts(3)), "capacity"),
        ]
        signals = tuple(report.signal_lines([
            report.Signal("Capacity", "buy a builder", "user"),
            report.Signal("Red tests", "fix them", "ops"),
        ]))
        reports = [channel.Report("demo", "2026-10-30", Path("reports/demo.md"), signals),
                   channel.Report("landing", "2026-10-29", Path("reports/landing.md"), ())]
        rendered = channel.render(entries, reports, ts(4), ["plan: bad TOML", "other: missing field"])
        self.assertEqual(rendered, f"""# The user's page
{ts(4)}. Only what is the user's (budgets, machines, what is hard to reverse) and what has no owner fab knows.

## Questions

### demo: question budget

**Budget?**
keep `Markdown`

- Waits: core, ui
- Answer: write its `answer` in `plan.toml` and land it with `fab land`

### demo/core, asked {ts(1)}

Question: choose a host

> quoted

- Read: `calls/cut/report.md`
- Answer: `fab page answer demo/core TEXT`

### demo/ui, parked {ts(2)}

refused

Failed: scope

- Read: `review.md`
- Answer: `fab page answer demo/ui TEXT`

### other, parked {ts(3)}

capacity

- Answer: `fab page answer other TEXT`

## Open signals

(none)

## Daily reports

### demo, 2026-10-30

`reports/demo.md`

- **Capacity:** buy a builder (user)

### landing, 2026-10-29

`reports/landing.md`

- none

## Unread

- plan: bad TOML
- other: missing field
""")

    def test_render_signals_uses_the_same_block_with_clear_only_when_clearable(self):
        opened = [channel.Signal("queue:hand/pushed", "rejected hand/pushed", ts(1),
                                 ("- Tip: `tip`", "- Step: `default`", "- Tests: pkg::test"),
                                 "gate-host:/queue/check.log", True),
                  channel.Signal("unclearable", "needs recovery", ts(2),
                                 ("- Reason: still open",), "gate-host:/run.log", False)]
        page = channel.render([], [], ts(3), open_signals=opened)
        self.assertIn(f"""## Open signals

### queue:hand/pushed, rejected hand/pushed, since {ts(1)}

- Tip: `tip`
- Step: `default`
- Tests: pkg::test
- Read: `gate-host:/queue/check.log`
- Clear: `fab page clear queue:hand/pushed TEXT`

### unclearable, needs recovery, since {ts(2)}

- Reason: still open
- Read: `gate-host:/run.log`

## Daily reports""", page)
        self.assertNotIn("fab page clear unclearable", page)

    def test_landing_lines_show_the_newest_run_and_its_new_reds(self):
        events = [dict(ev="tiers.run", ts="t1", tip="old", verdict="green"),
                  dict(ev="tiers.red", tip="old", profile="qa-jig", test="gone"),
                  dict(ev="tiers.red", tip="abcdef1234567890", profile="qa-jig", test="t1",
                       branches=["d/a", "d/b"]),
                  dict(ev="tiers.red", tip="abcdef1234567890", profile="qa-temper", test="t2"),
                  dict(ev="tiers.run", ts="t2", tip="abcdef1234567890", verdict="red", new=2,
                       standing=0, unattributed=1, flake=3, faults=["browser-jig: exit 75"])]
        self.assertEqual(channel.landing_lines(events), [
            "red at `abcdef123456`, t2: new 2, standing 0, unattributed 1, flakes 3; faults: browser-jig: exit 75",
            "new red: qa-jig t1, since d/a, d/b",
            "new red: qa-temper t2, since unknown branches"])
        self.assertEqual(channel.landing_lines(events[1:4]), [])
        page = channel.render([], [], ts(0), landing=["green at `x`, t: new 0"])
        self.assertIn("\n\n## After landing\n\n- green at `x`, t: new 0\n", page)

    def test_landing_lines_distinguish_new_and_unattributed_reds(self):
        events = [dict(ev="tiers.run", tip="x", verdict="red", new=2, unattributed=1),
                  dict(ev="tiers.red", tip="x", profile="p", test="legacy"),
                  dict(ev="tiers.red", tip="x", state="new", profile="p", test="new",
                       branches=["d/a"]),
                  dict(ev="tiers.red", tip="x", state="unattributed", profile="p", test="unknown",
                       branches=["d/b"]),
                  dict(ev="tiers.red", tip="old", state="unattributed", profile="p", test="old")]
        self.assertEqual(channel.landing_lines(events)[1:], [
            "new red: p legacy, since unknown branches",
            "new red: p new, since d/a",
            "unattributed red: p unknown, since d/b"])

    def test_render_empty_page_and_no_unread_section(self):
        self.assertEqual(channel.render([], [], ts(0)), f"""# The user's page
{ts(0)}. Only what is the user's (budgets, machines, what is hard to reverse) and what has no owner fab knows.

## Questions

(none)

## Open signals

(none)

## Daily reports

(none)
""")

    def test_render_other_owners_hidden_and_unreadable_report_visible(self):
        signals = tuple(report.signal_lines([
            report.Signal("ops signal", "ask the user", "ops"),
            report.Signal("lookalike", "act", "superuser"),
        ]))
        reports = [channel.Report("demo", "2026-10-30", Path("demo.md"), signals),
                   channel.Report("broken", "2026-10-30", Path("broken.md"),
                                  ("(unreadable: denied)",))]
        rendered = channel.render([], reports, ts(0))
        self.assertIn("`demo.md`\n\n- none", rendered)
        self.assertIn("(unreadable: denied)", rendered)
        self.assertNotIn("ops signal", rendered)
        self.assertNotIn("lookalike", rendered)
        self.assertNotIn("## Unread", rendered)
        self.assertTrue(rendered.endswith("\n"))
        self.assertFalse(rendered.endswith("\n\n"))

    def test_compose_loads_questions_reports_and_unread_plans_in_order(self):
        directory = self.home / "draft"
        plan_path = _write(directory / "plan.toml", '''draft = "demo"
repo = "agents"
part = []
[[question]]
id = "budget"
text = "How much?"
parts = ["core"]
''')
        broken = self.home / "broken"
        _write(broken / "plan.toml", "not TOML")
        missing = self.home / "not-cut"
        call_report = _write(self.fab_home / "calls/cut-1/report.md", "Question: Which host?\nOptions.")
        review_report = _write(self.fab_home / "runs/review-1/report.md", "Failed: capacity\nFindings.")
        daily = _write(self.fab_home / "reports/demo/2026-10-30.md",
                       "## Signals\n- **Capacity:** buy a builder (user)\n- red tests (ops)\n")
        events = [question(1), parked(2, "demo/ui", report=str(review_report)),
                  parked(3, "demo/other")]
        page = channel.compose([directory, missing, broken], events, ts(4))
        sections = ["### demo: question budget", f"### demo/core, asked {ts(1)}",
                    f"### demo/ui, parked {ts(2)}", f"### demo/other, parked {ts(3)}",
                    "## Daily reports", "## Unread"]
        self.assertEqual([page.index(section) for section in sections],
                         sorted(page.index(section) for section in sections))
        for quoted in ("How much?", str(plan_path), "Question: Which host?\nOptions.",
                       str(call_report), "Choose capacity\n\nFailed: capacity\nFindings.",
                       str(review_report), str(daily), "- **Capacity:** buy a builder (user)"):
            self.assertIn(quoted, page)
        self.assertIn(f"- {broken}: ", page)
        self.assertNotIn(str(missing), page)
        self.assertNotIn("red tests", page)
        self.assertIn("Choose capacity\n\n- Answer: `fab page answer demo/other TEXT`", page)

    def test_compose_plan_read_failure_is_one_unread_line(self):
        directory = self.home / "draft"
        _write(directory / "plan.toml", "present")
        with patch("fab.plan.load_plan", side_effect=OSError("first\nsecond")):
            page = channel.compose([directory], [], ts(1))
        self.assertIn(f"## Unread\n\n- {directory}: first second\n", page)

    def test_write_replaces_whole_page_under_fab_home(self):
        path = channel.write("old page\n")
        self.assertEqual(path, self.fab_home / "user.md")
        self.assertEqual(channel.write("new page\n"), path)
        self.assertEqual(path.read_text(), "new page\n")
        self.assertEqual(list(self.fab_home.iterdir()), [path])

    def test_answer_call_logs_first_nonblank_report_line_and_stripped_text(self):
        _write(self.fab_home / "calls/cut-1/report.md", "\n  \nQuestion: Which host?  \nOptions.")
        path = self.home / "custom/log.jsonl"
        with patch("fab.log.now", return_value=ts(2)):
            record = channel.answer("demo/core", "  hel8  ", [question(1)], log_path=path)
        self.assertEqual(record, dict(ts=ts(2), ev="call.answered", subject="demo/core",
                                      call="cut-1", by="user", question="Question: Which host?", answer="hel8"))
        self.assertEqual(log.read(path), [record])
        self.assertEqual((path.parent / "tick.want").read_text(), "answer demo/core\n")
        self.assertFalse((self.fab_home / "tick.want").exists())
        self.assertEqual(log.read(), [])

    def test_answer_uses_last_open_ask_and_parked_reason(self):
        record = channel.answer("demo/core", "Buy it", [question(1), parked(2)], by="free")
        self.assertEqual((record["call"], record["question"], record["by"]),
                         ("root-1", "parked: Choose capacity", "free"))
        self.assertEqual(log.read(), [record])
        self.assertEqual((self.fab_home / "tick.want").read_text(), "answer demo/core\n")
        self.assertEqual(channel.asks((), [question(1), parked(2), record]), [])

    def test_answer_refuses_blank_unknown_and_plan_id_without_logging(self):
        events = [question(1), parked(2), question(3, "other", "other-1")]
        for subject, text in (("demo/core", " \t"), ("missing", "yes"), ("budget", "100")):
            with self.subTest(subject=subject), self.assertRaises(ValueError) as caught:
                channel.answer(subject, text, events)
            self.assertIn(subject, str(caught.exception))
            self.assertIn("open subjects: demo/core, other", str(caught.exception))
            self.assertEqual(log.read(), [])
        with self.assertRaisesRegex(ValueError, "open subjects: none"):
            channel.answer("missing", "yes", [])
        self.assertFalse(log.default_path().exists())
        self.assertFalse((self.fab_home / "tick.want").exists())

    def test_main_show_and_write_through_cli(self):
        directory = self.home / "draft"
        _write(directory / "plan.toml", 'draft = "demo"\nrepo = "agents"\npart = []\n')
        output = io.StringIO()
        with patch("fab.log.now", return_value=ts(0)), redirect_stdout(output):
            self.assertEqual(cli.main(["page", "show", str(directory)]), 0)
        self.assertEqual(output.getvalue(), channel.compose([directory], [], ts(0)))
        self.assertFalse((self.fab_home / channel.PAGE).exists())
        output = io.StringIO()
        with patch("fab.log.now", return_value=ts(0)), redirect_stdout(output):
            self.assertEqual(cli.main(["page", "write", str(directory)]), 0)
        self.assertEqual(output.getvalue(), str(self.fab_home / channel.PAGE) + "\n")
        self.assertEqual((self.fab_home / channel.PAGE).read_text(), channel.compose([directory], [], ts(0)))

    def test_main_answer_logs_and_rewrites_page_without_question(self):
        log.append("call.ended", subject="demo/core", call="cut-1", outcome="question", ts=ts(1))
        _write(self.fab_home / "calls/cut-1/report.md", "Question: Which host?\n")
        channel.write(channel.compose([], log.read(), ts(1)))
        output = io.StringIO()
        with patch("fab.log.now", return_value=ts(2)), redirect_stdout(output):
            self.assertEqual(cli.main(["page", "answer", "demo/core", " Use  ", "\nhel8 "]), 0)
        self.assertEqual(log.read()[-1]["answer"], "Use hel8")
        self.assertEqual(log.read()[-1]["by"], "user")
        self.assertEqual(output.getvalue(), f"answered demo/core\n{self.fab_home / channel.PAGE}\n")
        page = (self.fab_home / channel.PAGE).read_text()
        self.assertNotIn("Which host?", page)
        self.assertIn("## Questions\n\n(none)", page)

    def test_main_clear_logs_rewrites_wakes_and_allows_later_rejections(self):
        for minute, option, by in ((1, [], "user"), (4, ["--by", "free"], "free")):
            with self.subTest(by=by):
                log.append(**self.rejection(minute, tests=["pkg::test"]))
                channel.write(channel.compose([], log.read(), ts(minute)))
                self.assertIn("### queue:hand/pushed,", (self.fab_home / channel.PAGE).read_text())
                output = io.StringIO()
                with patch("fab.log.now", return_value=ts(minute + 1)), redirect_stdout(output):
                    self.assertEqual(cli.main(["page", "clear", "queue:hand/pushed",
                                               " Retry  ", "\nelsewhere ", *option]), 0)
                self.assertEqual(log.read()[-1], event(minute + 1, "signal.cleared",
                                 signal="queue:hand/pushed", by=by, text="Retry elsewhere"))
                self.assertEqual(output.getvalue(), f"cleared queue:hand/pushed\n{self.fab_home / channel.PAGE}\n")
                self.assertIn("## Open signals\n\n(none)", (self.fab_home / channel.PAGE).read_text())
                self.assertIn("clear queue:hand/pushed\n", (self.fab_home / "tick.want").read_text())

    def test_main_clear_refuses_unknown_or_closed_without_writing_or_waking(self):
        for events in ([], [self.rejection(), event(2, "signal.cleared", signal="queue:hand/pushed")]):
            with self.subTest(events=events):
                for record in events:
                    log.append(**record)
                before = log.read()
                with redirect_stderr(io.StringIO()) as errors:
                    self.assertEqual(cli.main(["page", "clear", "queue:hand/pushed", "done"]), 1)
                self.assertIn("fab page: no open signal", errors.getvalue())
                self.assertEqual(log.read(), before)
                self.assertFalse((self.fab_home / channel.PAGE).exists())
                self.assertFalse((self.fab_home / "tick.want").exists())

    def test_clear_refuses_a_signal_that_cannot_be_cleared(self):
        with patch.object(channel, "signals", return_value=[
                channel.Signal("unclearable", "needs recovery", ts(1), (), "run.log", False)]):
            with self.assertRaisesRegex(ValueError, "cannot be cleared"):
                channel.clear("unclearable", "done", [])
        self.assertEqual(log.read(), [])
        self.assertFalse((self.fab_home / "tick.want").exists())

    def test_main_errors_exit_one_without_logging(self):
        errors = io.StringIO()
        with redirect_stderr(errors):
            self.assertEqual(cli.main(["page", "answer", "missing", "yes"]), 1)
            with patch.object(channel, "write", side_effect=OSError("disk full")):
                self.assertEqual(cli.main(["page", "write"]), 1)
        self.assertIn("fab page: no open call or parked chain", errors.getvalue())
        self.assertIn("fab page: disk full", errors.getvalue())
        self.assertEqual(log.read(), [])

    def test_main_bad_arguments_exit_two(self):
        for argv in ([], ["unknown"], ["answer"], ["answer", "demo/core"],
                     ["answer", "demo/core", "yes", "--by", "other"],
                     ["clear"], ["clear", "queue:hand/pushed"],
                     ["clear", "queue:hand/pushed", "done", "--by"]):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                cli.main(["page", *argv])
            self.assertEqual(caught.exception.code, 2)
