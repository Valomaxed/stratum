# Support and calculation review — 29 October 2026

Result: **PASS for the checks listed below**, within the existing linear research models. Machine-readable evidence and numerical-source hashes are in `support-review.json`. Reproduce with:

```powershell
.\.venv\Scripts\python.exe -m twin.support_audit
.\.venv\Scripts\python.exe -m unittest tests.test_support_audit -v
```

## Support layouts

| Model | Node | Blocked degrees of freedom | Free translations |
|---|---|---|---|
| Planar truss | N01 | X, Y | None |
| Planar truss | N05 | Y | X |
| Space truss | N01 | X, Y, Z | None |
| Space truss | N02 | X, Y | Z |
| Space truss | N17 | Y | X, Z |
| Bridge | N01 | X, Y, Z | None |
| Bridge | N02 | Y | X, Z |
| Bridge | N17 | Y, Z | X |
| Bridge | N18 | Y | X, Z |
| Seismic frames | Left and right column bases (zero-based nodes 0 and 2) | UX, UY, RZ | None |

Trusses have translational DOFs only. “Fixed” in the bridge bearing table means all translations are restrained; it does not mean a rotationally fixed beam connection. X runs along the span, Y is vertical, Z is transverse. Seismic frames use beam-column bending DOFs and truly fix the column-base rotations.

The planar supports remove three rigid-body motions. Space-truss and bridge supports remove all six. Free stiffness matrices are positive definite. All truss layouts admit uniform expansion about N01 without violating a restraint. This is a compatibility check; thermal loads are not implemented. The bridge has seven translation restraints and six rigid motions: its four vertical bearings introduce one elastic redundancy. Individual reactions therefore depend on structural stiffness, while abutment sums obey global statics.

## Calculations checked

- Eighteen static combinations: three models × three load cases × healthy/two damaged members. Supported displacements remain exactly zero.
- Reconstruct every joint force independently from member axial forces and direction cosines, then compare with applied loads and reactions.
- Check global force and moment balance, zero reaction at free DOFs, and element strain energy against half of external work.
- Check every free vibration mode against `K phi = omega² M phi`.
- Check a 72 km/h dynamic bridge crossing: free-DOF equilibrium and vertical balance including inertia and damping, through the free-vibration tail.
- Check all three seismic frame configurations: fixed column bases, condensed massless-DOF equilibrium, base shear and global moments including nodal moments. The unused middle base joint has no connected elements.

Maximum global static moment discrepancy was below `1e-7 N m`; modal relative residuals were below `2e-15`. The bridge dynamic free-DOF residual was below `6e-7 N`, and vertical balance discrepancy below `3e-12 kN`. These are numerical consistency measures, not estimates of physical modeling accuracy.

Existing regression checks additionally cover analytical axial bars and a spatial tripod, cantilever bending, force/moment-conserving axle transfer, dead-load/mass consistency, simple-statics abutment reactions, modal mass normalization, independent ODE solutions, time-step convergence, and the OpenSees seismic comparison. The saved OpenSees report remains source-hash checked separately in `seismic-validation/`.

Validation completed: **80 Python tests and 3 JavaScript tests passed**. The Python run included solver, support audit, load cases, playback, ML, sparse sensing, seismic analysis and independent OpenSees checks. Windows temporary-file permissions required rerunning the benchmark tests with TEMP/TMP inside `work/review-temp`; that rerun passed. The archived public-hosting test suite stalled in its concurrency test and was stopped; hosting is outside this local review. This is not a claim that every repository test passed. Browser verification confirmed Arial/grayscale text on both pages, distinct seismic line patterns, completed default seismic analysis, correct bridge restraint summaries, and no console warnings/errors.

## Review findings and UI

- Corrected bridge Model notes, which previously displayed the planar description.
- Added a visible support-restraint summary from solver metadata for every truss model, alongside schematic support symbols.
- Arial typography and an achromatic interface apply to the twin and seismic pages, including canvas/SVG labels. Monochrome series use distinct line styles where overlaid.
- No support layout or structural material/load assumption was changed as a result of this audit.

## Scope

The truss bridge is small-displacement, linear elastic and axial only. The deck transfers load and contributes mass but has no slab/floor-beam bending stiffness. Bearings are bilateral restraints; negative vertical reactions are uplift demand, not a contact solution. Moving loads are prescribed forces without vehicle suspension, moving mass or road/contact interaction. Seismic frames are elastic with floor-translation constraints and condensed massless DOFs; gravity/P-delta and inelastic brace buckling are excluded. These checks do not establish code compliance, bearing capacity or real-world structural safety. Unity's existing viewer was not revalidated or restyled in this browser UI change.
