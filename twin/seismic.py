"""Elastic 2D beam-column frames under uniform horizontal ground acceleration.

Rigid in-plane floor translation, lumped lateral floor masses, massless vertical
and rotation DOFs statically condensed. No gravity/P-delta or inelasticity.
"""
import hashlib
import re
import numpy as np
from scipy.linalg import eigh, solve
from .dynamics import newmark_linear

G = 9.80665
SYSTEMS = ('unbraced', 'x', 'chevron')
LABELS = {'unbraced': 'Unbraced', 'x': 'X-braced', 'chevron': 'Chevron'}
DEFAULTS = dict(stories=4, story_height_m=3.2, bay_width_m=6., floor_mass_t=40.,
                damping_ratio=.05, brace_area_mm2=2000., column_area_mm2=12000.,
                column_inertia_cm4=20000., beam_area_mm2=8000., beam_inertia_cm4=12000.)


def settings(values=None):
    values = {} if values is None else values
    if not isinstance(values, dict) or set(values)-set(DEFAULTS):
        raise ValueError('Unknown frame settings')
    result = DEFAULTS | values
    limits = dict(stories=(2, 8), story_height_m=(2.5, 5.), bay_width_m=(3., 10.),
                  floor_mass_t=(5., 200.), damping_ratio=(0., .1), brace_area_mm2=(200., 10000.),
                  column_area_mm2=(2000., 50000.), column_inertia_cm4=(1000., 100000.),
                  beam_area_mm2=(2000., 50000.), beam_inertia_cm4=(1000., 100000.))
    for key, (low, high) in limits.items():
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{key} must be finite and between {low} and {high}')
    if int(result['stories']) != result['stories']:
        raise ValueError('stories must be an integer')
    result['stories'] = int(result['stories'])
    return result


def parse_at2(text, unit='g', name='Imported PEER record'):
    """Read NPTS/DT header, explicit units, strict count and finite samples.

    Accept PEER header orders and Fortran D exponents. No filtering, detrending,
    baseline correction or automatic normalization is applied.
    """
    if not isinstance(text, str) or len(text.encode('utf8')) > 1_000_000:
        raise ValueError('AT2 text must be at most 1 MB')
    if unit not in ('g', 'm/s2', 'cm/s2'):
        raise ValueError('Acceleration unit must be g, m/s2 or cm/s2')
    lines = text.strip().splitlines()
    number = r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][+-]?\d+)?'
    header_index = None
    for i, line in enumerate(lines[:30]):
        count = re.search(r'\bNPTS\s*=\s*(\d+)\b', line, re.I)
        step = re.search(r'\bDT\s*=\s*('+number+r')', line, re.I)
        if count and step:
            header_index = i
            npts, dt = int(count[1]), float(step[1].replace('D', 'E').replace('d', 'e'))
            break
    if header_index is None:
        raise ValueError('AT2 file requires NPTS= and DT= in its header')
    if not 2 <= npts <= 30000 or not np.isfinite(dt) or not .001 <= dt <= .1 or (npts-1)*dt > 180:
        raise ValueError('Require 2..30000 samples, DT 0.001..0.1 s, and duration at most 180 s')
    header = '\n'.join(lines[:header_index+1])
    if re.search(r'VELOCITY|DISPLACEMENT', header, re.I):
        raise ValueError('Import an acceleration AT2, not a velocity/displacement record')
    # Common PEER acceleration headers encode units. Refuse known mismatches.
    declared = None
    if re.search(r'UNITS\s*(?:OF|ARE|=)?\s*\(?G\b|UNITS.*\(G\)', header, re.I): declared = 'g'
    if re.search(r'(?:CM/SEC|CM/S|CM/SEC\*\*2)', header, re.I): declared = 'cm/s2'
    elif re.search(r'(?:M/SEC|M/S)', header, re.I): declared = 'm/s2'
    if declared and declared != unit:
        raise ValueError(f'Header declares {declared}; select the matching acceleration unit')
    body = []
    for line in lines[header_index+1:]:
        if re.fullmatch(r'\s*\*+\s*End Data\s*\*+\s*', line, re.I): continue
        body.extend(line.replace(',', ' ').split())
    if len(body) != npts:
        raise ValueError(f'NPTS declares {npts} values; found {len(body)}')
    try:
        acceleration = np.array([float(v.replace('D', 'E').replace('d', 'e')) for v in body])
    except ValueError as error:
        raise ValueError('AT2 data contains a nonnumeric value') from error
    if not np.all(np.isfinite(acceleration)):
        raise ValueError('AT2 acceleration samples must be finite')
    acceleration *= {'g': G, 'm/s2': 1., 'cm/s2': .01}[unit]
    if np.max(np.abs(acceleration)) > 10*G:
        raise ValueError('Acceleration exceeds 10 g; check input units')
    return dict(name=str(name)[:180], dt=dt, acceleration=acceleration,
                npts=npts, duration_s=(npts-1)*dt, input_unit=unit,
                header=header[:2000], sha256=hashlib.sha256(text.encode('utf8')).hexdigest())


