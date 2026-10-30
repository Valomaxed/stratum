# Reproducibility and review levels

| Level | What can be checked | Requirements |
|---|---|---|
| Read | Question, source, results and figures | Repository access |
| Run FEM | Healthy/damaged example and viewer | Python + requirements.txt; no trained models |
| Core checks | Analytical, balance, modal, ODE and service checks | Python; Node.js for playback checks |
| Redraw figures | Saved JSON summary metrics | requirements-figures.txt |
| Repeat bridge ML | Dataset, forests, frozen policy and predictions | Full training/study jobs, more time/memory |

## Fast example

```bash
python examples/quick_review.py --output work/review-example.json
```

Run from the repository root after dependency installation. Compare engineering values with [recorded output](../data/review-example.json), allowing floating-point differences. Residuals quantify numerical consistency, not model-to-reality error.

## Full predictive study

```bash
python -m twin bridge-train --cases-per-member 40 --healthy-cases 400 --workers 2 --seed 281026
python -m twin bridge-sparse-study --workers 2
```

The second command reuses the baseline dataset and split. Keep hash-bound datasets, forests, placement and selection reports together. Exact serialized artifacts can vary with dependency versions. Original package versions are in requirements-lock.txt; CI exercises compatible dependencies separately. Planar studies have separate artifacts and are described in [RESEARCH.md](RESEARCH.md).

## Figure reproduction

```bash
python -m pip install -r requirements-figures.txt
python examples/plot_results.py
```

This redraws the saved report; it does not independently audit raw predictions or retrain. Raw-prediction tests run when local artifacts are present and explicitly skip otherwise. CI does not repeat the expensive training study.

Cite the commit alongside any reported result. [CITATION.cff](../CITATION.cff) supplies software attribution. The original combined workspace remains at tag `pre-split-2026-10-30`.
