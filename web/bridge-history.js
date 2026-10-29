/* Clean dynamic FEM channels, separate from configured noisy static sensors. */
const bridgeHistoryCharts=[
 ['bridge-acceleration','acceleration','bridge-a-value','m/s²'],
 ['bridge-displacement','displacement_mm','bridge-u-value','mm'],
 ['bridge-strain','strain_micro','bridge-e-value','με']
];
function initializeBridgeHistory(){
 for(const [id] of bridgeHistoryCharts)new ResizeObserver(()=>drawBridgeHistory()).observe($(id).parentElement);
 $('bridge-time').oninput=()=>{
  const p=bridgePlayback;if(p.frames?.method!=='dynamic-moving-force')return;
  const raw=Number($('bridge-time').value),end=p.frames.time_s.at(-1);
  // A millisecond-stepped range can round a non-integer duration just below
  // its max. Treat its final representable tick as the full crossing endpoint.
  const time=raw>=end-.0011?end:raw;
  pauseBridgePlayback();p.complete=false;applyBridgePlaybackFrame(time===end?p.frames.positions_m.at(-1):time*p.frames.speed_kmh/3.6,true);updateBridgeTransport();
 };
}
function prepareBridgeHistory(frames){
 const dynamic=frames.method==='dynamic-moving-force';$('bridge-history').hidden=!dynamic;
 if(!dynamic)return;
 $('bridge-time').max=frames.time_s.at(-1);$('bridge-duration').textContent=fmt(frames.time_s.at(-1),2)+' s';
 $('bridge-history-description').textContent=`${fmt(frames.speed_kmh,0)} km/h · ${fmt(frames.damping_ratio*100,1)}% damping at modes 1–2 · full 53-mode FEM`;
 updateBridgeHistory(0);
}
function updateBridgeHistory(time){
 const f=bridgePlayback.frames;if(f?.method!=='dynamic-moving-force'||time===null)return;
 $('bridge-time').value=time;$('bridge-time-value').textContent=fmt(time,2)+' s';
 $('bridge-phase').textContent=time>f.crossing_time_s?'Free vibration · vehicle exited':bridgePlayback.playing?'Vehicle crossing':'Paused crossing';
 for(const [,key,id,unit] of bridgeHistoryCharts){
  const current=fmt(bridgeTraceValue(f.signal,key,time),3),healthy=bridgeComparisonVisible()?fmt(bridgeTraceValue(f.healthy_signal,key,time),3):null;
  $(id).textContent=(healthy===null?current:'H '+healthy+' · C '+current)+' '+unit;
 }
 drawBridgeHistory();
}
function bridgeTraceValue(trace,key,time){
 const times=trace.time;let lo=0,hi=times.length-1;
 while(hi-lo>1){const mid=(lo+hi)>>1;if(times[mid]<=time)lo=mid;else hi=mid}
 const weight=Math.max(0,Math.min(1,(time-times[lo])/(times[hi]-times[lo])));
 return trace[key][lo]*(1-weight)+trace[key][hi]*weight;
}
function drawBridgeHistory(){
 const p=bridgePlayback,f=p.frames;if(f?.method!=='dynamic-moving-force'||$('bridge-history').hidden)return;
 const time=p.position/(f.speed_kmh/3.6),xs=f.signal.time,end=xs.at(-1);
 for(const [id,key] of bridgeHistoryCharts){
  const canvas=$(id),cx=canvas.getContext('2d'),[width,height]=resize(canvas,cx);if(width<60)continue;
  const ys=f.signal[key],left=48,top=12,w=width-left-12,h=height-top-25;
  const compare=bridgeComparisonVisible();
  let low=Infinity,high=-Infinity;for(const values of compare?[ys,f.healthy_signal[key]]:[ys])for(const y of values){low=Math.min(low,y);high=Math.max(high,y)}
  const margin=Math.max((high-low)*.12,1e-5);low-=margin;high+=margin;
  const px=t=>left+t/end*w,py=y=>top+(high-y)/(high-low)*h;
  cx.font='9px Arial';cx.lineWidth=.6;
  for(let i=0;i<3;i++){const y=low+(high-low)*i/2;cx.strokeStyle='#e1e1e1';cx.beginPath();cx.moveTo(left,py(y));cx.lineTo(left+w,py(y));cx.stroke();cx.fillStyle='#444444';cx.textAlign='right';cx.fillText(fmt(y,Math.abs(y)<1?3:1),left-5,py(y)+3)}
  cx.textAlign='center';for(let i=0;i<4;i++)cx.fillText(fmt(end*i/3,1)+(i===3?' s':''),px(end*i/3),height-6);
  function paint(trace,color,dashed){
   const tx=trace.time,ty=trace[key],stride=Math.max(1,Math.floor(tx.length/Math.max(w,1)));
   cx.strokeStyle=color;cx.lineWidth=dashed?1.2:1.5;
   for(let start=0;start<tx.length;start+=stride){
    let min=Infinity,max=-Infinity,imin=start,imax=start;
    for(let j=start;j<Math.min(start+stride,ty.length);j++){if(ty[j]<min){min=ty[j];imin=j}if(ty[j]>max){max=ty[j];imax=j}}
    cx.globalAlpha=(tx[start]<=time?1:.25)*(dashed?.9:1);
    // Connect extrema in time order, preserving narrow peaks. Gaps in healthy
    // bins distinguish coincident histories without shifting their values.
    if(dashed&&Math.floor(start/stride)%5===4)continue;
    const first=Math.min(imin,imax),last=Math.max(imin,imax),previous=Math.max(0,start-1);
    cx.beginPath();cx.moveTo(px(tx[previous]),py(ty[previous]));cx.lineTo(px(tx[first]),py(ty[first]));cx.lineTo(px(tx[last]),py(ty[last]));cx.lineTo(px(tx[Math.min(start+stride-1,ty.length-1)]),py(ty[Math.min(start+stride-1,ty.length-1)]));cx.stroke();
   }
  }
  paint(f.signal,plotColors.current,false);
  if(compare)paint(f.healthy_signal,plotColors.healthy,true);
  cx.globalAlpha=1;cx.setLineDash([3,3]);cx.strokeStyle='#8b8b8b';cx.beginPath();cx.moveTo(px(f.crossing_time_s),top);cx.lineTo(px(f.crossing_time_s),top+h);cx.stroke();cx.setLineDash([]);
  cx.strokeStyle='#5d5d5d';cx.beginPath();cx.moveTo(px(time),top);cx.lineTo(px(time),top+h);cx.stroke();
 }
}
