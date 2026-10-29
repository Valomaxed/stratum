"""Independent 3D benchmarks and invariants for the space-truss milestone."""
import json
import unittest
import numpy as np
from twin.fem import Truss, space_truss
from twin.load_cases import LoadCaseSensors, space_load_cases
from twin.server import TwinService


class SpaceFEMTests(unittest.TestCase):
    def test_tripod_closed_form_and_rotation_invariance(self):
        # Three equal inclined bars, fixed feet and a free apex. Symmetry gives
        # a diagonal 3x3 apex stiffness independently of the FEM assembly.
        radius, height, area, modulus = 2., 3., .001, 200e9
        angles = np.arange(3)*2*np.pi/3
        nodes = np.vstack((np.column_stack((radius*np.cos(angles), np.zeros(3), radius*np.sin(angles))), [0,height,0]))
        force = np.zeros((4,3)); force[3] = [1200,-3000,800]
        length = np.hypot(radius,height)
        diagonal = modulus*area/length**3*np.array([1.5*radius**2,3*height**2,1.5*radius**2])
        expected = force[3]/diagonal
        model = Truss(nodes, [[0,3],[1,3],[2,3]], area, modulus, 7850, range(9), force, 2)
        result = model.solve()
        np.testing.assert_allclose(result['displacement'][9:], expected, rtol=1e-12, atol=1e-16)
        apex_mass = 2+3*7850*area*length/2
        np.testing.assert_allclose(model.modes(count=3)['frequencies'],
                                   np.sort(np.sqrt(diagonal/apex_mass)/(2*np.pi)),rtol=1e-12)
        # Rotate geometry and force about an oblique axis (Rodrigues formula).
        axis = np.array([1.,2.,3.]); axis /= np.linalg.norm(axis)
        cross = np.array([[0,-axis[2],axis[1]],[axis[2],0,-axis[0]],[-axis[1],axis[0],0]])
        rotation = np.eye(3)+np.sin(.7)*cross+(1-np.cos(.7))*(cross@cross)
        rotated = Truss(nodes@rotation.T, model.members, area, modulus, 7850, range(9), force@rotation.T, 2)
        np.testing.assert_allclose(rotated.solve()['displacement'].reshape(-1,3), result['displacement'].reshape(-1,3)@rotation.T, rtol=1e-12, atol=1e-16)
        np.testing.assert_allclose(rotated.solve()['axial_force'],result['axial_force'],rtol=1e-12)

    def test_space_force_moment_energy_and_damage(self):
        model = space_truss()
        damage = np.zeros(len(model.members)); damage[[4,50]] = [.3,.2]
        self.assertEqual((len(model.nodes),len(model.members)),(20,78))
        self.assertEqual(len(model.free),54)
        for case in space_load_cases(model):
            force = case['forces']
            result = model.solve(damage,forces=force)
            total = (result['reactions']+force).reshape(-1,3)
            np.testing.assert_allclose(total.sum(axis=0),0,atol=1e-6)
            np.testing.assert_allclose(np.cross(model.nodes,total).sum(axis=0),0,atol=1e-5)
            np.testing.assert_allclose(result['displacement'][model.fixed_dofs],0,atol=0)
            np.testing.assert_allclose(result['reactions'][model.free],0,atol=1e-6)
            self.assertAlmostEqual(result['strain_energy'],.5*result['displacement']@force,places=8)
            self.assertGreater(result['strain_energy'],model.solve(forces=force)['strain_energy'])
        wind = model.solve(forces=space_load_cases(model)[2]['forces'])
        self.assertGreater(np.max(np.abs(wind['displacement'].reshape(-1,3)[:,2])),1e-5)

    def test_space_modes_and_transient_equilibrium(self):
        model = space_truss(); k,m,_ = model.assemble(); modal = model.modes()
        phi = modal['shapes']; omega2 = (2*np.pi*modal['frequencies'])**2
        np.testing.assert_allclose(phi.T@m@phi,np.eye(6),atol=1e-12)
        residual = (k@phi-(m@phi)*omega2)[model.free]
        self.assertLess(np.linalg.norm(residual)/np.linalg.norm((k@phi)[model.free]),1e-11)
        damage = np.zeros(78); damage[4]=.4
        self.assertTrue(np.all(model.modes(damage)['frequencies']<=modal['frequencies']+1e-10))
        dynamic = model.transient(damage,duration=.3)
        self.assertLess(dynamic['relative_residual'],1e-9)
        np.testing.assert_array_equal(dynamic['displacement'][:,model.fixed_dofs],0)

    def test_every_member_damage_and_3d_sensor_tangents(self):
        model = space_truss(); healthy = model.solve()['strain_energy']
        for index in range(len(model.members)):
            damage = np.zeros(78); damage[index]=.8
            # Every UI-selectable member can lose 80% stiffness without a mechanism.
            result = model.solve(damage)
            self.assertTrue(np.all(np.isfinite(result['displacement'])))
            self.assertGreaterEqual(result['strain_energy'],healthy-1e-9)
        sensors = LoadCaseSensors(model,cases=space_load_cases(model))
        damage = np.linspace(.1,.3,78); jacobian = sensors.jacobian(damage)
        for index in (0,4,50,77):
            step = np.zeros(78); step[index]=1e-5
            finite_difference = (sensors.response(damage+step)-sensors.response(damage-step))/(2e-5)/sensors.scale
            np.testing.assert_allclose(jacobian[:,index],finite_difference,rtol=1e-5,atol=1e-8)


class SpaceServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = TwinService()

    def test_model_dispatch_3d_loads_shapes_and_no_planar_inference(self):
        loss = np.zeros(78); loss[4]=.3
        response = self.service.analyze({'model_id':'space','protocol':'multi','display_case':'LC3',
                                       'damage':loss.tolist(),'sensor_count':12,'noise':0,'physics':True})
        self.assertEqual(response['dimension'],3)
        self.assertEqual(len(response['members']),78)
        self.assertEqual(response['summary']['sensor_capacity'],132)
        self.assertEqual(response['excitation']['active_observations'],36)
        self.assertEqual(response['members'][4]['damage'],.3)
        self.assertEqual(len(response['reactions'][0]),3)
        self.assertEqual(np.shape(response['modal']['shapes']),(6,20,3))
        self.assertTrue(any(abs(n['uz'])>1e-6 for n in response['nodes']))
        self.assertTrue(all(f['fz']>0 and f['fx']>0 for f in response['loads']))
        self.assertFalse(response['prediction']['available'])
        self.assertIn('not trained',response['prediction']['reason'])
        self.assertEqual(response['signal']['sensor_id'],'A09Y')
        json.dumps(response,allow_nan=False)
        planar = self.service.analyze({'sensor_count':10,'noise':0})
        self.assertEqual(planar['model_id'],'planar')
        self.assertEqual(len(planar['members']),21)
        self.assertTrue(all(n['z']==0 and n['uz']==0 for n in planar['nodes']))

    def test_model_and_geometry_mismatch_rejected(self):
        for request in ({'model_id':'unknown'}, {'model_id':'space','damage':[0]*21},
                        {'model_id':'space','sensor_count':133}):
            with self.assertRaises(ValueError):
                self.service.analyze(request)
        with self.assertRaisesRegex(ValueError,'only for the planar'):
            self.service.ingest({'model_id':'space','measurements':{'SG01':0}})


if __name__ == '__main__':
    unittest.main()
