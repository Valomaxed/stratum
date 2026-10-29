"""Prescribed moving axle forces on a linear bridge; all free modes retained."""
import numpy as np
from scipy.linalg import eigh
from .bridge import bridge_context, vehicle_forces


def _history(model, config, damage, scale, removed, speed, damping, tail=2., step_factor=30, include_trace=True):
    k, mass, elements = model.assemble(damage, removed)
    free = model.free
    values, phi = eigh(k[np.ix_(free, free)], mass[np.ix_(free, free)])
    if values[0] <= max(values[-1]*1e-12, 1e-8):
        raise ValueError("Unstable bridge in moving-load analysis")
    omega = np.sqrt(values)
    alpha = 2*damping*omega[0]*omega[1]/sum(omega[:2])
    beta = 2*damping/sum(omega[:2])
    modal_c = alpha+beta*values
    crossing = (24+config['axle_spacing_m'])/speed
    duration = crossing+tail
    steps = int(np.ceil(duration/min(.001, 2*np.pi/(step_factor*omega[-1]))))
    time = np.linspace(0, duration, steps+1); dt = time[1]
    # Free axle forces are continuous at bearing entry/exit. Interpolate their
    # exact piecewise-linear event representation, avoiding one solve per step.
    events = np.unique(np.r_[np.arange(0,25,6), np.arange(0,25,6)+config['axle_spacing_m']])
    forces = np.array([vehicle_forces(model, config, x)[free]*scale for x in events])
    moving = np.array([np.interp(time*speed, events, forces[:,j], right=0) for j in range(len(free))]).T
    force = moving @ phi
    q, v, a = (np.zeros_like(force) for _ in range(3))
    a[0] = force[0]
    a0, a1, a2 = 4/dt**2, 2/dt, 4/dt
    effective = values+a0+a1*modal_c
    for j in range(1, len(time)):
        q[j] = (force[j]+a0*q[j-1]+a2*v[j-1]+a[j-1]
                +modal_c*(a1*q[j-1]+v[j-1]))/effective
        a[j] = a0*(q[j]-q[j-1])-a2*v[j-1]-a[j-1]
        v[j] = v[j-1]+dt/2*(a[j-1]+a[j])
    residual = a+v*modal_c+q*values-force
    # Retain dense scalar traces for plotting; scene frames are presentation
    # samples. The actual integration resolves the highest retained frequency.
    stride = max(1, int(.005/dt))
    ix = np.unique(np.r_[np.arange(0,len(time),stride),len(time)-1])
    dead = model.solve(damage, load_scale=scale, removed=removed)['displacement']
    u = np.tile(dead,(len(ix),1)); velocity = np.zeros_like(u); acceleration = np.zeros_like(u)
    u[:,free] += q[ix] @ phi.T
    velocity[:,free] = v[ix] @ phi.T; acceleration[:,free] = a[ix] @ phi.T
    c = alpha*mass+beta*k
    internal = u @ k.T+velocity @ c.T+acceleration @ mass.T
    dynamic_y = (velocity @ c.T+acceleration @ mass.T)[:,1::3].sum(axis=1)/1000
    b = np.zeros((len(elements),model.nodes.size))
    for i,(dofs,projection,length,_) in enumerate(elements): b[i,dofs]=projection/length
    # N09Y is the left midspan bottom-deck joint; M05 is a face diagonal.
    sensor_dof = 25; sensor_mode = phi[np.flatnonzero(free==sensor_dof)[0]]
    strain_mode = b[4,free] @ phi
    trace = {'time':time.tolist(), 'acceleration':(a @ sensor_mode).tolist(),
             'displacement_mm':((q @ sensor_mode+dead[sensor_dof])*1000).tolist(),
             'strain_micro':((q @ strain_mode+b[4] @ dead)*1e6).tolist()} if include_trace else None
    return {'time':time[ix], 'displacement':u.reshape(-1,20,3), 'strain':u @ b.T,
            'internal_force':internal.reshape(-1,20,3), 'dynamic_vertical_kn':dynamic_y,
            'trace':trace, 'dt':dt, 'crossing':crossing, 'alpha':alpha, 'beta':beta,
            'relative_residual':float(np.linalg.norm(residual)/max(np.linalg.norm(force),1e-12)),
            'frequencies':(omega[:4]/(2*np.pi)).tolist(),
            'effective_modulus':np.array([e for _,_,_,e in elements])}


