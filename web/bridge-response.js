/* Pure numerical sampling, shared by browser playback and Node verification. */
const BridgeResponse=(()=>{
 function interpolate(a,b,t){return a.map((value,i)=>Array.isArray(value)?interpolate(value,b[i],t):value+(b[i]-value)*t)}
 function sample(bundle,position){
  if(!Number.isFinite(position))throw Error('Vehicle position must be finite');
  const xs=bundle.positions_m,x=Math.max(xs[0],Math.min(xs.at(-1),position));
  let lo=0,hi=xs.length-1;
  while(hi-lo>1){const middle=(lo+hi)>>1;if(xs[middle]<=x)lo=middle;else hi=middle}
  const t=(x-xs[lo])/(xs[hi]-xs[lo]);
  const u=interpolate(bundle.displacement[lo],bundle.displacement[hi],t);
  const dynamic=bundle.method==='dynamic-moving-force';
  const healthy=bundle.healthy_displacement?interpolate(bundle.healthy_displacement[lo],bundle.healthy_displacement[hi],t):null;
  const strain=interpolate(bundle.strain[lo],bundle.strain[hi],t);
  const internal=interpolate(bundle.internal_force[lo],bundle.internal_force[hi],t);
  const force=bundle.dead_forces.map(row=>row.slice()),c=bundle.settings;
  let live=0;
  for(const [axle,kn] of [[x,c.front_axle_kn],[x-c.axle_spacing_m,c.rear_axle_kn]]){
   if(axle<0||axle>24)continue;
   const bay=Math.min(Math.floor(axle/6),3),along=(axle-6*bay)/6,right=(c.lane_offset_m+2)/4;
   const weight=kn*1000*bundle.load_scale;live+=weight;
   for(const [station,a] of [[bay,1-along],[bay+1,along]])for(const [side,b] of [[0,1-right],[1,right]])force[4*station+side][1]-=weight*a*b;
  }
  const reactions=internal.map((row,i)=>row.map((value,j)=>value-force[i][j]));
  const stress=strain.map((eps,i)=>eps*bundle.effective_modulus[i]);
  const axial=stress.map((sigma,i)=>sigma*bundle.area[i]);
  const deck=[0,1,4,5,8,9,12,13,16,17];
  const down=Math.max(0,...deck.map(i=>-u[i][1]))*1000,healthyDown=dynamic?bundle.healthy_deck_down_mm[lo]+(bundle.healthy_deck_down_mm[hi]-bundle.healthy_deck_down_mm[lo])*t:Math.max(0,...deck.map(i=>-healthy[i][1]))*1000;
  const left=(reactions[0][1]+reactions[1][1])/1000,right=(reactions[16][1]+reactions[17][1])/1000;
  const total=-force.reduce((sum,row)=>sum+row[1],0)/1000;
  const dynamicVertical=dynamic?bundle.dynamic_vertical_kn[lo]+(bundle.dynamic_vertical_kn[hi]-bundle.dynamic_vertical_kn[lo])*t:0;
  return {position_m:x,time_s:dynamic?x/(bundle.speed_kmh/3.6):null,displacement:u,healthy_displacement:healthy,strain,stress,axial_force:axial,forces:force,reactions,
   max_displacement_mm:Math.max(...u.map(row=>Math.hypot(...row)))*1000,
   max_stress_mpa:Math.max(...stress.map(Math.abs))/1e6,
   strain_energy_j:dynamic?.5*strain.reduce((sum,eps,i)=>sum+eps*eps*bundle.effective_modulus[i]*bundle.area[i]*bundle.lengths[i],0):.5*u.reduce((sum,row,i)=>sum+row.reduce((s,value,j)=>s+value*internal[i][j],0),0),
   deck_down_mm:down,healthy_deck_down_mm:healthyDown,
   change_from_healthy_pct:healthyDown>1e-10?100*(down/healthyDown-1):null,
   left_reaction_kn:left,right_reaction_kn:right,applied_vertical_kn:total,
   dynamic_vertical_kn:dynamicVertical,vertical_balance_error_kn:left+right-total-dynamicVertical,live_load_kn:live/1000};
 }
 return {sample};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=BridgeResponse;
