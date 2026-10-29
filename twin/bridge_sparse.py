"""Paired sparse-channel RF study, with placement chosen from healthy physics.

The original full-array forest/dataset are read-only. Each physical channel
contributes all 20 phase observations; no hidden full-array summaries are used.
"""
import hashlib
import json
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier,RandomForestRegressor
from threadpoolctl import threadpool_limits
from .bridge_learning import (DIRECTORY as BASE,VERSION as BASE_VERSION,FIXED_SETTINGS,
    contract,features,evaluate,_summary,_initialize_worker,_simulate_case,BridgeDamageEstimator)
from .bridge import bridge_context
from .sensors import SensorArray

DIRECTORY=BASE.parent/'bridge-sparse'
VERSION='bridge-dynamic-sparse-v1'
BUDGETS=(131,50,20,10,5)


def sparse_features(packet,indices):
    packet=np.asarray(packet,float);indices=np.asarray(indices)
    if packet.shape!=(131,20) or indices.ndim!=1 or not len(indices) or indices.dtype.kind not in 'iu' or len(np.unique(indices))!=len(indices) or np.any((indices<0)|(indices>=131)):
        raise ValueError('Sparse features require distinct physical channel indices in 0..130')
    values=packet[indices]
    if not np.all(np.isfinite(values)):raise ValueError('Selected channel measurements must be finite')
    return np.r_[values.ravel(),values.mean(axis=1),np.sqrt(np.mean(values**2,axis=1))].astype(np.float32)


def healthy_order(sensitivity):
    """Greedy grouped D-optimal selection; each sensor supplies 20 readings."""
    sensitivity=np.asarray(sensitivity,float)
    if sensitivity.shape!=(131,20,78) or not np.all(np.isfinite(sensitivity)):
        raise ValueError('Healthy sensitivity must have shape (131,20,78)')
    inverse=np.eye(78)*100;remaining=list(range(131));order=[]
    for _ in range(131):
        rows=sensitivity[remaining]
        products=rows @ inverse
        blocks=np.eye(20)+products @ rows.transpose(0,2,1)
        signs,gains=np.linalg.slogdet(blocks)
        if np.any(signs<=0):raise ValueError('Invalid information matrix in placement')
        selected=remaining.pop(int(np.argmax(gains)));order.append(selected)
        chosen=sensitivity[selected];v=inverse @ chosen.T
        inverse-=v @ np.linalg.solve(np.eye(20)+chosen @ v,v.T)
        inverse=(inverse+inverse.T)/2
    return order


def paired_packets(dataset):
    """Replay the original noise RNG exactly; never refit a normalization."""
    packets=dataset['packet'];labels=dataset['label'];severity=dataset['severity'];split=dataset['split']
    seed=int(dataset['seed']);rng=np.random.default_rng(seed)
    replay_severity=np.where(labels>0,rng.uniform(.08,.65,len(labels)),0)
    replay_split=np.empty(len(labels),int)
    for label in range(79):
        ids=np.flatnonzero(labels==label);rng.shuffle(ids);a=int(.7*len(ids));b=int(.85*len(ids))
        replay_split[ids[:a]]=0;replay_split[ids[a:b]]=1;replay_split[ids[b:]]=2
    if not np.array_equal(severity,replay_severity) or not np.array_equal(split,replay_split):
        raise ValueError('Dataset does not match the frozen baseline noise/split protocol')
    train_ids=np.flatnonzero(split==0);val_ids=np.flatnonzero(split==1);test_ids=np.flatnonzero(split==2)
    train=np.empty((len(train_ids)*3,131,20),float)
    for row,i in enumerate(train_ids):
        for j,noise in enumerate((0,.005,.01)):
            train[3*row+j]=packets[i]+rng.normal(0,noise,(131,20))
    validation=np.array([packets[i]+rng.normal(0,.005,(131,20)) for i in val_ids])
    tests={name:np.array([packets[i]+rng.normal(0,noise,(131,20)) for i in test_ids])
           for name,noise in (('clean',0),('noise_0_5_pct',.005),('noise_1_pct',.01))}
    return train,validation,tests,train_ids,val_ids,test_ids


