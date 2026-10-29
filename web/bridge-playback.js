/* Prepared static or time-integrated moving-force FEM responses. */
const bridgePlayback={frames:null,playing:false,pending:false,complete:false,generation:0,
 position:0,lastTime:null,lastReadout:0,sensorOffsets:[],busy:false,healthyDisplacement:null,completedCrossings:0};
function initializeBridgePlayback(){
 initializeBridgeHistory();
 initializeBridgeComparison();
 initializeBridgeML();
 $('bridge-method').onchange=markPending;
 for(const id of ['bridge-vehicle-speed','bridge-damping'])$(id).oninput=markPending;
 $('bridge-play').onclick=()=>bridgePlayback.playing?pauseBridgePlayback():startBridgePlayback();
 $('bridge-restart').onclick=()=>{
  pauseBridgePlayback();bridgePlayback.complete=false;bridgePlayback.completedCrossings=0;
  $('bridge-position').value=0;$('bridge-case').value=$('display-case').value='LC2';
  if(bridgePlayback.frames)applyBridgePlaybackFrame(0,true);
  else{syncBridgePosition();markPending();run()}
  updateBridgeTransport();
 };
 document.addEventListener('visibilitychange',()=>{if(document.hidden)pauseBridgePlayback()});
}
function updateBridgeTransport(){
 const bridge=state.modelId==='bridge',p=bridgePlayback;
 $('bridge-playback').hidden=$('bridge-live-readout').hidden=!bridge;
 $('bridge-play').disabled=$('bridge-restart').disabled=!bridge||p.pending||p.busy||!state.data?.bridge;
 $('bridge-play').textContent=p.playing?'Pause':p.frames&&!p.complete?'Resume':'Play crossing';
 $('bridge-play').setAttribute('aria-pressed',String(p.playing));
 const method=p.frames?.method||$('bridge-method').value,label=method==='dynamic-moving-force'?'dynamic':'quasi-static';
 $('bridge-playback-status').textContent=p.pending?'Preparing crossing…':p.playing?'Playing · '+label:p.complete?'Crossing complete':p.frames?'Paused · '+label:'Ready · '+label;
 for(const id of ['bridge-method','bridge-vehicle-speed','bridge-damping','bridge-ml-budget','bridge-ml-placement'])$(id).disabled=p.pending||p.busy;
 $('bridge-vehicle-speed').parentElement.hidden=$('bridge-damping').parentElement.hidden=method!=='dynamic-moving-force';
 for(const id of ['bridge-ml-budget','bridge-ml-placement'])$(id).parentElement.hidden=method!=='dynamic-moving-force';
 $('bridge-comparison-tools').hidden=!bridge||method!=='dynamic-moving-force';
 for(const id of ['bridge-damage-example','bridge-clear-damage'])$(id).disabled=p.pending||p.busy||!state.data?.bridge;
}
function setBridgePlaybackBusy(busy){bridgePlayback.busy=busy;updateBridgeTransport()}
function invalidateBridgePlayback(){
 const p=bridgePlayback,wasPending=p.pending;p.generation++;p.frames=null;p.playing=p.pending=p.complete=false;p.lastTime=null;
 $('bridge-history').hidden=true;
 p.completedCrossings=0;resetBridgeML();
 p.healthyDisplacement=null;$('bridge-comparison-status').textContent='Prepare a crossing to compare configured loss';
 if(wasPending&&!$('run').disabled)setBridgeBusy(false);
 updateBridgeTransport();
}
function pauseBridgePlayback(){
 if(bridgePlayback.pending){invalidateBridgePlayback();return}
 bridgePlayback.playing=false;bridgePlayback.lastTime=null;
 if(bridgePlayback.frames){applyBridgePlaybackFrame(bridgePlayback.position,true);$('workspace-status').textContent='Paused · moving load'}
 updateBridgeTransport();
}
async function startBridgePlayback(){
 const p=bridgePlayback;if(state.modelId!=='bridge'||p.pending||$('run').disabled)return;
 if(!p.frames){
  // Commit edited parameters and choose the actual vehicle load case first.
  $('bridge-case').value=$('display-case').value='LC2';$('stream').checked=false;
  await run();if(state.modelId!=='bridge'||!$('error').hidden||!state.data?.bridge)return;
  const generation=p.generation;p.pending=true;setBridgeBusy(true);updateBridgeTransport();
  try{
   const request={...analysisRequest(),method:$('bridge-method').value,dynamic:{speed_kmh:Number($('bridge-vehicle-speed').value),damping_ratio:Number($('bridge-damping').value)/100}};
   const frames=await api('/api/bridge-playback',request);
   if(generation!==p.generation)return;
   p.frames=frames;p.position=0;p.complete=false;
   prepareBridgeHistory(frames);
   refreshBridgeComparison();
   $('bridge-playback-note').textContent=frames.method==='dynamic-moving-force'?`${fmt(frames.speed_kmh,0)} km/h · ${fmt(frames.crossing_time_s,2)} s crossing + 2 s vibration tail · ${fmt(frames.damping_ratio*100,1)}% damping at first two modes`:'Quasi-static · 1× = 12 s per crossing';
   p.sensorOffsets=state.data.sensors.map(s=>{
    const clean=s.kind==='strain'?state.data.members[s.member].strain:state.data.nodes[s.node][['ux','uy','uz'][s.axis]];
    return s.active?s.value-clean:0;
   });
  }catch(e){if(generation===p.generation){$('error').textContent='Could not prepare moving-load playback: '+e.message;$('error').hidden=false}}
  finally{if(generation===p.generation){p.pending=false;setBridgeBusy(false)}}
 }
 if(!p.frames)return;
 if(p.complete||p.position>=p.frames.positions_m.at(-1)){p.position=0;p.completedCrossings=0}
 if(state.view==='damage'||state.view==='mode')document.querySelector('[data-view="deformation"]').click();
 p.playing=true;p.complete=false;p.lastTime=null;
 applyBridgePlaybackFrame(p.position,true);updateBridgeTransport();
 $('workspace-status').textContent='Playing · '+(p.frames.method==='dynamic-moving-force'?'dynamic moving-force response':'quasi-static moving load');
}
function seekBridgePlayback(position){
 if(!bridgePlayback.frames)return false;
 pauseBridgePlayback();bridgePlayback.complete=false;applyBridgePlaybackFrame(position,true);updateBridgeTransport();return true;
}
function updateBridgePlayback(time){
 const p=bridgePlayback;if(!p.playing||!p.frames)return;
 const end=p.frames.positions_m.at(-1),speed=Number($('bridge-speed').value);
 const dt=p.lastTime===null?0:Math.min(.1,Math.max(0,(time-p.lastTime)/1000));p.lastTime=time;
 let position=p.position+dt*(p.frames.method==='dynamic-moving-force'?p.frames.speed_kmh/3.6:end/12)*speed;
 if(position>=end){
  p.completedCrossings++;
  if($('bridge-loop').checked)position%=end;
  else{position=end;p.playing=false;p.complete=true;p.lastTime=null;updateBridgeTransport();$('workspace-status').textContent='Moving-load crossing complete'}
 }
 applyBridgePlaybackFrame(position,!p.playing||time-p.lastReadout>=100);
 if(time-p.lastReadout>=100)p.lastReadout=time;
}
function applyBridgePlaybackFrame(position,readouts=false){
 const p=bridgePlayback,d=state.data;if(!p.frames||!d?.bridge)return;
 const f=BridgeResponse.sample(p.frames,position),b=d.bridge;p.position=f.position_m;
 d.source='simulated-playback';
 const dynamic=p.frames.method==='dynamic-moving-force';
 d.playback={method:p.frames.method,front_position_m:f.position_m,time_s:f.time_s,
  speed_kmh:dynamic?p.frames.speed_kmh:null,integration:dynamic?p.frames.integration:null,
  clean_sensor_history:dynamic?p.frames.signal:null,
  healthy_sensor_history:dynamic?p.frames.healthy_signal:null,comparison:dynamic?p.frames.comparison:null,
  bridge_ml:dynamic&&((p.completedCrossings>0)||f.position_m>=p.frames.positions_m.at(-1))?p.frames.ml:{available:false,reason:'Complete the crossing before reading the bridge ML estimate.'},
  ml_layout:dynamic&&p.frames.ml?.sensor_indices?{sensor_count:p.frames.ml.sensor_count,placement:p.frames.ml.placement,sensor_indices:p.frames.ml.sensor_indices}:null,
  sensor_error_model:'Configured masks and initial measurement offsets held fixed across this crossing. History plots show clean FEM channels.',assumptions:p.frames.note};
 d.nodes.forEach((n,i)=>{[n.ux,n.uy,n.uz]=f.displacement[i]});
 p.healthyDisplacement=dynamic?f.healthy_displacement:null;
 d.members.forEach((m,i)=>{m.strain=f.strain[i];m.stress=f.stress[i];m.axial_force=f.axial_force[i];m.stress_ratio=Math.abs(m.stress)/250e6});
 d.reactions=f.reactions;
 d.loads=f.forces.flatMap((force,node)=>force.some(v=>Math.abs(v)>1e-9)?[{node,fx:force[0],fy:force[1],fz:force[2]}]:[]);
 Object.assign(d.summary,{max_displacement_mm:f.max_displacement_mm,max_stress_mpa:f.max_stress_mpa,strain_energy_j:f.strain_energy_j});
 b.settings.vehicle_position_m=f.position_m;
 Object.assign(b.vehicle,{front_x:f.position_m,rear_x:f.position_m-p.frames.settings.axle_spacing_m,on_bridge_kn:f.live_load_kn,visible:f.position_m<=24+p.frames.settings.axle_spacing_m});
 for(const key of ['deck_down_mm','healthy_deck_down_mm','change_from_healthy_pct','left_reaction_kn','right_reaction_kn','applied_vertical_kn','vertical_balance_error_kn'])b.current[key]=f[key];
 b.current.dynamic_vertical_kn=f.dynamic_vertical_kn;
 b.supports.forEach(s=>{s.reaction_kn=f.reactions[s.node].map(v=>v/1000)});
 d.sensors.forEach((s,i)=>{
  if(!s.active)return;
  s.value=(s.kind==='strain'?f.strain[s.member]:f.displacement[s.node][s.axis])+p.sensorOffsets[i];
  if(s.case_values?.length>1)s.case_values[1]=s.value;
 });
 d.excitation.display_case='LC2';b.load_case='LC2';
 d.excitation.observability={available:false,rank:null,unknowns:d.members.length,condition_number:null,
  full_column_rank:null,singular_values:[],note:'Sensitivity is not recomputed between playback frames. Run a stationary analysis to calculate it.'};
 $('bridge-position').value=f.position_m;syncBridgePosition();
 $('bridge-position-output').value=f.position_m>24+p.frames.settings.axle_spacing_m?'Vehicle exited':fmt(f.position_m,2)+' m';
 if(readouts){
  updateDashboard({live:true});
  if(dynamic&&p.frames.ml?.sensor_count){$('active-sensors').textContent=p.frames.ml.sensor_count;$('measurement-foot').textContent=`ML crossing · ${p.frames.ml.sensor_count} channels × 20 phase samples`}
  $('displacement-context').textContent=dynamic?'Instantaneous dynamic response':'Under applied static load';
  updateBridgeHistory(f.time_s);
  updateBridgeML();
  $('excitation-info').textContent='Moving-load playback · sensitivity not recomputed between frames';
  $('telemetry-status').textContent='Simulated '+(dynamic?'dynamic':'quasi-static')+' moving-load playback: the grid shows the virtual field with stationary masks and initial offsets. '+(dynamic&&p.frames.ml?.sensor_count?`ML separately uses ${p.frames.ml.sensor_count} selected channels at 20 phase times; its layout is listed in the ML panel.`:'Run analysis for a fresh measurement packet.');
 }
 state.dirty=true;
}
function refreshBridgeReadout(){
 const b=state.data?.bridge;if(!b)return;
 $('bridge-live-x').textContent=b.vehicle.front_x>24+b.settings.axle_spacing_m?'Exited':fmt(b.vehicle.front_x,2)+' m';
 $('bridge-live-deflection').textContent=fmt(b.current.deck_down_mm,2)+' mm';
 $('bridge-live-reactions').textContent=fmt(b.current.left_reaction_kn,1)+' / '+fmt(b.current.right_reaction_kn,1)+' kN';
 const member=state.data.members[state.selected];$('bridge-live-member-label').textContent=member.name+' stress';$('bridge-live-stress').textContent=fmt(member.stress/1e6,2)+' MPa';$('bridge-live-force').textContent=fmt(member.axial_force/1000,1)+' kN';
}
