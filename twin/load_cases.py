"""Known static excitation protocols; sensor budgets count physical channels.

The same sensors are reused after each independent load has settled. Damage must
remain fixed throughout a protocol. Three cases require three acquisitions.
"""
import hashlib
import json
import numpy as np
from .sensors import SensorArray


def demo_load_cases(model):
    if model.nodes.shape != (10, 2):
        raise ValueError("The excitation protocol is defined for the demo truss")
    asymmetric = np.zeros_like(model.loads).reshape(-1, 2)
    asymmetric[6, 1] = -150000
    asymmetric[8, 1] = -75000
    lateral = np.zeros_like(asymmetric)
    lateral[5:10, 0] = 45000
    return [
        {"id": "LC1", "name": "Distributed vertical", "forces": model.loads.copy()},
        {"id": "LC2", "name": "Asymmetric upper vertical", "forces": asymmetric.ravel()},
        {"id": "LC3", "name": "Upper lateral", "forces": lateral.ravel()},
    ]


def space_load_cases(model):
    """Independent vertical, eccentric vertical and X/Z wind patterns."""
    if model.nodes.shape != (20, 3):
        raise ValueError("Space excitation requires the 20-node box truss")
    eccentric = np.zeros_like(model.nodes)
    eccentric[[6, 10, 14], 1] = -75000
    wind = np.zeros_like(model.nodes)
    upper = np.flatnonzero(model.nodes[:, 1] > 0)
    wind[upper, 0] = 5000
    wind[upper, 2] = 15000
    return [
        {"id": "LC1", "name": "Distributed vertical", "forces": model.loads.copy()},
        {"id": "LC2", "name": "Eccentric upper vertical", "forces": eccentric.ravel()},
        {"id": "LC3", "name": "Longitudinal + transverse wind", "forces": wind.ravel()},
    ]


def rank_report(jacobian, rtol=1e-8):
    """Explicit relative SVD threshold; avoids treating roundoff as information."""
    jacobian = np.asarray(jacobian, float)
    if jacobian.ndim != 2 or not np.all(np.isfinite(jacobian)):
        raise ValueError("Sensitivity must be a finite matrix")
    singular = np.linalg.svd(jacobian, compute_uv=False)
    maximum = float(singular[0]) if len(singular) else 0
    rank = int(np.sum(singular > maximum*rtol)) if maximum else 0
    full = rank == jacobian.shape[1]
    return {"rank": rank, "unknowns": jacobian.shape[1], "observations": jacobian.shape[0],
            "relative_tolerance": rtol, "singular_values": singular.tolist(),
            "full_column_rank": full,
            "condition_number": float(singular[0]/singular[-1]) if full else None,
            "note": "Local sensitivity at the stated stiffness; full rank does not prove global uniqueness or noise robustness."}


class LoadCaseSensors(SensorArray):
    def __init__(self, model, protocol="multi", cases=None):
        if protocol not in ("single", "multi"):
            raise ValueError("Protocol must be single or multi")
        # SensorArray initialization calls response, so install excitation first.
        cases = demo_load_cases(model) if cases is None else cases
        self.cases = cases[:1] if protocol == "single" else cases
        self.forces = np.array([c["forces"] for c in self.cases])
        self.protocol = protocol
        super().__init__(model)
        self.physical_count = len(self.catalog)
        self.case_count = len(self.cases)
        self.observation_count = self.case_count*self.physical_count
        self.baseline = self.response(np.zeros(len(model.members)))
        amplitudes = self.baseline.reshape(self.case_count, self.physical_count)
        split = len(model.members)
        self.scale = np.concatenate([np.r_[
            np.full(split, max(np.max(np.abs(row[:split])), 1e-6)),
            np.full(len(self.dofs), max(np.max(np.abs(row[split:])), 1e-6))] for row in amplitudes])

    def response(self, damage, load_scale=1):
        if not np.isfinite(load_scale) or load_scale <= 0:
            raise ValueError("Load scale must be finite and positive")
        solution = self.model.solve_load_cases(self.forces*load_scale, damage)
        return np.concatenate((solution["strain"], solution["displacement"][:, self.dofs]), axis=1).ravel()

    def jacobian(self, damage=None):
        result = self.model.solve_load_cases(self.forces, damage, derivatives=True)
        values = np.concatenate((result["strain_jacobian"], result["displacement_jacobian"][:, self.dofs]), axis=1)
        return values.reshape(-1, len(self.model.members))/self.scale[:, None]

    def sensitivity(self):
        if not hasattr(self, "_sensitivity"):
            self._sensitivity = self.jacobian()
        return self._sensitivity

    def mask_for(self, physical_indices):
        mask = np.zeros(self.physical_count, bool)
        mask[np.asarray(physical_indices, int)] = True
        return np.tile(mask, self.case_count)

    def optimal_order(self):
        if hasattr(self, "_order"):
            return self._order
        sensitivity = self.sensitivity().reshape(self.case_count, self.physical_count, -1)
        inverse = np.eye(len(self.model.members))*100
        remaining, order = list(range(self.physical_count)), []
        while remaining:
            # A sensor contributes one row per load case: select the entire group.
            gains = [np.linalg.slogdet(np.eye(self.case_count)+sensitivity[:, i] @ inverse @ sensitivity[:, i].T)[1]
                     for i in remaining]
            selected = remaining.pop(int(np.argmax(gains)))
            rows = sensitivity[:, selected]
            v = inverse @ rows.T
            inverse -= v @ np.linalg.solve(np.eye(self.case_count)+rows @ v, v.T)
            inverse = (inverse+inverse.T)/2
            order.append(selected)
        self._order = np.array(order)
        return self._order

    def observe(self, damage, count=None, noise=0, missing=0, drift=0, seed=42, load_scale=1, placement="optimal"):
        if not all(np.isfinite(v) for v in (noise, missing, drift, load_scale)) or load_scale <= 0:
            raise ValueError("Invalid observation parameters")
        if not 0 <= noise <= .2 or not 0 <= missing <= 1 or not -.2 <= drift <= .2:
            raise ValueError("Invalid noise, dropout, or drift")
        count = self.physical_count if count is None else int(count)
        if not 1 <= count <= self.physical_count:
            raise ValueError("Invalid physical sensor budget")
        rng = np.random.default_rng(seed)
        order = self.optimal_order() if placement == "optimal" else np.arange(self.physical_count)
        active = order[:count][rng.random(count) >= missing]
        mask = self.mask_for(active)
        # Common per-sensor bias across acquisitions; independent readout noise.
        bias = np.tile(np.full(self.physical_count, drift), self.case_count)
        values = self.response(damage, load_scale)+(rng.normal(0, noise, self.observation_count)+bias)*self.scale*load_scale
        return values, mask

    def signature(self):
        """Bind trained artifacts to geometry, properties, supports and excitation."""
        model = self.model
        values = {"schema": 2, "nodes": model.nodes.tolist(), "members": model.members.tolist(),
                  "area": model.area.tolist(), "E": model.elastic_modulus.tolist(),
                  "fixed": model.fixed_dofs.tolist(), "forces": self.forces.tolist(),
                  "sensors": self.catalog, "scale": self.scale.tolist()}
        return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
