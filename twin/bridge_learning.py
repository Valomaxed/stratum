"""First bridge-specific RF baseline: one complete crossing, zero/one loss.

Inputs contain phase-sampled strain/displacement only, never configured damage,
effective modulus, stresses, modal frequencies, or comparison summary labels.
"""
import hashlib
import json
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from threadpoolctl import threadpool_limits
from .bridge import bridge_context, DEFAULTS
from .bridge_dynamics import _history

DIRECTORY=Path(__file__).resolve().parents[1]/'data'/'bridge-ml'
VERSION='bridge-dynamic-full-array-v1'
POSITIONS=np.linspace(0,28,15)
TARGET_TIMES=np.r_[POSITIONS/10,2.8+np.array([.1,.3,.7,1.3,2.])]
FIXED_SETTINGS={k:DEFAULTS[k] for k in ('front_axle_kn','rear_axle_kn','axle_spacing_m','lane_offset_m','deck_load_kn_m')}


def contract():
    model=bridge_context()['model'];k,m,_=model.assemble()
    digest=hashlib.sha256()
    for value in (model.nodes,model.members,model.fixed_dofs,k,m,TARGET_TIMES):
        digest.update(np.asarray(value,dtype='<f8').tobytes())
    digest.update(VERSION.encode())
    return digest.hexdigest()


def sampled_channels(model, history, scale=1.):
    strain=np.asarray(history['strain'],float)
    displacement=np.asarray(history['displacement'],float).reshape(-1,60)[:,model.free]
    values=np.concatenate((strain,displacement),axis=1)/scale
    times=np.asarray(history['time'],float)
    if values.shape!=(len(times),131) or len(times)<2 or np.any(np.diff(times)<=0) or not np.all(np.isfinite(values)):
        raise ValueError('A finite, complete 131-channel crossing history is required')
    if times[0]>1e-9 or times[-1]<TARGET_TIMES[-1]-1e-9:
        raise ValueError('Crossing must include the complete 2 s vibration tail')
    return np.array([np.interp(TARGET_TIMES,times,values[:,j]) for j in range(131)])


def normalized_packet(model, current, healthy, scale=1.):
    reference=sampled_channels(model,healthy)
    normalization=np.r_[np.full((78,1),max(np.max(np.abs(reference[:78])),1e-6)),
                        np.full((53,1),max(np.max(np.abs(reference[78:])),1e-6))]
    return (sampled_channels(model,current,scale)-reference)/normalization


def features(packet):
    packet=np.asarray(packet,float)
    if packet.shape!=(131,20) or not np.all(np.isfinite(packet)):
        raise ValueError('Dynamic measurement packet must have 131 by 20 finite values')
    return np.r_[packet.ravel(),packet.mean(axis=1),np.sqrt(np.mean(packet**2,axis=1))].astype(np.float32)


def _initialize_worker():
    global _MODEL,_CONFIG,_HEALTHY,_LIMIT
    _LIMIT=threadpool_limits(limits=1)
    context=bridge_context();_MODEL=context['model'];_CONFIG=context['config']
    _HEALTHY=_history(_MODEL,_CONFIG,None,1,(),10,.02,include_trace=False)


def _simulate_case(job):
    case_id,label,severity=job
    if label==0:current=_HEALTHY
    else:
        loss=np.zeros(78);loss[label-1]=severity
        current=_history(_MODEL,_CONFIG,loss,1,(),10,.02,include_trace=False)
    return case_id,normalized_packet(_MODEL,current,_HEALTHY).astype(np.float32)


def evaluate(classifier,regressor,x,labels,severities,threshold=0.):
    votes=classifier.predict_proba(x);winning=np.argmax(votes,axis=1)
    predicted=classifier.classes_[winning];score=votes[np.arange(len(x)),winning]
    accepted=score>=threshold
    loss=regressor.predict(x);loss=np.where(predicted==0,0,loss)
    damaged=labels>0;healthy=~damaged;correct=predicted==labels
    assigned=np.where(correct&accepted,loss,0)
    return {'accuracy':float(np.mean(correct&accepted)),
            'damaged_location_accuracy':float(np.mean((correct&accepted)[damaged])) if damaged.any() else None,
            'healthy_false_alarm_rate':float(np.mean(((predicted!=0)&accepted)[healthy])) if healthy.any() else None,
            'coverage':float(np.mean(accepted)),
            'accuracy_when_accepted':float(np.mean(correct[accepted])) if accepted.any() else None,
            'damaged_severity_mae_pp':float(np.mean(np.abs(assigned[damaged]-severities[damaged]))*100) if damaged.any() else None,
            'correct_location_severity_mae_pp':float(np.mean(np.abs(loss[damaged&correct&accepted]-severities[damaged&correct&accepted]))*100) if np.any(damaged&correct&accepted) else None,
            'predicted':predicted,'score':score,'severity':loss,'accepted':accepted}


def _summary(result):return {k:v for k,v in result.items() if not isinstance(v,np.ndarray)}


