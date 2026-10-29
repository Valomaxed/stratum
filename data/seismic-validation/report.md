# Stratum seismic solver verification

Generated: 2026-10-29T16:47:16.188110+00:00

Overall result: **PASS**. 9/9 independent comparisons; 3/3 time-step studies.

## Independent implementation

OpenSees independently assembles elasticBeamColumn and axial Truss elements, applies fixed supports and horizontal equalDOF floor constraints, and retains its full massless vertical/rotation DOFs. It receives physical parameters and SI acceleration samples; it does not receive Stratum stiffness/mass matrices, connectivity, eigenvectors, damping coefficients or calculated response. Both engines use Newmark average acceleration and the same time grid, so this verifies implementation consistency rather than comparing different integration methods. All finite floor modes are compared.

The real earthquake is the bundled 31.16 s El Centro 1940 N–S Peknold example (1559 samples, DT=0.02 s). Two additional synthetic QA signals exercise 2- and 8-story models, changed sections/masses/geometry, zero and nonzero initial acceleration, 0% and 10% damping, and amplitude factors 1.7 and 0.65. They are verification fixtures, not an earthquake suite.

A nonzero first sample is retained. OpenSees initial relative accelerations, including massless DOFs, are recovered from its own complete eigenbasis and committed before integration; no leading zero or time shift is introduced. Rayleigh damping targets the first two independently calculated modes. Brace Rayleigh damping is explicitly enabled.

Reference engine: OpenSees 3.8.0, OpenSeesPy 3.8.0.0, Python 3.12.14. Stratum runtime: Python 3.13.5, NumPy 2.5.4, SciPy 1.18.1.

## Full-history comparison

| Case | System | Max frequency error (%) | Floor displacement history error (%) | Base shear history error (%) | Result |
|---|---|---:|---:|---:|---|
| el-centro-default-4-story | Unbraced | 2.38e-12 | 1.32e-09 | 4.38e-09 | PASS |
| el-centro-default-4-story | X-braced | 3.33e-13 | 2.53e-09 | 3.97e-09 | PASS |
| el-centro-default-4-story | Chevron | 1.11e-13 | 5.82e-09 | 6.56e-09 | PASS |
| synthetic-2-story-undamped | Unbraced | 1.34e-12 | 9.36e-11 | 9.9e-11 | PASS |
| synthetic-2-story-undamped | X-braced | 9.99e-14 | 1.89e-11 | 1.66e-11 | PASS |
| synthetic-2-story-undamped | Chevron | 2.22e-13 | 1.24e-11 | 1.41e-11 | PASS |
| synthetic-8-story-damped | Unbraced | 6.39e-12 | 1.25e-10 | 4.05e-10 | PASS |
| synthetic-8-story-damped | X-braced | 1.98e-12 | 7.67e-10 | 7.42e-10 | PASS |
| synthetic-8-story-damped | Chevron | 1.62e-12 | 1.13e-09 | 1.02e-09 | PASS |

History error is maximum absolute pointwise difference divided by the maximum absolute reference amplitude, over every integration sample (not a pointwise percentage near zero crossings). Roof absolute acceleration and drift/roof/shear peaks are also checked in the machine report.

## Time-step convergence: full El Centro record

| System | dt / dt2 / dt4 (s) | Drift change, dt→dt4 (%) | Roof change (%) | Shear change (%) | History error ratio | Result |
|---|---|---:|---:|---:|---:|---|
| Unbraced | 0.004 / 0.002 / 0.001 | 0.0179 | 0.0066 | 0.0603 | 3.999 | PASS |
| X-braced | 0.002 / 0.001 / 0.0005 | 0.0007 | 0.0037 | 0.0178 | 4.000 | PASS |
| Chevron | 0.00166667 / 0.000833333 / 0.000416667 | 0.0072 | 0.0233 | 0.0339 | 4.000 | PASS |

The convergence ratio is ‖u(dt)−u(dt/2)‖ / ‖u(dt/2)−u(dt/4)‖ with all floor histories compared on the original grid. A value near four is consistent with second-order integration. Peaks are evaluated on each run’s full grid. This is a refinement check, not an exact-solution error bound.

## Predeclared acceptance criteria

- Relative modal-frequency error ≤ 1e-7; normalized maximum history and relative peak errors ≤ 1e-6.
- Independent OpenSees support/damping force-balance error ≤ 1e-7.
- Current-step versus quarter-step drift/roof/shear peak changes ≤ 1%; half versus quarter ≤ 0.25%.
- Floor-history refinement ratio between 3 and 5.

## Base shear convention

Both compare generalized base shear demand V = −Σ m(a_relative + ag), equivalent to Stratum’s Σ(Ku + Cv). OpenSees separately recovers column-base support forces including stiffness-proportional damping. Its mass-proportional nodal dampers are not column elements, so their forces are added when checking support-plus-damper equilibrium. Raw support shear and nodal damping contributions are retained in the trace archive. Generalized demand is not solely the elastic column-end shear.

## Scope and reproducibility

These results verify the stated elastic idealization and the exercised configurations. They do not validate yielding, buckling, gravity/P–Delta, soil interaction, connection behavior, a real building or code compliance. The real-record study covers one example earthquake, not a hazard-selected suite. Source hashes and the raw input accelerogram identify this run; the app marks the saved report stale when numerical source or record hashes change.

Run: `python -m twin.seismic_benchmark --opensees-python work/opensees-venv/Scripts/python.exe`.

References: [OpenSees elasticBeamColumn](https://openseespydoc.readthedocs.io/en/latest/src/elasticBeamColumn.html), [equalDOF](https://openseespydoc.readthedocs.io/en/latest/src/equalDOF.html), [Truss Rayleigh option](https://openseespydoc.readthedocs.io/en/latest/src/trussEle.html), [Path time series](https://openseespydoc.readthedocs.io/en/latest/src/pathTs.html), [setNodeAccel](https://openseespydoc.readthedocs.io/en/latest/src/setNodeAccel.html).
