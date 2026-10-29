/* Local, dependency-free projected 3D viewer. The FEM remains in Python. */
const $ = id => document.getElementById(id);
const state = {modelId:'space', catalog:[], model:null, data:null, selected:13, damage:Array(21).fill(0), view:'damage', signal:'time', yaw:-.31, pitch:.27, zoom:1, panX:0, panY:0, dirty:true, metrics:null, robustMetrics:null, tick:0, requestId:0};
state.damage[13]=.3;
const canvas=$('structure'), ctx=canvas.getContext('2d'), chart=$('signal'), chartCtx=chart.getContext('2d');
let width=500,height=420, chartWidth=500,chartHeight=150, segments=[], drag=null, moved=false;
const fmt=(n,d=2)=>Number.isFinite(n)?(Math.abs(n)<.5*10**(-d)?0:n).toFixed(d):'—';
const pct=(n,d=0)=>fmt(n*100,d)+'%';
const colors={teal:'#111111',amber:'#555555',red:'#000000',purple:'#666666'};
const plotColors={healthy:'#2563eb',current:'#c65b13',signal:'#007f65',spectrum:'#7c3aed',envelope:'#7c3aed'};
function resize(c,cx){const r=c.getBoundingClientRect(),dpr=window.devicePixelRatio||1;c.width=Math.round(r.width*dpr);c.height=Math.round(r.height*dpr);cx.setTransform(dpr,0,0,dpr,0,0);return [r.width,r.height]}
new ResizeObserver(()=>{[width,height]=resize(canvas,ctx);state.dirty=true}).observe(canvas.parentElement);
new ResizeObserver(()=>{[chartWidth,chartHeight]=resize(chart,chartCtx);drawSignal()}).observe(chart.parentElement);
function resetCamera(){state.yaw=state.model?.dimension===3?-.57:-.31;state.pitch=.28;state.zoom=1;state.panX=state.panY=0;state.dirty=true}
function configureModel(id){
 const model=state.catalog.find(m=>m.id===id);if(!model)throw Error('Unknown structural model');
 state.modelId=id;state.model=model;state.data=null;segments=[];
 $('support-restraints').textContent=model.supports.map(s=>`N${String(s.node+1).padStart(2,'0')}: ${s.axes.join('/')} blocked; ${'XYZ'.slice(0,model.dimension).split('').filter(a=>!s.axes.includes(a)).join('/')||'none'} free`).join(' · ');
 state.selected=model.dimension===3?4:13;state.damage=Array(model.member_count).fill(0);state.damage[state.selected]=id==='bridge'?0:.3;
 $('damage-member').replaceChildren(...model.member_kinds.map((kind,i)=>new Option(`M${String(i+1).padStart(2,'0')} · ${kind}`,i)));
 $('damage-member').value=state.selected;
 $('sensor-count').max=model.sensor_capacity;$('sensor-count').value=model.sensor_capacity;
 $('deform-scale').value=model.dimension===3?50:250;$('deform-output').value=state.view==='mode'?fmt(Number($('deform-scale').value)/250,1)+'×':$('deform-scale').value+'×';
 $('load').value=100;$('noise').value=.5;$('missing').value=$('drift').value=0;$('stream').checked=false;state.tick=0;
 $('physics').checked=false;$('physics').disabled=$('refinement').disabled=!model.inference_supported;
 $('damage-source').value='configured';$('damage-source').querySelector('[value="estimated"]').disabled=!model.inference_supported;
 $('model-stage').textContent=model.stage;
 $('viewer-model-name').textContent=$('settings-model-name').textContent=model.name;
 const dimensions=model.extent.filter(v=>v>0).join(' × ')+' m';
 $('viewer-model-tag').textContent=`${model.dimension}D · ${model.member_count} members`;
 $('settings-model-details').textContent=`${dimensions} · ${model.member_count} members · Steel`;
 $('display-case').replaceChildren(...model.cases.map(c=>new Option(c.id+' · '+c.name,c.id)));
 $('protocol').value='multi';$('protocol').disabled=id==='bridge';$('display-case').disabled=false;
 $('inference-hint').textContent=model.inference_supported?'Sparse fit: up to 2 damaged members · uses configured noise σ':id==='bridge'?'Bridge RF uses a complete dynamic crossing in its own panel; static refinement is unavailable.':'3D inference training and validation are pending. Damage colors show configured stiffness loss.';
 $('selected-model-notes').textContent=id==='space'?'The 3D demo is a 24 × 4 × 4 m braced steel box truss with 20 joints, 78 axial members and 54 free translational degrees of freedom. Y is vertical and Z is transverse. Bearings restrain N01 in X/Y/Z, N02 in X/Y, and N17 in Y. Four longitudinal faces and all cross-sections are triangulated. LC1 applies a total 225 kN downward on six bottom joints; LC2 applies 225 kN on one upper side; LC3 applies 5 kN in X and 15 kN in Z at each upper joint. E = 200 GPa, A = 0.003 m², density = 7850 kg/m³. FEM response and virtual sensing are available; 3D ML damage estimation is not trained or validated.': 'The planar demo is a 24 × 4 m cross-braced steel truss with 10 joints and 21 axial members. Supports restrain N01 in X/Y and N05 in Y. Three downward 75 kN loads act at the internal bottom nodes. E = 200 GPa, A = 0.003 m², density = 7850 kg/m³. The existing inference studies below apply to this geometry only.';
 if(id==='bridge')$('selected-model-notes').textContent='The bridge is a 24 × 4 × 4 m steel axial truss with 20 joints, 78 members and 53 free translational degrees of freedom. Y is vertical and Z is transverse. N01 restrains X/Y/Z, N02 restrains Y, N17 restrains Y/Z and N18 restrains Y. These bilateral bearings allow longitudinal and transverse expansion about N01. Deck dead load and mass transfer to the bottom joints; the deck has no bending stiffness. Static loads and prescribed moving axle forces are available. Rotational bearing restraints, uplift/contact, vehicle suspension and design capacity checks are excluded.';
 $('refresh-telemetry').disabled=!model.inference_supported;
 $('telemetry-status').textContent=!model.inference_supported?'3D virtual sensor readings are shown below. External inference is currently available for the planar model only.':'External input: POST calibrated strain/displacement to /api/observations. The live twin uses simulated inputs.';
 for(const key of ['health','displacement','frequency','active-sensors','member-length','member-e','member-stress','member-strain','member-force','pred-loss','pred-vote'])$(key).textContent='—';
 $('sensor-total').textContent='/ '+model.sensor_capacity;$('measurement-foot').textContent='Preparing virtual sensor readings';$('frequency-shift').textContent='';
 $('prediction-note').textContent=model.inference_supported?'Preparing inference…':'3D inference is not trained or validated yet.';
 $('modal-rows').replaceChildren();$('sensor-grid').replaceChildren();$('member-name').textContent=`M${String(state.selected+1).padStart(2,'0')}`;
 configureBridgeUI(model);syncControls();resetCamera();drawSignal();
}
$('model-select').onchange=()=>{configureModel($('model-select').value);run()};
async function initialize(){
 try{const info=await api('/api/models');state.catalog=info.models;$('model-select').replaceChildren(...info.models.map(m=>new Option((m.dimension===3?'3D · ':'2D · ')+m.name,m.id)));$('model-select').value=info.default;configureModel(info.default);await run()}
 catch(e){$('error').textContent='Could not load model catalog: '+e.message;$('error').hidden=false;$('workspace-status').textContent='Model loading failed'}
}
function syncControls(){
 const id=Number($('damage-member').value), loss=state.damage[id];
 $('damage').value=loss*100;$('damage-output').value=pct(loss);$('damage-hint').textContent=`E = 200 → ${fmt(200*(1-loss),0)} GPa`;
 $('load-output').value=fmt(Number($('load').value)/100)+'×';
 $('sensor-count-output').value=$('sensor-count').value+' / '+$('sensor-count').max;
 for(const name of ['noise','missing','drift'])$(name+'-output').value=$(name).value+'%';
 $('damage-list').replaceChildren();
 state.damage.forEach((d,i)=>{if(d>0&&i!==id){const row=document.createElement('div');row.className='damage-chip';const label=document.createElement('span');label.textContent=`M${String(i+1).padStart(2,'0')} · ${pct(d)} loss`;const b=document.createElement('button');b.textContent='×';b.title='Clear damage';b.onclick=()=>{state.damage[i]=0;syncControls();markPending()};row.append(label,b);$('damage-list').append(row)}});
}
function markPending(){invalidateBridgePlayback();$('run-status').textContent='Scenario changed · run to update';$('run-status').style.color='#111111';$('workspace-status').textContent='Scenario edited · run to update'}
$('damage-member').onchange=()=>{state.selected=Number($('damage-member').value);syncControls();updateInspector();state.dirty=true};
$('damage').oninput=()=>{state.damage[Number($('damage-member').value)]=Number($('damage').value)/100;syncControls();markPending()};
for(const name of ['load','sensor-count','noise','missing','drift'])$(name).oninput=()=>{syncControls();markPending()};
$('physics').onchange=markPending;
const scenarioDialog=$('scenario-dialog');
$('open-scenario').onclick=()=>{pauseBridgePlayback();scenarioDialog.showModal()};
$('close-scenario').onclick=()=>scenarioDialog.close();
scenarioDialog.addEventListener('click',e=>{if(e.target!==scenarioDialog)return;const r=scenarioDialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)scenarioDialog.close()});
$('rerun').onclick=run;

