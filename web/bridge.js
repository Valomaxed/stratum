/* Bridge controls and drawing helpers. Numerical results come from Python. */
const bridgeFields={
 'bridge-front':['front_axle_kn',80], 'bridge-rear':['rear_axle_kn',120],
 'bridge-spacing':['axle_spacing_m',4], 'bridge-lane':['lane_offset_m',0],
 'bridge-deck':['deck_load_kn_m',10], 'bridge-wind':['wind_total_kn',50]
};
let sweepCanvas,sweepCtx,sweepWidth=0,sweepHeight=0;
function initializeBridgeUI(){
 sweepCanvas=$('bridge-sweep');sweepCtx=sweepCanvas.getContext('2d');
 new ResizeObserver(()=>{[sweepWidth,sweepHeight]=resize(sweepCanvas,sweepCtx);drawBridgeSweep()}).observe(sweepCanvas.parentElement);
 $('bridge-position').oninput=()=>{if(seekBridgePlayback(Number($('bridge-position').value)))return;syncBridgePosition();markPending()};
 $('bridge-position').onchange=()=>{if(!bridgePlayback.frames&&!$('run').disabled)run()};
 $('bridge-case').onchange=()=>{$('display-case').value=$('bridge-case').value;markPending();if(!$('run').disabled)run()};
 for(const id of Object.keys(bridgeFields))$(id).oninput=()=>{syncBridgePosition();markPending()};
 $('bridge-apply').onclick=run;
 for(const [id,step] of [['bridge-step-back',-1],['bridge-step-next',1]])$(id).onclick=()=>{
  const next=Number($('bridge-position').value)+step;if(seekBridgePlayback(next))return;$('bridge-position').value=next;syncBridgePosition();markPending();run()
 };
 $('bridge-show-deck').onchange=()=>{state.dirty=true};initializeBridgePlayback();
}
function syncBridgePosition(){
 const spacing=Number($('bridge-spacing').value);
 if(Number.isFinite(spacing)&&spacing>=2&&spacing<=8)$('bridge-position').max=24+spacing;
 $('bridge-position-output').value=fmt(Number($('bridge-position').value),2)+' m';
 $('bridge-position').nextElementSibling.lastElementChild.textContent='Exit '+$('bridge-position').max+' m';
}
function configureBridgeUI(model){
 invalidateBridgePlayback();const bridge=model.id==='bridge';document.body.classList.toggle('bridge-mode',bridge);
 $('bridge-controls').hidden=$('bridge-results').hidden=$('bridge-member-envelope').hidden=!bridge;
 if(bridge){
  $('model-stage').textContent='Bridge FEM · static + dynamic moving loads';
  for(const [id,[,value]] of Object.entries(bridgeFields))$(id).value=value;
  $('bridge-position').value=12;$('bridge-case').value=$('display-case').value='LC2';syncBridgePosition();
  $('bridge-show-deck').checked=true;
  $('selected-model-notes').textContent='The 24 × 4 × 4 m bridge uses 20 joints and 78 axial steel members. Four bearings restrain N01 in XYZ, N02 in Y, N17 in YZ and N18 in Y (53 free translational DOFs). Dead load includes truss steel self-weight and the declared deck line load. A two-axle research vehicle is distributed to adjacent bottom panel joints, preserving force and longitudinal/transverse moments. LC1 is dead load, LC2 dead + vehicle and LC3 dead + transverse wind, with no design-code factors. The deck is a load-distribution surface with mass; no local deck or floor-beam bending stiffness is represented. Vehicle-position envelopes use static solves at panel-crossing events plus a 0.5 m plotting grid. Browser Dynamic playback integrates all 53 modes with Newmark average acceleration under prescribed axle forces at constant speed, starting in dead-load equilibrium and retaining a 2 s free-vibration tail. Rayleigh damping targets the first two modes. Crossing sensor plots show clean N09Y acceleration/displacement and M05 strain. Vehicle suspension, moving mass and road-contact coupling are excluded. Bearing reactions assume bilateral linear restraints. Dynamic bridge ML is a separate scoped, full-crossing baseline; static bridge inference and capacity checks are not implemented.';
 }
 document.querySelector('.inspector-note').textContent=bridge?'Configured stiffness loss is simulation input. See Bridge ML for the separate full-crossing estimate and its validation scope. No structural safety rating.':'Research estimates. Forest votes are uncalibrated. No structural safety certification.';
 const onModel=document.querySelector('#tab-twin.active');
 if(onModel)$('page-heading').textContent=bridge?'Bridge observatory':'Structural observatory';
}
function setBridgeBusy(busy){
 setBridgePlaybackBusy(busy);
 for(const id of ['bridge-case','bridge-position','bridge-step-back','bridge-step-next','bridge-apply',...Object.keys(bridgeFields)])$(id).disabled=busy;
}
function bridgeRequest(){
 if(state.modelId!=='bridge')return undefined;
 const result={vehicle_position_m:Number($('bridge-position').value)};
 for(const [id,[key]] of Object.entries(bridgeFields)){
  if($(id).value===''||!Number.isFinite(Number($(id).value))||Number($(id).value)<Number($(id).min)||Number($(id).value)>Number($(id).max))throw Error('Review the bridge load parameters and their allowed ranges.');
  result[key]=Number($(id).value);
 }
 return result;
}
function updateBridgeResults(){
 const b=state.data?.bridge;$('bridge-results').hidden=!b;if(!b)return;
 const c=b.current,s=b.sweep;
 $('bridge-current-down').textContent=fmt(c.deck_down_mm,2)+' mm';
 const dynamic=state.data.playback?.method==='dynamic-moving-force';
 $('bridge-healthy-change').textContent=c.change_from_healthy_pct===null?'Healthy reference unavailable':(c.change_from_healthy_pct>=0?'+':'')+fmt(c.change_from_healthy_pct,1)+'% vs healthy · '+(dynamic?'same dynamic crossing':'same loading');
 $('bridge-live-load').textContent=fmt(b.vehicle.visible?b.vehicle.on_bridge_kn:0,1)+' kN';
 $('bridge-applied-total').textContent='Total downward load '+fmt(c.applied_vertical_kn,1)+' kN';
 $('bridge-left-reaction').textContent=fmt(c.left_reaction_kn,1)+' kN';
 $('bridge-right-reaction').textContent=fmt(c.right_reaction_kn,1)+' kN';
 $('bridge-sweep-peak').textContent=fmt(s.peak_down_mm,2)+' mm';
 $('bridge-critical-position').textContent='Peak at front axle x = '+fmt(s.critical_front_x_m,2)+' m';
 $('bridge-sweep-note').textContent=s.positions_count+' positions · panel-crossing events + 0.5 m grid · includes partial entry/exit. Envelope always uses dead + vehicle, independent of the current display case.';
 const rows=$('bridge-reaction-rows');
 if(rows.children.length!==b.supports.length){rows.replaceChildren();for(const support of b.supports){const row=document.createElement('tr');for(let i=0;i<9;i++)row.append(document.createElement('td'));rows.append(row)}}
 b.supports.forEach((support,i)=>{
  const values=['N'+String(support.node+1).padStart(2,'0'),support.bearing_kind||'Bearing',support.axes.join('/'),support.free_axes?.join('/')||'—',...support.reaction_kn.map(v=>fmt(v,2)),fmt(support.min_vertical_kn,2),fmt(support.max_vertical_kn,2)];
  values.forEach((value,j)=>{rows.children[i].children[j].textContent=value});
 });
 $('bridge-balance').textContent=(dynamic?'Dynamic balance R − F − inertia − damping: ':'Vertical equilibrium residual ')+fmt(c.vertical_balance_error_kn,dynamic?3:6)+' kN'+(dynamic?' · interpolated display frame; solver relative residual '+state.data.playback.integration.relative_residual.toExponential(1):'')+' · negative Y reaction indicates uplift demand in this bilateral model.';
 updateBridgeMember();drawBridgeSweep();refreshBridgeReadout();
}
function updateBridgeMember(){
 const sweep=state.data?.bridge?.sweep;$('bridge-member-envelope').hidden=!sweep;
 if(!sweep)return;
 $('bridge-member-min').textContent=fmt(sweep.member_min_axial_kn[state.selected],2)+' kN';
 $('bridge-member-max').textContent=fmt(sweep.member_max_axial_kn[state.selected],2)+' kN';
}
function drawBridgeSweep(){
 if(!sweepCtx)return;sweepCtx.clearRect(0,0,sweepWidth,sweepHeight);
 const b=state.data?.bridge;if(!b||sweepWidth<70)return;
 const s=b.sweep,left=45,right=15,top=18,bottom=27,w=sweepWidth-left-right,h=sweepHeight-top-bottom;
 const xmax=s.positions_m.at(-1),ymax=Math.max(...s.deck_down_mm,1)*1.1;
 const px=x=>left+x/xmax*w,py=y=>top+h-y/ymax*h;
 sweepCtx.font='9px Arial';sweepCtx.lineWidth=.6;
 for(let i=0;i<4;i++){const y=ymax*i/3;sweepCtx.strokeStyle='#e1e1e1';sweepCtx.beginPath();sweepCtx.moveTo(left,py(y));sweepCtx.lineTo(left+w,py(y));sweepCtx.stroke();sweepCtx.fillStyle='#444444';sweepCtx.textAlign='right';sweepCtx.fillText(fmt(y,1),left-7,py(y)+3)}
 for(let i=0;i<5;i++){const x=xmax*i/4;sweepCtx.textAlign='center';sweepCtx.fillText(fmt(x,1)+(i===4?' m':''),px(x),sweepHeight-8)}
 sweepCtx.textAlign='left';sweepCtx.fillText('DECK DOWNWARD · mm',left,10);
 sweepCtx.strokeStyle=plotColors.envelope;sweepCtx.lineWidth=1.7;sweepCtx.beginPath();s.positions_m.forEach((x,i)=>{i?sweepCtx.lineTo(px(x),py(s.deck_down_mm[i])):sweepCtx.moveTo(px(x),py(s.deck_down_mm[i]))});sweepCtx.stroke();
 if(b.vehicle.visible){sweepCtx.strokeStyle='#8b8b8b';sweepCtx.setLineDash([3,3]);sweepCtx.beginPath();sweepCtx.moveTo(px(b.vehicle.front_x),top);sweepCtx.lineTo(px(b.vehicle.front_x),top+h);sweepCtx.stroke();sweepCtx.setLineDash([])}
}
function bridgePolygon(points,fill,stroke='#949494'){
 ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.closePath();ctx.fillStyle=fill;ctx.fill();ctx.strokeStyle=stroke;ctx.lineWidth=.7;ctx.stroke();
}
function bridgeBox(low,high,colors,transform=p=>p){
 const points=[];for(const x of [low[0],high[0]])for(const y of [low[1],high[1]])for(const z of [low[2],high[2]])points.push(project(...transform([x,y,z])));
 const faces=[[0,1,3,2],[4,6,7,5],[0,4,5,1],[2,3,7,6],[0,2,6,4],[1,5,7,3]];
 faces.map((ids,i)=>({ids,color:colors[i%colors.length],depth:ids.reduce((sum,j)=>sum+points[j].z,0)/4})).sort((a,b)=>a.depth-b.depth).forEach(face=>bridgePolygon(face.ids.map(i=>points[i]),face.color));
}
function drawBridgeBase(){
 for(const x of [0,24])bridgeBox([x-.65,-1.25,-2.6],[x+.65,-.28,2.6],['#cecece','#bababa','#dbdbdb']);
}
function bridgeSurfacePoint(x,z,y,locations){
 const xc=Math.max(0,Math.min(24,x)),bay=Math.min(Math.floor(xc/6),3),t=(xc-6*bay)/6,right=(z+2)/4;
 const shift=[0,0,0];
 for(const [station,along] of [[bay,1-t],[bay+1,t]])for(const [side,across] of [[0,1-right],[1,right]]){
  const i=4*station+side,n=state.data.nodes[i];for(let j=0;j<3;j++)shift[j]+=(locations[i][j]-[n.x,n.y,n.z][j])*along*across;
 }
 return [x+shift[0],y+shift[1],z+shift[2]];
}
function drawBridgeFurniture(locations){
 const b=state.data.bridge;
 if($('bridge-show-deck').checked){
  for(let i=0;i<4;i++)bridgePolygon([[6*i,-2],[6*(i+1),-2],[6*(i+1),2],[6*i,2]].map(([x,z])=>project(...bridgeSurfacePoint(x,z,.08,locations))),'#d6d6d6','#adadad');
  for(let x=0;x<24;x+=2)line(project(...bridgeSurfacePoint(x,0,.1,locations)),project(...bridgeSurfacePoint(x+1,0,.1,locations)),'#fdfdfd',2);
 }
 if(!b.vehicle.visible)return;
 const front=b.vehicle.front_x,rear=b.vehicle.rear_x,z=b.vehicle.lane_z,transform=p=>bridgeSurfacePoint(p[0],p[2],p[1],locations);
 bridgeBox([rear-.65,.45,z-.7],[front-.45,1.45,z+.7],['#909090','#7e7e7e','#b2b2b2'],transform);
 bridgeBox([front-.45,.4,z-.7],[front+.65,1.35,z+.7],['#737373','#636363','#969696'],transform);
 for(const x of [rear,front])for(const side of [-.76,.76]){const p=project(...transform([x,.28,z+side]));circle(p,Math.max(3,Math.min(width/31,height/12)*state.zoom*.25),'#606060','#cccccc')}
 const p=project(...transform([(front+rear)/2,1.8,z]));label(bridgePlayback.playing?'MOVING LOAD':'RESEARCH VEHICLE',p,'#6b6b6b','8px Arial');
}
