import json
import tempfile
import unittest
from pathlib import Path
import joblib
import numpy as np
from twin.fem import demo_truss
from twin.load_cases import LoadCaseSensors,rank_report
from twin.learning import DamageEstimator,refine
from twin.experiments import STUDY,paired_interval
from twin.server import TwinService


class LoadCaseTests(unittest.TestCase):
    def setUp(self):
        self.model=demo_truss()
        self.sensors=LoadCaseSensors(self.model,"multi")

    def test_batch_matches_individual_solves_and_force_moment_balance(self):
        damage=np.zeros(21);damage[[4,13]]=[.2,.35]
        batch=self.model.solve_load_cases(self.sensors.forces,damage)
        for i,force in enumerate(self.sensors.forces):
            single=self.model.solve(damage,forces=force)
            np.testing.assert_allclose(batch["displacement"][i],single["displacement"],rtol=1e-12,atol=1e-15)
            np.testing.assert_allclose(batch["strain"][i],single["strain"],rtol=1e-12,atol=1e-15)
            total=(batch["reactions"][i]+force).reshape(-1,2)
            np.testing.assert_allclose(total.sum(axis=0),0,atol=1e-6)
            moment=np.sum(self.model.nodes[:,0]*total[:,1]-self.model.nodes[:,1]*total[:,0])
            self.assertAlmostEqual(moment,0,places=5)

    def test_exact_tangents_match_central_differences(self):
        damage=np.linspace(.1,.4,21)
        jac=self.sensors.jacobian(damage)
        for i in range(21):
            step=np.zeros(21);step[i]=1e-5
            fd=(self.sensors.response(damage+step)-self.sensors.response(damage-step))/(2e-5)/self.sensors.scale
            np.testing.assert_allclose(jac[:,i],fd,atol=1e-8,rtol=1e-6)

    def test_independent_loads_increase_rank_duplicate_loads_do_not(self):
        single=LoadCaseSensors(self.model,"single")
        self.assertEqual(rank_report(single.sensitivity())["rank"],17)
        self.assertEqual(rank_report(np.tile(single.sensitivity(),(3,1)))["rank"],17)
        self.assertEqual(rank_report(self.sensors.sensitivity())["rank"],21)
        order=self.sensors.optimal_order()
        self.assertEqual(rank_report(self.sensors.sensitivity()[self.sensors.mask_for(order[:10])])["rank"],21)
        self.assertEqual(rank_report(self.sensors.sensitivity()[self.sensors.mask_for(order[:5])])["rank"],13)

    def test_physical_sensor_budget_dropout_and_load_normalization(self):
        values,mask=self.sensors.observe(np.zeros(21),count=10,noise=.01,missing=.3,seed=21,load_scale=2)
        mask_by_case=mask.reshape(3,38)
        np.testing.assert_array_equal(mask_by_case[0],mask_by_case[1])
        np.testing.assert_array_equal(mask_by_case[1],mask_by_case[2])
        self.assertLessEqual(mask.sum(),30)
        np.testing.assert_allclose(self.sensors.features(values,mask,2),self.sensors.features(values/2,mask),atol=1e-14)
        _,none=self.sensors.observe(np.zeros(21),missing=1)
        self.assertFalse(none.any())

    def test_inverse_recovers_multi_member_damage_from_ten_sensors(self):
        damage=np.zeros(21);damage[[4,13]]=[.2,.35]
        values,mask=self.sensors.observe(damage,count=10,noise=0)
        estimate,info=refine(self.sensors,values,mask,np.zeros(21))
        self.assertTrue(info["converged"])
        self.assertTrue(info["locally_identifiable"])
        # A zero prior deliberately biases the weakly regularized inverse fit.
        np.testing.assert_allclose(estimate,damage,atol=.01)
        self.assertEqual(info["rank_at"],"refined estimate")

    def test_stale_artifact_and_invalid_load_shapes_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/"data") as directory:
            file=Path(directory)/"wrong.joblib";joblib.dump({"sensor_signature":"wrong"},file)
            estimator=DamageEstimator(self.sensors,file)
            result=estimator.predict(self.sensors.baseline,np.ones(114,bool))
            self.assertFalse(result["available"])
            self.assertIn("protocol differ",result["reason"])
        for forces in ([1,2],[[np.nan]*20],np.zeros((2,19))):
            with self.assertRaises(ValueError):self.model.solve_load_cases(forces)
        self.assertIsNone(paired_interval([])["mean"])

    def test_service_keeps_display_load_separate_from_full_protocol(self):
        service=TwinService();damage=np.zeros(21);damage[13]=.3
        result=service.analyze({"protocol":"multi","display_case":"LC3","damage":damage.tolist(),"sensor_count":10,"noise":0})
        self.assertEqual(result["excitation"]["case_count"],3)
        self.assertEqual(result["excitation"]["active_observations"],30)
        self.assertEqual(result["summary"]["active_sensors"],10)
        self.assertEqual(result["excitation"]["observability"]["rank"],21)
        self.assertEqual(result["signal"]["load_case"],"LC1")
        self.assertTrue(all(load["fx"]>0 and load["fy"]==0 for load in result["loads"]))
        np.testing.assert_allclose([n["ux"] for n in result["nodes"]],self.model.solve(damage,forces=self.sensors.forces[2])["displacement"][::2])
        readings=self.sensors.response(damage).reshape(3,38)
        packet={"protocol":"multi","measurements":{case["id"]:{c["id"]:float(v) for c,v in zip(self.sensors.catalog,row)}
                                                     for case,row in zip(self.sensors.cases,readings)}}
        received=service.ingest(packet)
        self.assertEqual(received["active_sensors"],38)
        self.assertEqual(received["active_observations"],114)
        json.dumps(received,allow_nan=False)
        for request in ({"protocol":"bad"},{"protocol":"single","display_case":"LC3"}):
            with self.assertRaises(ValueError):service.analyze(request)
        with self.assertRaises(ValueError):service.ingest({"protocol":"multi","measurements":{"SG01":0}})

    @unittest.skipUnless((STUDY/"report.json").exists(),"Run the paired study first")
    def test_saved_study_preserves_case_split_and_metric_pairing(self):
        if not all((STUDY/name).is_file() for name in ('dataset.npz', 'predictions.npz')):
            self.skipTest('Regenerate the excluded paired-study datasets to audit raw metrics')
        report=json.loads((STUDY/"report.json").read_text())
        with np.load(STUDY/"dataset.npz") as dataset,np.load(STUDY/"predictions.npz") as predictions:
            self.assertFalse(set(dataset["train_ids"])&set(dataset["test_ids"]))
            self.assertTrue(set(dataset["physics_ids"])<=set(dataset["test_ids"]))
            self.assertEqual(dataset["response"].shape[1:],(3,38))
            for i,row in enumerate(report["experiments"]):
                active=predictions["active"][i]
                actual=dataset["damage"][dataset["test_ids"]]>=.05
                correct=np.all((predictions["vote"][i]>=.5)==actual,axis=1)
                self.assertAlmostEqual(row["ml"]["exact_location_accuracy"],float(np.mean(correct[active])))
                self.assertEqual(row["protocol"],predictions["protocol"][i])
                self.assertEqual(row["condition"],predictions["condition"][i])
                lookup={int(case):j for j,case in enumerate(dataset["test_ids"])}
                sub_indices=np.array([lookup[int(case)] for case in dataset["physics_ids"]])
                eligible=active[sub_indices]
                truth=dataset["damage"][dataset["physics_ids"]][eligible]
                refined=predictions["refined"][i][eligible]
                fit_correct=np.all((refined>=.05)==(truth>=.05),axis=1)
                comparison=row["physics_comparison"]
                self.assertAlmostEqual(comparison["refined"]["exact_location_accuracy"],float(np.mean(fit_correct)))
                damaged=truth>=.05
                self.assertAlmostEqual(comparison["refined"]["damaged_severity_mae_pp"],float(100*np.mean(np.abs(refined[damaged]-truth[damaged]))))
                self.assertEqual(comparison["optimizer_failures"],int(np.sum(eligible & ~predictions["converged"][i])))


if __name__=="__main__":unittest.main()
