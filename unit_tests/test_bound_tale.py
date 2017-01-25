import unittest

import isambard_dev as isambard


class TestBoundTaleModelling(unittest.TestCase):
    def test_tale_helix_pair(self):
        thp = isambard.specifications.assembly_specs.bound_tale.TaleHelixPair()
        parameters = isambard.specifications.assembly_specs.bound_tale._repeating_unit_parameters
        self.assertAlmostEqual(thp.axis_distances[0], -parameters['axis_dist'], places=3)
        self.assertAlmostEqual(thp.axis_distances[1], parameters['axis_dist'], places=3)
        self.assertEqual(thp.z_shifts[0], 0)
        self.assertAlmostEqual(thp.z_shifts[1], parameters['z_shift'])
        self.assertAlmostEqual(thp.phis[0], parameters['ia_1'], places=3)
        self.assertAlmostEqual(thp.phis[1], parameters['ia_2'], places=3)
        self.assertEqual(thp.splays[0], 0)
        self.assertAlmostEqual(thp.splays[1], parameters['splay'], places=3)
        self.assertEqual(thp.off_plane[0], 0)
        self.assertAlmostEqual(thp.off_plane[1], parameters['off_plane'], places=3)
