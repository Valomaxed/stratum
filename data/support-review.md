# Truss and bridge support review

The current machine-readable audit is [support-review.json](support-review.json). Run `python -m twin.support_audit` to regenerate it. It checks three truss models, eighteen healthy/damaged static load cases, all free vibration modes, and dynamic bridge equilibrium.

| Model | Restrained translations | Free DOFs |
|---|---|---:|
| Planar | N01 XY; N05 Y | 17 |
| Spatial truss | N01 XYZ; N02 XY; N17 Y | 54 |
| Bridge | N01 XYZ; N02 Y; N17 YZ; N18 Y | 53 |

The checks reconstruct joint forces from axial forces, test force/moment and strain-energy balance, verify restrained displacements and free reactions, verify rigid-body restraint rank and stiffness stability, and check compatibility with uniform expansion about N01. Bridge dynamic balance includes inertia and damping.

These are linear model consistency checks, not bearing capacity, contact/uplift or design-code checks. Truss joints have no rotational DOFs. The frame audit and independent OpenSees comparisons now belong to [stratum-seismic](https://github.com/Valomaxed/stratum-seismic); the combined historical audit is retained at tag `pre-split-2026-10-30`.