def _save_model(job):
    placement,budget,indices,base_path,output_path=job
    with threadpool_limits(limits=1):
        dataset=np.load(Path(base_path)/'dataset.npz');seed=int(dataset['seed'])
        train,validation,_,train_ids,val_ids,_=paired_packets(dataset)
        x=np.array([sparse_features(packet,indices) for packet in train]);del train
        vx=np.array([sparse_features(packet,indices) for packet in validation]);del validation
        labels=dataset['label'];severity=dataset['severity']
        classifier=RandomForestClassifier(n_estimators=180,max_features='sqrt',class_weight='balanced_subsample',n_jobs=1,random_state=seed)
        regressor=RandomForestRegressor(n_estimators=160,max_features='sqrt',n_jobs=1,random_state=seed+1)
        classifier.fit(x,np.repeat(labels[train_ids],3));regressor.fit(x,np.repeat(severity[train_ids],3))
        candidates=[{'threshold':t,**_summary(evaluate(classifier,regressor,vx,labels[val_ids],severity[val_ids],t))} for t in (.2,.35,.5,.65)]
        feasible=[row for row in candidates if row['healthy_false_alarm_rate']<=.05 and row['coverage']>=.5]
        selected=max(feasible or candidates,key=lambda row:(row['accuracy'],-row['threshold']))
        path=Path(output_path)/'models'/f'{placement}-{budget}.joblib'
        artifact={'version':VERSION,'contract':contract(),'classifier':classifier,'regressor':regressor,
                  'threshold':selected['threshold'],'indices':list(indices),'budget':budget,'placement':placement,'training_scope':FIXED_SETTINGS}
        joblib.dump(artifact,path,compress=3)
        return {'placement':placement,'budget':budget,'indices':list(indices),'model_file':str(path.relative_to(output_path)),
                'forest_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'validation':selected,'validation_candidates':candidates}


def run(workers=2,output=DIRECTORY,base=BASE):
    if not 1<=workers<=4:raise ValueError('Use 1..4 numerical workers')
    output=Path(output);base=Path(base);output.mkdir(parents=True,exist_ok=True);(output/'models').mkdir(exist_ok=True)
    started=time.perf_counter();dataset_path=base/'dataset.npz';dataset=np.load(dataset_path)
    baseline=BridgeDamageEstimator(base)
    if baseline.artifact is None:raise ValueError('Train and validate the full-array bridge model first')
    dataset_hash=hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    if str(dataset['contract'])!=contract():raise ValueError('Bridge dataset contract changed')
    print('Computing dynamic healthy sensitivity for 78 member-loss directions',flush=True)
    sensitivity=np.empty((131,20,78));jobs=[(i,i+1,.02) for i in range(78)]
    with ProcessPoolExecutor(max_workers=workers,initializer=_initialize_worker) as pool:
        for i,packet in pool.map(_simulate_case,jobs):sensitivity[:,:,i]=packet/.02
    with threadpool_limits(limits=1):guided=healthy_order(sensitivity)
    random_order=np.random.default_rng(481026).permutation(131).tolist()
    catalog=SensorArray(bridge_context()['model']).catalog
    placements={'guided':guided,'random':random_order}
    placement_data={'version':VERSION,'contract':contract(),'dataset_sha256':dataset_hash,'random_seed':481026,
                    'healthy_loss_step':.02,'method':'Greedy grouped D-optimal, regularization 0.01; 20 phase readings per physical channel',
                    'orders':placements,'catalog':catalog}
    placement_path=output/'placement.json';placement_path.write_text(json.dumps(placement_data,indent=2),encoding='utf8')
    placement_hash=hashlib.sha256(placement_path.read_bytes()).hexdigest()
    np.savez_compressed(output/'healthy-sensitivity.npz',sensitivity=sensitivity)
    entries=[];training_jobs=[]
    for placement,order in placements.items():
        for budget in BUDGETS:
            if budget==131:
                # The complete array is the identical original model, not a retrain.
                entry={'placement':placement,'budget':131,'indices':list(range(131)),
                       'model_file':None,'forest_sha256':baseline.report['forest_sha256'],'validation':baseline.report['selection']}
                entries.append(entry)
            else:training_jobs.append((placement,budget,order[:budget],str(base),str(output)))
    print(f'Training {len(training_jobs)} reduced-channel forest pairs; baseline forest preserved',flush=True)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for entry in pool.map(_save_model,training_jobs):
            entries.append(entry);print(f"Frozen {entry['placement']} {entry['budget']} channels · {time.perf_counter()-started:.1f} s",flush=True)
    # All placement, model choices and thresholds are frozen before sparse-test evaluation.
    qualified=[row for row in entries if row['placement']=='guided' and row['validation']['accuracy']>=.9
               and row['validation']['coverage']>=.95 and row['validation']['healthy_false_alarm_rate']<=.05]
    recommended=min((row['budget'] for row in qualified),default=None)
    selection={'version':VERSION,'contract':contract(),'dataset_sha256':dataset_hash,'placement_sha256':placement_hash,
               'entries':entries,'recommended_budget':recommended,
               'recommendation_rule':'Smallest tested guided budget with validation accuracy >=90%, coverage >=95%, healthy false alarms <=5% at 0.5% noise. This is not a universal minimum.'}
    (output/'selection.json').write_text(json.dumps(selection,indent=2),encoding='utf8')
    selection_hash=hashlib.sha256((output/'selection.json').read_bytes()).hexdigest()
    del baseline
    train,validation,tests,_,val_ids,test_ids=paired_packets(dataset);del train,validation
    labels=dataset['label'];severity=dataset['severity'];raw={};experiments=[]
    for entry in entries:
        artifact=joblib.load(base/'forest.joblib' if entry['model_file'] is None else output/entry['model_file'])
        classifier=artifact['classifier'];regressor=artifact['regressor']
        for noise_index,(name,packets) in enumerate(tests.items()):
            x=np.array([features(packet) if entry['budget']==131 else sparse_features(packet,entry['indices']) for packet in packets])
            result=evaluate(classifier,regressor,x,labels[test_ids],severity[test_ids],entry['validation']['threshold'])
            prefix=f"{entry['placement']}_{entry['budget']}_{name}"
            for key in ('predicted','score','severity','accepted'):raw[prefix+'_'+key]=result[key]
            experiments.append({'placement':entry['placement'],'budget':entry['budget'],'condition':name,
                'noise_fraction':(0,.005,.01)[noise_index],**_summary(result)})
        print(f"Audited {entry['placement']} {entry['budget']} channels",flush=True)
    np.savez_compressed(output/'test-predictions.npz',case_ids=test_ids,label=labels[test_ids],true_severity=severity[test_ids],**raw)
    rank={str(budget):int(np.linalg.matrix_rank(sensitivity[guided[:budget]].reshape(-1,78),tol=np.linalg.svd(sensitivity[guided[:budget]].reshape(-1,78),compute_uv=False)[0]*1e-8)) for budget in BUDGETS}
    report={**{k:v for k,v in selection.items() if k!='entries'},'selection_sha256':selection_hash,'budgets':list(BUDGETS),'experiments':experiments,
            'training_cases':int(np.sum(dataset['split']==0)),'validation_cases':len(val_ids),'test_cases':len(test_ids),
            'source_baseline_version':BASE_VERSION,'source_forest_sha256':json.loads((base/'report.json').read_text(encoding='utf8'))['forest_sha256'],
            'guided_sensitivity_rank':rank,'elapsed_seconds':time.perf_counter()-started,
            'limitations':['Same fixed synthetic crossing and zero/one damage family as the full-array baseline.',
               'Physical channels are strain gauges or individual displacement axes; all 20 phase readings are kept per selected channel.',
               'One fixed nested random layout, not a distribution over random placements.',
               'Paired cases and pre-existing test split; no new independent real-world validation.',
               'The guided ordering is a local greedy information heuristic, not a globally optimal placement.',
               'Accuracy includes abstentions as failures; class votes are uncalibrated. Dropout and drift remain unsupported.']}
    (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf8')
    print(json.dumps({'recommended_budget':recommended,'elapsed_seconds':report['elapsed_seconds'],
                     'noisy_results':[r for r in experiments if r['condition']=='noise_0_5_pct']},indent=2),flush=True)
    return report


class SparseBridgeDamageEstimator:
    def __init__(self,baseline=None,directory=DIRECTORY):
        self.baseline=baseline or BridgeDamageEstimator();self.directory=Path(directory);self.report=None;self.selection=None;self.cache={};self.error=None
        try:
            report=json.loads((self.directory/'report.json').read_text(encoding='utf8'))
            selection=json.loads((self.directory/'selection.json').read_text(encoding='utf8'))
            placement=self.directory/'placement.json'
            if report['version']!=VERSION or selection['version']!=VERSION:
                raise ValueError('Sparse bridge study version mismatch')
            if report['contract']!=contract() or selection['contract']!=contract() or hashlib.sha256(placement.read_bytes()).hexdigest()!=report['placement_sha256']:
                raise ValueError('Sparse bridge model or placement signature changed')
            if hashlib.sha256((self.directory/'selection.json').read_bytes()).hexdigest()!=report['selection_sha256']:
                raise ValueError('Sparse model selection metadata changed')
            if self.baseline.report is None or report['source_forest_sha256']!=self.baseline.report['forest_sha256']:
                raise ValueError('Sparse models require the original validated baseline forest')
            self.report=report;self.selection=selection
            self.catalog=json.loads(placement.read_text(encoding='utf8'))['catalog']
        except (FileNotFoundError,ValueError,KeyError) as error:self.error=str(error)

    def predict(self,bundle,noise=0,seed=42,sensor_count=131,placement='guided',missing=0,drift=0):
        if placement not in ('guided','random') or sensor_count not in BUDGETS:
            return {'available':False,'reason':'Choose a validated ML budget: 131, 50, 20, 10 or 5 channels and guided/random placement.'}
        if self.report is None:
            if sensor_count==131:return self.baseline.predict(bundle,noise,seed,131,missing,drift)
            return {'available':False,'reason':'Run the bridge sparse-sensor study before using reduced ML budgets.'}
        # Apply the exact original acquisition guards without feeding damage labels.
        reason=self.baseline.eligibility(bundle,noise,131,missing,drift)
        if reason:return {'available':False,'reason':reason}
        entry=next(row for row in self.selection['entries'] if row['budget']==sensor_count and row['placement']==placement)
        if sensor_count==131:result=self.baseline.predict(bundle,noise,seed,131,missing,drift)
        else:
            key=(placement,sensor_count)
            if key not in self.cache:
                path=(self.directory/entry['model_file']).resolve()
                if not path.is_relative_to(self.directory.resolve()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=entry['forest_sha256']:
                    return {'available':False,'reason':'Sparse forest signature mismatch; rerun the validated study.'}
                artifact=joblib.load(path)
                if artifact['contract']!=contract() or artifact['indices']!=entry['indices'] or artifact['version']!=VERSION:
                    return {'available':False,'reason':'Sparse forest channel contract mismatch.'}
                self.cache.clear();self.cache[key]=artifact
            artifact=self.cache[key]
            packet=self.baseline.measurement_packet(bundle)
            packet+=np.random.default_rng(seed).normal(0,noise,packet.shape)
            x=sparse_features(packet,entry['indices'])[None,:];scores=artifact['classifier'].predict_proba(x)[0]
            winner=int(np.argmax(scores));label=int(artifact['classifier'].classes_[winner]);vote=float(scores[winner])
            result={'available':True,'label':'Healthy' if label==0 else f'M{label:02}','member':None if label==0 else label-1,
                    'class_vote':vote,'accepted':vote>=artifact['threshold'],'abstention_threshold':artifact['threshold'],
                    'severity':0. if label==0 else float(artifact['regressor'].predict(x)[0]),
                    'method':'Bridge sparse dynamic Random Forest','noise_fraction':noise,'scope':self.baseline.report['damage_family']}
        return {**result,'sensor_count':sensor_count,'placement':placement,'sensor_indices':entry['indices'],
                'selected_channels':[self.catalog[i] for i in entry['indices']],
                'acquisition':f'Complete simulated crossing; {sensor_count} physical channels x 20 phase samples; {placement} placement',
                'validation':[r for r in self.report['experiments'] if r['budget']==sensor_count and r['placement']==placement],
                'sparse_study':{'experiments':[r for r in self.report['experiments'] if r['condition']=='noise_0_5_pct'],
                                'recommended_budget':self.report['recommended_budget'],'recommendation_rule':self.report['recommendation_rule'],
                                'test_cases':self.report['test_cases']},
                'note':'Uncalibrated class vote; healthy/one-damage, fixed crossing. Sparse accuracy depends on placement. No dropout, drift or hardware validation.'}
