"""Synthetic random-forest baseline and physics-constrained inverse refinement."""
import json
from pathlib import Path
import numpy as np
import joblib
from scipy.optimize import least_squares
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import f1_score
from sklearn.model_selection import train_test_split
from .fem import demo_truss
from .sensors import SensorArray

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ARTIFACT = DATA / "forest.joblib"


def generate(samples=2000, seed=2026):
    if not 200 <= samples <= 100000:
        raise ValueError("Choose between 200 and 100000 simulations")
    model = demo_truss(); sensors = SensorArray(model)
    rng = np.random.default_rng(seed)
    damage = np.zeros((samples, len(model.members)))
    responses = np.empty((samples, len(sensors.catalog)))
    for i in range(samples):
        count = int(rng.choice([0, 1, 2], p=[0.2, 0.6, 0.2]))
        indices = rng.choice(len(model.members), count, replace=False)
        damage[i, indices] = rng.uniform(0.08, 0.65, count)
        responses[i] = sensors.response(damage[i])
    return sensors, responses, damage


def metrics(truth, severity, probabilities):
    actual = truth >= 0.05
    detected = probabilities >= 0.5
    return {"exact_location_accuracy": float(np.mean(np.all(actual == detected, axis=1))),
            "member_f1": float(f1_score(actual, detected, average="micro", zero_division=0)),
            "damaged_severity_mae_pp": float(100*np.mean(np.abs(truth[actual]-severity[actual]))),
            "healthy_false_alarm_rate": float(np.mean(np.any(detected[~np.any(actual, axis=1)], axis=1)))
            if np.any(~np.any(actual, axis=1)) else None}


def probability_matrix(classifier, x):
    outputs = classifier.predict_proba(x)
    return np.column_stack([p[:, list(classes).index(1)] if 1 in classes else np.zeros(len(x))
                            for p, classes in zip(outputs, classifier.classes_)])


