import json
import unittest
import numpy as np
from twin.bridge import prepare_playback, bridge_context, vehicle_forces
from twin.server import TwinService


class PlaybackTests(unittest.TestCase):
    def test_continuous_response_interpolation_matches_fresh_fem(self):
        config={'axle_spacing_m':3.7,'lane_offset_m':.8,'front_axle_kn':95,'deck_load_kn_m':12}
        damage=np.zeros(78);damage[[4,50]]=[.3,.2]
        bundle=prepare_playback(config,damage,1.4)
        model=bridge_context(config)['model'];xs=np.array(bundle['positions_m'])
        for x in (0,.01,3.7,6.125,12.789,23.999,24,24.001,27.69,27.7):
            i=min(max(np.searchsorted(xs,x,side='right')-1,0),len(xs)-2)
            t=(x-xs[i])/(xs[i+1]-xs[i])
            force=(model.loads+vehicle_forces(model,bundle['settings'],x))*1.4
            exact=model.solve(damage,forces=force)
            for field,expected in (('displacement',exact['displacement'].reshape(-1,3)),
                                   ('strain',exact['strain']),
                                   ('internal_force',(exact['reactions']+force).reshape(-1,3))):
                values=np.array(bundle[field]);approx=values[i]+(values[i+1]-values[i])*t
                np.testing.assert_allclose(approx,expected,rtol=1e-9,atol=1e-7)
        json.dumps(bundle,allow_nan=False)

    def test_exit_reaction_jump_is_not_interpolated(self):
        bundle=prepare_playback();model=bridge_context()['model'];config=bundle['settings']
        a=model.solve(forces=model.loads+vehicle_forces(model,config,24))
        b=model.solve(forces=model.loads+vehicle_forces(model,config,24+1e-8))
        # Displacement is continuous, but a front axle directly on the right
        # bearing disappears immediately after leaving the span.
        np.testing.assert_allclose(a['displacement'],b['displacement'],atol=1e-10)
        right=lambda r:r['reactions'].reshape(-1,3)[[16,17],1].sum()/1000
        self.assertAlmostEqual(right(a)-right(b),80,places=5)

    def test_api_model_and_parameter_guards(self):
        service=TwinService('bridge')
        for request in ({'model_id':'space'}, {'model_id':'bridge','load_scale':0},
                        {'model_id':'bridge','damage':[0]*21},
                        {'model_id':'bridge','removed':['4']},
                        {'model_id':'bridge','bridge':{'front_axle_kn':-1}}):
            with self.assertRaises(ValueError):service.playback(request)
        result=service.playback({'model_id':'bridge','damage':[0]*78})
        self.assertEqual(result['method'],'quasi-static')
        self.assertEqual(np.shape(result['displacement']),(57,20,3))


if __name__=='__main__':unittest.main()