def train(cases_per_member=40,healthy_cases=400,workers=4,seed=281026,output=DIRECTORY):
    if not 10<=cases_per_member<=200 or not 40<=healthy_cases<=2000 or not 1<=workers<=8:
        raise ValueError('Require 10..200 cases/member, 40..2000 healthy cases and 1..8 workers')
    output=Path(output);output.mkdir(parents=True,exist_ok=True);started=time.perf_counter();rng=np.random.default_rng(seed)
    labels=np.r_[np.zeros(healthy_cases,int),np.repeat(np.arange(1,79),cases_per_member)]
    severity=np.where(labels>0,rng.uniform(.08,.65,len(labels)),0)
    split=np.empty(len(labels),int)
    # Stratify by location; partition independent severity scenarios BEFORE any
    # corruption. Healthy replicates share one zero-loss FEM state and provide
    # independent noise draws, not independent structural configurations.
    for label in range(79):
        ids=np.flatnonzero(labels==label);rng.shuffle(ids);a=int(.7*len(ids));b=int(.85*len(ids))
        split[ids[:a]]=0;split[ids[a:b]]=1;split[ids[b:]]=2
    packets=np.empty((len(labels),131,20),np.float32)
    jobs=[(i,int(label),float(s)) for i,(label,s) in enumerate(zip(labels,severity))]
    print(f'Generating {len(jobs)} bridge crossings; {workers} numerical workers',flush=True)
    with ProcessPoolExecutor(max_workers=workers,initializer=_initialize_worker) as pool:
        for done,(i,packet) in enumerate(pool.map(_simulate_case,jobs,chunksize=4),1):
            packets[i]=packet
            if done%128==0 or done==len(jobs):print(f'FEM {done}/{len(jobs)} · {time.perf_counter()-started:.1f} s',flush=True)
    np.savez_compressed(output/'dataset.npz',packet=packets,label=labels,severity=severity,split=split,
                        target_times=TARGET_TIMES,seed=seed,contract=contract())
    train_ids=np.flatnonzero(split==0);val_ids=np.flatnonzero(split==1);test_ids=np.flatnonzero(split==2)
    x=[];ys=[];ls=[]
    for i in train_ids:
        for noise in (0,.005,.01):
            x.append(features(packets[i]+rng.normal(0,noise,(131,20))));ys.append(labels[i]);ls.append(severity[i])
    x=np.asarray(x);ys=np.array(ys);ls=np.array(ls)
    classifier=RandomForestClassifier(n_estimators=180,max_features='sqrt',class_weight='balanced_subsample',n_jobs=2,random_state=seed)
    regressor=RandomForestRegressor(n_estimators=160,max_features='sqrt',n_jobs=2,random_state=seed+1)
    print('Training bridge location classifier and severity regressor',flush=True)
    classifier.fit(x,ys);regressor.fit(x,ls)
    validation_x=np.array([features(packets[i]+rng.normal(0,.005,(131,20))) for i in val_ids])
    thresholds=(.2,.35,.5,.65)
    candidates=[{'threshold':threshold,**_summary(evaluate(classifier,regressor,validation_x,labels[val_ids],severity[val_ids],threshold))} for threshold in thresholds]
    feasible=[row for row in candidates if row['healthy_false_alarm_rate']<=.05 and row['coverage']>=.5]
    selected=max(feasible or candidates,key=lambda row:(row['accuracy'],-row['threshold']))
    # Save the validation-selected policy and forest BEFORE auditing test data.
    artifact={'version':VERSION,'contract':contract(),'classifier':classifier,'regressor':regressor,
              'threshold':selected['threshold'],'seed':seed,'training_scope':FIXED_SETTINGS}
    joblib.dump(artifact,output/'forest.joblib',compress=3)
    forest_hash=hashlib.sha256((output/'forest.joblib').read_bytes()).hexdigest()
    (output/'selection.json').write_text(json.dumps({'candidates':candidates,'selected':selected,'forest_sha256':forest_hash},indent=2),encoding='utf8')
    experiments=[];raw={}
    for index,(name,noise) in enumerate((('clean',0),('noise_0_5_pct',.005),('noise_1_pct',.01))):
        test_x=np.array([features(packets[i]+rng.normal(0,noise,(131,20))) for i in test_ids])
        result=evaluate(classifier,regressor,test_x,labels[test_ids],severity[test_ids],selected['threshold'])
        experiments.append({'condition':name,'noise_fraction':noise,**_summary(result)})
        for key in ('predicted','score','severity','accepted'):raw[f'{name}_{key}']=result[key]
        if index==1:
            per_member=[{'member':f'M{m:02}','cases':int(np.sum(labels[test_ids]==m)),
                         'accuracy':float(np.mean((result['predicted'][labels[test_ids]==m]==m)&result['accepted'][labels[test_ids]==m]))} for m in range(1,79)]
    np.savez_compressed(output/'test-predictions.npz',case_ids=test_ids,label=labels[test_ids],true_severity=severity[test_ids],**raw)
    report={'version':VERSION,'contract':contract(),'forest_sha256':forest_hash,'seed':seed,'cases':len(labels),
            'distinct_structural_scenarios':int(np.sum(labels>0)+1),'healthy_noise_replicates':healthy_cases,
            'train_cases':len(train_ids),'validation_cases':len(val_ids),'test_cases':len(test_ids),
            'augmented_training_packets':len(x),'physical_channels':131,'phase_samples':20,'feature_count':x.shape[1],
            'speed_kmh':36,'damping_ratio':.02,'settings':FIXED_SETTINGS,'severity_range':[.08,.65],
            'damage_family':'Healthy or one damaged axial member. Multiple damage and member removal are not validated.',
            'sensor_scope':'Full 78 strain + 53 free-displacement channels; complete crossing plus 2 s tail. Independent Gaussian sample noise relative to healthy per-type peak scale; no dropout or drift.',
            'selection':selected,'experiments':experiments,'per_member_noisy':per_member,
            'elapsed_seconds':time.perf_counter()-started,
            'limitations':['Same FEM for training and test; no hardware or cross-geometry validation.',
                'Forest class votes are uncalibrated, not damage probabilities.',
                'Accuracy counts abstentions as failures. Severity error assigns zero at a true damaged member when the member is missed or rejected.',
                'Healthy cases are independent noise replicates of a single structural state; class/severity scenarios split before augmentation.',
                'Fixed supports, materials, deck mass, axles, lane, speed and damping; load multiplier cancels by known linear normalization.']}
    (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf8')
    print(json.dumps({'report':str(output/'report.json'),'experiments':experiments,'elapsed_seconds':report['elapsed_seconds']},indent=2),flush=True)
    return report


class BridgeDamageEstimator:
    def __init__(self,directory=DIRECTORY):
        self.directory=Path(directory);self.artifact=None;self.report=None;self.error=None
        try:
            report=json.loads((self.directory/'report.json').read_text(encoding='utf8'))
            path=self.directory/'forest.joblib'
            if report['contract']!=contract() or hashlib.sha256(path.read_bytes()).hexdigest()!=report['forest_sha256']:
                raise ValueError('Bridge model or forest signature changed; retrain before use')
            artifact=joblib.load(path)
            if artifact['contract']!=contract() or artifact['version']!=VERSION or artifact['training_scope']!=FIXED_SETTINGS:
                raise ValueError('Bridge ML contract or loading protocol mismatch')
            self.artifact=artifact;self.report=report
        except (FileNotFoundError,ValueError,KeyError) as error:self.error=str(error)
        self.baseline=None

    def eligibility(self,bundle,noise=0,sensor_count=131,missing=0,drift=0):
        if self.artifact is None:return 'Bridge dynamic ML is not trained or its artifact is incompatible.'
        if bundle.get('method')!='dynamic-moving-force':return 'Bridge ML requires a complete dynamic crossing.'
        if any(abs(bundle['settings'][k]-v)>1e-8 for k,v in FIXED_SETTINGS.items()) or abs(bundle['speed_kmh']-36)>1e-8 or abs(bundle['damping_ratio']-.02)>1e-8:
            return 'Baseline requires default axles/deck/lane, 36 km/h and 2% damping. Other conditions are outside training.'
        if sensor_count!=131:return 'The original baseline requires all 131 channels; use a validated sparse model for a reduced budget.'
        if missing!=0 or drift!=0 or not np.isfinite(noise) or not 0<=noise<=.01:
            return 'Bridge ML supports no dropout or drift and only 0–1% sample noise.'
        return None

    def measurement_packet(self,bundle):
        model=bridge_context()['model']
        if self.baseline is None:self.baseline=_history(model,bridge_context()['config'],None,1,(),10,.02,include_trace=False)
        current={'time':bundle['time_s'],'strain':bundle['strain'],'displacement':bundle['displacement']}
        return normalized_packet(model,current,self.baseline,bundle['load_scale'])

    def predict(self,bundle,noise=0,seed=42,sensor_count=131,missing=0,drift=0):
        reason=self.eligibility(bundle,noise,sensor_count,missing,drift)
        if reason:return {'available':False,'reason':reason}
        packet=self.measurement_packet(bundle)
        x=features(packet+np.random.default_rng(seed).normal(0,noise,packet.shape))[None,:]
        scores=self.artifact['classifier'].predict_proba(x)[0];winner=int(np.argmax(scores))
        label=int(self.artifact['classifier'].classes_[winner]);vote=float(scores[winner])
        accepted=vote>=self.artifact['threshold']
        severity=0. if label==0 else float(self.artifact['regressor'].predict(x)[0])
        return {'available':True,'accepted':accepted,'label':'Healthy' if label==0 else f'M{label:02}',
                'member':None if label==0 else label-1,'severity':severity,'class_vote':vote,
                'abstention_threshold':self.artifact['threshold'],'noise_fraction':noise,
                'method':'Bridge dynamic Random Forest baseline','acquisition':'Complete simulated crossing; 131 strain/displacement channels × 20 phase samples',
                'validation':self.report['experiments'],'scope':self.report['damage_family'],
                'note':'Uncalibrated class vote; zero/one-damage assumption. Fixed research crossing only. No hardware validation.'}