def prepare_dynamic_playback(values=None, damage=None, load_scale=1., removed=(), dynamic=None):
    dynamic = {} if dynamic is None else dynamic
    if not isinstance(dynamic,dict) or set(dynamic)-{'speed_kmh','damping_ratio'}:
        raise ValueError('Dynamic settings require speed_kmh and damping_ratio only')
    speed_kmh=float(dynamic.get('speed_kmh',36)); damping=float(dynamic.get('damping_ratio',.02))
    if not np.isfinite(speed_kmh) or not 10 <= speed_kmh <= 120:
        raise ValueError('Vehicle speed must be between 10 and 120 km/h')
    if not np.isfinite(damping) or not 0 <= damping <= .1:
        raise ValueError('Damping ratio must be between 0 and 0.1')
    if not np.isfinite(load_scale) or not .1 <= load_scale <= 3:
        raise ValueError('Load scale must be between 0.1 and 3')
    context=bridge_context(values); model=context['model']; config=context['config']
    r=_history(model,config,damage,load_scale,removed,speed_kmh/3.6,damping)
    # Healthy comparison is a separate dynamic crossing, not a static baseline.
    healthy=r if not removed and (damage is None or not np.any(damage)) else _history(model,config,None,load_scale,(),speed_kmh/3.6,damping)
    deck=[0,1,4,5,8,9,12,13,16,17]
    healthy_down=np.maximum(0,-healthy['displacement'][:,deck,1].min(axis=1))*1000
    healthy_u=healthy['displacement'].reshape(-1,60)
    aligned_healthy=np.array([np.interp(r['time'],healthy['time'],healthy_u[:,j]) for j in range(60)]).T.reshape(-1,20,3)
    comparison_rows=[]
    for key,label,unit in [('acceleration','N09Y peak |acceleration|','m/s²'),
                           ('displacement_mm','N09Y peak |displacement|','mm'),
                           ('strain_micro','M05 peak |strain|','με')]:
        reference=float(np.max(np.abs(healthy['trace'][key])))
        current=float(np.max(np.abs(r['trace'][key])))
        comparison_rows.append({'id':key,'label':label,'unit':unit,'healthy':reference,'current':current,
                                'change_pct':100*(current/reference-1) if reference>1e-12 else None})
    for i,(reference,current) in enumerate(zip(healthy['frequencies'],r['frequencies'])):
        comparison_rows.append({'id':f'mode_{i+1}','label':f'Natural frequency {i+1}','unit':'Hz',
                                'healthy':reference,'current':current,'change_pct':100*(current/reference-1)})
    configured_loss=1-r['effective_modulus']/model.elastic_modulus
    return {'method':'dynamic-moving-force','settings':config,'load_scale':float(load_scale),
            'speed_kmh':speed_kmh,'damping_ratio':damping,'time_s':r['time'].tolist(),
            'positions_m':(r['time']*speed_kmh/3.6).tolist(),'crossing_time_s':r['crossing'],
            'healthy_deck_down_mm':np.interp(r['time'],healthy['time'],healthy_down).tolist(),
            'healthy_displacement':aligned_healthy.tolist(),'healthy_signal':healthy['trace'],
            'comparison':{'rows':comparison_rows,'damaged_members':[
                {'id':i,'name':f'M{i+1:02}','stiffness_loss':float(loss),'removed':i in removed}
                for i,loss in enumerate(configured_loss) if loss>1e-12],
                'healthy_integration':{'dt_s':healthy['dt'],'relative_residual':healthy['relative_residual']},
                'note':'Identical geometry, deck mass, axle forces, speed, lane and load scale. Damping ratio is targeted at the first two modes separately for each state. Absolute channel peaks include dead-load offset and the full crossing plus 2 s tail; these are not global bridge maxima or damage predictions.'},
            'displacement':r['displacement'].tolist(),'strain':r['strain'].tolist(),
            'internal_force':r['internal_force'].tolist(),'dynamic_vertical_kn':r['dynamic_vertical_kn'].tolist(),
            'dead_forces':(model.loads.reshape(-1,3)*load_scale).tolist(),
            'effective_modulus':r['effective_modulus'].tolist(),'area':model.area.tolist(),'lengths':model.lengths.tolist(),
            'signal':r['trace'],'integration':{'method':'Newmark average acceleration; all 53 free modes',
                'dt_s':r['dt'],'relative_residual':r['relative_residual'],
                'rayleigh_alpha':r['alpha'],'rayleigh_beta':r['beta']},
            'note':'Dead-load equilibrium initial state; prescribed constant axle forces and speed; 2 s free-vibration tail. No vehicle suspension, moving mass, road roughness or contact coupling.'}
