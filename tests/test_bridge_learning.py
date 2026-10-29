import json
import unittest
from pathlib import Path
import numpy as np
from twin.bridge import bridge_context
from twin.bridge_dynamics import _history,prepare_dynamic_playback
from twin.bridge_learning import (BridgeDamageEstimator,features,normalized_packet,contract,evaluate)


class ClassifierStub:
    classes_=np.array([0,5])
    def predict_proba(self,x):
        self.last=x.copy();return np.tile([.05,.95],(len(x),1))


class RegressorStub:
    def predict(self,x):return np.full(len(x),.4)


class BridgeLearningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context=bridge_context();model=cls.context['model'];config=cls.context['config']
        cls.healthy=_history(model,config,None,1,(),10,.02,include_trace=False)
        loss=np.zeros(78);loss[4]=.4
        cls.bundle=prepare_dynamic_playback(damage=loss)

    def estimator(self):
        directory=Path(__file__).parent/'_missing_bridge_artifact_for_test'
        self.assertFalse(directory.exists());estimator=BridgeDamageEstimator(directory)
        estimator.artifact={'classifier':ClassifierStub(),'regressor':RegressorStub(),'threshold':.35}
        estimator.report={'experiments':[],'damage_family':'Healthy/one loss'};estimator.baseline=self.healthy
        return estimator

    def test_packet_has_only_measured_strain_displacement_and_load_invariance(self):
        model=self.context['model'];healthy=self.healthy
        packet=normalized_packet(model,healthy,healthy)
        np.testing.assert_array_equal(packet,0)
        self.assertEqual(features(packet).shape,(2882,))
        scaled={**healthy,'strain':healthy['strain']*1.7,'displacement':healthy['displacement']*1.7}
        np.testing.assert_allclose(normalized_packet(model,scaled,healthy,1.7),0,atol=1e-14)
        self.assertEqual(len(contract()),64)

    def test_inference_does_not_consume_configured_labels(self):
        estimator=self.estimator();first=estimator.predict(self.bundle,noise=.005)
        first_features=estimator.artifact['classifier'].last.copy()
        forged={**self.bundle,'comparison':{'damaged_members':[]},'effective_modulus':[0]*78,
                'damage':[.8]*78,'healthy_signal':None,'healthy_displacement':None}
        second=estimator.predict(forged,noise=.005)
        self.assertEqual(first,second)
        np.testing.assert_array_equal(first_features,estimator.artifact['classifier'].last)
        self.assertEqual(first['member'],4);self.assertTrue(first['accepted'])

    def test_outside_domain_missing_artifact_and_incomplete_history_abstain(self):
        directory=Path(__file__).parent/'_missing_bridge_artifact_for_test'
        self.assertFalse(directory.exists())
        self.assertFalse(BridgeDamageEstimator(directory).predict(self.bundle)['available'])
        estimator=self.estimator()
        for change in ({'speed_kmh':60},{'damping_ratio':0}, {'method':'quasi-static'},
                       {'settings':{**self.bundle['settings'],'lane_offset_m':1}}):
            self.assertFalse(estimator.predict({**self.bundle,**change})['available'])
        for kwargs in ({'sensor_count':10},{'missing':.1},{'noise':.02},{'drift':.01}):
            self.assertFalse(estimator.predict(self.bundle,**kwargs)['available'])
        shortened={**self.healthy,'time':self.healthy['time'][:-3],
                   'strain':self.healthy['strain'][:-3],'displacement':self.healthy['displacement'][:-3]}
        with self.assertRaises(ValueError):normalized_packet(self.context['model'],shortened,self.healthy)

    def test_metrics_count_rejection_and_wrong_location_as_missed_severity(self):
        labels=np.array([0,5]);truth=np.array([0,.4]);x=np.zeros((2,2882))
        result=evaluate(ClassifierStub(),RegressorStub(),x,labels,truth,threshold=.99)
        self.assertEqual(result['accuracy'],0);self.assertEqual(result['coverage'],0)
        self.assertAlmostEqual(result['damaged_severity_mae_pp'],40)

    def test_saved_report_and_test_predictions_are_recomputable_if_present(self):
        from twin.bridge_learning import DIRECTORY
        report_path=DIRECTORY/'report.json'
        if not report_path.exists():self.skipTest('Training artifact not present')
        report=json.loads(report_path.read_text(encoding='utf8'))
        raw=np.load(DIRECTORY/'test-predictions.npz');labels=raw['label'];damage=labels>0
        for condition in report['experiments']:
            name=condition['condition'];pred=raw[name+'_predicted'];accepted=raw[name+'_accepted'];correct=pred==labels
            self.assertAlmostEqual(condition['accuracy'],np.mean(correct&accepted))
            assigned=np.where(correct&accepted,raw[name+'_severity'],0)
            self.assertAlmostEqual(condition['damaged_severity_mae_pp'],100*np.mean(np.abs(assigned[damage]-raw['true_severity'][damage])))
        dataset=np.load(DIRECTORY/'dataset.npz');split=dataset['split']
        self.assertEqual(report['test_cases'],np.sum(split==2))
        self.assertTrue(np.all(split[raw['case_ids']]==2))


if __name__=='__main__':unittest.main()
