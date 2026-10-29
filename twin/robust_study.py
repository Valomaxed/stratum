"""Validation-only sparse-policy selection, followed by a fresh frozen-policy audit."""
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime,timezone
import json
from pathlib import Path
import time
import joblib
import numpy as np
from .fem import demo_truss
from .load_cases import LoadCaseSensors
from .learning import probability_matrix,refine
from .experiments import STUDY,BUDGETS,CONDITIONS,scores,paired_interval
from .robust import ROBUST_DIR,PENALTIES,StaticResponseOperator,sparse_candidates,select_sparse,artifact_digest

_worker_sensors=None
_worker_operator=None


def init_worker(protocol):
    global _worker_sensors,_worker_operator
    _worker_sensors=LoadCaseSensors(demo_truss(),protocol)
    _worker_operator=StaticResponseOperator(_worker_sensors)


def fit_packet(arguments):
    values,mask,prior,noise,penalties,legacy=arguments
    s=_worker_sensors
    if not mask.any():
        return {"severity":np.zeros((len(penalties),21)),"bias":np.zeros(len(penalties)),"candidate_failures":0,
                "legacy":prior.copy(),"legacy_converged":False}
    candidates=sparse_candidates(s,values,mask,prior,noise,operator=_worker_operator)
    estimates=[];bias=[]
    for penalty in penalties:
        estimate,info=select_sparse(candidates,penalty)
        estimates.append(estimate);bias.append(info["estimated_common_bias"])
    old,old_info=refine(s,values,mask,prior) if legacy else (prior,{"converged":True})
    return {"severity":np.array(estimates),"bias":np.array(bias),"candidate_failures":candidates["fit_failures"],
            "legacy":old,"legacy_converged":old_info["converged"]}


def generate_fresh(samples,seed,sensors):
    rng=np.random.default_rng(seed);damage=np.zeros((samples,21));response=[]
    for i in range(samples):
        count=int(rng.choice([0,1,2],p=[.2,.6,.2]))
        damage[i,rng.choice(21,count,replace=False)]=rng.uniform(.08,.65,count)
        response.append(sensors.response(damage[i]))
    return damage,np.array(response)


def observations(response,multi,order,count,condition,seed):
    _,noise,missing,drift=condition
    rng=np.random.default_rng(np.random.SeedSequence([seed,913,int(noise*1000),int(missing*1000)]))
    # Same noise realizations and persistent sensor failures in both protocols and all budgets.
    perturb=rng.normal(0,noise,response.shape)
    alive=rng.random((len(response),38))>=missing
    selected=np.zeros(38,bool);selected[order[:count]]=True
    masks=np.tile(alive&selected,(1,3))
    return response+(perturb+drift)*multi.scale,masks


def aggregate_validation(records,truth):
    curve=[]
    for j,penalty in enumerate(PENALTIES):
        metrics=[]
        for record in records:
            eligible=record["eligible"]
            if not eligible.any():continue
            severity=record["severity"][:,j]
            metrics.append(scores(truth[eligible],severity[eligible],severity[eligible]>=.05))
        curve.append({"penalty":penalty,
            "mean_exact_location_accuracy":float(np.mean([m["exact_location_accuracy"] for m in metrics])),
            "mean_member_f1":float(np.mean([m["member_f1"] for m in metrics])),
            "mean_healthy_false_alarm_rate":float(np.mean([m["healthy_false_alarm_rate"] for m in metrics if m["healthy_false_alarm_rate"] is not None])),
            "mean_damaged_severity_mae_pp":float(np.mean([m["damaged_severity_mae_pp"] for m in metrics if m["damaged_severity_mae_pp"] is not None]))})
    feasible=[row for row in curve if row["mean_healthy_false_alarm_rate"]<=.05]
    if feasible:
        selected=max(feasible,key=lambda row:(row["mean_exact_location_accuracy"],row["mean_member_f1"],-row["penalty"]))
    else:
        selected=min(curve,key=lambda row:(row["mean_healthy_false_alarm_rate"],-row["mean_exact_location_accuracy"],row["penalty"]))
    return selected,curve,bool(feasible)


