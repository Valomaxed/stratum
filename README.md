# STRATUM

**Structural digital twin for trusses and bridges.**

[![Tests](https://github.com/Valomaxed/stratum/actions/workflows/tests.yml/badge.svg)](https://github.com/Valomaxed/stratum/actions/workflows/tests.yml)
![Stage: research prototype](https://img.shields.io/badge/stage-research%20prototype-555555)

Combine linear FEM, virtual structural sensing, scoped machine learning and interactive 3D visualization to study structural damage.

![Dynamic bridge response comparison](data/colored-graphs-preview.jpg)

## Two focused projects

| Project | Purpose |
|---|---|
| **This repository** | Planar/spatial trusses, bridge loading, virtual sensing and damage estimation |
| [STRATUM Seismic](https://github.com/Valomaxed/stratum-seismic) | Unbraced/X-braced/chevron frames under earthquake acceleration |

The seismic application is an independent project. [Migration and original combined snapshot](docs/REPOSITORY_SPLIT.md).

## Capabilities

- **FEM:** displacement, reactions, axial forces, stress, strain, strain energy and vibration modes.
- **Bridge analysis:** four-bearing 24 m truss, dead/vehicle/wind cases, vehicle-position envelopes and dynamic moving-force crossings.
- **Interactive viewer:** orbit, zoom, select members, inspect response, animate deformation and compare healthy/configured bridges.
- **Damage estimation:** planar RF/physics inverse methods and separately trained dynamic bridge classifiers/regressors.
- **Sparse sensing:** paired 131/50/20/10/5-channel experiments with guided and fixed random placement.
- **Optional clients:** Unity static viewer and a Python bridge for calibrated external sensor packets.

## Quick start

Python 3.12 or 3.13 is recommended for the documented development workflow. Run from a source checkout; the web assets and research artifacts live alongside the Python package.

```bash
git clone https://github.com/Valomaxed/stratum.git
cd stratum
python -m venv .venv
```

**Windows PowerShell**

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m twin serve --host 127.0.0.1 --port 8766
```

**macOS / Linux**

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m twin serve --host 127.0.0.1 --port 8766
```

Open **http://127.0.0.1:8766/**. Select a structure, set loading and configured damage, then run the analysis. Use **Play crossing** for dynamics or **Use M05 · 40% loss** for a healthy/damaged comparison. [Unity setup](unity/README.md).

## Machine-learning artifacts

The repository includes source, tests, reports and previews. Trained forests and generated datasets are excluded. **FEM and visualization run without them; ML panels explicitly report unavailable until training is complete.**

```powershell
.\.venv\Scripts\python.exe -m twin train
.\.venv\Scripts\python.exe -m twin study
.\.venv\Scripts\python.exe -m twin robust-study
.\.venv\Scripts\python.exe -m twin bridge-train --workers 2
.\.venv\Scripts\python.exe -m twin bridge-sparse-study --workers 2
```

Sparse bridge training depends on the preceding bridge baseline. Training jobs can take several minutes or longer. [Experiment protocols, metrics and regeneration details](docs/RESEARCH.md).

## Validation

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_fem tests.test_space tests.test_bridge tests.test_bridge_dynamics tests.test_playback tests.test_pipeline tests.test_load_cases tests.test_robust tests.test_bridge_learning tests.test_bridge_sparse tests.test_support_audit -v
node --test tests/bridge-playback.test.cjs
.\.venv\Scripts\python.exe -m twin.support_audit
```

Tests cover analytical bars/tripods, support stability, force/moment and energy balance, modal equations, axle transfer, independent ODE comparisons, time-step convergence and inference contracts. Artifact-dependent tests skip explicitly when their local training files are absent. The optional legacy public-server adapter uses separate dependencies and tests; CI focuses on the local research application. No hosting or deployment is enabled by this repository setup.

## Repository map

| Path | Contents |
|---|---|
| `twin/` | FEM, bridge dynamics, sensing, estimators and HTTP API |
| `web/` | Browser workspace, plots and projected 3D model |
| `tests/` | Numerical, API/service and playback regression checks |
| `unity/` | Optional Unity project and static viewer |
| `hardware/` | Calibrated packet forwarding example |
| `data/` | Versioned reports/previews; generated large binaries ignored |
| `docs/` | Architecture, research protocol and repository migration |

## Research scope

The bridge is a linear, small-displacement axial-truss model. Deck mass/load transfer is included; local deck bending, contact/uplift, vehicle suspension/moving mass, nonlinear buckling, capacity and code checks are excluded. The displayed stiffness index is **not a structural safety rating**.

Bridge ML is validated on synthetic healthy/single-member loss cases within its declared default crossing and noise domain. Sparse dropout/drift, multi-member bridge damage and physical transfer are not established. Forest votes are uncalibrated. Only the full 131-channel guided layout met the study's predefined 90% validation target; fewer sensors trade accuracy for coverage. See [research notes](docs/RESEARCH.md) for the complete numerical results.

## Documentation and contributions

[Architecture](docs/ARCHITECTURE.md) · [Research](docs/RESEARCH.md) · [Support audit](data/support-review.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Issues](https://github.com/Valomaxed/stratum/issues)
