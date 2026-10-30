"""Run a small bridge FEM comparison without a server or trained ML models.

Run from the repository root: python examples/quick_review.py
"""
import argparse
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from twin.bridge import bridge_context


def run():
    context = bridge_context()
    model = context['model']
    force = context['cases'][1]['forces']  # Dead + static vehicle at x=12 m.
    rows = []
    for name, loss in [('Healthy', 0.), ('M05 stiffness loss 40%', .4)]:
        damage = np.zeros(len(model.members)); damage[4] = loss
        response = model.solve(damage, forces=force)
        u = response['displacement'].reshape(-1, 3)
        deck = [4*i+j for i in range(5) for j in (0, 1)]
        total = (response['reactions']+force).reshape(-1, 3)
        rows.append({'configuration': name,
                     'peak_displacement_mm': float(np.linalg.norm(u, axis=1).max()*1000),
                     'deck_down_mm': float(max(0., -u[deck, 1].min())*1000),
                     'first_frequency_hz': float(model.modes(damage, 1)['frequencies'][0]),
                     'M05_axial_force_kn': float(response['axial_force'][4]/1000),
                     'global_force_balance_error_n': float(np.linalg.norm(total.sum(axis=0))),
                     'global_moment_balance_error_nm': float(np.linalg.norm(np.cross(model.nodes, total).sum(axis=0)))})
    return {'example': 'Static FEM comparison; configured damage is known input',
            'settings': context['config'], 'rows': rows,
            'scope': 'Linear axial truss. This example performs no ML inference or capacity assessment.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Optional JSON result path')
    args = parser.parse_args()
    result = run()
    text = json.dumps(result, indent=2, allow_nan=False)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf8')
    print(text, end='')


if __name__ == '__main__':
    main()
