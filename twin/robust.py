"""Noise-aware sparse static inverse fitting; no damage labels enter inference.

Candidate structures contain zero, one or two damaged members, matching the
validated synthetic damage family. A profiled common normalized sensor bias is
fitted for every candidate, including healthy. This is a restricted model search,
not a general damage solver or calibrated probability estimator.
"""
from itertools import combinations
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy.linalg import cho_factor,cho_solve
from scipy.optimize import least_squares

ROBUST_DIR=Path(__file__).resolve().parents[1]/"data"/"robust-study"
CONFIG=ROBUST_DIR/"config.json"
PENALTIES=(.5,1.,2.,4.,8.)


def artifact_digest(path):
    digest=hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda:file.read(1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()


class StaticResponseOperator:
    """Vectorized equivalent of the independently tested general truss solver."""
    def __init__(self,sensors):
        self.sensors=sensors;model=sensors.model;free=model.free
        _,_,elements=model.assemble()
        stiffness=[];strain=np.zeros((len(elements),model.nodes.size))
        for i,(dofs,projection,length,_) in enumerate(elements):
            v=np.zeros(model.nodes.size);v[dofs]=projection
            stiffness.append(model.elastic_modulus[i]*model.area[i]/length*np.outer(v[free],v[free]))
            strain[i,dofs]=projection/length
        self.elements=np.array(stiffness)
        self.observation=np.vstack((strain[:,free],np.eye(len(free))))
        self.force=sensors.forces[:,free].T
        self.nmembers=len(elements)
        self.baseline=sensors.baseline/sensors.scale
        self.signature=sensors.signature()

    def evaluate(self,damage,indices=()):
        damage=np.asarray(damage,float)
        if damage.shape!=(self.nmembers,) or not np.all(np.isfinite(damage)) or np.any((damage<0)|(damage>.9)):
            raise ValueError("Sparse inverse losses must be finite and between 0 and 0.9")
        stiffness=np.tensordot(1-damage,self.elements,axes=(0,0))
        factor=cho_factor(stiffness)
        u=cho_solve(factor,self.force)
        response=(self.observation @ u).T.ravel()/self.sensors.scale
        indices=np.asarray(indices,int)
        if not len(indices):return response,None
        rhs=np.einsum("mij,jc->icm",self.elements[indices],u)
        du=cho_solve(factor,rhs.reshape(len(u),-1)).reshape(rhs.shape)
        jac=np.einsum("si,ick->csk",self.observation,du).reshape(-1,len(indices))/self.sensors.scale[:,None]
        return response,jac


def sparse_candidates(sensors,values,mask,prior,noise_std,load_scale=1,operator=None):
    """Fit candidates once; selection penalties can be varied on validation only."""
    sensors.features(values,mask,load_scale)
    mask=np.asarray(mask,bool);prior=np.asarray(prior,float)
    if prior.shape!=(len(sensors.model.members),) or not np.all(np.isfinite(prior)):
        raise ValueError("Invalid prior vector")
    if not np.isfinite(noise_std) or not 0<=noise_std<=.2:
        raise ValueError("Normalized noise standard deviation must be in [0, 0.2]")
    if not mask.any():return {"available":False,"reason":"No active sensor observations"}
    if not hasattr(sensors,"forces"):
        raise ValueError("Sparse refinement requires the explicit load-case sensor protocol")
    operator=operator or StaticResponseOperator(sensors)
    if operator.signature!=sensors.signature():raise ValueError("Forward operator and sensor protocol differ")
    target=np.asarray(values)[mask]/load_scale/sensors.scale[mask]
    # Clean synthetic data still use a numerical discrepancy floor; never divide by zero.
    sigma=max(float(noise_std),1e-4)
    n=mask.sum();candidates=[];failures=0

    def fit(indices):
        nonlocal failures
        indices=tuple(sorted(indices));ids=np.array(indices,int)
        if not indices:
            prediction=operator.baseline[mask]
            bias=float(np.clip(np.mean(target-prediction),-.2,.2))
            error=prediction+bias-target
            return {"severity":np.zeros(operator.nmembers),"rss":float(error @ error),"size":0,
                    "bias":bias,"converged":True,"support":[],"nfev":0}
        cache={}
        def evaluate(x):
            if "x" not in cache or not np.array_equal(cache["x"],x):
                damage=np.zeros(operator.nmembers);damage[ids]=x
                prediction,jac=operator.evaluate(damage,ids)
                prediction=prediction[mask];jac=jac[mask]
                mean=float(np.mean(target-prediction));bias=float(np.clip(mean,-.2,.2))
                if abs(mean)<.2:jac=jac-jac.mean(axis=0)
                cache.update(x=x.copy(),error=prediction+bias-target,jac=jac,bias=bias)
            return cache
        start=np.clip(prior[ids],.01,.8)
        result=least_squares(lambda x:evaluate(x)["error"],start,jac=lambda x:evaluate(x)["jac"],bounds=(0,.9),
                             max_nfev=30,ftol=1e-7,xtol=1e-7,gtol=1e-8)
        fitted=evaluate(result.x);severity=np.zeros(operator.nmembers);severity[ids]=result.x
        failures+=int(not result.success)
        return {"severity":severity,"rss":float(fitted["error"] @ fitted["error"]),"size":len(indices),
                "bias":fitted["bias"],"converged":bool(result.success),"support":list(indices),"nfev":int(result.nfev)}

    candidates.append(fit(()))
    if n>=3:
        singles=[fit((i,)) for i in range(operator.nmembers)]
        candidates.extend(singles)
        # Shortlist using only measured residuals, without true locations or severities.
        shortlist=sorted(range(operator.nmembers),key=lambda i:(not singles[i]["converged"],singles[i]["rss"],i))[:6]
        if n>=4:
            candidates.extend(fit(pair) for pair in combinations(shortlist,2))
    return {"available":True,"candidates":candidates,"sigma":sigma,"noise_std":float(noise_std),
            "observations":int(n),"fit_failures":failures,"max_damaged_members":2,
            "pair_shortlist_size":6,"bias_model":"One common additive normalized offset, profiled within [-0.2, 0.2]"}


def select_sparse(result,penalty):
    if not np.isfinite(penalty) or penalty<=0:raise ValueError("Sparse penalty must be finite and positive")
    if not result["available"]:return None,{"converged":False,"reason":result["reason"]}
    candidates=[c for c in result["candidates"] if c["converged"]]
    multiplier=float(penalty)*np.log(max(result["observations"],3))
    def score(candidate):return candidate["rss"]/result["sigma"]**2+multiplier*candidate["size"]
    best=min(candidates,key=lambda c:(score(c),c["size"]))
    severity=best["severity"].copy()
    return severity,{"converged":True,"method":"Noise-aware sparse physics",
        "support":best["support"],"detected_members":np.flatnonzero(severity>=.05).tolist(),
        "max_damaged_members":2,"candidate_count":len(result["candidates"]),"candidate_fit_failures":result["fit_failures"],
        "normalized_sensor_rmse":float(np.sqrt(best["rss"]/result["observations"])),
        "noise_std":result["noise_std"],"noise_floor":1e-4,"estimated_common_bias":best["bias"],
        "selection_penalty":float(penalty),"selection_score":float(score(best)),
        "detection_threshold":.05,
        "note":"Restricted zero/one/two-member search with a six-member pair shortlist; noise level must be supplied or assumed. No calibrated damage probability."}


def sparse_refine(sensors,values,mask,prior,noise_std,penalty,load_scale=1,operator=None):
    return select_sparse(sparse_candidates(sensors,values,mask,prior,noise_std,load_scale,operator),penalty)