def train(samples=2400, seed=2026):
    sensors, responses, damage = generate(samples, seed)
    train_ids, test_ids = train_test_split(np.arange(samples), test_size=0.25, random_state=seed)
    rng = np.random.default_rng(seed+1)
    xs, ys = [], []
    order = sensors.optimal_order()
    for i in train_ids:
        # Three independent corruptions of each TRAIN case; split before augmentation.
        for j in range(3):
            mask = np.ones(len(order), bool)
            if j:
                count = int(rng.choice([5, 10, 20, len(order)]))
                mask[:] = False; mask[order[:count]] = True
                mask &= rng.random(len(order)) >= rng.uniform(0, 0.2)
            values = responses[i]+rng.normal(0, rng.uniform(0, 0.015), len(order))*sensors.scale
            xs.append(sensors.features(values, mask)); ys.append(damage[i])
    x, y = np.array(xs), np.array(ys)
    classifier = RandomForestClassifier(n_estimators=160, min_samples_leaf=1, max_features=0.8,
                                        n_jobs=-1, random_state=seed, class_weight="balanced_subsample")
    regressor = RandomForestRegressor(n_estimators=160, min_samples_leaf=1, max_features=0.9,
                                      n_jobs=-1, random_state=seed)
    classifier.fit(x, y >= 0.05); regressor.fit(x, y)
    report = {"samples": samples, "seed": seed, "train_cases": len(train_ids), "test_cases": len(test_ids),
              "channels": len(order), "training_severity_range": [0.08, 0.65],
              "scope": "Known geometry/material/load. Independent synthetic cases; split before augmentation.",
              "probability_note": "Tree votes are uncalibrated, not engineering reliability probabilities.", "experiments": []}
    report["observability"] = {"local_sensitivity_rank": int(np.linalg.matrix_rank(sensors.sensitivity())),
        "unknown_member_losses": len(sensors.model.members),
        "note": "One static load pattern is rank deficient even with all channels. An ML prior or sparsity assumption cannot guarantee unique damage identification."}
    for count in (len(order), 20, 10, 5):
        for noise, missing, drift in ((0, 0, 0), (0.01, 0.1, 0), (0.03, 0.2, 0.01)):
            test_x = []
            for i in test_ids:
                mask = np.zeros(len(order), bool); mask[order[:count]] = True
                mask &= rng.random(len(order)) >= missing
                values = responses[i]+(rng.normal(0, noise, len(order))+drift)*sensors.scale
                test_x.append(sensors.features(values, mask))
            test_x = np.array(test_x)
            report["experiments"].append({"sensors": count, "noise_fraction": noise,
                "missing_fraction": missing, "drift_fraction": drift,
                **metrics(damage[test_ids], regressor.predict(test_x), probability_matrix(classifier, test_x))})
    # Compare inverse refinement with the same clean held-out cases, no labels supplied to the optimizer.
    physics_results, pure_results, truths, failures = [], [], [], 0
    for i in test_ids[:40]:
        mask = np.ones(len(order), bool)
        features = sensors.features(responses[i], mask)[None, :]
        pure = regressor.predict(features)[0]
        refined, info = refine(sensors, responses[i], mask, pure)
        physics_results.append(refined); pure_results.append(pure); truths.append(damage[i])
        failures += int(not info["converged"])
    truth = np.array(truths); active = truth >= 0.05
    report["physics_comparison"] = {"cases": len(truths), "sensors": len(order), "noise_fraction": 0,
        "pure_ml_damaged_mae_pp": float(100*np.mean(np.abs(np.array(pure_results)[active]-truth[active]))),
        "physics_refined_damaged_mae_pp": float(100*np.mean(np.abs(np.array(physics_results)[active]-truth[active]))),
        "optimizer_failures": failures,
        "note": "Static FEM inverse refinement with an ML prior; not a PINN. Same-model synthetic evaluation."}
    DATA.mkdir(exist_ok=True)
    np.savez_compressed(DATA/"dataset.npz", response=responses, damage=damage, train_ids=train_ids, test_ids=test_ids,
                        sensor_ids=np.array([s["id"] for s in sensors.catalog]))
    joblib.dump({"classifier": classifier, "regressor": regressor, "report": report}, ARTIFACT, compress=3)
    (DATA/"metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def refine(sensors, values, mask, prior, load_scale=1):
    sensors.features(values, mask, load_scale)  # shape/finite validation also covers all-missing packets
    mask = np.asarray(mask, bool)
    if mask.sum() == 0:
        return prior.copy(), {"converged": False, "reason": "No active sensor channels"}
    target = values[mask]/load_scale
    scale = sensors.scale[mask]
    def residual(damage):
        response = sensors.response(damage)[mask]
        return np.concatenate(((response-target)/scale, 0.025*(damage-prior)))
    def jac(damage):
        return np.vstack((sensors.jacobian(damage)[mask], .025*np.eye(len(prior))))
    result = least_squares(residual, np.clip(prior, 1e-6, 0.8), bounds=(0, 0.9),
                           jac=jac if hasattr(sensors, "jacobian") else "2-point",
                           max_nfev=60, ftol=1e-7, xtol=1e-7, gtol=1e-7)
    mismatch = (sensors.response(result.x)[mask]-target)/scale
    jacobian = (sensors.jacobian(result.x) if hasattr(sensors, "jacobian") else sensors.sensitivity())[mask]
    from .load_cases import rank_report
    rank = rank_report(jacobian)
    return result.x, {"converged": bool(result.success), "iterations": int(result.nfev),
                       "normalized_sensor_rmse": float(np.sqrt(np.mean(mismatch**2))),
                       "local_sensitivity_rank": rank["rank"],
                       "locally_identifiable": rank["full_column_rank"],
                       "rank_at": "refined estimate" if hasattr(sensors, "jacobian") else "healthy baseline",
                       "note": "Static equilibrium inverse fit with an ML prior; sparse sensing may be non-unique."}


class DamageEstimator:
    def __init__(self, sensors, artifact_path=ARTIFACT):
        self.sensors = sensors
        artifact_path = Path(artifact_path)
        self.artifact_path=artifact_path
        self.artifact = joblib.load(artifact_path) if artifact_path.exists() else None
        self.unavailable_reason = ("Train the synthetic baseline with python -m twin train" if artifact_path == ARTIFACT
                                   else "Train the excitation study with python -m twin study, then restart the server")
        if self.artifact is not None:
            actual = self.artifact.get("sensor_signature")
            if actual is not None and (not hasattr(sensors, "signature") or actual != sensors.signature()):
                self.artifact = None
                self.unavailable_reason = "Model and excitation protocol differ; retrain with python -m twin study"
        self.sparse_policy=None
        self.sparse_operator=None
        self.sparse_reason="Run python -m twin robust-study and restart to enable validated sparse refinement"
        if self.artifact is not None and hasattr(sensors,"forces"):
            from .robust import CONFIG,ROBUST_DIR,artifact_digest,StaticResponseOperator
            if CONFIG.exists():
                config=json.loads(CONFIG.read_text(encoding="utf-8"))
                setting=config.get("settings",{}).get(sensors.protocol)
                report_file=ROBUST_DIR/"report.json"
                audit=json.loads(report_file.read_text(encoding="utf-8")) if report_file.exists() else {}
                audited=audit.get("frozen_config_sha256")==artifact_digest(CONFIG)
                if audited and config.get("method")=="noise-aware-sparse-v1" and setting and setting.get("sensor_signature")==sensors.signature() and setting.get("forest_sha256")==artifact_digest(artifact_path):
                    self.sparse_policy=setting
                    self.sparse_operator=StaticResponseOperator(sensors)
                else:
                    self.sparse_reason="Sparse policy is unaudited or does not match the current forest/excitation; rerun python -m twin robust-study"

    def predict(self, values, mask, load_scale=1, physics=False, refinement="legacy", noise_std=None):
        if refinement not in ("legacy","sparse"):
            raise ValueError("Refinement must be legacy or sparse")
        if noise_std is not None and (not np.isfinite(noise_std) or not 0<=noise_std<=.2):
            raise ValueError("Noise standard deviation must be finite and in [0, 0.2]")
        if self.artifact is None:
            return {"available": False, "reason": self.unavailable_reason}
        if not np.any(mask):
            return {"available": False, "reason": "No active sensors; damage cannot be estimated"}
        x = self.sensors.features(values, mask, load_scale)[None, :]
        severity = self.artifact["regressor"].predict(x)[0]
        probability = probability_matrix(self.artifact["classifier"], x)[0]
        info = None
        method="Random forest"
        if physics:
            if refinement=="legacy":
                severity, info = refine(self.sensors, values, mask, severity, load_scale)
                method="RF + legacy physics fit"
            elif self.sparse_policy is None:
                info={"converged":False,"available":False,"reason":self.sparse_reason,"method":"Sparse physics unavailable"}
                method="Random forest (sparse refinement unavailable)"
            else:
                from .robust import sparse_refine
                assumed=noise_std is None
                severity,info=sparse_refine(self.sensors,values,mask,severity,.01 if assumed else noise_std,
                                          self.sparse_policy["penalty"],load_scale,self.sparse_operator)
                info["noise_source"]="assumed 1% normalized standard deviation" if assumed else "supplied normalized standard deviation"
                info["selection_source"]="Validation-selected policy; held-out audit is separate"
                method="RF + noise-aware sparse physics"
        return {"available": True, "method": method,
                "severity": severity.tolist(), "damage_vote": probability.tolist(), "physics": info,
                "vote_note": "Uncalibrated forest vote for loss >= 5%; not a reliability probability",
                "out_of_training_range": bool(np.max(severity) > 0.65)}