$('refinement').onchange=markPending;
$('protocol').onchange=()=>{const single=$('protocol').value==='single';if(single)$('display-case').value='LC1';$('display-case').disabled=single;markPending()};
$('display-case').onchange=()=>{if(state.modelId==='bridge')$('bridge-case').value=$('display-case').value;markPending()};
$('damage-source').onchange=()=>{updateSceneStatus();state.dirty=true};
setInterval(()=>{if($('stream').checked&&!$('run').disabled){state.tick++;run()}},3000);
$('add-damage').onclick=()=>{const i=state.damage.findIndex((v,i)=>v===0&&i!==Number($('damage-member').value));if(i<0)return;state.damage[i]=.2;state.selected=i;$('damage-member').value=i;syncControls();updateInspector();markPending();state.dirty=true};
$('advanced-toggle').onclick=()=>{const hidden=$('advanced-options').hidden;$('advanced-options').hidden=!hidden;$('advanced-toggle').setAttribute('aria-expanded',String(hidden));$('advanced-toggle').lastElementChild.textContent=hidden?'−':'＋'};
for(const b of document.querySelectorAll('[data-view]'))b.onclick=()=>{if(b.dataset.view==='mode')pauseBridgePlayback();state.view=b.dataset.view;$('deformation-tools').hidden=!['deformation','mode'].includes(state.view);document.querySelectorAll('[data-view]').forEach(x=>x.classList.toggle('active',x===b));$('damage-source').disabled=state.view!=='damage';updateSceneStatus();$('deform-label').textContent=state.view==='mode'?'Mode 1 visual amplitude':'Deformation magnification';$('deform-output').value=state.view==='mode'?fmt(Number($('deform-scale').value)/250,1)+'×':$('deform-scale').value+'×';$('legend').innerHTML=state.view==='stress'?'<i style="background:#111111"></i>Compression <i style="background:#bbbbbb"></i>Low stress <i style="background:#666666"></i>Tension':state.view==='mode'?'<i style="background:#868686"></i>First mode · normalized visual amplitude':'<i style="background:#999999"></i>Healthy <i style="background:#555555"></i>Reduced stiffness <i style="background:#000000"></i>High stiffness loss';state.dirty=true};
for(const b of document.querySelectorAll('[data-signal]'))b.onclick=()=>{state.signal=b.dataset.signal;document.querySelectorAll('[data-signal]').forEach(x=>x.classList.toggle('active',x===b));drawSignal()};
for(const id of ['show-loads','show-sensors','deform-scale'])$(id).oninput=()=>{$('deform-output').value=state.view==='mode'?fmt(Number($('deform-scale').value)/250,1)+'×':$('deform-scale').value+'×';state.dirty=true};
$('home-view').onclick=resetCamera;
$('reset').onclick=()=>{state.damage.fill(0);state.selected=state.model.dimension===3?4:13;$('damage-member').value=state.selected;$('load').value=100;$('sensor-count').value=$('sensor-count').max;$('noise').value=.5;$('missing').value=0;$('drift').value=0;$('physics').checked=false;syncControls();run()};
$('run').onclick=run;
document.addEventListener('keydown',e=>{if(e.key==='Enter'&&!['BUTTON','SELECT'].includes(document.activeElement.tagName)&&!$('run').disabled)run()});
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const data=await r.json();if(!r.ok)throw Error(data.error||`HTTP ${r.status}`);return data}
function analysisRequest(){return {model_id:state.modelId,bridge:bridgeRequest(),bridge_ml:state.modelId==='bridge'?{sensor_count:Number($('bridge-ml-budget').value),placement:$('bridge-ml-placement').value}:undefined,damage:state.damage,load_scale:Number($('load').value)/100,sensor_count:Number($('sensor-count').value),noise:Number($('noise').value)/100,missing:Number($('missing').value)/100,drift:Number($('drift').value)/100,physics:$('physics').checked,refinement:$('refinement').value,seed:42+state.tick,protocol:$('protocol').value,display_case:$('display-case').value}}
async function run(){
 invalidateBridgePlayback();
 if(state.modelId==='bridge')syncBridgePosition();
 $('run').disabled=true;$('rerun').disabled=true;setBridgeBusy(true);$('model-select').disabled=true;$('workspace-status').textContent='Computing response…';$('run-status').textContent=state.model?.inference_supported?'Solving FEM & estimating damage…':'Solving 3D FEM & virtual sensing…';$('run-status').style.color='';$('error').hidden=true;
 const started=performance.now(),requestId=++state.requestId;
 try{const result=await api('/api/analyze',analysisRequest());if(requestId!==state.requestId)return;state.data=result;updateDashboard();if(scenarioDialog.open)scenarioDialog.close();$('workspace-status').textContent='Analysis updated · simulated measurements';$('run-status').textContent=`Analysis complete · ${fmt((performance.now()-started)/1000,2)} s${$('stream').checked?' · frame '+state.tick:''}`}
 catch(e){if(requestId!==state.requestId)return;$('error').textContent=e.message;$('error').hidden=false;$('run-status').textContent='Analysis failed · review the message above';$('workspace-status').textContent='Analysis needs attention'}
 finally{if(requestId===state.requestId){$('run').disabled=false;$('rerun').disabled=false;setBridgeBusy(false);$('model-select').disabled=false}}
}
function updateDashboard({live=false}={}){
 const d=state.data,s=d.summary;
 if(!live)$('displacement-context').textContent='Under applied static load';
 $('health').textContent=fmt(s.stiffness_index,1);$('health-meter').style.width=s.stiffness_index+'%';
 $('displacement').textContent=fmt(s.max_displacement_mm,2);$('frequency').textContent=fmt(d.modal.frequencies[0],2);
 $('frequency-shift').textContent=fmt(100*(d.modal.frequencies[0]/d.modal.baseline[0]-1),1)+'%';
 $('active-sensors').textContent=s.active_sensors;$('sensor-total').textContent='/ '+s.sensor_capacity;
 const ex=d.excitation;if(ex){$('measurement-foot').textContent=`${ex.case_count} loading test${ex.case_count>1?'s':''} · ${ex.active_observations} active observations`;$('excitation-info').textContent=`Local sensitivity rank ${ex.observability.rank}/${ex.observability.unknowns} · ${ex.active_observations} observations · ${ex.display_case} displayed`}
 updateSceneStatus();updateSupportReview();
 if(!live)$('modal-rows').innerHTML=d.modal.frequencies.slice(0,4).map((f,i)=>`<div class="modal-row"><span>φ${i+1} &nbsp; Mode ${i+1}</span><span>${fmt(d.modal.baseline[i])} Hz</span><span>${fmt(f)} Hz</span><span>${fmt(100*(f/d.modal.baseline[i]-1),1)}%</span></div>`).join('');
 $('signal-sensor').textContent=d.signal.sensor_id||'A03Y';$('signal-description').textContent=d.signal.label+' · independent of static display';updateInspector();if(!live){renderSensors();drawSignal()}updateBridgeResults();state.dirty=true;
}
function updateSupportReview(){
 const d=state.data,holder=$('support-review-rows');if(!d||!holder)return;
 holder.replaceChildren();
 for(const support of d.supports){
  const row=document.createElement('tr'),reaction=d.reactions[support.node];
  const free=support.free_axes||'XYZ'.slice(0,d.dimension).split('').filter(axis=>!support.axes.includes(axis));
  const values=['N'+String(support.node+1).padStart(2,'0'),support.axes.join(' / '),free.join(' / ')||'None',
   ...[0,1,2].map(i=>i<d.dimension?fmt(reaction[i]/1000,3):'—')];
  for(const value of values){const cell=document.createElement('td');cell.textContent=value;row.append(cell)}holder.append(row);
 }
 const total=Array(d.dimension).fill(0);for(const force of d.reactions)force.forEach((value,i)=>total[i]+=value);
 for(const load of d.loads)[load.fx,load.fy,load.fz||0].slice(0,d.dimension).forEach((value,i)=>total[i]+=value);
 $('support-review-status').textContent=d.playback?.method==='dynamic-moving-force'?
  'Current dynamic reactions. The bridge panel reports force balance including inertia and damping.':
  `Current static reaction + applied-load balance: ${fmt(Math.hypot(...total),6)} N. Reaction signs follow the global axes.`;
}
function visualLoss(m){const p=state.data.prediction;return $('damage-source').value==='estimated'?(p.available?p.severity[m.id]:0):m.damage}
function updateSceneStatus(){if(!state.data)return;if(state.view!=='damage'){$('scene-status').textContent='SIMULATED '+state.view.toUpperCase()+' · '+(state.data.excitation?.display_case||'LC1');return;}const estimated=$('damage-source').value==='estimated',p=state.data.prediction;const affected=state.data.members.filter(m=>visualLoss(m)>(estimated?.05:.001)).length;$('scene-status').textContent=estimated?(p.available?`ML ESTIMATE · ${affected} MEMBER${affected!==1?'S':''} ABOVE 5% LOSS`:'ML ESTIMATE UNAVAILABLE'):(affected?`${affected} DAMAGED MEMBER${affected!==1?'S':''} · CONFIGURED`:'HEALTHY CONFIGURATION')}
function updateInspector(){
 if(!state.data)return;
 const m=state.data.members[state.selected],p=state.data.prediction;
 $('member-name').textContent=m.name;$('member-type').textContent=m.kind||'Truss member';
 $('member-status').textContent=m.damage>.001?'REDUCED':'HEALTHY';$('member-status').classList.toggle('healthy',m.damage<=.001);
 $('member-length').textContent=fmt(m.length)+' m';$('member-e').textContent=fmt(m.effective_modulus/1e9,0)+' GPa';
 $('member-stress').textContent=fmt(m.stress/1e6,2)+' MPa';$('member-strain').textContent=fmt(m.strain*1e6,1)+' με';$('member-force').textContent=fmt(m.axial_force/1000,1)+' kN';
 $('stress-meter').style.width=Math.min(100,m.stress_ratio*100)+'%';$('stress-meter').style.background=m.stress_ratio>1?colors.red:colors.purple;
 $('ground-truth').textContent=pct(m.damage);updateBridgeMember();refreshBridgeReadout();
 $('pred-loss').textContent=p.available?pct(p.severity[m.id]):'—';$('pred-vote').textContent=p.available?pct(p.damage_vote[m.id]):'—';$('vote-meter').style.width=p.available?p.damage_vote[m.id]*100+'%':'0%';
 if(!p.available)$('prediction-note').textContent=p.reason;
 else if(p.physics?.reason)$('prediction-note').textContent=p.physics.reason;
 else if(p.physics?.method==='Noise-aware sparse physics')$('prediction-note').textContent=`Sparse physics · ≤2 damaged members · σ ${pct(p.physics.noise_std,1)} · estimated bias ${pct(p.physics.estimated_common_bias,2)}. Forest votes remain unrefined.`;
 else $('prediction-note').textContent=p.physics?`${p.physics.converged?'Converged':'Incomplete'} legacy fit · ${p.physics.locally_identifiable?'locally identifiable':'possibly non-unique'} · RF votes remain unrefined.`:`Random forest · ${state.data.excitation?.case_count||1} load case(s). Uncalibrated vote for loss ≥ 5%.`;
}
function renderSensors(){
 const holder=$('sensor-grid');holder.replaceChildren();
 for(const s of state.data.sensors){const el=document.createElement('article');el.className='sensor-card'+(s.active?'':' off');const title=document.createElement('h3');title.textContent=s.id+' · '+(s.active?'ONLINE':s.selected?'MISSING':'UNSELECTED');const value=document.createElement('strong');value.textContent=s.active?(s.kind==='strain'?fmt(s.value*1e6,2)+' με':fmt(s.value*1000,3)+' mm'):'No observation';const note=document.createElement('small');note.textContent=s.kind==='strain'?`Strain gauge · M${String(s.member+1).padStart(2,'0')}`:`Displacement · Node ${s.node+1} · ${'XYZ'[s.axis]}`;el.append(title,value,note);if(s.case_values?.length>1){const cases=document.createElement('small');cases.textContent=s.case_values.map((v,i)=>`LC${i+1}: ${v===null?'missing':s.kind==='strain'?fmt(v*1e6,1)+' με':fmt(v*1000,2)+' mm'}`).join(' · ');el.append(cases)}holder.append(el)}
}
$('export').onclick=()=>{if(!state.data)return;const url=URL.createObjectURL(new Blob([JSON.stringify(state.data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='stratum-analysis.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
for(const b of document.querySelectorAll('[data-tab]'))b.onclick=()=>{
 pauseBridgePlayback();if(b.dataset.tab==='sensors'&&state.data)renderSensors();
 const titles={twin:state.modelId==='bridge'?'Bridge observatory':'Structural observatory',sensors:'Sensor observatory',research:'Research findings',about:'Model & assumptions'};
 $('page-heading').textContent=titles[b.dataset.tab];
 document.querySelectorAll('.nav').forEach(x=>{x.classList.toggle('active',x===b);x.setAttribute('aria-pressed',String(x===b))});document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x.id==='tab-'+b.dataset.tab));state.dirty=true;if(b.dataset.tab==='research')loadResearch()};
async function loadResearch(){
 try{const [loads,robust]=await Promise.all([api('/api/study'),api('/api/robust-study')]);state.metrics=loads;state.robustMetrics=robust;renderResearch()}
 catch(e){$('research-results').textContent=e.message}
}
$('research-condition').onchange=renderResearch;
$('research-study').onchange=renderResearch;
function renderResearch(){if($('research-study').value==='robust')renderRobustResearch();else renderLoadResearch()}
function renderLoadResearch(){
 const r=state.metrics;if(!r?.experiments){$('research-results').textContent='Run python -m twin study, then restart the server.';return}
 const condition=$('research-condition').value, rows=r.experiments.filter(e=>e.condition===condition);
 const table=rows.map(e=>{const p=e.physics_comparison;return `<tr><td>${e.protocol==='multi'?'3 loads':'LC1 only'}</td><td>${e.sensor_count}</td><td>${e.nominal_observations}</td><td>${e.local_rank_before_dropout}/21</td><td>${pct(e.ml.exact_location_accuracy,1)}</td><td>${fmt(e.ml.damaged_severity_mae_pp,2)} pp</td><td>${pct(p.ml.exact_location_accuracy,1)} → ${pct(p.refined.exact_location_accuracy,1)}</td><td>${fmt(p.refined.damaged_severity_mae_pp,2)} pp</td><td>${p.optimizer_failures} / ${p.cases}</td></tr>`}).join('');
 const effects=r.paired_effects.filter(e=>e.condition===condition).map(e=>{const effect=e.refined_damaged_mae_reduction_pp;return `<tr><td>${e.sensor_count}</td><td>${fmt(effect.mean,2)} pp</td><td>${effect.ci95.map(v=>fmt(v,2)).join(' to ')} pp</td></tr>`}).join('');
 $('research-results').innerHTML=`<div class="research-stats"><div class="research-stat"><strong>17 → 21 / 21</strong><span>Full-array healthy sensitivity rank</span></div><div class="research-stat"><strong>${r.test_cases} / ${rows[0].physics_comparison.cases}</strong><span>Held-out ML / inverse-fit test cases per cell</span></div><div class="research-stat"><strong>1 → 3 loading tests</strong><span>Same sensors; three times the acquisitions</span></div></div><div class="info-note">Shared damage cases, physical sensor locations, LC1 noise draws and sensor failures. Missing physical sensors remain missing across all load cases. Full rank is local and does not guarantee noise robustness.</div><table><thead><tr><th>EXCITATION</th><th>SENSORS</th><th>READINGS</th><th>HEALTHY RANK</th><th>RF LOCATION · ${r.test_cases}</th><th>RF DAMAGE MAE</th><th>LOCATION RF → FIT · ${rows[0].physics_comparison.cases}</th><th>FIT DAMAGE MAE</th><th>FIT FAILURES</th></tr></thead><tbody>${table}</tbody></table><p>Location accuracy requires the entire predicted damage set to match. RF detection uses forest vote ≥ 0.5; fitted detection uses loss ≥ 5%. Severity MAE is measured on actually damaged members. All-missing cases abstain and are excluded from accuracy denominators. The saved report includes member F1, healthy false-alarm rates and abstention counts.</p><p class="study-warning">Physics fitting can improve severity while introducing false-positive damage under noise. Compare location and severity together. Failed optimizations remain included in reported errors; their counts appear above.</p><h3>Paired effect of three loads on refined severity</h3><table><thead><tr><th>PHYSICAL SENSORS</th><th>MAE REDUCTION · PER DAMAGED CASE</th><th>PAIRED BOOTSTRAP 95% INTERVAL</th></tr></thead><tbody>${effects}</tbody></table><p>Positive reductions favor three loads. Intervals resample paired held-out cases, with one training seed; they do not cover training-seed uncertainty. ${r.samples} independent FEM damage scenarios, ${r.train_cases} training cases; split before augmentation. Sensor order uses only healthy-model sensitivity. The single protocol uses the same placement as the combined protocol to isolate excitation effects. Known geometry, materials and load patterns; unchanged damage across the three loading tests. No hardware transfer validation.</p>`;
}
function renderRobustResearch(){
 const r=state.robustMetrics;if(!r?.experiments){$('research-results').textContent='Run python -m twin robust-study to select and audit a sparse refinement policy.';return}
 const condition=$('research-condition').value,rows=r.experiments.filter(e=>e.condition===condition&&e.noise_assumption_factor===1);
 const table=rows.map(e=>{const m=e.metrics;return `<tr><td>${e.protocol==='multi'?'3 loads':'LC1 only'}</td><td>${e.sensor_count}</td><td>${pct(m.rf.exact_location_accuracy,1)}</td><td>${pct(m.legacy.exact_location_accuracy,1)}</td><td class="highlight-value">${pct(m.sparse.exact_location_accuracy,1)}</td><td>${pct(m.legacy.healthy_false_alarm_rate,1)} → ${pct(m.sparse.healthy_false_alarm_rate,1)}</td><td>${fmt(m.legacy.damaged_severity_mae_pp,2)} → ${fmt(m.sparse.damaged_severity_mae_pp,2)} pp</td><td>${e.abstentions}</td></tr>`}).join('');
 const effects=rows.map(e=>{const effect=e.paired_location_gain_pp;return `<tr><td>${e.protocol==='multi'?'3 loads':'LC1 only'}</td><td>${e.sensor_count}</td><td>${fmt(effect.mean,1)} pp</td><td>${effect.ci95?.map(v=>fmt(v,1)).join(' to ')||'—'} pp</td></tr>`}).join('');
 const assumed=r.experiments.filter(e=>e.sensor_count===10&&e.condition==='noisy').sort((a,b)=>a.protocol.localeCompare(b.protocol)||a.noise_assumption_factor-b.noise_assumption_factor).map(e=>`<tr><td>${e.protocol==='multi'?'3 loads':'LC1 only'}</td><td>${pct(e.assumed_noise_std,1)}</td><td>${pct(e.metrics.sparse.exact_location_accuracy,1)}</td><td>${pct(e.metrics.sparse.healthy_false_alarm_rate,1)}</td><td>${fmt(e.metrics.sparse.damaged_severity_mae_pp,2)} pp</td></tr>`).join('');
 $('research-results').innerHTML=`<div class="research-stats"><div class="research-stat"><strong>${r.validation_cases} → ${r.test_cases}</strong><span>Fresh validation → untouched test cases</span></div><div class="research-stat"><strong>${r.selection.single.selected.penalty} / ${r.selection.multi.selected.penalty}</strong><span>Validation-selected penalty · 1 / 3 loads</span></div><div class="research-stat"><strong>Healthy + 1 + 2</strong><span>Restricted candidate damage models</span></div></div><div class="info-note">The penalty was frozen before generating fresh test data. All three methods use the same observations and pretrained forests. Sparse fitting uses the declared noise σ and estimates a common normalized offset; it never receives the actual drift or damage.</div><table><thead><tr><th>EXCITATION</th><th>SENSORS</th><th>RF LOCATION</th><th>LEGACY FIT LOCATION</th><th>SPARSE LOCATION</th><th>HEALTHY ALARMS · OLD → NEW</th><th>DAMAGED MAE · OLD → NEW</th><th>ABSTAIN</th></tr></thead><tbody>${table}</tbody></table><p>All cells use the same ${r.test_cases} independent fresh test cases. Accuracy requires the entire damage set to match; healthy false alarms mean any detected damage in an actually healthy case. All-missing packets abstain and are excluded from conditional accuracy. RF uses vote ≥0.5; both inverse methods use severity ≥5%. The raw report also includes member F1, per-case metrics, and discarded or failed fits.</p><p class="study-warning">This method assumes at most two damaged members, known Gaussian noise σ, and one shared normalized sensor offset. Pairs are searched within the six best single-member fits, not every possible pair. Smaller false-alarm rates can come with missed damage. These same-model synthetic tests do not validate hardware transfer, other drift patterns, or training-seed uncertainty.</p><h3>Paired location improvement over the legacy fit</h3><table><thead><tr><th>EXCITATION</th><th>SENSORS</th><th>ACCURACY GAIN</th><th>PAIRED 95% INTERVAL</th></tr></thead><tbody>${effects}</tbody></table><h3>Sensitivity to declared noise · 10 sensors</h3><p>True noise is 1%, with 10% persistent sensor dropout. Under- and over-stated σ were audited after freezing the policy.</p><table><thead><tr><th>EXCITATION</th><th>DECLARED NOISE σ</th><th>SPARSE LOCATION</th><th>HEALTHY FALSE ALARMS</th><th>DAMAGED MAE</th></tr></thead><tbody>${assumed}</tbody></table><p>Validation seed ${r.validation_seed}; fresh test seed ${r.test_seed}; fixed forest training seed ${r.forest_training_seed}. Penalty selection maximized validation location accuracy subject to a 5% mean healthy-alarm target across all budgets and conditions. The constraint is a validation target, not a guaranteed test false-alarm bound. Case-bootstrap intervals do not cover model selection or forest-training variability.</p>`;
}
$('refresh-telemetry').onclick=async()=>{try{const p=await api('/api/telemetry');const el=$('telemetry-status');if(!p.received_at){el.textContent='No external observations received. Send calibrated channels to POST /api/observations.';return}el.replaceChildren();const line=document.createElement('div');line.textContent=`Latest external packet · ${p.active_sensors} channels · ${new Date(p.received_at).toLocaleString()} · known load ${p.load_scale}×`;el.append(line);if(p.prediction.physics?.method==='Noise-aware sparse physics'){const assumptions=document.createElement('div');assumptions.textContent=`Sparse physics · ${p.prediction.physics.noise_source} · up to 2 damaged members`;el.append(assumptions)}if(p.prediction.available){p.prediction.severity.forEach((v,i)=>{if(v>=.05){const detail=document.createElement('div');detail.textContent=`M${String(i+1).padStart(2,'0')}: estimated loss ${pct(v,1)}, forest vote ${pct(p.prediction.damage_vote[i],1)}`;el.append(detail)}})}else{const detail=document.createElement('div');detail.textContent=p.prediction.reason;el.append(detail)}}catch(e){$('telemetry-status').textContent=e.message}};
function project(x,y,z=0){
 const center=state.model?.center||[12,2,0];x-=center[0];y-=center[1];z-=center[2];
 const ca=Math.cos(state.yaw),sa=Math.sin(state.yaw),cp=Math.cos(state.pitch),sp=Math.sin(state.pitch);
 const rx=ca*x+sa*z,rz=-sa*x+ca*z,ry=cp*y-sp*rz,depth=sp*y+cp*rz;
 const extent=state.model?.extent||[24,4,0];const scale=Math.min(width/(extent[0]+7),height/(Math.max(extent[1],extent[2])+8))*state.zoom;
 return {x:width/2+state.panX+rx*scale,y:height*.5+state.panY-ry*scale,z:depth};
}
function line(a,b,color,lw=1,dash=[]){ctx.beginPath();ctx.setLineDash(dash);ctx.strokeStyle=color;ctx.lineWidth=lw;ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();ctx.setLineDash([])}
function circle(p,r,color,stroke){ctx.beginPath();ctx.arc(p.x,p.y,r,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=1;ctx.stroke()}}
function label(text,p,color='#8f8f8f',font='9px Arial'){ctx.font=font;ctx.fillStyle='#111111';ctx.textAlign='center';ctx.fillText(text,p.x,p.y)}
function memberColor(m){
 if(state.view==='damage'&&$('damage-source').value==='estimated'&&!state.data.prediction.available)return '#a4a4a4';
 if(state.view==='stress'){const strength=Math.min(1,Math.abs(m.stress)/Math.max(1,...state.data.members.map(x=>Math.abs(x.stress))));return m.stress<0?blend('#bbbbbb','#111111',strength):blend('#bbbbbb','#666666',strength)}
 if(state.view==='mode')return '#868686';
 const loss=visualLoss(m),threshold=$('damage-source').value==='estimated'?.05:.001;
 return loss>.5?colors.red:loss>threshold?colors.amber:'#999999';
}
function blend(a,b,t){const x=parseInt(a.slice(1),16),y=parseInt(b.slice(1),16);return '#'+[16,8,0].map(s=>Math.round(((x>>s)&255)*(1-t)+((y>>s)&255)*t).toString(16).padStart(2,'0')).join('')}
function drawScene(t){
 ctx.clearRect(0,0,width,height);
 const gradient=ctx.createRadialGradient(width*.5,height*.42,10,width*.5,height*.42,width*.8);
 gradient.addColorStop(0,'#ffffff');gradient.addColorStop(1,'#f3f3f3');ctx.fillStyle=gradient;ctx.fillRect(0,0,width,height);
 for(let x=-12;x<=36;x+=2)line(project(x,-.8,-12),project(x,-.8,12),'#aeaeae25',.65);
 for(let z=-12;z<=12;z+=2)line(project(-12,-.8,z),project(36,-.8,z),'#aeaeae25',.65);
 if(!state.data){label('Preparing structural model…',{x:width/2,y:height/2},'#898989','11px Arial');return}
 const data=state.data,amp=Number($('deform-scale').value);
 const locations=data.nodes.map((n,i)=>{let x=n.x,y=n.y,z=n.z;if(state.view==='deformation'){x+=n.ux*amp;y+=n.uy*amp;z+=n.uz*amp}if(state.view==='mode'){const shape=data.modal.shapes[0],normal=Math.max(...shape.flat().map(Math.abs)),a=Math.sin(t/450)*amp/250*.65;x+=shape[i][0]/normal*a;y+=shape[i][1]/normal*a;z+=(shape[i][2]||0)/normal*a}return [x,y,z]});const points=locations.map(p=>project(...p));
 const original=data.nodes.map(n=>project(n.x,n.y,n.z));if(data.bridge)drawBridgeBase();
 if(state.view==='mode'||(state.view==='deformation'&&!(bridgeComparisonVisible()&&$('bridge-healthy-outline').checked)))for(const m of data.members)line(original[m.a],original[m.b],'#96969655',1,[3,4]);
 const dl=project(0,-1.9),dr=project(24,-1.9);line(dl,dr,'#ababab',.7);line({x:dl.x,y:dl.y-3},{x:dl.x,y:dl.y+3},'#9c9c9c');line({x:dr.x,y:dr.y-3},{x:dr.x,y:dr.y+3},'#9c9c9c');label('24.00 m',{x:(dl.x+dr.x)/2,y:(dl.y+dr.y)/2+14},'#8f8f8f','9px Arial');
 segments=[];const ordered=[...data.members].sort((a,b)=>(points[a.a].z+points[a.b].z)-(points[b.a].z+points[b.b].z));ctx.lineCap='round';
 for(const m of ordered){
  const a=points[m.a],b=points[m.b],selected=m.id===state.selected,color=memberColor(m);
  if(selected)line(a,b,color+'20',12);
  line(a,b,'#dadada',6);line(a,b,color,selected?4.7:3.1);line({x:a.x,y:a.y-.7},{x:b.x,y:b.y-.7},'#ffffff65',.8);
  segments.push({a,b,id:m.id});
  if(selected||visualLoss(m)>.05){const p={x:(a.x+b.x)/2,y:(a.y+b.y)/2-12},text=m.name+(visualLoss(m)>.05?' · −'+pct(visualLoss(m)):'');ctx.font='9px Arial';const tw=ctx.measureText(text).width;ctx.fillStyle='#fefefeee';ctx.fillRect(p.x-tw/2-6,p.y-10,tw+12,16);label(text,p,selected?'#707070':'#7f7f7f','9px Arial')}
 }
 if(data.bridge)drawBridgeFurniture(locations);
 if(data.bridge)drawHealthyBridgeOutline();
 for(let i=0;i<points.length;i++){circle(points[i],3.4,'#fafafa','#929292');circle(points[i],1,'#8d8d8d');if(!data.bridge||[0,1,16,17,data.members[state.selected].a,data.members[state.selected].b].includes(i))label('N'+String(i+1).padStart(2,'0'),{x:points[i].x+11,y:points[i].y+14},'#8d8d8d','8px Arial')}
 for(const support of data.supports){const p=original[support.node];ctx.beginPath();ctx.moveTo(p.x,p.y+4);ctx.lineTo(p.x-10,p.y+20);ctx.lineTo(p.x+10,p.y+20);ctx.closePath();ctx.fillStyle='#e1e1e1';ctx.fill();ctx.strokeStyle='#909090';ctx.lineWidth=1;ctx.stroke();if(support.type==='roller'){circle({x:p.x-5,y:p.y+24},2.5,'#f9f9f9','#909090');circle({x:p.x+5,y:p.y+24},2.5,'#f9f9f9','#909090')}line({x:p.x-14,y:p.y+29},{x:p.x+14,y:p.y+29},'#909090',1);label(support.axes.join('/')+' locked',{x:p.x,y:p.y+42},'#111111','9px Arial')}
 if($('show-loads').checked)for(const load of data.loads){const p=points[load.node],n=data.nodes[load.node],magnitude=Math.hypot(load.fx,load.fy,load.fz||0),q=project(n.x+load.fx/magnitude*2,n.y+load.fy/magnitude*2,n.z+(load.fz||0)/magnitude*2),base=original[load.node],dx=q.x-base.x,dy=q.y-base.y,norm=Math.hypot(dx,dy)||1,ux=dx/norm,uy=dy/norm,maximum=Math.max(...data.loads.map(f=>Math.hypot(f.fx,f.fy,f.fz||0))),arrow=data.bridge?12+32*Math.sqrt(magnitude/maximum):44,end={x:p.x+ux*arrow,y:p.y+uy*arrow};line({x:p.x+ux*9,y:p.y+uy*9},end,'#8d8d8d',1.3);line({x:end.x-ux*7-uy*4,y:end.y-uy*7+ux*4},end,'#8d8d8d',1.3);line({x:end.x-ux*7+uy*4,y:end.y-uy*7-ux*4},end,'#8d8d8d',1.3);if(!data.bridge||magnitude>=maximum*.6)label(fmt(magnitude/1000,Number.isInteger(magnitude/1000)?0:1)+' kN',{x:end.x+ux*12,y:end.y+uy*12+4},'#818181','9px Arial')}
 const mlIndices=data.playback?.ml_layout?.sensor_indices;const displayedSensors=mlIndices?mlIndices.map(i=>data.sensors[i]):data.sensors;
 if($('show-sensors').checked)for(const s of displayedSensors){if(!mlIndices&&!s.active)continue;let p;if(s.kind==='strain'){const m=data.members[s.member];p={x:(points[m.a].x+points[m.b].x)/2,y:(points[m.a].y+points[m.b].y)/2}}else{const n=points[s.node];p={x:n.x+(s.axis?0:7),y:n.y+(s.axis?-8:0)}}circle(p,3,'#f3f3f3','#8e8e8e');circle(p,1,'#8e8e8e')}
 const origin=project(...(state.model?.center||[12,2,0])),base={x:31,y:height-44};
 for(const [i,axis,color] of [[0,'X','#737373'],[1,'Y','#727272'],[2,'Z','#797979']]){if(i===2&&data.dimension!==3)continue;const point=[...(state.model?.center||[12,2,0])];point[i]+=1;const q=project(...point),norm=Math.hypot(q.x-origin.x,q.y-origin.y)||1;const end={x:base.x+24*(q.x-origin.x)/norm,y:base.y+24*(q.y-origin.y)/norm};line(base,end,color,1.2);label(axis,{x:end.x,y:end.y-4},color,'9px Arial')}
 ctx.lineCap='butt';
}
function drawSignal(){
 chartCtx.clearRect(0,0,chartWidth,chartHeight);if(!state.data||chartWidth<10)return;
 const s=state.data.signal,frequency=state.signal==='frequency',xs=frequency?s.frequency:s.time,ys=frequency?s.spectrum:s.acceleration;
 const left=47,right=18,top=25,bottom=25,w=chartWidth-left-right,h=chartHeight-top-bottom;
 let low=frequency?0:Math.min(...ys)*1.15,high=Math.max(...ys)*1.15;if(high-low<1e-8)high=low+1;
 chartCtx.font='9px Arial';chartCtx.lineWidth=.5;
 for(let i=0;i<4;i++){const y=top+h*i/3;chartCtx.strokeStyle='#e1e1e1';chartCtx.setLineDash([2,4]);chartCtx.beginPath();chartCtx.moveTo(left,y);chartCtx.lineTo(left+w,y);chartCtx.stroke();chartCtx.textAlign='right';chartCtx.fillStyle='#444444';chartCtx.fillText(fmt(high-(high-low)*i/3,frequency?0:2),left-9,y+3)}
 chartCtx.setLineDash([]);chartCtx.fillStyle='#444444';chartCtx.textAlign='left';chartCtx.fillText(frequency?'FFT AMPLITUDE (UNNORMALIZED)':'ACCELERATION (m/s²)',left,11);
 for(let i=0;i<6;i++){const x=left+w*i/5;chartCtx.textAlign='center';chartCtx.fillText(fmt(xs.at(-1)*i/5,1)+(i===5?(frequency?' Hz':' s'):''),x,chartHeight-7)}
 const path=new Path2D();ys.forEach((y,i)=>{const px=left+xs[i]/xs.at(-1)*w,py=top+(high-y)/(high-low)*h;i?path.lineTo(px,py):path.moveTo(px,py)});
 const color=frequency?plotColors.spectrum:plotColors.signal;
 chartCtx.strokeStyle=color;chartCtx.lineWidth=1.6;chartCtx.stroke(path);
 const fill=new Path2D(path);fill.lineTo(left+w,top+h);fill.lineTo(left,top+h);fill.closePath();const gradient=chartCtx.createLinearGradient(0,top,0,top+h);gradient.addColorStop(0,color+'22');gradient.addColorStop(1,color+'00');chartCtx.fillStyle=gradient;chartCtx.fill(fill);
}
function distance(p,a,b){const dx=b.x-a.x,dy=b.y-a.y,t=Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.y-a.y)*dy)/(dx*dx+dy*dy||1)));return Math.hypot(p.x-a.x-t*dx,p.y-a.y-t*dy)}
function pick(e){const r=canvas.getBoundingClientRect(),p={x:e.clientX-r.left,y:e.clientY-r.top};let best=null,min=11;for(const s of segments){const d=distance(p,s.a,s.b);if(d<=min){min=d;best=s}}return {best,p}}
canvas.onpointerdown=e=>{drag={x:e.clientX,y:e.clientY,shift:e.shiftKey};moved=false;canvas.setPointerCapture(e.pointerId)};
canvas.onpointermove=e=>{if(drag){const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>1)moved=true;if(drag.shift){state.panX+=dx;state.panY+=dy}else{state.yaw+=dx*.006;state.pitch=Math.max(-1,Math.min(1,state.pitch+dy*.005))}drag.x=e.clientX;drag.y=e.clientY;state.dirty=true;$('tooltip').hidden=true}else{const {best,p}=pick(e);canvas.style.cursor=best?'pointer':'grab';$('tooltip').hidden=!best;if(best){$('tooltip').textContent=state.data.members[best.id].name+' · Click to inspect';$('tooltip').style.left=Math.min(width-140,p.x+12)+'px';$('tooltip').style.top=Math.max(0,p.y-30)+'px'}}};
canvas.onpointerup=e=>{if(!moved){const {best}=pick(e);if(best){state.selected=best.id;$('damage-member').value=best.id;syncControls();updateInspector();state.dirty=true}}drag=null};
canvas.onpointercancel=()=>drag=null;canvas.onpointerleave=()=>{$('tooltip').hidden=true};canvas.onwheel=e=>{e.preventDefault();state.zoom=Math.max(.4,Math.min(3,state.zoom*Math.exp(-e.deltaY*.001)));state.dirty=true};
function frame(t){updateBridgePlayback(t);if(state.dirty||state.view==='mode'){drawScene(t);state.dirty=false}requestAnimationFrame(frame)}
initializeBridgeUI();requestAnimationFrame(frame);initialize();

// The hosted simulation profile intentionally has no shared physical sensor feed.
api('/api/health').then(info=>{
 if(info.mode!=='public-demo')return;
 document.querySelector('.pill').textContent='PUBLIC RESEARCH DEMO';
 $('deployment-label').textContent='SI UNITS · PUBLIC SIMULATION';
 $('refresh-telemetry').disabled=true;
 $('telemetry-status').textContent='This public demo uses simulated measurements. External sensor uploads and shared telemetry are disabled; use the local server for hardware integration.';
}).catch(()=>{});
