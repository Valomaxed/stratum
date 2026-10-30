# Contributing

Start with a focused issue describing the problem, expected behavior, and a reproducible input. For numerical changes, include units, boundary conditions, and the expected analytical or independently computed result.

1. Create a branch from `main` and make one coherent change.
2. Set up the local Python environment described in the README.
3. Run the documented tests and JavaScript syntax checks.
4. Update assumptions, API examples, and screenshots when behavior changes.
5. Open a pull request describing the problem, resulting behavior, validation, and limitations.

Numerical changes need meaningful equilibrium, analytical, convergence, or independent-solver checks. Preserve train/validation/test boundaries and report abstentions and failed cases. Do not retune a method against held-out results. Generated models, environments, sensor recordings, credentials, and caches do not belong in commits.

A saved verification report is evidence for its recorded source hashes and configuration. Regenerate it after changing its numerical sources; do not edit a PASS flag manually. Screenshots and simulated examples do not establish physical validation or design-code compliance.