def run(validation_cases=120,test_cases=240,workers=2,validation_seed=31027,test_seed=41027,output=ROBUST_DIR):
    if not 20<=validation_cases<=2000 or not 20<=test_cases<=5000 or not 1<=workers<=8:
        raise ValueError("Require 20..2000 validation cases, 20..5000 test cases and 1..8 workers")
    if validation_seed==test_seed or validation_seed in (2026,) or test_seed in (2026,):
        raise ValueError("Validation/test seeds must be distinct and differ from forest training seed")
    started=time.perf_counter();output=Path(output);output.mkdir(parents=True,exist_ok=True)
    sensors={p:LoadCaseSensors(demo_truss(),p) for p in ("single","multi")}
    multi=sensors["multi"]
    with np.load(STUDY/"dataset.npz") as trained:
        order=trained["shared_sensor_order"].copy()
    model_hashes={p:artifact_digest(STUDY/f"{p}.joblib") for p in sensors}
    forests={p:joblib.load(STUDY/f"{p}.joblib") for p in sensors}
    for p,s in sensors.items():
        if forests[p]["sensor_signature"]!=s.signature():raise ValueError("Retrain the excitation forests for this geometry")
    vtruth,vresponse=generate_fresh(validation_cases,validation_seed,multi)
    settings={};vrecords={};curves={}
    for protocol,s in sensors.items():
        records=[]
        with ProcessPoolExecutor(max_workers=workers,initializer=init_worker,initargs=(protocol,)) as pool:
            for count in BUDGETS:
                for condition in CONDITIONS:
                    values,masks=observations(vresponse,multi,order,count,condition,validation_seed)
                    n=s.observation_count;values=values[:,:n];masks=masks[:,:n]
                    x=np.array([s.features(v,m) for v,m in zip(values,masks)])
                    prior=forests[protocol]["regressor"].predict(x)
                    results=list(pool.map(fit_packet,((v,m,p,condition[1],PENALTIES,False) for v,m,p in zip(values,masks,prior)),chunksize=4))
                    records.append({"sensor_count":count,"condition":condition[0],"eligible":masks.any(axis=1),
                                    "severity":np.array([r["severity"] for r in results])})
                print(f"Validation: {protocol}, {count} sensors, all three conditions",flush=True)
        selected,curve,met_constraint=aggregate_validation(records,vtruth)
        settings[protocol]={"penalty":selected["penalty"],"sensor_signature":s.signature(),"forest_sha256":model_hashes[protocol]}
        curves[protocol]={"candidates":curve,"selected":selected,"false_alarm_constraint_met":met_constraint}
        vrecords[protocol]=records
    frozen={"schema_version":1,"method":"noise-aware-sparse-v1","frozen_at":datetime.now(timezone.utc).isoformat(),
        "validation_seed":validation_seed,"validation_cases":validation_cases,"settings":settings,
        "selection_rule":"Maximize mean exact location over 12 validation cells, subject to mean healthy false-alarm rate <=5%; if infeasible minimize false alarms",
        "limits":"Known noise standard deviation; common normalized bias; zero/one/two damage family; pair search restricted to six best single-member residual fits",
        "penalty_candidates":list(PENALTIES),"detection_threshold":.05,"noise_floor":1e-4,"max_damaged_members":2}
    # Persist the policy before test generation/evaluation. No test labels select parameters.
    (output/"config.json").write_text(json.dumps(frozen,indent=2,allow_nan=False),encoding="utf-8")
    frozen_digest=artifact_digest(output/"config.json")
    print(f"Policy frozen on validation: { {p:cfg['penalty'] for p,cfg in settings.items()} }. Starting fresh test audit.",flush=True)
    truth,response=generate_fresh(test_cases,test_seed,multi)
    report={"schema_version":1,"validation_cases":validation_cases,"test_cases":test_cases,
        "validation_seed":validation_seed,"test_seed":test_seed,"forest_training_seed":2026,
        "frozen_config_sha256":frozen_digest,"selection":curves,"experiments":[],
        "protocol":{"split":"Frozen pretrained forests; fresh validation and test seeds, distinct from original training and prior test study",
            "pairing":"Identical test damage, layout, observation draws and dropout for RF, legacy fit and sparse fit",
            "noise":"Declared Gaussian noise standard deviation supplied to sparse method; not estimated from hidden labels",
            "drift":"Common normalized offset is estimated from observations, not supplied to inverse fit",
            "abstention":"All-missing packets excluded from conditional accuracy and separately counted",
            "metrics":"Damage threshold 5%; RF location uses vote >=0.5; both inverse methods use severity >=0.05",
            "uncertainty":"Paired case-bootstrap intervals, one forest-training seed; no hardware/model-mismatch validation",
            "search":"Healthy + all 21 single-member fits + pairs among six best single-member residual fits"}}
    rows=[];raw=[]
    for protocol,s in sensors.items():
        with ProcessPoolExecutor(max_workers=workers,initializer=init_worker,initargs=(protocol,)) as pool:
            cells=[(n,c,1.) for n in BUDGETS for c in CONDITIONS]
            cells += [(10,CONDITIONS[1],factor) for factor in (.5,2.)]
            for count,condition,factor in cells:
                values,masks=observations(response,multi,order,count,condition,test_seed)
                n=s.observation_count;values=values[:,:n];masks=masks[:,:n]
                features=np.array([s.features(v,m) for v,m in zip(values,masks)])
                prior=forests[protocol]["regressor"].predict(features)
                votes=probability_matrix(forests[protocol]["classifier"],features)
                active=masks.any(axis=1);penalty=settings[protocol]["penalty"]
                results=list(pool.map(fit_packet,((v,m,p,condition[1]*factor,(penalty,),True) for v,m,p in zip(values,masks,prior)),chunksize=4))
                sparse=np.array([r["severity"][0] for r in results]);legacy=np.array([r["legacy"] for r in results])
                metrics={"rf":scores(truth[active],prior[active],votes[active]>=.5),
                         "legacy":scores(truth[active],legacy[active],legacy[active]>=.05),
                         "sparse":scores(truth[active],sparse[active],sparse[active]>=.05)}
                actual=truth>=.05
                old_correct=np.all((legacy>=.05)==actual,axis=1);new_correct=np.all((sparse>=.05)==actual,axis=1)
                healthy=active & ~actual.any(axis=1)
                alarm_reduction=legacy[healthy].max(axis=1)>=.05
                alarm_reduction=alarm_reduction.astype(float)-(sparse[healthy].max(axis=1)>=.05).astype(float)
                row={"protocol":protocol,"sensor_count":count,"condition":condition[0],"true_noise_std":condition[1],
                    "assumed_noise_std":condition[1]*factor,"noise_assumption_factor":factor,"penalty":penalty,
                    "test_cases":test_cases,"evaluated_cases":int(active.sum()),"healthy_cases":int(healthy.sum()),
                    "abstentions":int((~active).sum()),"metrics":metrics,
                    "legacy_optimizer_failures":int(np.sum(active & ~np.array([r["legacy_converged"] for r in results]))),
                    "sparse_discarded_candidate_fits":int(sum(r["candidate_failures"] for r in results)),
                    "paired_location_gain_pp":paired_interval(100*(new_correct[active].astype(float)-old_correct[active].astype(float))),
                    "paired_healthy_alarm_reduction_pp":paired_interval(100*alarm_reduction)}
                rows.append(row);raw.append({"protocol":protocol,"count":count,"condition":condition[0],"factor":factor,
                    "active":active,"rf":prior,"vote":votes,"legacy":legacy,"sparse":sparse,
                    "bias":np.array([r["bias"][0] for r in results]),"legacy_converged":np.array([r["legacy_converged"] for r in results])})
                print(f"Test: {protocol}, {count}, {condition[0]}, noise factor {factor}: legacy {metrics['legacy']['exact_location_accuracy']:.3f}, sparse {metrics['sparse']['exact_location_accuracy']:.3f}",flush=True)
    assert artifact_digest(output/"config.json")==frozen_digest,"Policy changed after freezing"
    report["experiments"]=rows;report["elapsed_seconds"]=time.perf_counter()-started
    np.savez_compressed(output/"dataset.npz",validation_damage=vtruth,validation_response=vresponse,test_damage=truth,test_response=response,
                        validation_ids=np.array([f"{validation_seed}:{i}" for i in range(validation_cases)]),
                        test_ids=np.array([f"{test_seed}:{i}" for i in range(test_cases)]),shared_sensor_order=order)
    np.savez_compressed(output/"validation-predictions.npz",severity=np.array([r["severity"] for p in sensors for r in vrecords[p]]),
                        active=np.array([r["eligible"] for p in sensors for r in vrecords[p]]),
                        protocol=np.array([p for p in sensors for r in vrecords[p]]),
                        sensor_count=np.array([r["sensor_count"] for p in sensors for r in vrecords[p]]),
                        condition=np.array([r["condition"] for p in sensors for r in vrecords[p]]),penalties=np.array(PENALTIES))
    np.savez_compressed(output/"test-predictions.npz",**{k:np.array([r[k] for r in raw]) for k in raw[0]})
    (output/"report.json").write_text(json.dumps(report,indent=2,allow_nan=False),encoding="utf-8")
    return report
