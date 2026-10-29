"""Independent analytical, equilibrium and convergence checks for seismic frames."""
import unittest
from pathlib import Path
import numpy as np
from scipy.integrate import solve_ivp
from twin.dynamics import newmark_linear
from twin.seismic import G, parse_at2, beam_stiffness, build_frame, frame_history, compare


class SeismicTests(unittest.TestCase):
    def record(self, dt=.02):
        t=np.arange(round(2/dt)+1)*dt
        a=.1*G*np.sin(2*np.pi*1.3*t)*np.sin(np.pi*t/2)**2
        return dict(npts=len(t),dt=dt,acceleration=a)

    def test_cantilever_beam_matches_bending_and_axial_solutions(self):
        e,a,i,l=200e9,.01,2e-4,3.
        for endpoint,load,expected in [([l,0],[0,1000,0],[0,1000*l**3/(3*e*i),1000*l*l/(2*e*i)]),
                                      ([0,l],[-1000,0,0],[-1000*l**3/(3*e*i),0,1000*l*l/(2*e*i)]),
                                      ([l,0],[1000,0,0],[1000*l/(e*a),0,0])]:
            k=beam_stiffness([0,0],endpoint,a,i,e)
            np.testing.assert_allclose(np.linalg.solve(k[3:,3:],load),expected,atol=1e-13)
            np.testing.assert_allclose(k,k.T,atol=1e-10)

    def test_shared_newmark_matches_independent_ode_and_converges(self):
        errors=[]
        omega,zeta=7.,.03
        def rhs(t,y): return [y[1],np.sin(3*t)-2*zeta*omega*y[1]-omega**2*y[0]]
        for dt in (.02,.01,.005):
            time=np.arange(round(2/dt)+1)*dt
            f=np.sin(3*time)[:,None]
            r=newmark_linear([[omega**2]],[[1]],[[2*zeta*omega]],f,dt)
            reference=solve_ivp(rhs,[0,2],[0,0],t_eval=time,rtol=1e-11,atol=1e-13)
            errors.append(np.max(np.abs(r['displacement'][:,0]-reference.y[0])))
            self.assertLess(r['relative_residual'],1e-10)
        self.assertTrue(3.8<errors[0]/errors[1]<4.2)
        self.assertTrue(3.8<errors[1]/errors[2]<4.2)

    def test_condensation_preserves_energy_and_massless_equilibrium(self):
        for system in ('unbraced','x','chevron'):
            f=build_frame(system=system); u=np.array([.001,.002,.004,.007])
            full=f['recovery'] @ u; force=f['full_K'] @ full
            self.assertAlmostEqual(full @ f['full_K'] @ full,u @ f['K'] @ u,places=8)
            # Every upper node has zero vertical and moment unbalanced force.
            np.testing.assert_allclose(force.reshape(-1,3)[3:,1:],0,atol=1e-7)
            self.assertAlmostEqual(force.reshape(-1,3)[:3,0].sum(),-sum(f['K'] @ u),places=6)
            phi=f['modes']
            np.testing.assert_allclose(phi.T @ f['M'] @ phi,np.eye(4),atol=1e-12)
            self.assertTrue(np.all(f['omega']>0))
        x,c=build_frame(system='x'),build_frame(system='chevron')
        self.assertAlmostEqual(x['brace_volume_m3'],c['brace_volume_m3'],places=12)
        self.assertGreater(x['omega'][0],build_frame()['omega'][0])

    def test_ground_acceleration_initial_state_shear_balance_and_linearity(self):
        f=build_frame(system='chevron'); motion=self.record()
        r=frame_history(f,motion); doubled=frame_history(f,motion,2)
        for key in ('peak_drift_pct','peak_roof_mm','peak_base_shear_kn'):
            self.assertAlmostEqual(doubled[key],2*r[key],places=9)
        self.assertLess(r['integration']['relative_residual'],1e-8)
        self.assertLess(r['integration']['base_shear_balance_error'],1e-8)
        self.assertAlmostEqual(r['history']['time_s'][-1],2.)
        nonzero=dict(npts=3,dt=.02,acceleration=np.array([G,0,0]))
        initial=frame_history(f,nonzero)['history']
        self.assertEqual(initial['roof_mm'][0],0.)
        self.assertAlmostEqual(initial['roof_absolute_acceleration_m_s2'][0],0.,places=10)
        zeros=frame_history(f,dict(npts=5,dt=.02,acceleration=np.zeros(5)))
        self.assertEqual(zeros['peak_base_shear_kn'],0.)

    def test_real_record_count_provenance_and_validation(self):
        p=Path(__file__).resolve().parents[1]/'web/records/el-centro-1940.at2'
        text=p.read_text(); r=parse_at2(text)
        self.assertEqual(r['npts'],1559); self.assertEqual(r['dt'],.02)
        self.assertEqual(r['sha256'],'fcc4417f9eba2083d8573010659d1e8177e1f795f47a8e8faa9382ef6fa753a0')
        self.assertAlmostEqual(max(abs(r['acceleration']))/G,.31882,places=5)
        for bad in (text.replace('1559, DT','1560, DT'),text+'\n0.0',text.replace('0.00630','nan',1),text.replace('DT= .02000','DT= 0')):
            with self.assertRaises(ValueError):parse_at2(bad)
        with self.assertRaises(ValueError):parse_at2(text,'m/s2')
        r=parse_at2('PEER ACCELERATION IN UNITS OF G\nNPTS= 3, DT= .01 SEC\n0.0 1.0D-1 0.0')
        self.assertAlmostEqual(r['acceleration'][1],.1*G)

    def test_comparison_and_invalid_inputs(self):
        record=dict(text='ACCELERATION IN UNITS OF G\nNPTS= 3, DT= .02 SEC\n0 .1 0',unit='g',name='test')
        r=compare(dict(record=record))
        self.assertEqual(len(r['systems']),3)
        for bad in ({'frame':{'stories':3.5}}, {'frame':{'floor_mass_t':float('nan')}},
                    {'scale_factor':0}, {'scale_factor':True}, {'frame':{'unknown':1}}):
            with self.assertRaises(ValueError):compare(dict(record=record)|bad)

    def test_frame_response_against_independent_state_space_solution(self):
        frame=build_frame({'stories':2},'x'); record=self.record()
        r=frame_history(frame,record)
        k,m=frame['K'],frame['M']; integ=r['integration']
        c=integ['rayleigh_alpha']*m+integ['rayleigh_beta']*k
        original_time=np.arange(record['npts'])*record['dt']
        def rhs(t,state):
            u,v=state[:2],state[2:]
            return np.r_[v,np.linalg.solve(m,-k @ u-c @ v)-np.interp(t,original_time,record['acceleration'])]
        time=np.array(r['history']['time_s'])
        reference=solve_ivp(rhs,[0,time[-1]],np.zeros(4),t_eval=time,rtol=1e-10,atol=1e-12,max_step=.002)
        observed=np.array(r['history']['floor_displacement_mm'])/1000
        relative=np.linalg.norm(observed-reference.y[:2].T)/np.linalg.norm(reference.y[:2])
        self.assertLess(relative,.003)


if __name__=='__main__':unittest.main()
