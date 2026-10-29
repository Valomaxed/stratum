"""Paired single-versus-multiple static excitation study.

Train/test damage cases, physical sensor layout, corruptions and model settings
are shared. Repeated excitations add measurements, not physical sensors.
"""
import json
import time
from pathlib import Path
import numpy as np
import joblib
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import f1_score
from .fem import demo_truss
from .load_cases import LoadCaseSensors, rank_report
from .learning import DATA, probability_matrix, refine

STUDY = DATA/"load-study"
CONDITIONS = [("clean", 0., 0., 0.), ("noisy", .01, .1, 0.), ("harsh", .03, .2, .01)]
BUDGETS = (5, 10, 20, 38)


def scores(truth, severity, detected):
    actual = truth >= .05
    active = actual.any(axis=1)
    return {"exact_location_accuracy": float(np.mean(np.all(actual == detected, axis=1))),
            "member_f1": float(f1_score(actual, detected, average="micro", zero_division=0)),
            "damaged_severity_mae_pp": float(100*np.mean(np.abs(truth[actual]-severity[actual]))) if actual.any() else None,
            "all_member_severity_mae_pp": float(100*np.mean(np.abs(truth-severity))),
            "healthy_false_alarm_rate": float(np.mean(detected[~active].any(axis=1))) if (~active).any() else None}


def paired_interval(values, seed=7):
    values = np.asarray(values, float)
    if not len(values):
        return {"mean":None,"ci95":None,"method":"No eligible cases"}
    rng = np.random.default_rng(seed)
    means = np.mean(values[rng.integers(0, len(values), (1000, len(values)))], axis=1)
    return {"mean": float(np.mean(values)), "ci95": np.quantile(means, [.025, .975]).tolist(),
            "method": "Paired bootstrap over independent test cases, 1000 resamples; one training seed"}


