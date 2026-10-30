# Repository separation

On 30 October 2026 the combined workspace was separated into two independently runnable projects:

| Repository | Scope | Default local address |
|---|---|---|
| [stratum](https://github.com/Valomaxed/stratum) | Planar/spatial trusses, bridge FEM, sensing and damage estimation | http://127.0.0.1:8766/ |
| [stratum-seismic](https://github.com/Valomaxed/stratum-seismic) | Elastic seismic frame comparison and independent OpenSees verification | http://127.0.0.1:8767/ |

The original combined source remains available at the `pre-split-2026-10-30` tag in stratum. Both projects retain their numerical assumptions and research limitations. Each now has its own HTTP service, frontend, tests and documentation. Neither imports the other repository. The small linear Newmark integrator is maintained as a local source copy in each project.

Saved machine-learning datasets and model binaries are intentionally excluded from Git. Regenerate them only in the truss project. The seismic application requires no trained model. Ground-motion provenance and OpenSees verification live in the seismic repository.
