"""Linear axial-truss bridge with idealized deck load transfer.

The deck distributes vertical loads to bottom panel joints; it contributes mass
and dead load, but no plate/beam stiffness. Vehicles are static axle forces.
No design-code vehicle, dynamic impact, contact, or capacity check is implied.
"""
import numpy as np
from .fem import space_truss

GRAVITY = 9.80665
DEFAULTS = {"vehicle_position_m": 12., "front_axle_kn": 80., "rear_axle_kn": 120.,
            "axle_spacing_m": 4., "lane_offset_m": 0., "deck_load_kn_m": 10., "wind_total_kn": 50.}


def settings(values=None):
    if values is None:
        values = {}
    if not isinstance(values, dict) or set(values)-set(DEFAULTS):
        raise ValueError("Bridge settings must be an object with recognized parameter names")
    result = {key: float(values.get(key, default)) for key, default in DEFAULTS.items()}
    limits = {"front_axle_kn": (0,250), "rear_axle_kn": (0,250), "axle_spacing_m": (2,8),
              "lane_offset_m": (-1.2,1.2), "deck_load_kn_m": (0,30), "wind_total_kn": (0,200)}
    limits["vehicle_position_m"] = (0,24+result["axle_spacing_m"])
    for key, (low, high) in limits.items():
        if not np.isfinite(result[key]) or not low <= result[key] <= high:
            raise ValueError(f"{key} must be finite and between {low} and {high}")
    return result


def bridge_truss(deck_load_kn_m=10.):
    model = space_truss()
    model.name = "24 m steel truss bridge"
    # Four vertical bearings, two transverse guides, one longitudinal anchor.
    model.fixed_dofs = np.array([0,1,2,4,49,50,52])  # N01 XYZ, N02 Y, N17 YZ, N18 Y
    tributary = np.array([3.,6.,6.,6.,3.])
    deck_force = np.zeros_like(model.nodes)
    for i, length in enumerate(tributary):
        deck_force[4*i:4*i+2,1] = -deck_load_kn_m*1000*length/2
    model.nodal_mass = -deck_force[:,1]/GRAVITY
    # Member mass remains assembled once in FEM; only its weight is added here.
    weight = np.zeros_like(model.nodes)
    for (a,b), length, area, density in zip(model.members,model.lengths,model.area,model.density):
        weight[[a,b],1] -= density*area*length*GRAVITY/2
    model.loads = (deck_force+weight).ravel()
    return model