def study(samples=2400, seed=2026, physics_cases=60, output=STUDY):
    if not 200 <= samples <= 100000 or not 1 <= physics_cases <= 500:
        raise ValueError("Require 200..100000 scenarios and 1..500 physics comparison cases")
    started = time.perf_counter()
    model = demo_truss()
    sensors = {name: LoadCaseSensors(model, name) for name in ("single", "multi")}
    multi = sensors["multi"]
    # Fix the common physical placement using only healthy-model sensitivity.
    order = multi.optimal_order()
    sensors["single"]._order = order.copy()
    rng = np.random.default_rng(seed)
    damage = np.zeros((samples, len(model.members)))
    response = np.empty((samples, multi.observation_count))
    for i in range(samples):
        count = int(rng.choice([0, 1, 2], p=[.2,.6,.2]))
        damage[i, rng.choice(len(model.members), count, replace=False)] = rng.uniform(.08,.65,count)
        response[i] = multi.response(damage[i])
    train_ids, test_ids = train_test_split(np.arange(samples), test_size=.25, random_state=seed)
    physics_ids = test_ids[:min(physics_cases, len(test_ids))]
    print(f"Generated {samples} paired cases; {len(test_ids)} held out; {len(physics_ids)} physics cases per cell", flush=True)
    xtrain = {name: [] for name in sensors}; labels=[]
    rng = np.random.default_rng(seed+1)
    for i in train_ids:
        for j in range(3):
            count = 38 if j == 0 else int(rng.choice(BUDGETS))
            selected = order[:count]
            if j:
                selected = selected[rng.random(count) >= rng.uniform(0,.2)]
            mask = multi.mask_for(selected)
            values = response[i]+rng.normal(0,rng.uniform(0,.015),multi.observation_count)*multi.scale
            for name, s in sensors.items():
                n=s.observation_count
                xtrain[name].append(s.features(values[:n],mask[:n]))
            labels.append(damage[i])
    ytrain = np.array(labels)
    forests={}
    for name,s in sensors.items():
        x = np.array(xtrain[name])
        classifier = RandomForestClassifier(n_estimators=160,min_samples_leaf=1,max_features=.8,
                    n_jobs=-1,random_state=seed,class_weight="balanced_subsample")
        regressor = RandomForestRegressor(n_estimators=160,min_samples_leaf=1,max_features=.9,
                    n_jobs=-1,random_state=seed)
        classifier.fit(x,ytrain>=.05); regressor.fit(x,ytrain)
        forests[name]={"classifier":classifier,"regressor":regressor,"sensor_signature":s.signature()}
        print(f"Trained {name} forest on {len(x)} augmented training observations",flush=True)
    observability={name: {"full_array":rank_report(s.sensitivity()),
                    "budgets": {str(n):rank_report(s.sensitivity()[s.mask_for(order[:n])]) for n in BUDGETS}}
                    for name,s in sensors.items()}
    report={"schema_version":2,"samples":samples,"seed":seed,"train_cases":len(train_ids),"test_cases":len(test_ids),
        "physical_sensor_capacity":38,"case_names":[{"id":c["id"],"name":c["name"],"forces_n":c["forces"].tolist()} for c in multi.cases],
        "shared_sensor_order":[multi.catalog[i]["id"] for i in order],"observability":observability,
        "protocol":{"comparison":"Single LC1 versus LC1+LC2+LC3, same physical sensors and held-out cases",
            "noise":"Independent case/channel Gaussian draws; same LC1 draw in both protocols; normalized per case/type",
            "missing":"Physical sensor failure persists across all three load acquisitions",
            "physics_subset":"First test IDs from fixed random split; includes healthy, one- and two-member damage",
            "classification":"RF uses vote >=0.5; inverse refinement uses estimated stiffness loss >=0.05",
            "limits":"Known same-model geometry/load; unchanged damage across acquisitions; one training seed; no hardware transfer validation"},
        "experiments":[],"paired_effects":[]}
    rows=[]; predictions=[]
    test_lookup={int(i):j for j,i in enumerate(test_ids)}
    sub_indices=np.array([test_lookup[int(i)] for i in physics_ids])
    for count in BUDGETS:
        for condition,noise,missing,drift in CONDITIONS:
            # Deterministic common draws; sensor dropout shared across protocols/budgets.
            rng=np.random.default_rng(np.random.SeedSequence([seed,72,int(noise*1000),int(missing*1000)]))
            perturb=rng.normal(0,noise,(len(test_ids),multi.observation_count))
            alive=rng.random((len(test_ids),38))>=missing
            selected=np.zeros(38,bool); selected[order[:count]]=True
            masks=np.tile(alive & selected,(1,3))
            values=response[test_ids]+(perturb+drift)*multi.scale
            paired={}
            for name,s in sensors.items():
                n=s.observation_count
                features=np.array([s.features(v[:n],m[:n]) for v,m in zip(values,masks)])
                forest=forests[name]
                severity=forest["regressor"].predict(features)
                votes=probability_matrix(forest["classifier"],features)
                active=masks[:,:n].any(axis=1)
                # All-missing cases abstain; never manufacture healthy predictions.
                score=scores(damage[test_ids][active],severity[active],votes[active]>=.5) if active.any() else {}
                row={"protocol":name,"sensor_count":count,"load_case_count":s.case_count,
                    "nominal_observations":count*s.case_count,"condition":condition,"noise_fraction":noise,
                    "missing_fraction":missing,"drift_fraction":drift,"test_cases":len(test_ids),
                    "evaluated_cases":int(active.sum()),"abstentions":int((~active).sum()),
                    "local_rank_before_dropout":observability[name]["budgets"][str(count)]["rank"],"ml":score}
                sub_truth=damage[physics_ids]; sub_severity=severity[sub_indices]
                refined=[]; convergence=[]; rmses=[]; elapsed=[]
                sub_active=active[sub_indices]
                for j,idx in enumerate(sub_indices):
                    before=time.perf_counter()
                    estimate,info=refine(s,values[idx,:n],masks[idx,:n],sub_severity[j])
                    refined.append(estimate);convergence.append(bool(info["converged"]))
                    rmses.append(info.get("normalized_sensor_rmse",np.nan));elapsed.append(time.perf_counter()-before)
                refined=np.array(refined)
                row["physics_comparison"]={"cases":len(physics_ids),"evaluated_cases":int(sub_active.sum()),
                    "abstentions":int((~sub_active).sum()),
                    "optimizer_failures":int(np.sum(sub_active & ~np.array(convergence))),
                    "mean_seconds":float(np.mean(elapsed)),
                    "ml":scores(sub_truth[sub_active],sub_severity[sub_active],votes[sub_indices][sub_active]>=.5) if sub_active.any() else {},
                    "refined":scores(sub_truth[sub_active],refined[sub_active],refined[sub_active]>=.05) if sub_active.any() else {}}
                paired[name]={"ml_correct":np.all((votes[sub_indices]>=.5)==(sub_truth>=.05),axis=1),
                    "refined_correct":np.all((refined>=.05)==(sub_truth>=.05),axis=1),
                    "ml_error":case_damaged_error(sub_truth,sub_severity),
                    "refined_error":case_damaged_error(sub_truth,refined),"active":sub_active}
                rows.append(row)
                predictions.append({"sensor_count":count,"condition":condition,"protocol":name,
                    "severity":severity,"vote":votes,"active":active,"refined":refined,"converged":np.array(convergence)})
            a,b=paired["single"],paired["multi"]
            keep=a["active"]&b["active"]
            damaged=keep & np.any(damage[physics_ids]>=.05,axis=1)
            report["paired_effects"].append({"sensor_count":count,"condition":condition,"cases":int(keep.sum()),
                "refined_location_gain_pp":paired_interval(100*(b["refined_correct"][keep].astype(float)-a["refined_correct"][keep].astype(float))),
                "refined_damaged_mae_reduction_pp":paired_interval(a["refined_error"][damaged]-b["refined_error"][damaged]),
                "note":"Positive values favor multiple loads; severity effect averages per damaged case."})
            print(f"Evaluated budget {count}, {condition}: single and multi on identical measurements of LC1",flush=True)
    report["experiments"]=rows
    report["elapsed_seconds"]=time.perf_counter()-started
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(output/"dataset.npz",response=response.reshape(samples,3,38),damage=damage,
                        train_ids=train_ids,test_ids=test_ids,physics_ids=physics_ids,
                        sensor_ids=np.array([s["id"] for s in multi.catalog]),forces=multi.forces,shared_sensor_order=order)
    np.savez_compressed(output/"predictions.npz",severity=np.array([p["severity"] for p in predictions]),
                        vote=np.array([p["vote"] for p in predictions]),active=np.array([p["active"] for p in predictions]),
                        refined=np.array([p["refined"] for p in predictions]),converged=np.array([p["converged"] for p in predictions]),
                        protocol=np.array([p["protocol"] for p in predictions]),condition=np.array([p["condition"] for p in predictions]),
                        sensor_count=np.array([p["sensor_count"] for p in predictions]))
    for name,forest in forests.items():
        forest["report"]={"schema_version":2,"protocol":name,"seed":seed,"shared_sensor_order":order.tolist()}
        joblib.dump(forest,output/f"{name}.joblib",compress=3)
    (output/"report.json").write_text(json.dumps(report,indent=2,allow_nan=False),encoding="utf-8")
    return report


def case_damaged_error(truth,severity):
    mask=truth>=.05
    return 100*np.sum(np.abs(truth-severity)*mask,axis=1)/np.maximum(mask.sum(axis=1),1)