def beam_stiffness(a, b, area, inertia, elastic_modulus=200e9):
    """Euler-Bernoulli element, DOFs [ux,uy,rz] at each end."""
    delta = np.asarray(b)-a
    length = float(np.linalg.norm(delta))
    c, s = delta/length
    ea, ei = elastic_modulus*area/length, elastic_modulus*inertia
    k = np.array([[ea,0,0,-ea,0,0],
                  [0,12*ei/length**3,6*ei/length**2,0,-12*ei/length**3,6*ei/length**2],
                  [0,6*ei/length**2,4*ei/length,0,-6*ei/length**2,2*ei/length],
                  [-ea,0,0,ea,0,0],
                  [0,-12*ei/length**3,-6*ei/length**2,0,12*ei/length**3,-6*ei/length**2],
                  [0,6*ei/length**2,2*ei/length,0,-6*ei/length**2,4*ei/length]])
    t = np.zeros((6,6))
    rotation = np.array([[c,s,0],[-s,c,0],[0,0,1]])
    t[:3,:3] = t[3:,3:] = rotation
    return t.T @ k @ t


def build_frame(config=None, system='unbraced'):
    config = settings(config)
    if system not in SYSTEMS: raise ValueError('Unknown bracing system')
    n, h, w = config['stories'], config['story_height_m'], config['bay_width_m']
    nodes = np.array([[x, level*h] for level in range(n+1) for x in (0,w/2,w)], float)
    stiffness = np.zeros((nodes.size//2*3,)*2)
    elements = []
    def add(a, b, kind, area, inertia=0.):
        dofs = np.r_[np.arange(3*a,3*a+3),np.arange(3*b,3*b+3)]
        length = np.linalg.norm(nodes[b]-nodes[a])
        if kind == 'brace':
            direction = (nodes[b]-nodes[a])/length
            projection = np.r_[-direction,0,direction,0]
            k = 200e9*area/length*np.outer(projection, projection)
        else:
            k = beam_stiffness(nodes[a],nodes[b],area,inertia)
        stiffness[np.ix_(dofs,dofs)] += k
        elements.append(dict(a=a,b=b,kind=kind,area_m2=float(area),length_m=float(length)))
    brace_area = config['brace_area_mm2']*1e-6
    if system == 'chevron': brace_area *= np.hypot(w,h)/np.hypot(w/2,h)
    for level in range(1,n+1):
        below, above = 3*(level-1), 3*level
        for side in (0,2):
            add(below+side,above+side,'column',config['column_area_mm2']*1e-6,config['column_inertia_cm4']*1e-8)
        for side in (0,1):
            add(above+side,above+side+1,'beam',config['beam_area_mm2']*1e-6,config['beam_inertia_cm4']*1e-8)
        if system == 'x':
            add(below,above+2,'brace',brace_area); add(below+2,above,'brace',brace_area)
        elif system == 'chevron':
            add(below,above+1,'brace',brace_area); add(below+2,above+1,'brace',brace_area)
    # Floor horizontal translations retained. All upper vertical and rotation
    # DOFs remain independent and massless; column/beam bending is assembled.
    transform = np.zeros((len(stiffness),n+6*n))
    for level in range(1,n+1):
        for side in range(3):
            node = 3*level+side
            transform[3*node,level-1] = 1
            for local in (1,2):
                transform[3*node+local,n+6*(level-1)+2*side+local-1] = 1
    kt = transform.T @ stiffness @ transform
    secondary = -solve(kt[n:,n:],kt[n:,:n],assume_a='pos')
    recovery = transform @ np.vstack((np.eye(n),secondary))
    reduced = recovery.T @ stiffness @ recovery
    reduced = (reduced+reduced.T)/2
    mass = np.eye(n)*config['floor_mass_t']*1000
    eigenvalues, modes = eigh(reduced,mass)
    if eigenvalues[0] <= 0: raise ValueError('Unstable frame')
    return dict(config=config,system=system,nodes=nodes,elements=elements,K=reduced,M=mass,
                full_K=stiffness,recovery=recovery,omega=np.sqrt(eigenvalues),modes=modes,
                brace_volume_m3=sum(e['length_m']*e['area_m2'] for e in elements if e['kind']=='brace'))


def frame_history(frame, record, scale=1., step_factor=30, time_step_divisor=1, full_history=False, step_limit=60000):
    if type(time_step_divisor) is not int or not 1 <= time_step_divisor <= 8:
        raise ValueError('Time-step divisor must be an integer from 1 to 8')
    if type(step_limit) is not int or not 1 <= step_limit <= 240000:
        raise ValueError('Step limit must be an integer from 1 to 240000')
    k, m, omega = frame['K'], frame['M'], frame['omega']
    zeta = frame['config']['damping_ratio']
    alpha, beta = 2*zeta*omega[0]*omega[1]/sum(omega[:2]), 2*zeta/sum(omega[:2])
    c = alpha*m+beta*k
    # Subdivide every input interval. Keep all original samples and both ends.
    subdivisions = max(1,int(np.ceil(record['dt']/min(.01,2*np.pi/(step_factor*omega[-1])))))
    subdivisions *= time_step_divisor
    steps = (record['npts']-1)*subdivisions
    if steps > step_limit: raise ValueError(f'Analysis exceeds {step_limit} time steps; shorten the record or soften the frame')
    dt = record['dt']/subdivisions
    time = np.arange(steps+1)*dt
    ag = np.interp(time,np.arange(record['npts'])*record['dt'],record['acceleration'])*scale
    force = -ag[:,None]*(m @ np.ones(len(k)))[None,:]
    result = newmark_linear(k,m,c,force,dt)
    u, v, a = (result[key] for key in ('displacement','velocity','acceleration'))
    absolute = a+ag[:,None]
    # Positive restoring-demand convention; ground reaction has opposite sign.
    shear = (u @ k.T+v @ c.T).sum(axis=1)
    inertia_shear = -(absolute @ m.T).sum(axis=1)
    drift = np.diff(np.column_stack((np.zeros(len(time)),u)),axis=1)/frame['config']['story_height_m']
    peaks = np.max(np.abs(drift),axis=0)*100
    peak_index = int(np.argmax(np.max(np.abs(drift),axis=1)))
    ix = np.arange(len(time)) if full_history else np.unique(np.r_[np.arange(0,len(time),max(1,int(np.ceil(len(time)/1800)))),len(time)-1,peak_index])
    return dict(system=frame['system'],label=LABELS[frame['system']],
        period_s=float(2*np.pi/omega[0]),frequencies_hz=(omega/(2*np.pi)).tolist(),
        peak_drift_pct=float(peaks.max()),story_peak_drift_pct=peaks.tolist(),
        peak_roof_mm=float(np.max(np.abs(u[:,-1]))*1000),
        peak_base_shear_kn=float(np.max(np.abs(shear))/1000),
        peak_base_shear_weight=float(np.max(np.abs(shear))/(m.trace()*G)),
        brace_volume_m3=frame['brace_volume_m3'],
        brace_area_mm2=next((e['area_m2']*1e6 for e in frame['elements'] if e['kind']=='brace'),0.),
        integration=dict(dt_s=dt,steps=steps,method='Newmark average acceleration',
            relative_residual=result['relative_residual'],
            base_shear_balance_error=float(np.max(np.abs(shear-inertia_shear))/max(np.max(np.abs(shear)),1.)),
            rayleigh_alpha=float(alpha),rayleigh_beta=float(beta),
            modal_damping_ratios=((alpha/omega+beta*omega)/2).tolist()),
        history=dict(time_s=time[ix].tolist(),roof_mm=(u[ix,-1]*1000).tolist(),
            base_shear_kn=(shear[ix]/1000).tolist(),ground_g=(ag[ix]/G).tolist(),
            floor_displacement_mm=(u[ix]*1000).tolist(),
            roof_absolute_acceleration_m_s2=absolute[ix,-1].tolist()),
        geometry=dict(nodes_m=frame['nodes'].tolist(),elements=frame['elements'],
            peak_drift_time_s=float(time[peak_index]),
            peak_drift_displacement_m=(frame['recovery'] @ u[peak_index]).reshape(-1,3)[:,:2].tolist()))


def compare(request):
    if not isinstance(request,dict) or set(request)-{'frame','record','scale_factor'}:
        raise ValueError('Request requires frame, record and scale_factor only')
    config = settings(request.get('frame'))
    motion = request.get('record',{})
    if not isinstance(motion,dict) or set(motion)-{'text','unit','name'}:
        raise ValueError('Record requires text, unit and name only')
    record = parse_at2(motion.get('text'),motion.get('unit','g'),motion.get('name','Imported PEER record'))
    scale = request.get('scale_factor',1.)
    if isinstance(scale,bool) or not isinstance(scale,(int,float)) or not np.isfinite(scale) or not .05 <= scale <= 5:
        raise ValueError('Scale factor must be between 0.05 and 5')
    return dict(schema_version=1,frame=config,scale_factor=scale,
        record={key:value for key,value in record.items() if key!='acceleration'} | {
            'original_at2':motion['text'],
            'unscaled_pga_g':float(np.max(np.abs(record['acceleration']))/G),
            'scaled_pga_g':float(np.max(np.abs(record['acceleration']))*scale/G)},
        comparison_basis='Identical geometry, beam/column sections and total prescribed floor masses; equal brace steel volume for X and chevron.',
        assumptions=['Linear elastic 2D Euler-Bernoulli frame; rigid horizontal floor translations; fixed bases.',
            'Only horizontal floor inertia is modeled; massless vertical/rotation DOFs are statically condensed.',
            'Total floor mass includes all assigned structural/nonstructural mass; member self-mass is not added separately.',
            'Pin-ended axial braces; X diagonals cross without a joint; chevron braces meet a beam midpoint.',
            'No yielding, buckling, connection flexibility, gravity/P-delta, soil interaction or capacity/code assessment.',
            'Rayleigh damping targets modes 1 and 2 separately for each system; higher-mode damping may differ.',
            'Input samples are linearly interpolated; no filtering, detrending or baseline correction.',
            'Peaks cover the supplied record only. Histories are sampled for display; peaks use every integration step.',
            'Roof displacement is relative to the ground; absolute acceleration includes ground acceleration.',
            'Base shear demand V = 1ᵀ(Ku + Cv) = −1ᵀM(a + r·ag); support-on-frame reaction has opposite sign.',
            'Amplitude factors are user-defined; this workflow does not perform hazard-spectrum matching.'],
        systems=[frame_history(build_frame(config,system),record,scale) for system in SYSTEMS])
