"""Verification must detect disagreements and cannot retain stale PASS badges."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from twin.seismic import G, build_frame, frame_history
from twin.seismic_benchmark import ROOT, compare_reference, saved_report, source_hashes


class ReportIntegrityTests(unittest.TestCase):
    def test_missing_changed_corrupt_and_inconsistent_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.json'
            self.assertFalse(saved_report(path)['available'])
            report=dict(schema_version=1,source_hashes=source_hashes(),passed=True,
                        comparisons=[{'passed':True}],convergence=[{'passed':True}])
            path.write_text(json.dumps(report))
            self.assertTrue(saved_report(path)['current_pass'])
            with patch('twin.seismic_benchmark.source_hashes',return_value={'changed':'numerical-source'}):
                result=saved_report(path)
                self.assertTrue(result['available']);self.assertFalse(result['fresh']);self.assertFalse(result['current_pass'])
            report['comparisons'][0]['passed']=False
            path.write_text(json.dumps(report))
            self.assertFalse(saved_report(path)['available'])
            path.write_text('{invalid')
            self.assertFalse(saved_report(path)['available'])

    def test_full_history_refines_grid_without_changing_production_peaks(self):
        frame=build_frame({'stories':2},'chevron')
        t=np.arange(51)*.01;record=dict(npts=len(t),dt=.01,acceleration=.1*G*np.sin(3*t))
        baseline=frame_history(frame,record)
        full=frame_history(frame,record,full_history=True)
        half=frame_history(frame,record,time_step_divisor=2,full_history=True)
        for key in ('peak_drift_pct','peak_roof_mm','peak_base_shear_kn'):
            self.assertEqual(baseline[key],full[key])
        np.testing.assert_allclose(half['history']['time_s'][::2],full['history']['time_s'],atol=1e-14)
        self.assertEqual(half['integration']['steps'],2*full['integration']['steps'])
        with self.assertRaisesRegex(ValueError,'exceeds 1 time steps'):
            frame_history(frame,record,step_limit=1)
        for invalid in (0,True,1.5,9):
            with self.assertRaises(ValueError):frame_history(frame,record,time_step_divisor=invalid)


class IndependentOpenSeesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.executable=Path(os.environ.get('OPENSEES_PYTHON',ROOT/'work/opensees-venv/Scripts/python.exe'))
        if not cls.executable.is_file():raise unittest.SkipTest('Optional OpenSees verification interpreter is not installed')
        cls.frame=build_frame(dict(stories=2,damping_ratio=.07,bay_width_m=4.5,story_height_m=3.5),'chevron')
        t=np.arange(101)*.01
        cls.record=dict(npts=len(t),dt=.01,acceleration=G*(.02*np.cos(3*t)+.01*np.sin(7*t)))
        cls.result=frame_history(cls.frame,cls.record,scale=.8,full_history=True)
        spec=dict(frame=cls.frame['config'],system='chevron',record_dt_s=.01,
                  acceleration_m_s2=cls.record['acceleration'].tolist(),scale_factor=.8,
                  analysis_dt_s=cls.result['integration']['dt_s'])
        with tempfile.TemporaryDirectory() as directory:
            source,target=Path(directory)/'input.json',Path(directory)/'output.json'
            source.write_text(json.dumps(spec))
            worker=subprocess.run([str(cls.executable),str(ROOT/'twin/opensees_reference.py'),str(source),str(target)],
                                  capture_output=True,text=True,timeout=30)
            if worker.returncode:raise RuntimeError(worker.stderr)
            cls.reference=json.loads(target.read_text())

    def test_independent_full_history_and_nonzero_initial_acceleration(self):
        comparison=compare_reference(self.result,self.reference)
        self.assertTrue(comparison['passed'],comparison)
        self.assertLess(comparison['errors']['floor_displacement_m']['normalized_max'],1e-7)
        first=np.array(self.reference['relative_acceleration_m_s2'])[0]
        np.testing.assert_allclose(first,-self.record['acceleration'][0]*.8,atol=1e-12)
        self.assertLess(self.reference['support_and_damper_balance_error'],1e-8)

    def test_disagreements_fail_without_relaxing_thresholds(self):
        for key in ('frequencies_hz','displacement_m','base_shear_kn','relative_acceleration_m_s2'):
            changed=deepcopy(self.reference)
            changed[key]=(np.asarray(changed[key])*1.01).tolist()
            self.assertFalse(compare_reference(self.result,changed)['passed'],key)
        changed=deepcopy(self.reference);changed['peaks']['drift_pct']*=1.01
        self.assertFalse(compare_reference(self.result,changed)['passed'])
        changed=deepcopy(self.reference);changed['support_and_damper_balance_error']=.01
        self.assertFalse(compare_reference(self.result,changed)['passed'])

    def test_mismatched_time_grid_is_rejected(self):
        changed=deepcopy(self.reference);changed['time_s'][-1]+=.001
        with self.assertRaisesRegex(ValueError,'same integration grid'):
            compare_reference(self.result,changed)


if __name__=='__main__':unittest.main()
