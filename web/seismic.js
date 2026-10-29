const $=id=>document.getElementById(id);
const colors={unbraced:'#111111',x:'#444444',chevron:'#666666'};
const plotColors={unbraced:'#2563eb',x:'#c65b13',chevron:'#007f65',ground:'#7c3aed'};
const linePatterns={unbraced:[],x:[7,4],chevron:[2,4]};
let study=[],active=0,playing=false,lastTick=0,playTime=0,geometryScale=1,stale=false;
const fmt=(n,d=3)=>Number(n).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const ns='http://www.w3.org/2000/svg';
function svgNode(tag,attrs={},parent){const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(parent)parent.append(e);return e;}
function svgText(parent,x,y,text,attrs={}){const e=svgNode('text',{x,y,...attrs},parent);e.textContent=text;return e;}
function stop(){playing=false;$('play').textContent='Play';}
function download(name,text,type){const url=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function selected(){return study[active];}
function markStale(){if(!study.length)return;stale=true;stop();$('status').textContent='Settings changed. Run Compare frames to update the results.';}
function setupSource(){const files=$('source').value==='files';$('file-fields').hidden=!files;$('unit').disabled=!files;if(!files)$('unit').value='g';markStale();}
$('source').addEventListener('change',setupSource);
$('files').addEventListener('change',()=>{$('file-list').textContent=Array.from($('files').files).map(f=>f.name).join(' · ')||'No files selected.';});
$('study-form').addEventListener('input',markStale);
function formSettings(){const data=new FormData($('study-form')),frame={};for(const [key,value] of data)frame[key==='damping_pct'?'damping_ratio':key]=Number(value)/(key==='damping_pct'?100:1);return frame;}
async function inputRecords(){
 if($('source').value==='example'){const r=await fetch('/records/el-centro-1940.at2');if(!r.ok)throw Error('The bundled accelerogram could not be loaded.');return [{name:'El Centro 1940 · N–S (Peknold version)',unit:'g',text:await r.text()}];}
 const files=Array.from($('files').files);if(!files.length||files.length>7)throw Error('Select between 1 and 7 PEER acceleration records.');
 return Promise.all(files.map(async file=>{if(file.size>1_000_000)throw Error(`${file.name}: exceeds the 1 MB file limit.`);return {name:file.name,unit:$('unit').value,text:await file.text()};}));
}
async function run(event){
 event?.preventDefault();if(!$('study-form').reportValidity())return;
 stop();$('error').hidden=true;const frame=formSettings(),scale=Number($('scale').value);
 $('settings').disabled=true;$('run').textContent='Computing…';$('result-body').setAttribute('aria-busy','true');
 try{
  const records=await inputRecords(),results=[];
  for(let i=0;i<records.length;i++){
   $('status').textContent=`Analyzing record ${i+1} of ${records.length} · three frame configurations…`;
   const response=await fetch('/api/seismic',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({frame,record:records[i],scale_factor:scale})});
   let data;try{data=await response.json();}catch{throw Error('The analysis service returned an unreadable response. Start the Stratum server and try again.');}
   if(!response.ok)throw Error(`${records[i].name}: ${data.error||'Analysis failed.'}`);results.push(data);
  }
  study=results;active=0;stale=false;$('record-picker').replaceChildren();
  study.forEach((r,i)=>{const o=document.createElement('option');o.value=i;o.textContent=r.record.name;$('record-picker').append(o);});
  $('record-picker-label').hidden=study.length===1;$('result-body').hidden=false;render();
  $('status').textContent=`Analysis complete · ${study.length} record${study.length>1?'s':''} × 3 configurations. Results below use the displayed study settings.`;
 }catch(error){$('error').hidden=false;$('error').textContent=error.message;$('status').textContent=study.length?'Analysis failed. Previous results remain displayed.':'Analysis could not be completed.';}
 finally{$('settings').disabled=false;$('unit').disabled=$('source').value==='example';$('run').innerHTML='Compare frames <span>→</span>';$('result-body').removeAttribute('aria-busy');}
}
$('study-form').addEventListener('submit',run);
function tableRow(parent,values,system){const tr=document.createElement('tr');values.forEach((v,i)=>{const td=document.createElement('td');td.textContent=v;if(i===0)td.style.color='#111111';tr.append(td);});parent.append(tr);}
function median(a){const s=[...a].sort((x,y)=>x-y),m=Math.floor(s.length/2);return s.length%2?s[m]:(s[m-1]+s[m])/2;}
function render(){
 const r=selected();$('record-title').textContent=r.record.name;
 $('record-meta').textContent=`${r.frame.stories} stories · ${fmt(r.frame.story_height_m,1)} m story height · ${fmt(r.frame.bay_width_m,1)} m bay · ${r.frame.floor_mass_t} t / floor · ${fmt(r.frame.damping_ratio*100,1)}% damping`;
 $('pga').textContent=`PGA ${fmt(r.record.scaled_pga_g)} g`;$('duration').textContent=`${fmt(r.record.duration_s,2)} s · Δt record ${r.record.dt} s`;
 $('record-count').textContent=`${r.record.npts.toLocaleString()} samples · factor ×${r.scale_factor}`;
 $('comparison').replaceChildren();r.systems.forEach(s=>tableRow($('comparison'),[s.label,fmt(s.period_s),fmt(s.peak_drift_pct),fmt(s.peak_roof_mm,2),fmt(s.peak_base_shear_kn,1),fmt(s.peak_base_shear_weight)],s.system));
 $('suite-panel').hidden=study.length<2;$('suite-rows').replaceChildren();
 r.systems.forEach((s,i)=>{const drift=study.map(x=>x.systems[i].peak_drift_pct),shear=study.map(x=>x.systems[i].peak_base_shear_kn);tableRow($('suite-rows'),[s.label,`${fmt(median(drift))} / ${fmt(Math.max(...drift))}`,`${fmt(median(shear),1)} / ${fmt(Math.max(...shear),1)}`],s.system);});
 $('comparison-basis').textContent=r.comparison_basis;$('assumptions').replaceChildren();r.assumptions.forEach(a=>{const li=document.createElement('li');li.textContent=a;$('assumptions').append(li);});
 $('provenance').textContent=`Source header: ${r.record.header}\nSHA-256: ${r.record.sha256}. Input unit: ${r.record.input_unit}. Unscaled PGA: ${fmt(r.record.unscaled_pga_g)} g. Scale factor: ${r.scale_factor}.`;
 const residual=Math.max(...r.systems.map(s=>s.integration.relative_residual));$('verification').textContent=`Equilibrium residual ${residual.toExponential(1)} · Newmark β=¼, γ=½`;
 drawCharts(r);initFrames(r);$('timeline').max=r.record.duration_s;$('timeline').value=0;playTime=0;drawFrames(0);
}
function lineChart(id,series,{xLabel='Time · s',yLabel='',symmetric=false,integerY=false}={}){
 const host=$(id);host.replaceChildren();const width=520,height=224,left=56,right=17,top=18,bottom=40,pw=width-left-right,ph=height-top-bottom;
 const svg=svgNode('svg',{viewBox:`0 0 ${width} ${height}`,role:'img','aria-label':host.parentElement.querySelector('h3').textContent},host);
 let xmin=Infinity,xmax=-Infinity,ymin=Infinity,ymax=-Infinity;
 for(const s of series)for(let i=0;i<s.x.length;i++){xmin=Math.min(xmin,s.x[i]);xmax=Math.max(xmax,s.x[i]);ymin=Math.min(ymin,s.y[i]);ymax=Math.max(ymax,s.y[i]);}
 if(symmetric){const lim=Math.max(Math.abs(ymin),Math.abs(ymax),.001)*1.08;ymin=-lim;ymax=lim;}else{ymin=Math.min(0,ymin);ymax=integerY?Math.max(1,Math.ceil(ymax)):Math.max(.001,ymax)*1.08;}
 if(xmax===xmin)xmax=xmin+1;
 const px=x=>left+(x-xmin)/(xmax-xmin)*pw,py=y=>top+ph-(y-ymin)/(ymax-ymin)*ph;
 const yTicks=integerY?Array.from({length:ymax+1},(_,i)=>i):Array.from({length:5},(_,i)=>ymin+(ymax-ymin)*i/4);
 for(const y of yTicks){svgNode('line',{x1:left,y1:py(y),x2:width-right,y2:py(y),stroke:'#e5e5e5'},svg);svgText(svg,left-9,py(y)+3,Number(y.toPrecision(3)).toString(),{'text-anchor':'end',fill:'#555555','font-size':10});}
 for(let i=0;i<=4;i++){const x=xmin+(xmax-xmin)*i/4;svgText(svg,px(x),height-22,Number(x.toPrecision(3)).toString(),{'text-anchor':'middle',fill:'#555555','font-size':10});}
 for(const s of series){const path=s.x.map((x,i)=>`${i?'L':'M'}${px(x).toFixed(2)},${py(s.y[i]).toFixed(2)}`).join(' ');svgNode('path',{d:path,stroke:s.color,fill:'none','stroke-width':1.5,'stroke-linejoin':'round','stroke-dasharray':s.dash?.join(' ')||'none'},svg);}
 svgText(svg,left+pw/2,height-4,xLabel,{'text-anchor':'middle',fill:'#111111','font-size':10});if(yLabel)svgText(svg,5,10,yLabel,{fill:'#111111','font-size':9});
}
function drawCharts(r){
 const series=key=>r.systems.map(s=>({x:s.history.time_s,y:s.history[key],color:plotColors[s.system],dash:linePatterns[s.system]}));
 lineChart('ground-chart',[{x:r.systems[0].history.time_s,y:r.systems[0].history.ground_g,color:plotColors.ground}],{symmetric:true});
 lineChart('roof-chart',series('roof_mm'),{symmetric:true});lineChart('shear-chart',series('base_shear_kn'),{symmetric:true});
 lineChart('drift-chart',r.systems.map(s=>({x:[0,...s.story_peak_drift_pct],y:[0,...s.story_peak_drift_pct.map((_,i)=>i+1)],color:plotColors[s.system],dash:linePatterns[s.system]})),{xLabel:'Peak interstory drift · %',yLabel:'Story',integerY:true});
}
function initFrames(r){
 $('frames').replaceChildren();const maxDisp=Math.max(...r.systems.map(s=>s.peak_roof_mm/1000));geometryScale=maxDisp>1e-10?Math.min(500,r.frame.bay_width_m*.15/maxDisp):1;
 $('magnification').textContent=`Displacement ×${fmt(geometryScale,0)}`;
 r.systems.forEach(s=>{const card=document.createElement('div');card.className='frame-card';const h=document.createElement('h3');h.style.color='#111111';h.textContent=s.label;const small=document.createElement('small');small.textContent=`T₁ ${fmt(s.period_s,2)} s`;h.append(small);card.append(h);svgNode('svg',{viewBox:'0 0 240 250',id:`frame-${s.system}`,role:'img','aria-label':`${s.label} frame displacement animation`},card);const p=document.createElement('div');p.className='frame-caption';p.textContent=s.system==='unbraced'?'Moment frame':`Brace A ${fmt(s.brace_area_mm2,0)} mm²`;card.append(p);$('frames').append(card);});
}
function interpolatedFloors(s,time){const t=s.history.time_s;let lo=0,hi=t.length-1;while(hi-lo>1){const m=(lo+hi)>>1;if(t[m]<=time)lo=m;else hi=m;}const fraction=Math.min(1,Math.max(0,(time-t[lo])/(t[hi]-t[lo])));return s.history.floor_displacement_mm[lo].map((u,i)=>(u+(s.history.floor_displacement_mm[hi][i]-u)*fraction)/1000);}
function drawFrames(time){
 const r=selected();if(!r)return;$('time-label').textContent=`${fmt(time,2)} s`;
 const h=r.frame.story_height_m*r.frame.stories,w=r.frame.bay_width_m,scale=Math.min(155/w,198/h),ox=(240-w*scale)/2,oy=218;
 r.systems.forEach(s=>{const svg=$(`frame-${s.system}`);svg.replaceChildren();const u=interpolatedFloors(s,time),nodes=s.geometry.nodes_m;
 const point=(i,deformed)=>{const p=nodes[i],level=Math.round(p[1]/r.frame.story_height_m);return [ox+p[0]*scale+(deformed&&level?u[level-1]*geometryScale*scale:0),oy-p[1]*scale];};
 for(const displaced of [false,true])for(const e of s.geometry.elements){const a=point(e.a,displaced),b=point(e.b,displaced);svgNode('line',{x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:displaced?colors[s.system]:'#c0c0c0','stroke-width':displaced?(e.kind==='brace'?1.7:3):1,'stroke-dasharray':displaced?'none':'4 4'},svg);}
 for(const side of [0,2]){const [x,y]=point(side,false);svgNode('path',{d:`M ${x-10} ${y+3} H ${x+10} M ${x-7} ${y+4} l -5 6 M ${x} ${y+4} l -5 6 M ${x+7} ${y+4} l -5 6`,stroke:'#7c7c7c','stroke-width':1,fill:'none'},svg);}
 });
}
$('record-picker').addEventListener('change',()=>{stop();active=Number($('record-picker').value);render();});
$('timeline').addEventListener('input',()=>{stop();playTime=Number($('timeline').value);drawFrames(playTime);});
$('play').addEventListener('click',()=>{if(playing){stop();return;}if(playTime>=selected().record.duration_s)playTime=0;playing=true;lastTick=0;$('play').textContent='Pause';requestAnimationFrame(tick);});
function tick(now){if(!playing)return;if(lastTick)playTime+=(now-lastTick)/1000;lastTick=now;playTime=Math.min(playTime,selected().record.duration_s);$('timeline').value=playTime;drawFrames(playTime);if(playTime>=selected().record.duration_s)stop();else requestAnimationFrame(tick);}
$('export-json').addEventListener('click',()=>download('stratum-seismic-study.json',JSON.stringify({exported_at:new Date().toISOString(),display_settings_changed:stale,records:study},null,2),'application/json'));
function csvCell(value){let text=String(value);if(/^[=+\-@\t\r]/.test(text)&&typeof value==='string')text="'"+text;return '"'+text.replaceAll('"','""')+'"';}
$('export-csv').addEventListener('click',()=>{const rows=[['Record','SHA256','Stories','Height_m','Bay_m','Floor_mass_t','Damping_ratio','Scale_factor','System','T1_s','Peak_drift_pct','Peak_roof_mm','Peak_base_shear_kN','V_over_W','Brace_volume_m3']];for(const r of study)for(const s of r.systems)rows.push([r.record.name,r.record.sha256,r.frame.stories,r.frame.story_height_m,r.frame.bay_width_m,r.frame.floor_mass_t,r.frame.damping_ratio,r.scale_factor,s.label,s.period_s,s.peak_drift_pct,s.peak_roof_mm,s.peak_base_shear_kn,s.peak_base_shear_weight,s.brace_volume_m3]);download('stratum-seismic-peaks.csv',rows.map(row=>row.map(csvCell).join(',')).join('\r\n'),'text/csv');});
async function loadBenchmark(){
 try{
  const response=await fetch('/api/seismic-validation');if(!response.ok)throw Error('Verification report is unavailable.');
  const report=await response.json();
  if(!report.available){$('benchmark-status').textContent=report.reason||'No saved verification report.';return;}
  if(!report.fresh){$('benchmark-status').textContent='Saved report is out of date. The numerical sources changed; verification must be rerun.';$('benchmark-status').classList.add('benchmark-stale');return;}
  const count=report.comparisons.filter(c=>c.passed).length;
  $('benchmark-status').textContent=`${report.current_pass?'PASS':'FAIL'} · ${count}/${report.comparisons.length} independent comparisons · OpenSees ${report.engine.version}`;
  $('benchmark-status').classList.add(report.current_pass?'benchmark-pass':'benchmark-stale');
  $('benchmark-detail').hidden=false;$('benchmark-rows').replaceChildren();
  report.comparisons.filter(c=>c.case==='el-centro-default-4-story').forEach(c=>{
   const refinement=report.convergence.find(row=>row.system===c.system);
   const change=100*Math.max(...Object.values(refinement.peaks).map(p=>p.production_to_quarter_relative));
   tableRow($('benchmark-rows'),[{unbraced:'Unbraced',x:'X-braced',chevron:'Chevron'}[c.system],
    (100*c.errors.frequency_max_relative).toExponential(2),(100*c.errors.floor_displacement_m.normalized_max).toExponential(2),`${fmt(change,4)}%`],c.system);
  });
  const ratios=report.convergence.map(c=>c.history_difference_ratio);
  $('benchmark-summary').textContent=`All three dt / dt2 / dt4 studies ${report.convergence.every(c=>c.passed)?'pass':'do not pass'}. Floor-history refinement ratio ${fmt(Math.min(...ratios),3)}–${fmt(Math.max(...ratios),3)} (second-order target ≈4). ${report.freshness_note}`;
 }catch(error){$('benchmark-status').textContent=error.message;}
}
setupSource();run();loadBenchmark();
