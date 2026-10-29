import unittest
import numpy as np
from scipy.integrate import solve_ivp
from twin.bridge import bridge_context, vehicle_forces
from twin.bridge_dynamics import prepare_dynamic_playback, _history
from twin.server import TwinService


class MovingDynamicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle=prepare_dynamic_playback(dynamic={'speed_kmh':72})

    def test_equilibrium_constraints_and_initial_dead_load(self):
        b=self.bundle;model=bridge_context()['model'];u=np.array(b['displacement']).reshape(-1,60)
        np.testing.assert_allclose(u[0],model.solve()['displacement'],atol=1e-12)
        np.testing.assert_array_equal(u[:,model.fixed_dofs],0)
        for i in range(0,len(u),31):
            force=model.loads+vehicle_forces(model,b['settings'],b['positions_m'][i])
            reaction=np.array(b['internal_force'][i]).ravel()-force
            np.testing.assert_allclose(reaction[model.free],0,atol=1e-5)
            self.assertAlmostEqual((reaction[1::3].sum()+force[1::3].sum())/1000,b['dynamic_vertical_kn'][i],places=7)
        self.assertLess(b['integration']['relative_residual'],1e-8)

    def test_independent_physical_dof_integrator(self):
        b=self.bundle;model=bridge_context()['model'];free=model.free;k,m,_=model.assemble()
        c=b['integration']['rayleigh_alpha']*m+b['integration']['rayleigh_beta']*k
        k=k[np.ix_(free,free)];c=c[np.ix_(free,free)];mass=np.diag(m)[free]
        n=len(free);speed=20
        def rhs(t,z):
            return np.r_[z[n:],(vehicle_forces(model,b['settings'],speed*t)[free]-c@z[n:]-k@z[:n])/mass]
        times=np.array(b['signal']['time']);ix=np.arange(0,len(times),53)
        exact=solve_ivp(rhs,(0,times[-1]),np.zeros(2*n),method='DOP853',rtol=2e-9,atol=1e-11,t_eval=times[ix])
        self.assertTrue(exact.success)
        sensor=np.flatnonzero(free==25)[0]
        dead=model.solve()['displacement'][25]
        np.testing.assert_allclose(np.array(b['signal']['displacement_mm'])[ix],(exact.y[sensor]+dead)*1000,atol=2e-4)
        expected=np.array([rhs(t,z)[n+sensor] for t,z in zip(exact.t,exact.y.T)])
        np.testing.assert_allclose(np.array(b['signal']['acceleration'])[ix],expected,atol=.006)

    def test_zero_live_load_stays_at_equilibrium(self):
        b=prepare_dynamic_playback({'front_axle_kn':0,'rear_axle_kn':0},dynamic={'speed_kmh':120})
        np.testing.assert_array_equal(b['signal']['acceleration'],0)
        self.assertLess(np.ptp(b['signal']['displacement_mm']),1e-12)

    def test_speed_damage_and_free_vibration(self):
        b=self.bundle
        self.assertAlmostEqual(b['crossing_time_s'],1.4)
        self.assertAlmostEqual(b['time_s'][-1],3.4)
        times=np.array(b['signal']['time']);a=np.array(b['signal']['acceleration'])
        self.assertGreater(np.max(np.abs(a[times>b['crossing_time_s']+.05])),.001)
        loss=np.zeros(78);loss[4]=.5
        damaged=prepare_dynamic_playback(damage=loss,dynamic={'speed_kmh':72})
        self.assertGreater(np.max(np.abs(np.array(damaged['signal']['strain_micro']))),np.max(np.abs(b['signal']['strain_micro'])))
        self.assertFalse(np.allclose(np.array(damaged['healthy_deck_down_mm']),np.maximum(0,-np.array(damaged['displacement'])[:,[0,1,4,5,8,9,12,13,16,17],1].min(axis=1))*1000))

    def test_time_step_convergence(self):
        context=bridge_context();args=(context['model'],context['config'],None,1,(),20,.02)
        coarse=_history(*args,step_factor=30);fine=_history(*args,step_factor=60)
        t=np.array(coarse['trace']['time'])
        for key,tolerance in [('displacement_mm',.0002),('acceleration',.006)]:
            expected=np.interp(t,fine['trace']['time'],fine['trace'][key])
            self.assertLess(np.max(np.abs(np.array(coarse['trace'][key])-expected)),tolerance)

    def test_api_guards(self):
        service=TwinService('bridge')
        for extra in ({'method':'unknown'},{'dynamic':{'speed_kmh':0}}, {'dynamic':{'speed_kmh':float('nan')}},
                      {'dynamic':{'damping_ratio':-.1}}, {'dynamic':{'extra':3}}, {'damage':[0]*21}, {'removed':[78]}):
            request={'model_id':'bridge','method':'dynamic-moving-force',**extra}
            with self.assertRaises(ValueError):service.playback(request)
        result=service.playback({'model_id':'bridge','method':'dynamic-moving-force','dynamic':{'speed_kmh':120}})
        self.assertEqual(result['method'],'dynamic-moving-force')

    def test_healthy_comparison_is_identical(self):
        b=self.bundle
        np.testing.assert_array_equal(b['healthy_displacement'],b['displacement'])
        self.assertEqual(b['healthy_signal'],b['signal'])
        self.assertEqual(b['comparison']['damaged_members'],[])
        for row in b['comparison']['rows']:
            self.assertEqual(row['current'],row['healthy'])
            self.assertEqual(row['change_pct'],0)

    def test_reference_preserves_loads_mass_and_native_time_grid(self):
        config={'deck_load_kn_m':14,'lane_offset_m':.9,'front_axle_kn':100,'rear_axle_kn':130,'axle_spacing_m':3.7}
        dynamic={'speed_kmh':65,'damping_ratio':.035};loss=np.zeros(78);loss[[4,20]]=[.4,.25]
        b=prepare_dynamic_playback(config,loss,1.3,dynamic=dynamic)
        healthy=prepare_dynamic_playback(config,load_scale=1.3,dynamic=dynamic)
        self.assertEqual(b['healthy_signal'],healthy['signal'])
        self.assertEqual(b['comparison']['healthy_integration'],healthy['comparison']['healthy_integration'])
        self.assertNotEqual(b['signal']['time'],b['healthy_signal']['time'])
        self.assertEqual([m['id'] for m in b['comparison']['damaged_members']],[4,20])
        u=np.array(healthy['displacement']).reshape(-1,60)
        expected=np.array([np.interp(b['time_s'],healthy['time_s'],u[:,j]) for j in range(60)]).T.reshape(-1,20,3)
        np.testing.assert_allclose(b['healthy_displacement'],expected,atol=1e-12)
        for row in b['comparison']['rows'][:3]:
            self.assertAlmostEqual(row['healthy'],max(abs(v) for v in healthy['signal'][row['id']]))
            self.assertAlmostEqual(row['current'],max(abs(v) for v in b['signal'][row['id']]))
            self.assertAlmostEqual(row['change_pct'],100*(row['current']/row['healthy']-1))
        np.testing.assert_allclose([row['healthy'] for row in b['comparison']['rows'][3:]],
                                   bridge_context(config)['model'].modes(count=4)['frequencies'])

    def test_comparison_handles_zero_reference_and_member_removal(self):
        zero=prepare_dynamic_playback({'front_axle_kn':0,'rear_axle_kn':0},dynamic={'speed_kmh':120})
        self.assertEqual(zero['comparison']['rows'][0]['healthy'],0)
        self.assertIsNone(zero['comparison']['rows'][0]['change_pct'])
        removed=prepare_dynamic_playback(removed=[4],dynamic={'speed_kmh':120})
        self.assertEqual(removed['comparison']['damaged_members'],[
            {'id':4,'name':'M05','stiffness_loss':1.,'removed':True}])
        self.assertEqual(len(removed['comparison']['rows']),7)


if __name__=='__main__':unittest.main()
