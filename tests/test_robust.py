import json
import unittest
import numpy as np
from twin.fem import demo_truss
from twin.load_cases import LoadCaseSensors
from twin.robust import StaticResponseOperator,sparse_candidates,select_sparse,sparse_refine,ROBUST_DIR,artifact_digest
from twin.robust_study import aggregate_validation
from twin.experiments import scores


class RobustTests(unittest.TestCase):
    def setUp(self):
        self.s=LoadCaseSensors(demo_truss(),"multi")
        self.op=StaticResponseOperator(self.s)

    def test_fast_operator_matches_general_solver_and_tangents(self):
        for protocol in ("single","multi"):
            s=LoadCaseSensors(demo_truss(),protocol);operator=StaticResponseOperator(s)
            for damage in (np.zeros(21),np.linspace(.02,.45,21)):
                values,jac=operator.evaluate(damage,np.arange(21))
                np.testing.assert_allclose(values,s.response(damage)/s.scale,atol=1e-12)
                np.testing.assert_allclose(jac,s.jacobian(damage),atol=1e-12)
            d=np.full(21,.2);step=np.zeros(21);step[13]=1e-5
            plus,_=operator.evaluate(d+step);minus,_=operator.evaluate(d-step)
            _,jac=operator.evaluate(d,[13])
            np.testing.assert_allclose(jac[:,0],(plus-minus)/2e-5,atol=1e-8)

    def test_healthy_model_rejects_damage_prior_and_profiles_sensor_bias(self):
        values=self.s.baseline+.012*self.s.scale
        prior=np.zeros(21);prior[13]=.3
        severity,info=sparse_refine(self.s,values,np.ones(114,bool),prior,.01,2,operator=self.op)
        np.testing.assert_array_equal(severity,np.zeros(21))
        self.assertAlmostEqual(info["estimated_common_bias"],.012,places=12)
        self.assertEqual(info["detected_members"],[])

    def test_clean_one_and_two_member_recovery(self):
        for indices in ([13],[4,13]):
            damage=np.zeros(21);damage[indices]=[.2,.35] if len(indices)==2 else [.3]
            values=self.s.response(damage)
            severity,info=sparse_refine(self.s,values,np.ones(114,bool),np.zeros(21),0,2,operator=self.op)
            self.assertTrue(info["converged"])
            self.assertEqual(info["detected_members"],indices)
            np.testing.assert_allclose(severity,damage,atol=1e-4)

    def test_masks_load_normalization_and_no_observation_abstention(self):
        d=np.zeros(21);d[13]=.3
        values,mask=self.s.observe(d,count=10,noise=.01,seed=7,load_scale=2)
        a,_=sparse_refine(self.s,values,mask,np.zeros(21),.01,2,load_scale=2,operator=self.op)
        b,_=sparse_refine(self.s,values/2,mask,np.zeros(21),.01,2,operator=self.op)
        np.testing.assert_allclose(a,b,atol=1e-12)
        estimate,info=sparse_refine(self.s,values,np.zeros(114,bool),np.zeros(21),.01,2)
        self.assertIsNone(estimate);self.assertFalse(info["converged"])

    def test_penalty_reduces_selected_model_size(self):
        d=np.zeros(21);d[13]=.3
        values,mask=self.s.observe(d,count=10,noise=.03,seed=9)
        result=sparse_candidates(self.s,values,mask,np.zeros(21),.03,operator=self.op)
        _,low=select_sparse(result,.5);_,high=select_sparse(result,8)
        self.assertLessEqual(len(high["support"]),len(low["support"]))
        self.assertLessEqual(len(low["support"]),2)

    def test_invalid_noise_prior_and_operator_rejected(self):
        for noise in (-.01,np.nan,.3):
            with self.assertRaises(ValueError):sparse_candidates(self.s,self.s.baseline,np.ones(114,bool),np.zeros(21),noise)
        with self.assertRaises(ValueError):sparse_candidates(self.s,self.s.baseline,np.ones(114,bool),np.zeros(20),.01)
        with self.assertRaises(ValueError):select_sparse({"available":False,"reason":"missing"},-1)
        other=LoadCaseSensors(demo_truss(),"single")
        with self.assertRaisesRegex(ValueError,"protocol differ"):
            sparse_candidates(other,other.baseline,np.ones(38,bool),np.zeros(21),.01,operator=self.op)

    def test_validation_rule_respects_healthy_false_alarm_constraint(self):
        truth=np.zeros((4,21));truth[2:,13]=.3
        predictions=np.tile(truth[:,None,:],(1,5,1))
        predictions[:2,:3,4]=.2  # Three penalties fail the false-alarm constraint.
        predictions[3,3,13]=0
        predictions[:,4]=0
        selected,curve,feasible=aggregate_validation([{"eligible":np.ones(4,bool),"severity":predictions}],truth)
        self.assertTrue(feasible)
        self.assertEqual(selected["penalty"],4)
        self.assertEqual(selected["mean_healthy_false_alarm_rate"],0)

    @unittest.skipUnless((ROBUST_DIR/"report.json").exists(),"Run robust-study first")
    def test_api_sparse_mode_noise_assumptions_and_healthy_bias(self):
        from twin.server import TwinService
        service=TwinService()
        result=service.analyze({"protocol":"multi","physics":True,"refinement":"sparse","noise":0,"drift":.01})
        p=result["prediction"]
        self.assertTrue(p["available"])
        self.assertEqual(p["physics"]["method"],"Noise-aware sparse physics")
        self.assertEqual(p["physics"]["detected_members"],[])
        self.assertAlmostEqual(p["physics"]["estimated_common_bias"],.01,places=10)
        values=(self.s.baseline+.01*self.s.scale).reshape(3,38)
        measurements={case["id"]:{channel["id"]:float(v) for channel,v in zip(self.s.catalog,row)}
                      for case,row in zip(self.s.cases,values)}
        packet=service.ingest({"protocol":"multi","physics":True,"refinement":"sparse","measurements":measurements})
        self.assertIn("assumed 1%",packet["prediction"]["physics"]["noise_source"])
        for request in ({"refinement":"unknown"},{"noise":float('nan')}):
            with self.assertRaises(ValueError):service.analyze(request)

    @unittest.skipUnless((ROBUST_DIR/"report.json").exists(),"Run robust-study first")
    def test_audit_preserves_frozen_policy_and_recomputable_metrics(self):
        report=json.loads((ROBUST_DIR/"report.json").read_text())
        config=json.loads((ROBUST_DIR/"config.json").read_text())
        self.assertEqual(report["frozen_config_sha256"],artifact_digest(ROBUST_DIR/"config.json"))
        with np.load(ROBUST_DIR/"dataset.npz") as data,np.load(ROBUST_DIR/"test-predictions.npz") as predictions:
            self.assertFalse(set(data["validation_ids"]) & set(data["test_ids"]))
            truth=data["test_damage"]
            for i,row in enumerate(report["experiments"]):
                active=predictions["active"][i]
                self.assertEqual(row["penalty"],config["settings"][row["protocol"]]["penalty"])
                for method in ("rf","legacy","sparse"):
                    severity=predictions[method][i]
                    detected=predictions["vote"][i]>=.5 if method=="rf" else severity>=.05
                    measured=scores(truth[active],severity[active],detected[active])
                    for key,value in measured.items():
                        if value is None:self.assertIsNone(row["metrics"][method][key])
                        else:self.assertAlmostEqual(value,row["metrics"][method][key])


if __name__=="__main__":unittest.main()
