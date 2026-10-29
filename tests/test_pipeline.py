import json
import unittest
import numpy as np
from twin.fem import demo_truss
from twin.sensors import SensorArray
from twin.learning import ARTIFACT, DamageEstimator, refine
from twin.server import TwinService


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sensors = SensorArray(demo_truss())

    def test_sensor_masks_and_known_load_normalization(self):
        s = self.sensors; damage = np.zeros(21); damage[13]=.3
        values, mask = s.observe(damage, count=5, missing=0, load_scale=2)
        self.assertEqual(mask.sum(), 5)
        np.testing.assert_allclose(s.features(values, mask, 2), s.features(values/2, mask), atol=1e-14)
        values[~mask]=np.nan
        self.assertTrue(np.all(np.isfinite(s.features(values, mask, 2))))
        _, mask = s.observe(damage, missing=1)
        self.assertFalse(mask.any())

    def test_sensor_placement_is_a_complete_permutation(self):
        order = self.sensors.optimal_order()
        self.assertEqual(sorted(order.tolist()), list(range(38)))
        # Independent static channels are fewer than stiffness unknowns for one load pattern.
        self.assertLess(np.linalg.matrix_rank(self.sensors.sensitivity()), 21)

    def test_physics_inverse_recovers_clean_damage(self):
        damage = np.zeros(21); damage[[4,13]]=[.2,.3]
        values = self.sensors.response(damage)
        recovered, info = refine(self.sensors, values, np.ones(38, bool), np.zeros(21))
        self.assertTrue(info['converged'])
        np.testing.assert_allclose(recovered, damage, atol=.015)

    @unittest.skipUnless(ARTIFACT.exists(), 'Train the model first')
    def test_estimator_uses_measurements_and_handles_no_sensors(self):
        estimator = DamageEstimator(self.sensors); damage = np.zeros(21); damage[13]=.3
        values, mask = self.sensors.observe(damage)
        result = estimator.predict(values, mask, physics=True)
        self.assertTrue(result['available'])
        self.assertEqual(int(np.argmax(result['severity'])), 13)
        self.assertAlmostEqual(result['severity'][13], .3, delta=.02)
        self.assertFalse(estimator.predict(values, np.zeros(38,bool))['available'])

    def test_service_payload_and_external_observations(self):
        service = TwinService(); damage = np.zeros(21); damage[13]=.3
        result = service.analyze({'damage':damage.tolist(), 'sensor_count':10})
        self.assertEqual(len(result['nodes']), 10)
        self.assertEqual(len(result['members']), 21)
        self.assertEqual(result['summary']['active_sensors'], 10)
        json.dumps(result, allow_nan=False)
        readings = self.sensors.response(damage)
        packet = {'load_scale':1, 'measurements':{s['id']:float(v) for s,v in zip(self.sensors.catalog,readings)}}
        output = service.ingest(packet)
        self.assertEqual(output['active_sensors'], 38)
        with self.assertRaises(ValueError):
            service.ingest({'measurements':{'unknown':1}})
        with self.assertRaises(ValueError):
            service.ingest({'measurements':{'SG01':float('nan')}})
        with self.assertRaises(ValueError):
            service.analyze({'damage':damage.tolist(), 'load_scale':float('nan')})
        removed = service.analyze({'removed':[13], 'noise':0})
        self.assertEqual(removed['members'][13]['effective_modulus'], 0)
        self.assertEqual(removed['members'][13]['axial_force'], 0)
        self.assertFalse(removed['prediction']['available'])
        self.assertAlmostEqual(removed['summary']['stiffness_index'], 100*20/21)


if __name__ == '__main__':
    unittest.main()
