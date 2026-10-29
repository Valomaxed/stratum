"""Static bridge load transfer, bearing equilibrium and envelope checks."""
import json
import unittest
import numpy as np
from twin.bridge import (GRAVITY, settings, bridge_truss, axle_forces,
                         vehicle_forces, bridge_context, bridge_report)
from twin.server import TwinService


class BridgeTests(unittest.TestCase):
    def test_bearing_layout_stability_and_expansion(self):
        model=bridge_truss();restraints=model.fixed_dofs
        self.assertEqual(restraints.tolist(),[0,1,2,4,49,50,52])
        # Restrained components must eliminate all six rigid-body modes.
        rigid=np.zeros((60,6))
        for i,p in enumerate(model.nodes):
            rigid[3*i:3*i+3,:3]=np.eye(3)
            rigid[3*i:3*i+3,3:]=np.array([np.cross(axis,p) for axis in np.eye(3)]).T
        self.assertEqual(np.linalg.matrix_rank(rigid[restraints]),6)
        # Uniform expansion about the fixed bearing satisfies every restraint:
        # X movement is permitted at both right-end bearings, Z across width.
        expansion=(model.nodes-model.nodes[0]).ravel()*1e-4
        np.testing.assert_array_equal(expansion[restraints],0)
        self.assertTrue(all(3*i+1 in restraints for i in (0,1,16,17)))
        self.assertTrue(all(3*i not in restraints for i in (16,17)))
        k,_,_=model.assemble();self.assertGreater(np.linalg.eigvalsh(k[np.ix_(model.free,model.free)])[0],0)
        for axis in range(3):
            force=np.zeros((20,3));force[8,axis]=10000
            r=model.solve(forces=force.ravel())
            np.testing.assert_allclose(r['reactions'][model.free],0,atol=1e-7)
            np.testing.assert_allclose((r['reactions'].reshape(-1,3)+force).sum(axis=0),0,atol=1e-7)

    def test_axle_transfer_conserves_force_and_two_moments(self):
        model = bridge_truss()
        for x in (0,1.25,6,12.4,24):
            for z in (-1.2,0,1.2):
                force = axle_forces(model,x,80,z).reshape(-1,3)
                np.testing.assert_allclose(force.sum(axis=0),[0,-80000,0],atol=1e-9)
                np.testing.assert_allclose(np.cross(model.nodes,force).sum(axis=0),[80000*z,0,-80000*x],atol=1e-8)
        np.testing.assert_array_equal(axle_forces(model,-.01,80),0)
        np.testing.assert_array_equal(axle_forces(model,24.01,80),0)
        exact = axle_forces(model,6,80,0).reshape(-1,3)
        self.assertEqual(np.count_nonzero(exact),2)
        np.testing.assert_allclose(exact[[4,5],1],[-40000,-40000])

    def test_dead_load_and_deck_mass_are_consistent(self):
        model = bridge_truss(10)
        steel_mass = np.sum(model.density*model.area*model.lengths)
        expected = steel_mass*GRAVITY+10000*24
        self.assertAlmostEqual(-model.loads.reshape(-1,3)[:,1].sum(),expected,places=7)
        self.assertAlmostEqual(model.nodal_mass.sum()*GRAVITY,240000,places=7)
        self.assertEqual(len(model.free),53)
        response = model.solve()
        total = (response['reactions']+model.loads).reshape(-1,3)
        np.testing.assert_allclose(total.sum(axis=0),0,atol=1e-7)
        np.testing.assert_allclose(np.cross(model.nodes,total).sum(axis=0),0,atol=1e-6)

    def test_abutment_reactions_match_simple_statics(self):
        model = bridge_truss(); config=settings({'vehicle_position_m':15})
        dead = model.solve()['reactions'].reshape(-1,3)
        live = vehicle_forces(model,config)
        combined = model.solve(forces=model.loads+live)['reactions'].reshape(-1,3)
        increment = combined-dead
        expected_right = (80000*15+120000*11)/24
        self.assertAlmostEqual(increment[[16,17],1].sum(),expected_right,places=6)
        self.assertAlmostEqual(increment[[0,1],1].sum(),200000-expected_right,places=6)
        # Axles already beyond an abutment do not keep applying force to it.
        off = settings({'vehicle_position_m':28})
        self.assertAlmostEqual(-vehicle_forces(model,off).reshape(-1,3)[:,1].sum(),120000)

    def test_sweep_envelopes_bound_independent_solves(self):
        context=bridge_context({'vehicle_position_m':13.1,'axle_spacing_m':3.7,'lane_offset_m':.8})
        model=context['model']; config=context['config']; damage=np.zeros(78);damage[4]=.3
        force=context['cases'][1]['forces']; result=model.solve(damage,forces=force)
        report=bridge_report(model,config,damage,1,[],result,force,'LC2')
        sweep=report['sweep']
        for event in np.r_[np.arange(0,25,6),np.arange(0,25,6)+3.7]:
            self.assertTrue(np.any(np.isclose(sweep['positions_m'],event)))
        rng=np.random.default_rng(42)
        for position in rng.uniform(0,27.7,12):
            sample=model.solve(damage,forces=model.loads+vehicle_forces(model,config,position))
            axial=sample['axial_force']/1000
            self.assertTrue(np.all(axial>=np.array(sweep['member_min_axial_kn'])-1e-8))
            self.assertTrue(np.all(axial<=np.array(sweep['member_max_axial_kn'])+1e-8))
            down=max(0,-sample['displacement'].reshape(-1,3)[report['deck_nodes'],1].min())*1000
            self.assertLessEqual(down,sweep['peak_down_mm']+1e-8)
        self.assertAlmostEqual(report['current']['vertical_balance_error_kn'],0,places=8)
        json.dumps(report,allow_nan=False)

    def test_zero_vehicle_gives_constant_dead_load_envelope(self):
        context=bridge_context({'front_axle_kn':0,'rear_axle_kn':0})
        model=context['model'];force=model.loads;result=model.solve()
        report=bridge_report(model,context['config'],np.zeros(78),1,[],result,force,'LC1')
        np.testing.assert_allclose(report['sweep']['deck_down_mm'],report['current']['deck_down_mm'],atol=1e-10)
        np.testing.assert_allclose(report['sweep']['member_min_axial_kn'],result['axial_force']/1000,atol=1e-10)
        self.assertFalse(report['vehicle']['visible'])

    def test_service_uses_current_vehicle_and_explicit_bridge_model(self):
        service=TwinService('bridge')
        first=service.analyze({'display_case':'LC2','protocol':'multi','noise':0,'sensor_count':10,
                               'bridge':{'vehicle_position_m':6,'lane_offset_m':1}})
        last=service.analyze({'display_case':'LC2','protocol':'multi','noise':0,'sensor_count':10,
                              'bridge':{'vehicle_position_m':18,'lane_offset_m':1}})
        self.assertEqual(first['model_id'],'bridge')
        self.assertEqual(first['summary']['sensor_capacity'],131)
        self.assertFalse(first['prediction']['available'])
        self.assertGreater(first['bridge']['current']['left_reaction_kn'],last['bridge']['current']['left_reaction_kn'])
        self.assertEqual(last['bridge']['vehicle']['front_x'],18)
        for response in (first,last):
            self.assertEqual(len(response['bridge']['supports']),4)
            self.assertAlmostEqual(response['bridge']['current']['vertical_balance_error_kn'],0,places=7)
            self.assertEqual(response['excitation']['active_observations'],30)
            json.dumps(response,allow_nan=False)

    def test_invalid_bridge_parameters_rejected(self):
        for config in ({'vehicle_position_m':float('nan')},{'front_axle_kn':-1},
                       {'axle_spacing_m':0},{'lane_offset_m':2},{'deck_load_kn_m':31},
                       {'vehicle_position_m':29},{'unknown':1},[]):
            with self.assertRaises(ValueError):settings(config)


if __name__=='__main__':unittest.main()
