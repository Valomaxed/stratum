"""Standalone OpenSees reference worker. No imports from Stratum.

Run with the optional Python 3.12 OpenSeesPy environment. JSON input contains
physical parameters and SI acceleration samples, never Stratum matrices,
connectivity, modes, damping coefficients or calculated response.
"""
import argparse
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import numpy as np
import openseespy.opensees as ops


def reference(spec):
    cfg = spec['frame']
    n, height, width = int(cfg['stories']), cfg['story_height_m'], cfg['bay_width_m']
    kind, dt = spec['system'], spec['analysis_dt_s']
    ag = np.asarray(spec['acceleration_m_s2'], float)*spec['scale_factor']
    record_dt = spec['record_dt_s']
    subdivisions = int(round(record_dt/dt))
    if subdivisions < 1 or not math.isclose(subdivisions*dt, record_dt, rel_tol=1e-12):
        raise ValueError('Analysis time step must divide the record interval')
    steps = (len(ag)-1)*subdivisions
    floor_mass = cfg['floor_mass_t']*1000
    def tag(level, position): return 100*level+position+1
    nodes = {tag(0,0):(0.,0.), tag(0,2):(width,0.)}
    for level in range(1,n+1):
        for position in range(3): nodes[tag(level,position)]=(width*position/2,height*level)
    ops.wipe()
    try:
        ops.model('basic','-ndm',2,'-ndf',3)
        for node, xy in nodes.items(): ops.node(node,*xy)
        for base in (tag(0,0), tag(0,2)): ops.fix(base,1,1,1)
        for level in range(1,n+1):
            master = tag(level,0)
            ops.mass(master,floor_mass,0.,0.)
            for position in (1,2): ops.equalDOF(master,tag(level,position),1)
        ops.geomTransf('Linear',1)
        ops.uniaxialMaterial('Elastic',1,200_000_000_000.)
        element_tag = 0
        brace_area = cfg['brace_area_mm2']/1_000_000
        if kind == 'chevron':
            brace_area *= math.sqrt(width*width+height*height)/math.sqrt(width*width/4+height*height)
        def beam(a,b,section):
            nonlocal element_tag
            element_tag += 1
            ops.element('elasticBeamColumn',element_tag,a,b,
                        cfg[section+'_area_mm2']/1_000_000,200_000_000_000.,
                        cfg[section+'_inertia_cm4']/100_000_000,1)
        def brace(a,b):
            nonlocal element_tag
            element_tag += 1
            # Truss elements omit Rayleigh damping by default: enable it to
            # represent the stipulated C = alpha*M + beta*K for the whole frame.
            ops.element('Truss',element_tag,a,b,brace_area,1,'-doRayleigh',1)
        for level in range(1,n+1):
            for position in (0,2): beam(tag(level-1,position),tag(level,position),'column')
            beam(tag(level,0),tag(level,1),'beam')
            beam(tag(level,1),tag(level,2),'beam')
            if kind == 'x':
                brace(tag(level-1,0),tag(level,2)); brace(tag(level-1,2),tag(level,0))
            elif kind == 'chevron':
                brace(tag(level-1,0),tag(level,1)); brace(tag(level-1,2),tag(level,1))
            elif kind != 'unbraced': raise ValueError('Unknown system')
        ops.constraints('Transformation')
        ops.numberer('RCM')
        ops.system('BandGeneral')
        eigenvalues = np.asarray(ops.eigen('-fullGenLapack',n))
        if np.any(~np.isfinite(eigenvalues)) or np.any(eigenvalues <= 0):
            raise RuntimeError('Reference eigenproblem did not return positive finite modes')
        omega = np.sqrt(eigenvalues)
        zeta = cfg['damping_ratio']
        alpha = 2*zeta*omega[0]*omega[1]/(omega[0]+omega[1])
        beta = 2*zeta/(omega[0]+omega[1])
        ops.rayleigh(float(alpha),float(beta),0.,0.)
        # Complete OpenSees modes independently recover initial massless DOF
        # acceleration when the record has a nonzero first sample. This avoids
        # silently adding a leading zero or changing the El Centro input.
        floor_phi = np.array([[ops.nodeEigenvector(tag(level,0),mode,1)
                               for mode in range(1,n+1)] for level in range(1,n+1)])
        norms = floor_mass*np.sum(floor_phi**2,axis=0)
        participation = floor_mass*floor_phi.sum(axis=0)/norms
        for node in nodes:
            if node in (tag(0,0),tag(0,2)): continue
            shape = np.array([ops.nodeEigenvector(node,mode) for mode in range(1,n+1)]).T
            initial = -ag[0]*(shape @ participation)
            for dof in range(1,4): ops.setNodeAccel(node,dof,float(initial[dof-1]),'-commit')
        ops.timeSeries('Path',1,'-dt',record_dt,'-values',*ag.tolist(),'-useLast')
        ops.pattern('UniformExcitation',1,1,'-accel',1)
        ops.test('NormDispIncr',1e-12,10)
        ops.algorithm('Linear')
        ops.integrator('Newmark',.5,.25)
        ops.analysis('Transient')
        time = np.arange(steps+1)*dt
        ground = np.interp(time,np.arange(len(ag))*record_dt,ag)
        u, v, a = (np.zeros((steps+1,n)) for _ in range(3))
        base_reaction = np.zeros(steps+1)
        def sample(j):
            for level in range(1,n+1):
                node=tag(level,0)
                u[j,level-1]=ops.nodeDisp(node,1)
                v[j,level-1]=ops.nodeVel(node,1)
                a[j,level-1]=ops.nodeAccel(node,1)
            ops.reactions('-dynamic')
            base_reaction[j]=sum(ops.nodeReaction(node,1) for node in (tag(0,0),tag(0,2)))
        sample(0)
        for j in range(1,steps+1):
            if ops.analyze(1,dt) != 0: raise RuntimeError(f'OpenSees failed at step {j}')
            sample(j)
        inertia_demand = -floor_mass*(a+ground[:,None]).sum(axis=1)
        # Support element forces include beta*K damping but not the virtual
        # alpha*M nodal dampers. Report both and independently check their sum.
        nodal_damping = alpha*floor_mass*v.sum(axis=1)
        recovered_demand = -base_reaction+nodal_damping
        drift = np.diff(np.column_stack((np.zeros(len(u)),u)),axis=1)/height
        return dict(system=kind,frequencies_hz=(omega/(2*math.pi)).tolist(),
            rayleigh_alpha=float(alpha),rayleigh_beta=float(beta),
            analysis_dt_s=dt,steps=steps,time_s=time.tolist(),
            displacement_m=u.tolist(),relative_acceleration_m_s2=a.tolist(),
            base_shear_kn=(inertia_demand/1000).tolist(),
            base_support_demand_kn=(-base_reaction/1000).tolist(),
            mass_damping_demand_kn=(nodal_damping/1000).tolist(),
            support_and_damper_balance_error=float(np.max(abs(inertia_demand-recovered_demand))/max(np.max(abs(inertia_demand)),1.)),
            peaks=dict(drift_pct=float(np.max(abs(drift))*100),
                       roof_mm=float(np.max(abs(u[:,-1]))*1000),
                       base_shear_kn=float(np.max(abs(inertia_demand))/1000)),
            engine=dict(name='OpenSees',version=ops.version(),python=platform.python_version(),
                        openseespy=importlib.metadata.version('openseespy')),
            model=dict(nodes=len(nodes),elements=element_tag,retained_inertial_dofs=n,
                       beam_column='elasticBeamColumn',brace='Truss, doRayleigh=1',
                       constraints='Transformation + equalDOF in horizontal direction'))
    finally:
        ops.wipe()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args()
    spec=json.loads(args.input.read_text(encoding='utf8'))
    result=reference(spec)
    args.output.write_text(json.dumps(result,allow_nan=False),encoding='utf8')


if __name__=='__main__':main()
