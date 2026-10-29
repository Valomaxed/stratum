"""Demo geometry registry; inference artifacts remain specific to the planar model."""
import numpy as np
from .fem import demo_truss, space_truss
from .load_cases import demo_load_cases, space_load_cases
from .bridge import bridge_truss, bridge_load_cases

FACTORIES = {"planar": demo_truss, "space": space_truss, "bridge": bridge_truss}
CASE_FACTORIES = {"planar": demo_load_cases, "space": space_load_cases, "bridge": bridge_load_cases}


def member_kind(model, index):
    a, b = model.members[index]
    delta = np.abs(model.nodes[b]-model.nodes[a]) > 1e-10
    if delta.sum() == 1:
        return ("Longitudinal chord", "Vertical member", "Transverse tie")[int(np.argmax(delta))]
    return "Spatial diagonal" if delta.sum() == 3 else "Face diagonal"


def describe_model(model_id, model=None):
    model = FACTORIES[model_id]() if model is None else model
    positions = np.zeros((len(model.nodes), 3))
    positions[:, :model.dim] = model.nodes
    supports = []
    for node in range(len(model.nodes)):
        axes = ["XYZ"[d % model.dim] for d in model.fixed_dofs if d // model.dim == node]
        if axes:
            support={"node": node, "type": "pin" if len(axes) == model.dim else "roller", "axes": axes,
                     "free_axes":[axis for axis in 'XYZ'[:model.dim] if axis not in axes]}
            if model_id=='bridge':
                support.update(bearing_kind='Fixed' if axes==list('XYZ') else 'Guided expansion' if axes==list('YZ') else 'Free expansion',
                               free_axes=[axis for axis in 'XYZ' if axis not in axes])
            supports.append(support)
    return {"id": model_id, "name": model.name, "dimension": model.dim,
            "node_count": len(model.nodes), "member_count": len(model.members),
            "sensor_capacity": len(model.members)+len(model.free),
            "extent": np.ptp(positions, axis=0).tolist(),
            "center": ((positions.min(axis=0)+positions.max(axis=0))/2).tolist(),
            "supports": supports,
            "member_kinds": [member_kind(model, i) for i in range(len(model.members))],
            "cases": [{"id": c["id"], "name": c["name"]} for c in CASE_FACTORIES[model_id](model)],
            "inference_supported": model_id == "planar",
            "stage": "Validated planar inference" if model_id == "planar" else "Bridge FEM · static vehicle loading" if model_id == "bridge" else "3D FEM · inference training pending"}


def model_catalog():
    return [describe_model(key) for key in FACTORIES]
