import hashlib
import json
import unittest
from pathlib import Path
import numpy as np
from threadpoolctl import threadpool_limits
from twin.bridge_sparse import (sparse_features,healthy_order,paired_packets,SparseBridgeDamageEstimator,DIRECTORY,BUDGETS)
from twin.bridge_learning import features,BridgeDamageEstimator,DIRECTORY as BASE
from twin.bridge import bridge_context
from twin.sensors import SensorArray
from tests.test_bridge_learning import ClassifierStub,RegressorStub


class SparseBridgeTests(unittest.TestCase):
    def test_features_use_only_selected_physical_channels(self):
        packet=np.random.default_rng(4).normal(size=(131,20));indices=[0,4,7,52,130]
        expected=sparse_features(packet,indices)
        forged=packet.copy();forged[np.setdiff1d(np.arange(131),indices)]=np.nan
        np.testing.assert_array_equal(sparse_features(forged,indices),expected)
        np.testing.assert_array_equal(sparse_features(packet,list(range(131))),features(packet))
        self.assertEqual(len(expected),5*22)
        for bad in ([],[1,1],[-1],[131],[2.5]):
            with self.assertRaises(ValueError):sparse_features(packet,bad)

    def test_healthy_placement_selects_entire_time_groups(self):
        sensitivity=np.zeros((131,20,78))
        for i in range(78):sensitivity[i,0,i]=1
        sensitivity[130,np.arange(20),np.arange(20)]=2
        with threadpool_limits(limits=1):order=healthy_order(sensitivity)
        self.assertEqual(order[0],130)
        self.assertEqual(sorted(order),list(range(131)))
        self.assertTrue(set(order[:5])<set(order[:10])<set(order[:20]))
        with self.assertRaises(ValueError):healthy_order(sensitivity[:10])

    def test_original_noise_and_test_predictions_are_replayed(self):
        if not (BASE/'dataset.npz').exists():self.skipTest('Original bridge study not present')
        dataset=np.load(BASE/'dataset.npz');train,validation,tests,train_ids,val_ids,test_ids=paired_packets(dataset)
        self.assertFalse(set(train_ids)&set(val_ids));self.assertFalse(set(train_ids)&set(test_ids))
        self.assertEqual(train.shape[0],len(train_ids)*3)
        estimator=BridgeDamageEstimator(BASE);self.assertIsNotNone(estimator.artifact)
        raw=np.load(BASE/'test-predictions.npz');np.testing.assert_array_equal(test_ids,raw['case_ids'])
        ids=np.linspace(0,len(test_ids)-1,30,dtype=int)
        x=np.array([features(tests['noise_0_5_pct'][i]) for i in ids])
        clf=estimator.artifact['classifier'];votes=clf.predict_proba(x);winner=np.argmax(votes,axis=1)
        np.testing.assert_array_equal(clf.classes_[winner],raw['noise_0_5_pct_predicted'][ids])
        np.testing.assert_allclose(votes[np.arange(len(x)),winner],raw['noise_0_5_pct_score'][ids],atol=1e-15)
        predicted=clf.classes_[winner];severity=np.where(predicted==0,0,estimator.artifact['regressor'].predict(x))
        np.testing.assert_allclose(severity,raw['noise_0_5_pct_severity'][ids],atol=1e-15)

    def test_sparse_prediction_does_not_run_full_array_predictor(self):
        class Baseline:
            report={'damage_family':'Healthy/one loss'}
            packet=np.random.default_rng(5).normal(size=(131,20))
            def eligibility(self,*args):return None
            def measurement_packet(self,bundle):return self.packet.copy()
            def predict(self,*args):raise AssertionError('Hidden full-array inference was called')
        baseline=Baseline();empty=Path(__file__).parent/'_missing_sparse_artifact_for_test';self.assertFalse(empty.exists())
        estimator=SparseBridgeDamageEstimator(baseline,empty)
        indices=[0,3,9,40,120]
        estimator.report={'experiments':[],'recommended_budget':5,'recommendation_rule':'Fixture','test_cases':10}
        estimator.selection={'entries':[{'budget':5,'placement':'guided','indices':indices}]}
        estimator.catalog=SensorArray(bridge_context()['model']).catalog
        classifier=ClassifierStub();estimator.cache[('guided',5)]={'classifier':classifier,'regressor':RegressorStub(),'threshold':.35}
        first=estimator.predict({},sensor_count=5);measured=classifier.last.copy()
        baseline.packet[np.setdiff1d(np.arange(131),indices)]=np.nan
        second=estimator.predict({},sensor_count=5)
        self.assertEqual(first,second);np.testing.assert_array_equal(classifier.last,measured)
        self.assertEqual(first['sensor_indices'],indices);self.assertEqual(classifier.last.shape,(1,110))
        self.assertFalse(estimator.predict({},sensor_count=17)['available'])

    def test_frozen_sparse_report_and_raw_metrics_are_recomputable(self):
        if not (DIRECTORY/'report.json').exists():self.skipTest('Sparse study is still generating or not present')
        if not (DIRECTORY/'test-predictions.npz').is_file():
            self.skipTest('Regenerate the excluded sparse predictions and forests to audit raw metrics')
        report=json.loads((DIRECTORY/'report.json').read_text(encoding='utf8'))
        selection=json.loads((DIRECTORY/'selection.json').read_text(encoding='utf8'))
        placement=json.loads((DIRECTORY/'placement.json').read_text(encoding='utf8'))
        self.assertEqual(hashlib.sha256((DIRECTORY/'selection.json').read_bytes()).hexdigest(),report['selection_sha256'])
        self.assertEqual(hashlib.sha256((DIRECTORY/'placement.json').read_bytes()).hexdigest(),report['placement_sha256'])
        raw=np.load(DIRECTORY/'test-predictions.npz');labels=raw['label'];damaged=labels>0
        for row in report['experiments']:
            key=f"{row['placement']}_{row['budget']}_{row['condition']}"
            pred=raw[key+'_predicted'];accepted=raw[key+'_accepted'];correct=pred==labels
            self.assertAlmostEqual(row['accuracy'],np.mean(correct&accepted))
            assigned=np.where(correct&accepted,raw[key+'_severity'],0)
            self.assertAlmostEqual(row['damaged_severity_mae_pp'],100*np.mean(np.abs(assigned[damaged]-raw['true_severity'][damaged])))
        for entry in selection['entries']:
            if entry['budget']!=131:
                self.assertEqual(entry['indices'],placement['orders'][entry['placement']][:entry['budget']])
                path=DIRECTORY/entry['model_file']
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),entry['forest_sha256'])
        qualified=[entry['budget'] for entry in selection['entries'] if entry['placement']=='guided' and entry['validation']['accuracy']>=.9 and entry['validation']['coverage']>=.95 and entry['validation']['healthy_false_alarm_rate']<=.05]
        self.assertEqual(report['recommended_budget'],min(qualified,default=None))

    def test_api_separates_dynamic_ml_budget_from_stationary_sensor_budget(self):
        from twin.server import TwinService
        service=TwinService('bridge')
        for options in ([],{'unrecognized':10}):
            with self.assertRaises(ValueError):service.playback({'model_id':'bridge','method':'dynamic-moving-force','bridge_ml':options})
        if not (DIRECTORY/'report.json').exists():self.skipTest('Sparse study is still generating or not present')
        if not (DIRECTORY/'models/guided-10.joblib').is_file() or not (DIRECTORY.parent/'bridge-ml/forest.joblib').is_file():
            self.skipTest('Regenerate the excluded bridge baseline and guided-10 forests to test trained inference')
        result=service.playback({'model_id':'bridge','method':'dynamic-moving-force','sensor_count':1,
                                 'bridge_ml':{'sensor_count':10,'placement':'guided'}})
        self.assertTrue(result['ml']['available']);self.assertEqual(result['ml']['sensor_count'],10)
        self.assertEqual(len(result['ml']['sensor_indices']),10)


if __name__=='__main__':unittest.main()
