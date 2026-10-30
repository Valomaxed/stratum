"""Support metadata, rigid restraint rank and independent joint equilibrium."""
import unittest
from twin.support_audit import audit


class SupportAuditTests(unittest.TestCase):
    def test_all_model_supports_and_equilibrium(self):
        report = audit()
        self.assertTrue(report['passed'])
        self.assertEqual([m['model'] for m in report['trusses']], ['planar', 'space', 'bridge'])
        self.assertEqual(sum(len(m['cases']) for m in report['trusses']), 18)
        self.assertEqual(report['frames'], [])
        self.assertLess(report['bridge_dynamic']['free_equilibrium_error_n'], 1e-5)


if __name__ == '__main__':
    unittest.main()
