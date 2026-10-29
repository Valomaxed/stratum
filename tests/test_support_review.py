"""Verify support metadata and global equilibrium for every registered structure."""
import unittest
import numpy as np
from twin.models import FACTORIES, CASE_FACTORIES, describe_model


class SupportReviewTests(unittest.TestCase):
    def test_all_support_axes_match_solver_restraints_and_remove_rigid_motion(self):
        for model_id,factory in FACTORIES.items():
            with self.subTest(model=model_id):
                model=factory();description=describe_model(model_id,model)
                reported=[s['node']*model.dim+'XYZ'.index(axis) for s in description['supports'] for axis in s['axes']]
                self.assertEqual(sorted(reported),model.fixed_dofs.tolist())
                for support in description['supports']:
                    self.assertEqual(support['free_axes'],[axis for axis in 'XYZ'[:model.dim] if axis not in support['axes']])
                count=3 if model.dim==2 else 6
                rigid=np.zeros((model.nodes.size,count))
                for i,point in enumerate(model.nodes):
                    rigid[i*model.dim:(i+1)*model.dim,:model.dim]=np.eye(model.dim)
                    if model.dim==2:rigid[2*i:2*i+2,2]=[-point[1],point[0]]
                    else:rigid[3*i:3*i+3,3:]=np.array([np.cross(axis,point) for axis in np.eye(3)]).T
                self.assertEqual(np.linalg.matrix_rank(rigid[model.fixed_dofs]),count)

    def test_all_model_load_cases_balance_forces_moments_and_free_dofs(self):
        for model_id,factory in FACTORIES.items():
            model=factory()
            for case in CASE_FACTORIES[model_id](model):
                with self.subTest(model=model_id,case=case['id']):
                    force=case['forces'];result=model.solve(forces=force)
                    np.testing.assert_array_equal(result['displacement'][model.fixed_dofs],0)
                    np.testing.assert_allclose(result['reactions'][model.free],0,atol=1e-6)
                    net=(result['reactions']+force).reshape(-1,model.dim)
                    np.testing.assert_allclose(net.sum(axis=0),0,atol=1e-6)
                    if model.dim==2:
                        self.assertLess(abs(np.sum(model.nodes[:,0]*net[:,1]-model.nodes[:,1]*net[:,0])),1e-5)
                    else:np.testing.assert_allclose(np.cross(model.nodes,net).sum(axis=0),0,atol=1e-5)


if __name__=='__main__':unittest.main()
