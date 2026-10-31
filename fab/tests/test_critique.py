import unittest

from fab import critique
from fab.tests.critiques import Story, assert_stage, critic

PENDING = "pending: agents-rebuild/critique"  # the task critic-run removes it when it fills the module


@unittest.skip(PENDING)
class ExemplarTest(unittest.TestCase):
    def test_findings_are_fixed_once_then_the_branch_goes_on(self):
        story = Story().ran("implement", "done")
        assert_stage(self, story, "critique")
        story.started(critique.KIND)
        assert_stage(self, story, "critiquing", critic_run=critic(1))
        story.ended("failed")
        assert_stage(self, story, "fix", critic_run=critic(1))
        story.fixed("done")
        assert_stage(self, story, "clear", critic_run=critic(1))
        story.rejected("gate:size").ran("repair", "done")
        assert_stage(self, story, "clear", critic_run=critic(1))


if __name__ == "__main__":
    unittest.main()
