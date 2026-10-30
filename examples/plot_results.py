"""Render the reviewer figure from the saved sparse-sensing report.

Requires the optional requirements-figures.txt dependencies; no model training.
"""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def main():
    report = json.loads((ROOT/'data/bridge-sparse/report.json').read_text(encoding='utf8'))
    budgets = [5, 10, 20, 50, 131]
    rows = {(r['placement'], r['budget']): r for r in report['experiments']
            if r['noise_fraction'] == .005}
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False,
                         'axes.spines.right': False, 'savefig.facecolor': 'white'})
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.9))
    for placement, label, color, marker in [('guided', 'Healthy-model guided', '#2563eb', 'o'),
                                           ('random', 'One fixed random layout', '#c65b13', 's')]:
        accuracy = [100*rows[placement, n]['accuracy'] for n in budgets]
        severity = [rows[placement, n]['damaged_severity_mae_pp'] for n in budgets]
        for ax, values in zip(axes, (accuracy, severity)):
            ax.plot(range(5), values, marker=marker, color=color, label=label, linewidth=1.8)
    axes[0].set(ylabel='Location accuracy including healthy (%)', ylim=(0, 105),
                title='Sparse sensing changes detection accuracy')
    axes[1].set(ylabel='End-to-end damaged severity MAE (pp)', ylim=(0, None),
                title='Missed damage contributes to severity error')
    for ax in axes:
        ax.set_xticks(range(5), [str(n) for n in budgets])
        ax.set_xlabel('Physical strain/displacement channels')
        ax.grid(axis='y', alpha=.18)
    axes[0].legend(frameon=False, fontsize=9, loc='lower right')
    fig.suptitle('Paired synthetic bridge study · 528 held-out cases · 0.5% sensor noise', fontsize=12)
    fig.text(.5, .02, 'Abstentions count as errors. Wrong/rejected locations assign zero loss at the true damaged member.',
             ha='center', fontsize=8, color='#444444')
    fig.tight_layout(rect=(0, .05, 1, .92))
    path = ROOT/'data/bridge-sparse/review-summary.png'
    fig.savefig(path, dpi=180)
    print(path)


if __name__ == '__main__':
    main()
