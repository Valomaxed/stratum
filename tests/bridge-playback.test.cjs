const {test}=require('node:test');
const assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
const fs=require('node:fs');
const path=require('node:path');
const {sample}=require('../web/bridge-response.js');
const root=path.resolve(__dirname,'..');
const venv=path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const python=process.env.PYTHON||(fs.existsSync(venv)?venv:'python');
const source=`
import json,numpy as np
from twin.bridge import prepare_playback,bridge_context,vehicle_forces
config={'axle_spacing_m':3.7,'lane_offset_m':.8,'front_axle_kn':95,'deck_load_kn_m':12}
damage=np.zeros(78);damage[[4,50]]=[.3,.2]
bundle=prepare_playback(config,damage,1.4)
model=bridge_context(config)['model'];expected=[]
for x in (0,.01,3.7,6.125,12.789,23.999,24,24.001,27.69,27.7):
 force=(model.loads+vehicle_forces(model,bundle['settings'],x))*1.4
 r=model.solve(damage,forces=force)
 expected.append({'x':x,'displacement':r['displacement'].reshape(-1,3).tolist(),
  'stress':r['stress'].tolist(),'axial_force':r['axial_force'].tolist(),
  'reactions':r['reactions'].reshape(-1,3).tolist(),'forces':force.reshape(-1,3).tolist(),
  'energy':r['strain_energy']})
print(json.dumps({'bundle':bundle,'expected':expected}))
`;
const fixture=JSON.parse(execFileSync(python,['-c',source],{cwd:root,maxBuffer:5*1024*1024,encoding:'utf8'}));
function close(actual,expected,atol=1e-6,rtol=1e-9){
 if(Array.isArray(expected)){assert.equal(actual.length,expected.length);expected.forEach((value,i)=>close(actual[i],value,atol,rtol));return}
 assert.ok(Math.abs(actual-expected)<=atol+rtol*Math.abs(expected),`${actual} != ${expected}`);
}
test('browser sampling matches fresh FEM, including axle exits',()=>{
 for(const expected of fixture.expected){
  const f=sample(fixture.bundle,expected.x);
  for(const key of ['displacement','stress','axial_force','forces','reactions'])close(f[key],expected[key]);
  close(f.strain_energy_j,expected.energy);
  close(f.vertical_balance_error_kn,0,1e-7);
 }
});
test('seek clamps to the crossing and rejects nonfinite position',()=>{
 close(sample(fixture.bundle,-10).position_m,0);
 close(sample(fixture.bundle,100).position_m,27.7);
 assert.throws(()=>sample(fixture.bundle,NaN),/finite/);
});
test('dynamic browser sampling preserves inertia, energy and post-exit vibration',()=>{
 const source=`
import json,numpy as np
from twin.bridge_dynamics import prepare_dynamic_playback
from twin.bridge import bridge_context,vehicle_forces
damage=np.zeros(78);damage[4]=.25
b=prepare_dynamic_playback(damage=damage,dynamic={'speed_kmh':72})
model=bridge_context()['model'];k,_,_=model.assemble(damage);expected=[]
for i in (0,35,150,len(b['positions_m'])-1):
 u=np.array(b['displacement'][i]).ravel()
 force=model.loads+vehicle_forces(model,b['settings'],b['positions_m'][i])
 expected.append({'x':b['positions_m'][i],'u':u.reshape(-1,3).tolist(),
  'healthy_u':b['healthy_displacement'][i],
  'energy':float(.5*u@k@u),'reaction':(np.array(b['internal_force'][i]).ravel()-force).reshape(-1,3).tolist(),
  'time':b['time_s'][i]})
print(json.dumps({'bundle':b,'expected':expected}))
`;
 const f=JSON.parse(execFileSync(python,['-c',source],{cwd:root,maxBuffer:15*1024*1024,encoding:'utf8'}));
 for(const e of f.expected){
  const r=sample(f.bundle,e.x);close(r.displacement,e.u);close(r.reactions,e.reaction);
  close(r.healthy_displacement,e.healthy_u);
  close(r.time_s,e.time);close(r.strain_energy_j,e.energy);close(r.vertical_balance_error_kn,0,1e-6);
 }
 const tail=sample(f.bundle,f.bundle.positions_m.at(-1));
 close(tail.live_load_kn,0);assert.ok(tail.time_s>f.bundle.crossing_time_s);
 assert.ok(tail.max_stress_mpa>0);
});
