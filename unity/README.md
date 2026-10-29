# Unity client

Open this directory in the installed Unity **6000.6.6f1** editor. This project uses built-in rendering, UnityWebRequest, legacy Input, and IMGUI; no external packages are required.

1. Start the backend from the repository root: `.\.venv\Scripts\python.exe -m twin serve --port 8766`.
2. In Unity select **Twin → Create Demo Scene** (a generated scene is also provided after batch validation).
3. Press Play. The script creates the camera, lighting, supports, loads, sensor markers and selectable members.
4. Drag in the viewport to orbit; scroll to zoom; click a member to inspect. Configure stiffness loss, then Run analysis. Toggle stress/deformation/loads/sensors.

The API URL is editable in the Unity panel. The default is `http://127.0.0.1:8766`. Keep **Active Input Handling** set to the legacy Input Manager or Both; the supplied project uses Unity's default Input Manager. This prototype targets the editor/desktop player. WebGL requires CORS and a separately configured hosting arrangement.

The default scene now uses the true 3D, 20-joint / 78-member braced space truss (24 × 4 × 4 m). Its XYZ coordinates, displacements, and load vectors come from the 3D FEM model. Use the **Structure** button to switch to the original planar 21-member model; switching resets the scenario. Member navigation, damage arrays and sensor budgets follow the selected geometry (132 channels in 3D, 38 in 2D). The 3D client shows configured damage and FEM results; ML/refinement is currently available only for the planar model. No beam/frame elements are implemented.

The headless `TwinSceneSetup.VerifyRuntime` check first verifies 78 rendered members, three loading cases, and nonzero Z loads/displacements under LC3, then switches to planar and runs the existing rank-21/sparse-healthy regression checks. Results are saved in `data/unity-runtime-validation.json` in the repository root. This verifies scene construction/API integration, not visual rendering quality.

Both models combine their own LC1+LC2+LC3 by default. Toggle three-load sensing, choose which static load to display, set a physical sensor budget, then Run analysis. The inspector shows local rank and total readings; loads use their actual force direction. The same sensors are reused across three settled acquisitions. The headless verification exercises both LC1 and LC3 and requires rank 21.

Enable physics refinement and the noise-aware sparse toggle to use the validated sparse policy. The noise slider controls the simulated noise and the declared inverse-fit σ together. Sparse fitting assumes at most two damaged members; the panel shows estimated common bias. Legacy fitting remains selectable. Headless verification now also checks that a clean healthy case returns no sparse damage alarms.

## Bridge analysis

The Structure button now cycles **space → bridge → planar**. The bridge has four bearings and 131 candidate sensor channels. Its deck mesh is a load-distribution surface, with a two-axle research truck. Change front-axle position, axle loads/spacing, lane offset, deck line load and total transverse wind, then Run analysis. LC1 is dead, LC2 dead + static vehicle, and LC3 dead + wind. The inspector shows current deck-joint downward deflection, abutment reactions, sweep peak/critical position and the selected member's axial-force envelope.

The bridge remains a linear axial truss: no local slab/floor-beam bending, vehicle impact, bearing contact, capacity checks or bridge ML inference. Modal mass excludes the truck. Headless verification includes the bridge's four bearings, 131-channel catalog, vertical reaction balance and envelope bound before running planar regression checks.
