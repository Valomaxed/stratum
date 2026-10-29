"""Reproducible support/equilibrium audit. Run: python -m twin.support_audit."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import numpy as np
from .models import FACTORIES, CASE_FACTORIES, describe_model
from .bridge import bridge_context, vehicle_forces
from .bridge_dynamics import _history
from .seismic import build_frame

ROOT = Path(__file__).resolve().parents[1]


def audit():
    report = {'generated_utc': datetime.now(timezone.utc).isoformat(), 'trusses': [], 'frames': []}
    for name, factory in FACTORIES.items():
        model = factory()
        dim = model.dim
        xyz = np.zeros((len(model.nodes), 3)); xyz[:, :dim] = model.nodes
        rigid = np.zeros((model.nodes.size, 3 if dim == 2 else 6))
        for i, p in enumerate(model.nodes):
            rigid[dim*i:dim*(i+1), :dim] = np.eye(dim)
            if dim == 2:
                rigid[2*i:2*i+2, 2] = [-p[1], p[0]]
            else:
                rigid[3*i:3*i+3, 3:] = np.array([np.cross(a, p) for a in np.eye(3)]).T
        rank = int(np.linalg.matrix_rank(rigid[model.fixed_dofs]))
        assert rank == rigid.shape[1], f'{name}: rigid body motion remains'
        expansion = (model.nodes-model.nodes[0]).ravel()*1e-4
        assert np.max(np.abs(expansion[model.fixed_dofs])) == 0
        metadata = describe_model(name, model)['supports']
        published = sorted(model.dim*s['node']+'XYZ'.index(a) for s in metadata for a in s['axes'])
        assert published == model.fixed_dofs.tolist(), f'{name}: UI restraints differ'
        cases = []
        for damaged in (False, True):
            loss = np.zeros(len(model.members))
            if damaged: loss[[0, 4]] = [.2, .4]
            for case in CASE_FACTORIES[name](model):
                force = case['forces']
                result = model.solve(loss, forces=force)
                u = result['displacement']; reactions = result['reactions']
                # Reconstruct joint forces from member axial forces, without K*u.
                nodal = np.zeros_like(model.nodes)
                element_energy = 0.
                for i, (a, b) in enumerate(model.members):
                    delta = model.nodes[b]-model.nodes[a]
                    length = np.linalg.norm(delta); direction = delta/length
                    extension = (u.reshape(-1, dim)[b]-u.reshape(-1, dim)[a]) @ direction
                    axial = result['axial_force'][i]
                    nodal[a] -= axial*direction; nodal[b] += axial*direction
                    element_energy += .5*axial*extension
                residual = nodal.ravel()-force-reactions
                total = np.zeros_like(xyz); total[:, :dim] = (force+reactions).reshape(-1, dim)
                force_error = float(np.max(np.abs(total.sum(axis=0))))
                moment_error = float(np.max(np.abs(np.cross(xyz, total).sum(axis=0))))
                joint_error = float(np.max(np.abs(residual)))
                free_error = float(np.max(np.abs(reactions[model.free])))
                energy_error = float(abs(element_energy-.5*u @ force)/max(abs(.5*u @ force), 1.))
                assert force_error < 1e-6 and moment_error < 1e-5
                assert joint_error < 1e-6 and free_error < 1e-6 and energy_error < 1e-10
                assert np.max(np.abs(u[model.fixed_dofs])) == 0
                cases.append(dict(case=case['id'], damaged=damaged, force_error_n=force_error,
                                  moment_error_nm=moment_error, joint_error_n=joint_error,
                                  free_reaction_error_n=free_error, energy_relative_error=energy_error))
        k, m, _ = model.assemble(); modes = model.modes(count=len(model.free))
        phi = modes['shapes']; omega2 = (2*np.pi*modes['frequencies'])**2
        modal_error = float(np.linalg.norm((k @ phi-(m @ phi)*omega2)[model.free])/np.linalg.norm((k @ phi)[model.free]))
        assert modal_error < 1e-10
        eig = np.linalg.eigvalsh(k[np.ix_(model.free, model.free)])
        assert eig[0] > 0
        report['trusses'].append(dict(model=name, restraints=metadata, restrained_dofs=len(model.fixed_dofs),
            free_dofs=len(model.free), rigid_restraint_rank=rank,
            minimum_free_stiffness_eigenvalue_n_m=float(eig[0]),
            expansion_constraint_error_m=0., modal_relative_error=modal_error, cases=cases))

    context = bridge_context(); model, config = context['model'], context['config']
    dynamic = _history(model, config, None, 1., (), 20., .02, include_trace=False)
    free_error = balance_error = 0.
    for t, internal, dynamic_y in zip(dynamic['time'], dynamic['internal_force'], dynamic['dynamic_vertical_kn']):
        force = model.loads+vehicle_forces(model, config, float(t)*20.)
        reaction = internal.ravel()-force
        free_error = max(free_error, float(np.max(np.abs(reaction[model.free]))))
        balance_error = max(balance_error, abs(float((reaction[1::3]+force[1::3]).sum()/1000-dynamic_y)))
    assert free_error < 1e-5 and balance_error < 1e-8
    report['bridge_dynamic'] = dict(speed_kmh=72, free_equilibrium_error_n=free_error,
        vertical_balance_error_kn=balance_error, integration_relative_residual=dynamic['relative_residual'])

    for system in ('unbraced', 'x', 'chevron'):
        frame = build_frame(system=system)
        u = np.linspace(.001, .007, frame['config']['stories'])
        full = frame['recovery'] @ u; internal = frame['full_K'] @ full
        # Base translations/rotations are fixed; unused middle base joint is isolated.
        assert np.max(np.abs(full[:9])) == 0
        assert not any(e['a'] == 1 or e['b'] == 1 for e in frame['elements'])
        force = internal.reshape(-1, 3)
        secondary_error = float(np.max(np.abs(force[3:, 1:])))
        base_shear_error = float(abs(force[:3, 0].sum()+sum(frame['K'] @ u)))
        # Include nodal moments when taking moments about the base origin.
        moment = frame['nodes'][:, 0]*force[:, 1]-frame['nodes'][:, 1]*force[:, 0]+force[:, 2]
        moment_error = float(abs(moment.sum()))
        assert secondary_error < 1e-6 and base_shear_error < 1e-6 and moment_error < 1e-5
        report['frames'].append(dict(system=system, fixed_column_base_nodes=[0, 2],
            blocked_dofs=['UX', 'UY', 'RZ'], base_constraint_error=0.,
            massless_dof_equilibrium_error=secondary_error,
            base_shear_error_n=base_shear_error, global_moment_error_nm=moment_error))
    sources = ('twin/fem.py', 'twin/bridge.py', 'twin/bridge_dynamics.py', 'twin/models.py',
               'twin/dynamics.py', 'twin/seismic.py', 'twin/support_audit.py')
    report['source_sha256'] = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources}
    report['passed'] = True
    return report


def main():
    report = audit()
    path = ROOT/'data/support-review.json'
    path.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'report': str(path),
                      'static_truss_cases': sum(len(m['cases']) for m in report['trusses'])}))


if __name__ == '__main__':
    main()