def axle_forces(model, x, load_kn, lane_offset_m=0.):
    """Bilinear panel transfer conserves vertical force and X/Z moments."""
    result = np.zeros_like(model.nodes)
    if x < 0 or x > 24:
        return result.ravel()
    bay = min(int(x//6),3)
    t = (x-6*bay)/6
    right = (lane_offset_m+2)/4
    for station, along in ((bay,1-t),(bay+1,t)):
        for side, across in ((0,1-right),(1,right)):
            result[4*station+side,1] -= load_kn*1000*along*across
    return result.ravel()


def vehicle_forces(model, config, position=None):
    x = config["vehicle_position_m"] if position is None else position
    return (axle_forces(model,x,config["front_axle_kn"],config["lane_offset_m"])
            + axle_forces(model,x-config["axle_spacing_m"],config["rear_axle_kn"],config["lane_offset_m"]))


def bridge_load_cases(model, config=None):
    config = settings(config)
    wind = np.zeros_like(model.nodes)
    upper = np.flatnonzero(model.nodes[:,1]>0)
    wind[upper,2] = config["wind_total_kn"]*1000/len(upper)
    return [{"id":"LC1", "name":"Dead load", "forces":model.loads.copy()},
            {"id":"LC2", "name":"Dead + static vehicle", "forces":model.loads+vehicle_forces(model,config)},
            {"id":"LC3", "name":"Dead + transverse wind", "forces":model.loads+wind.ravel()}]


def bridge_context(values=None):
    config = settings(values)
    model = bridge_truss(config["deck_load_kn_m"])
    return {"config":config, "model":model, "cases":bridge_load_cases(model,config)}


def crossing_positions(config):
    end = 24+config["axle_spacing_m"]
    events = np.r_[np.arange(0,25,6),np.arange(0,25,6)+config["axle_spacing_m"]]
    return np.unique(np.r_[np.arange(0,end,.5),events,end,config["vehicle_position_m"]])


def prepare_playback(values=None, damage=None, load_scale=1., removed=()):
    """Event-resolved quasi-static responses for continuous client playback.

    Displacements, strains and K*u are continuous/piecewise linear in axle
    position. Reactions must be reconstructed as K*u-F(x): applied forces can
    jump at an axle's entry/exit bearing. Interpolating reactions directly would
    incorrectly smear that jump over the neighboring position interval.
    """
    if not np.isfinite(load_scale) or not .1 <= load_scale <= 3:
        raise ValueError("Load scale must be between 0.1 and 3")
    context = bridge_context(values); model = context["model"]; config = context["config"]
    loss = np.zeros(len(model.members)) if damage is None else np.asarray(damage,float)
    positions = crossing_positions(config)
    forces = np.array([model.loads+vehicle_forces(model,config,x) for x in positions])*load_scale
    response = model.solve_load_cases(forces,loss,removed=removed)
    healthy = model.solve_load_cases(forces)
    effective_e = model.elastic_modulus*(1-loss)
    effective_e[list(removed)] = 0
    return {"method":"quasi-static", "positions_m":positions.tolist(), "settings":config,
            "load_scale":float(load_scale), "dead_forces":(model.loads.reshape(-1,3)*load_scale).tolist(),
            "displacement":response["displacement"].reshape(-1,len(model.nodes),3).tolist(),
            "healthy_displacement":healthy["displacement"].reshape(-1,len(model.nodes),3).tolist(),
            "strain":response["strain"].tolist(),
            "internal_force":(response["reactions"]+forces).reshape(-1,len(model.nodes),3).tolist(),
            "effective_modulus":effective_e.tolist(), "area":model.area.tolist(),
            "note":"Animated static equilibrium, not vehicle dynamics. Interpolate continuous response fields; rebuild axle forces at the exact position."}


def bridge_report(model, config, damage, load_scale, removed, current, force_pattern, case_id):
    # Include every axle/panel crossing, plus a 0.5 m plotting grid. Endpoints
    # capture extrema of this piecewise-linear nodal load-transfer model.
    positions = crossing_positions(config)
    forces = np.array([model.loads+vehicle_forces(model,config,x) for x in positions])*load_scale
    sweep = model.solve_load_cases(forces,damage,removed=removed)
    deck_nodes = np.array([4*i+j for i in range(5) for j in (0,1)])
    displacement = sweep["displacement"].reshape(-1,len(model.nodes),3)
    downward = np.maximum(0,-displacement[:,deck_nodes,1].min(axis=1))*1000
    effective_e = model.elastic_modulus*(1-damage)
    effective_e[list(removed)] = 0
    axial = sweep["strain"]*effective_e*model.area/1000
    reactions = sweep["reactions"].reshape(-1,len(model.nodes),3)/1000
    u = current["displacement"].reshape(-1,3)
    current_down = max(0,float(-u[deck_nodes,1].min()))*1000
    healthy_u = model.solve(forces=force_pattern*load_scale)["displacement"].reshape(-1,3)
    healthy_down = max(0,float(-healthy_u[deck_nodes,1].min()))*1000
    supports = []
    current_reactions = current["reactions"].reshape(-1,3)/1000
    for node in (0,1,16,17):
        axes = ["XYZ"[d%3] for d in model.fixed_dofs if d//3==node]
        supports.append({"node":node,"axes":axes,
                         "bearing_kind":"Fixed" if axes==list('XYZ') else "Guided expansion" if axes==list('YZ') else "Free expansion",
                         "free_axes":[axis for axis in 'XYZ' if axis not in axes],
                         "reaction_kn":current_reactions[node].tolist(),
                         "min_vertical_kn":float(reactions[:,node,1].min()),
                         "max_vertical_kn":float(reactions[:,node,1].max())})
    on_bridge_kn = -float(vehicle_forces(model,config).reshape(-1,3)[:,1].sum())*load_scale/1000
    left = float(current_reactions[[0,1],1].sum())
    right = float(current_reactions[[16,17],1].sum())
    return {"settings":config, "load_case":case_id, "deck_nodes":deck_nodes.tolist(),
            "vehicle":{"front_x":config["vehicle_position_m"],"rear_x":config["vehicle_position_m"]-config["axle_spacing_m"],
                       "lane_z":config["lane_offset_m"],"on_bridge_kn":on_bridge_kn,
                       "visible":case_id=="LC2"},
            "current":{"deck_down_mm":current_down,"healthy_deck_down_mm":healthy_down,
                       "change_from_healthy_pct":100*(current_down/healthy_down-1) if healthy_down>1e-10 else None,
                       "dead_load_kn":-float(model.loads.reshape(-1,3)[:,1].sum())*load_scale/1000,
                       "applied_vertical_kn":-float(force_pattern.reshape(-1,3)[:,1].sum())*load_scale/1000,
                       "left_reaction_kn":left,"right_reaction_kn":right,
                       "vertical_balance_error_kn":left+right+float(force_pattern.reshape(-1,3)[:,1].sum())*load_scale/1000},
            "supports":supports,
            "sweep":{"positions_m":positions.tolist(),"deck_down_mm":downward.tolist(),
                     "peak_down_mm":float(downward.max()),"critical_front_x_m":float(positions[np.argmax(downward)]),
                     "member_min_axial_kn":axial.min(axis=0).tolist(),"member_max_axial_kn":axial.max(axis=0).tolist(),
                     "combination":"Dead + static vehicle", "positions_count":len(positions)},
            "assumptions":["Research axle loads, not a code vehicle or factored design combination.",
                           "Deck transfers loads to panel joints; slab/floor-beam stiffness and local deck bending are excluded.",
                           "Sweep is a sequence of static solves; no vehicle dynamics or impact factor.",
                           "Bearings are bilateral linear restraints; uplift/contact and capacity checks are excluded.",
                           "Modal mass includes steel and declared deck mass, but excludes vehicle mass."]}
