/* Healthy reference and configured-loss comparison; no damage inference. */
function bridgeComparisonVisible(){return bridgePlayback.frames?.method==='dynamic-moving-force'&&$('bridge-compare').checked}
function initializeBridgeComparison(){
 $('bridge-compare').onchange=()=>{refreshBridgeComparison();const f=bridgePlayback.frames;if(f?.method==='dynamic-moving-force')updateBridgeHistory(bridgePlayback.position/(f.speed_kmh/3.6));state.dirty=true};
 $('bridge-healthy-outline').onchange=()=>{state.dirty=true};
 async function applyDamageExample(loss){
  if(bridgePlayback.busy||bridgePlayback.pending||state.modelId!=='bridge')return;
  state.damage.fill(0);state.damage[4]=loss;state.selected=4;$('damage-member').value=4;
  $('bridge-method').value='dynamic-moving-force';$('bridge-compare').checked=true;
  syncControls();markPending();await startBridgePlayback();
 }
 $('bridge-damage-example').onclick=()=>applyDamageExample(.4);
 $('bridge-clear-damage').onclick=()=>applyDamageExample(0);
}
function refreshBridgeComparison(){
 const frames=bridgePlayback.frames,visible=bridgeComparisonVisible();
 $('bridge-healthy-outline').disabled=!$('bridge-compare').checked;
 $('bridge-comparison-report').hidden=$('bridge-comparison-legend').hidden=!visible;
 if(!frames?.comparison)return;
 const comparison=frames.comparison,damaged=comparison.damaged_members;
 $('bridge-comparison-status').textContent=damaged.length?`${damaged.length} member${damaged.length===1?'':'s'} with configured loss · same crossing`:'Both bridges healthy · responses coincide';
 $('bridge-damage-summary').textContent=damaged.length?'Configured stiffness loss · '+damaged.map(m=>`${m.name} ${pct(m.stiffness_loss)}`).join(', '):'Zero configured damage · coincident traces';
 const rows=$('bridge-comparison-rows');rows.replaceChildren();
 for(const measure of comparison.rows){
  const row=document.createElement('tr'),digits=measure.unit==='Hz'?3:measure.unit==='m/s²'?4:3;
  const change=measure.change_pct===null?'— (zero baseline)':(Math.abs(measure.change_pct)<.005?'0.00':(measure.change_pct>0?'+':'')+fmt(measure.change_pct,2))+'%';
  for(const text of [measure.label,fmt(measure.healthy,digits)+' '+measure.unit,fmt(measure.current,digits)+' '+measure.unit,change]){const cell=document.createElement('td');cell.textContent=text;row.append(cell)}
  rows.append(row);
 }
 const members=$('bridge-comparison-members');members.replaceChildren();
 for(const member of damaged){
  const button=document.createElement('button');button.className='secondary';button.textContent=member.name+' · '+pct(member.stiffness_loss)+' stiffness loss';
  button.onclick=()=>{state.selected=member.id;$('damage-member').value=member.id;syncControls();updateInspector();state.dirty=true};members.append(button);
 }
 $('bridge-comparison-note').textContent='Peaks use |response| over the full crossing + 2 s tail and include dead-load offsets. N09Y and M05 are fixed channels, not global bridge maxima. Damping targets the same ratio at modes 1–2 of each state. Configured loss is simulation input; this comparison is not damage detection.';
}
function drawHealthyBridgeOutline(){
 if(!bridgeComparisonVisible()||!$('bridge-healthy-outline').checked||state.view!=='deformation'||!bridgePlayback.healthyDisplacement)return;
 const amp=Number($('deform-scale').value),points=state.data.nodes.map((n,i)=>{
  const u=bridgePlayback.healthyDisplacement[i];return project(n.x+u[0]*amp,n.y+u[1]*amp,n.z+u[2]*amp);
 });
 for(const member of state.data.members)line(points[member.a],points[member.b],'#838383aa',1.4,[4,4]);
}
