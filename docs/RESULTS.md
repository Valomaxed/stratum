# Results and interpretation

 ## Dynamic bridge experiment

 The 24 m bridge has 78 axial members and 131 candidate strain/displacement channels. A complete prescribed moving-force crossing plus 2 s tail supplies 20 phase observations per channel. Classification identifies healthy/damaged member; regression estimates stiffness loss.

 The baseline contains 3,520 cases: 3,120 single-damage scenarios and 400 healthy noise replicates of one zero-loss state. Splits contain 2,464 training, 528 validation and 528 held-out test cases. Test cases comprise 468 damaged scenarios and 60 healthy replicates. Splits precede noise augmentation. Geometry, supports, materials, deck mass, axles, lane, 36 km/h speed and 2% target damping are fixed to the documented defaults.

 ## Paired sparse-sensor test results

 These results reuse **the same 528 held-out cases and noise draws**, at 0.5% sensor noise. Every reduced budget trains separate forests from selected channel histories only. The random comparator is one fixed nested layout.

 | Channels | Guided location accuracy | Fixed random accuracy | Guided damaged severity MAE (pp) |
 |---|---:|---:|---:|
 | 131 | 92.61% | 92.61% | 5.18 |
| 50 | 88.26% | 88.07% | 6.34 |
| 20 | 74.05% | 77.84% | 12.29 |
| 10 | 59.28% | 59.09% | 16.59 |
| 5 | 45.08% | 39.77% | 21.41 |

 ![Paired sparse-sensor results](../data/bridge-sparse/review-summary.png)

 ## Interpretation

 - Fifty guided channels reduce channel count by 61.8%, giving 88.26% accuracy versus 92.61% for the full array.
 - The 20-channel random layout performs better than guided placement here. The healthy-model sensitivity criterion is a local information heuristic.
 - Only 131 guided channels satisfy the predefined **validation** rule: accuracy at least 90%, coverage at least 95%, healthy alarms at most 5% at 0.5% noise. Qualification is based on validation data, independently of the displayed test results.
 - Five guided channels achieve 45.08% accuracy. The interface retains failed estimates rather than substituting configured damage.

 ## Metric definitions

 Location accuracy includes healthy cases and counts abstentions as incorrect. A displacement axis counts as one physical channel. Noise is scaled by healthy per-type response peaks; 0.5% does not describe load uncertainty. End-to-end damaged severity MAE assigns zero loss at the true damaged member when its location is wrong or rejected. `pp` means percentage points of stiffness loss. The full report also provides coverage and healthy alarms. Forest votes are uncalibrated.

 ## Source and reproduction

 [Baseline report](../data/bridge-ml/report.json) · [Sparse report](../data/bridge-sparse/report.json) · [Frozen selection](../data/bridge-sparse/selection.json) · [Placement catalog](../data/bridge-sparse/placement.json)

 [plot_results.py](../examples/plot_results.py) redraws the figure from saved summary metrics. Repeating every prediction requires the excluded forests and raw arrays, regenerated through [the full workflow](REPRODUCIBILITY.md).

 ## Small FEM example

 [quick_review.py](../examples/quick_review.py) runs without ML artifacts. The healthy static case has first frequency about 6.178 Hz and deck downward deflection 10.896 mm; the configured 40% M05-loss case gives about 6.157 Hz and 11.162 mm under the same loading. [Recorded output](../data/review-example.json). Local member stiffness loss is distinct from global bridge stiffness retention.

 ## Evidence boundaries

 Analytical, balance, modal, ODE and convergence checks support numerical implementation. Predictive results apply to the stated synthetic acquisition family. Physical transfer, multi-member bridge damage, changed operating conditions, drift/dropout and capacity assessment require separate validation. Planar inverse studies use a different geometry/protocol and should not be pooled with these bridge results.
