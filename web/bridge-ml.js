/* End-of-crossing inference, kept separate from configured damage colors. */
let bridgeMLKey='';
function initializeBridgeML(){
 for(const id of ['bridge-ml-budget','bridge-ml-placement'])$(id).onchange=markPending;
 $('bridge-ml-inspect').onclick=()=>{
  const ml=bridgePlayback.frames?.ml;if(!ml?.accepted||ml.member===null)return;
  state.selected=ml.member;$('damage-member').value=ml.member;syncControls();updateInspector();state.dirty=true;
 };
}
function resetBridgeML(){
 bridgeMLKey='';$('bridge-ml').hidden=state.modelId!=='bridge';
 $('bridge-ml-member').textContent=$('bridge-ml-loss').textContent=$('bridge-ml-vote').textContent='—';
 $('bridge-ml-status').textContent='Awaiting crossing';$('bridge-ml-detail').textContent='Complete a supported dynamic crossing to read the estimate.';
 $('bridge-ml-inspect').hidden=$('bridge-ml-validation').hidden=true;
 $('bridge-ml-layout').hidden=$('bridge-sparse-results').hidden=true;
}
function updateBridgeML(){
 const p=bridgePlayback,f=p.frames;if(state.modelId!=='bridge'||f?.method!=='dynamic-moving-force')return;
 $('bridge-ml').hidden=false;
 const complete=p.completedCrossings>0||p.position>=f.positions_m.at(-1)-1e-8,ml=f.ml;
 const key=p.generation+':'+complete+':'+Boolean(ml?.available);if(key===bridgeMLKey)return;bridgeMLKey=key;
 if(ml?.selected_channels){
  $('bridge-ml-layout').hidden=false;const list=$('bridge-ml-channel-list');list.replaceChildren();
  for(const sensor of ml.selected_channels){const item=document.createElement('span');item.textContent=sensor.id;item.title=sensor.kind==='strain'?`M${sensor.member+1} strain`:`N${sensor.node+1} ${'XYZ'[sensor.axis]} displacement`;list.append(item)}
  $('bridge-ml-layout-summary').textContent=`Selected ML channels · ${ml.sensor_count} · ${ml.placement==='guided'?'healthy-model placement':'fixed random placement'}`;
 }
 if(!complete){
  $('bridge-ml-member').textContent=$('bridge-ml-loss').textContent=$('bridge-ml-vote').textContent='—';
  $('bridge-ml-inspect').hidden=$('bridge-ml-validation').hidden=true;
  $('bridge-ml-status').textContent='Acquiring crossing';$('bridge-ml-detail').textContent='The model uses a complete crossing and its 2 s vibration tail. Estimates appear after acquisition.';return;
 }
 if(!ml?.available){
  $('bridge-ml-status').textContent='Outside model scope';$('bridge-ml-detail').textContent=ml?.reason||'Bridge model is not trained.';return;
 }
 $('bridge-ml-status').textContent=ml.accepted?'Crossing analyzed':'Uncertain · abstained';
 $('bridge-ml-member').textContent=ml.accepted?ml.label:'Uncertain';
 $('bridge-ml-loss').textContent=ml.accepted?pct(ml.severity,1):'—';
 $('bridge-ml-vote').textContent=pct(ml.class_vote,1);
 $('bridge-ml-detail').textContent=(ml.accepted?'':'Top candidate '+ml.label+' falls below the validation-selected vote threshold. ')+ml.acquisition+` · ${fmt(ml.noise_fraction*100,1)}% simulated noise. `+ml.note;
 const benchmark=ml.validation.find(row=>Math.abs(row.noise_fraction-.005)<1e-9);
 if(benchmark)$('bridge-ml-detail').textContent+=` Held-out location accuracy for this layout at 0.5% noise: ${pct(benchmark.accuracy,1)}.`;
 $('bridge-ml-inspect').hidden=!ml.accepted||ml.member===null;
 $('bridge-ml-inspect').textContent='Inspect '+ml.label;
 const report=$('bridge-ml-report');report.replaceChildren();
 const table=document.createElement('table'),head=document.createElement('thead'),row=document.createElement('tr');
 for(const title of ['TEST CONDITION','LOCATION ACCURACY','COVERAGE','HEALTHY ALARMS','DAMAGE MAE']){const cell=document.createElement('th');cell.textContent=title;row.append(cell)}head.append(row);table.append(head);
 const body=document.createElement('tbody');for(const result of ml.validation){const row=document.createElement('tr');for(const text of [fmt(result.noise_fraction*100,1)+'% noise',pct(result.accuracy,1),pct(result.coverage,1),pct(result.healthy_false_alarm_rate,1),fmt(result.damaged_severity_mae_pp,2)+' pp']){const cell=document.createElement('td');cell.textContent=text;row.append(cell)}body.append(row)}table.append(body);report.append(table);$('bridge-ml-validation').hidden=false;
 renderBridgeSparseResults(ml.sparse_study);
}
function renderBridgeSparseResults(study){
 $('bridge-sparse-results').hidden=!study;if(!study)return;
 $('bridge-sparse-selection').textContent=study.recommended_budget===null?'No tested guided budget met the validation target.':(study.recommended_budget===131?'Only the full 131-channel guided layout met the validation target; none of the reduced tested layouts qualified.':`${study.recommended_budget} channels met the validation target.`)+' Target: ≥90% location, ≥95% coverage, ≤5% healthy alarms on validation data. This is a comparison of tested budgets, not a universal minimum.';
 const rows=$('bridge-sparse-rows');rows.replaceChildren();
 for(const budget of [131,50,20,10,5]){
  const guided=study.experiments.find(r=>r.placement==='guided'&&r.budget===budget),random=study.experiments.find(r=>r.placement==='random'&&r.budget===budget);if(!guided||!random)continue;
  const row=document.createElement('tr');for(const text of [String(budget),pct(guided.accuracy,1),pct(random.accuracy,1),pct(guided.coverage,1),fmt(guided.damaged_severity_mae_pp,2)+' pp']){const cell=document.createElement('td');cell.textContent=text;row.append(cell)}rows.append(row);
 }
 $('bridge-sparse-test-count').textContent=`Same ${study.test_cases} held-out cases · 0.5% noise · one fixed random layout · abstentions counted as failures.`;
}
