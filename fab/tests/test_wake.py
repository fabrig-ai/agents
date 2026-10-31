import unittest

from fab import wake
from fab.sh import ssh
from fab.tests.support import FakeRunner
from fab.tests.wakes import BUILDER, DISPATCHER, HOSTS, WakeTestCase, ended, started


class ExemplarTest(WakeTestCase):
    @unittest.skip("pending: agents-rebuild/wake")
    def test_an_event_reaches_the_tick_once_and_a_lost_one_is_noted(self):
        fake = FakeRunner()
        # A builder's run ends: its wake goes over ssh to the dispatcher, where it is a want.
        self.assertTrue(wake.wake("codex 1", sh=fake, hosts=HOSTS, here=BUILDER))
        self.assertEqual(fake.argvs(), [ssh(HOSTS[DISPATCHER].ssh, ["fab", "wake", "codex 1"])])
        self.assertNoWant()
        self.assertTrue(wake.wake("codex 1", sh=fake, hosts=HOSTS, here=DISPATCHER))
        self.assertTrue(wake.wake("queue landed draft/a", sh=fake, hosts=HOSTS, here=DISPATCHER))
        self.assertEqual(len(fake.calls), 1)
        self.assertWanted("codex 1", "queue landed draft/a")
        # A burst is one want, taken once.
        self.assertEqual(wake.take(self.want), ["codex 1", "queue landed draft/a"])
        self.assertIsNone(wake.take(self.want))
        # A backstop round that collects an ended run found an event nobody announced.
        lines = wake.settle("backstop", None, [started("draft/b-1"), ended("draft/a-1")],
                            path=self.want, log_path=self.log_path)
        self.assertEqual(self.notes(), ["lost event: run.ended draft/a-1"])
        self.assertWanted("tick 1: run.ended")
        self.assertEqual(lines, ["lost - lost event: run.ended draft/a-1",
                                 "again - tick 1: run.ended"])


if __name__ == "__main__":
    unittest.main()
