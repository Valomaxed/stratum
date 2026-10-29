"""Analytical and invariant checks, independent of visual/ML implementation."""
import unittest
import numpy as np
from twin.fem import Truss, demo_truss


class FEMTests(unittest.TestCase):
    def bar(self, dim=2):
        nodes = np.zeros((2, dim)); nodes[1, 0] = 2
        force = np.zeros((2, dim)); force[1, 0] = 1000
        fixed = list(range(dim))+list(range(dim+1, 2*dim))
        return Truss(nodes, [[0, 1]], .001, 200e9, 7850, fixed, force, 1)

    def test_bar_analytical_2d_and_3d(self):
        for dim in (2, 3):
            model = self.bar(dim); result = model.solve()
            self.assertAlmostEqual(result['displacement'][dim], 1000*2/(.001*200e9), places=12)
            self.assertAlmostEqual(result['reactions'][0], -1000)
            self.assertAlmostEqual(result['axial_force'][0], 1000)
            self.assertAlmostEqual(result['stress'][0], 1e6)
            self.assertAlmostEqual(result['strain'][0], 5e-6)

    def test_stiffness_loss_matches_analytical_compliance(self):
        model = self.bar(); healthy = model.solve(); damaged = model.solve([.25])
        self.assertAlmostEqual(damaged['displacement'][2]/healthy['displacement'][2], 4/3)
        self.assertAlmostEqual(damaged['axial_force'][0], healthy['axial_force'][0])

    def test_mass_and_modal_frequency_analytical(self):
        model = self.bar(); result = model.solve()
        k = 200e9*.001/2; mass = 1+7850*.001*2/2
        expected = np.sqrt(k/mass)/(2*np.pi)
        self.assertAlmostEqual(model.modes(count=1)['frequencies'][0], expected, places=10)
        self.assertAlmostEqual(result['M'][2, 2], mass)

    def test_force_moment_energy_and_symmetry(self):
        model = demo_truss(); damage = np.zeros(len(model.members)); damage[[3, 13]]=[.2,.45]
        result = model.solve(damage)
        total = (result['reactions']+model.loads).reshape(-1, 2)
        np.testing.assert_allclose(total.sum(axis=0), 0, atol=1e-6)
        moment = np.sum(model.nodes[:, 0]*total[:, 1]-model.nodes[:, 1]*total[:, 0])
        self.assertAlmostEqual(moment, 0, places=5)
        np.testing.assert_allclose(result['K'], result['K'].T, atol=1e-10)
        self.assertAlmostEqual(result['strain_energy'], .5*result['displacement'] @ model.loads, places=7)
        np.testing.assert_allclose(result['reactions'][model.free], 0, atol=1e-6)

    def test_modal_residual_and_mass_orthogonality(self):
        model = demo_truss(); k,m,_ = model.assemble(); modal = model.modes(); phi = modal['shapes']
        np.testing.assert_allclose(phi.T @ m @ phi, np.eye(phi.shape[1]), atol=1e-12)
        residual = (k @ phi-m @ phi @ np.diag((2*np.pi*modal['frequencies'])**2))[model.free]
        self.assertLess(np.linalg.norm(residual)/np.linalg.norm((k @ phi)[model.free]), 1e-12)

    def test_newmark_equilibrium_and_step_convergence(self):
        model = demo_truss()
        coarse = model.transient(dt=.002, duration=.5)
        fine = model.transient(dt=.001, duration=.5)
        finer = model.transient(dt=.0005, duration=.5)
        self.assertLess(coarse['relative_residual'], 1e-9)
        e1 = np.linalg.norm(coarse['displacement']-fine['displacement'][::2])
        e2 = np.linalg.norm(fine['displacement'][::2]-finer['displacement'][::4])
        self.assertGreater(e1/e2, 3)
        self.assertLess(e1/e2, 5)
        np.testing.assert_array_equal(coarse['displacement'][:, model.fixed_dofs], 0)

    def test_unstable_and_invalid_models_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unstable'):
            self.bar().solve([1])
        with self.assertRaisesRegex(ValueError, 'Unstable'):
            self.bar().solve(removed=[0])
        for loss in ([float('nan')], [-.1], [1.1], [0,0]):
            with self.assertRaises(ValueError):
                self.bar().solve(loss)

    def test_fractional_support_connectivity_and_removal_indices_rejected(self):
        for value in ([0,.5],[0,float('nan')],[True,False],['0','1']):
            with self.assertRaisesRegex(ValueError,'Support DOFs'):
                Truss([[0,0],[2,0]],[[0,1]],.001,200e9,7850,value,[[0,0],[1000,0]],1)
        with self.assertRaisesRegex(ValueError,'Member connectivity'):
            Truss([[0,0],[2,0]],[[0,.9]],.001,200e9,7850,[0,1,3],[[0,0],[1000,0]],1)
        with self.assertRaisesRegex(ValueError,'Removed members'):
            self.bar().solve(removed=[.5])


if __name__ == '__main__':
    unittest.main()
