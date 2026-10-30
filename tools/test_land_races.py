"""Upstream race policy with disposable remotes and fake claimed builders."""
import unittest
import test_land as fixture


class LandRaceTests(fixture.LandFixture):
    def test_races_disjoint_once_overlapping_twice_second_refused(self):
        self.env['RACE_PATH']='b/upstream'
        self.land('--host','hetzner7')
        self.assertEqual((self.home/'gates').read_text(),'1')
        self.assertEqual(self.tip(),self.git('rev-parse','HEAD'))
        self.assert_released()

    def test_overlapping_race_checks_twice(self):
        self.env['RACE_PATH']='a/upstream'
        self.land('--host','hetzner7')
        self.assertEqual((self.home/'gates').read_text(),'2')
        self.assert_released()

    def test_second_race_never_pushes_candidate(self):
        self.env.update(RACE_PATH='a/upstream',SECOND_RACE='1')
        self.land('--host','hetzner7',expected=1)
        self.assertNotEqual(self.tip(),self.git('rev-parse','HEAD'))
        self.assert_released()


if __name__ == "__main__":
    unittest.main()
