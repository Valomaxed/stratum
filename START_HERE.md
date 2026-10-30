# Academic review guide

**Atharv Sharma · STRATUM truss/bridge digital twin**

## 1. Question and finding

How much damage-location and stiffness-loss information can be recovered from fewer strain/displacement channels in a simulated truss bridge?

Read [the results](docs/RESULTS.md). The main finding is a sensor-budget/accuracy trade-off. No reduced tested budget meets the predefined 90% validation rule, and guided placement does not beat the fixed random layout at every budget.

## 2. Source review route

| Topic | Entry point | What to inspect |
|---|---|---|
| Element formulation | [fem.py](twin/fem.py) | Axial projection, K/M assembly, support elimination and response recovery |
| Bridge model | [bridge.py](twin/bridge.py) | Four bearings, dead load, axle transfer and sweep |
| Dynamics | [bridge_dynamics.py](twin/bridge_dynamics.py) | Modal basis, damping and Newmark integration |
| Learning | [bridge_learning.py](twin/bridge_learning.py) | Measurement features, targets, splits and acquisition scope |
| Sparse experiment | [bridge_sparse.py](twin/bridge_sparse.py) | Healthy-model placement, selected-only features and paired evaluation |
| Verification | [tests](tests/) | Analytical, balance, independent ODE and convergence checks |

NumPy/SciPy provide linear algebra and scikit-learn provides the forests. Structural assembly, load transfer, sensing/evaluation and visualization are implemented around those libraries.

## 3. Run without training

Install requirements.txt, then run from the repository root:

```bash
python examples/quick_review.py
```

The example compares a healthy bridge with configured 40% M05 stiffness loss under identical static loads. It prints deformation, frequency, forces and equilibrium residuals. Compare [recorded output](data/review-example.json). The damage is known input to this FEM example, not a predicted result.

Run `python -m twin serve` for the browser workspace at http://127.0.0.1:8766/.

## 4. Assess the evidence

[Results and definitions](docs/RESULTS.md) · [Reproduction levels](docs/REPRODUCIBILITY.md) · [Full protocol](docs/RESEARCH.md) · [Support audit](data/support-review.md)

Training and test use the same FEM family. Healthy cases are noise replicates of one physical state. Numerical consistency and within-family predictive performance are distinct from physical transfer, which requires future validation.

## 5. Further research

Broader load/speed/damage families, sparse dropout/drift, uncertainty calibration and physical measurements require new datasets and validation. These are proposed extensions.

[Authorship](AUTHORS.md) · [Private access](docs/REVIEWER_ACCESS.md) · [Architecture](docs/ARCHITECTURE.md)
