"""Small-displacement, linear elastic, pin-jointed 2D/3D truss FEM.

Positive axial force/stress/strain means tension. Structural self-weight is
excluded from static loads. Mass is lumped to translational degrees of freedom.
"""
from dataclasses import dataclass
import numpy as np
from scipy.linalg import eigh, cho_factor, cho_solve
from .dynamics import newmark_linear


def _indices(values, label):
    """Reject fractional/non-numeric DOFs and connectivity before integer conversion."""
    raw = np.asarray(values)
    if raw.size and (raw.dtype.kind not in 'iuf' or not np.all(np.isfinite(raw))
                     or np.any(raw != np.floor(raw))):
        raise ValueError(f'{label} must contain finite integer indices')
    return np.asarray(raw, dtype=int)


@dataclass
class Truss:
    nodes: np.ndarray
    members: np.ndarray
    area: np.ndarray
    elastic_modulus: np.ndarray
    density: np.ndarray
    fixed_dofs: np.ndarray
    loads: np.ndarray
    nodal_mass: np.ndarray
    name: str = "Truss"

    def __post_init__(self):
        self.nodes = np.asarray(self.nodes, dtype=float)
        self.members = _indices(self.members, 'Member connectivity')
        n, dim = self.nodes.shape
        m = len(self.members)
        if dim not in (2, 3) or self.members.shape != (m, 2) or m < 1:
            raise ValueError("Expected 2D/3D nodes and a nonempty (m, 2) connectivity array")
        if np.any(self.members < 0) or np.any(self.members >= n):
            raise ValueError("Member references an unknown node")
        for attr in ("area", "elastic_modulus", "density"):
            value = np.broadcast_to(np.asarray(getattr(self, attr), float), (m,)).copy()
            if not np.all(np.isfinite(value)) or np.any(value <= 0):
                raise ValueError(f"{attr} must be finite and positive")
            setattr(self, attr, value)
        self.loads = np.asarray(self.loads, float).reshape(n * dim)
        self.nodal_mass = np.broadcast_to(np.asarray(self.nodal_mass, float), (n,)).copy()
        self.fixed_dofs = np.unique(_indices(self.fixed_dofs, 'Support DOFs'))
        if np.any(self.fixed_dofs < 0) or np.any(self.fixed_dofs >= n * dim):
            raise ValueError("Invalid support degree of freedom")
        if not all(np.all(np.isfinite(v)) for v in (self.nodes, self.loads, self.nodal_mass)):
            raise ValueError("Model contains nonfinite values")
        if np.any(self.nodal_mass < 0) or np.any(self.lengths <= 1e-12):
            raise ValueError("Mass must be nonnegative and members must have positive length")

    @property
    def dim(self):
        return self.nodes.shape[1]

    @property
    def lengths(self):
        return np.linalg.norm(self.nodes[self.members[:, 1]] - self.nodes[self.members[:, 0]], axis=1)

    @property
    def free(self):
        return np.setdiff1d(np.arange(self.nodes.size), self.fixed_dofs)

    def assemble(self, damage=None, removed=()):
        m = len(self.members)
        loss = np.zeros(m) if damage is None else np.asarray(damage, float)
        if loss.shape != (m,) or not np.all(np.isfinite(loss)) or np.any((loss < 0) | (loss > 1)):
            raise ValueError("Stiffness losses must be a finite vector in [0, 1]")
        removed = _indices(list(removed), 'Removed members')
        if np.any((removed < 0) | (removed >= m)):
            raise ValueError("Invalid removed member index")
        stiffness = np.zeros((self.nodes.size, self.nodes.size))
        mass = np.repeat(self.nodal_mass.copy(), self.dim)
        element_data = []
        for i, (a, b) in enumerate(self.members):
            length = self.lengths[i]
            direction = (self.nodes[b] - self.nodes[a]) / length
            projection = np.concatenate((-direction, direction))
            dofs = np.concatenate((np.arange(a*self.dim, (a+1)*self.dim), np.arange(b*self.dim, (b+1)*self.dim)))
            present = i not in removed
            effective_e = self.elastic_modulus[i] * (1-loss[i]) * present
            stiffness[np.ix_(dofs, dofs)] += effective_e * self.area[i] / length * np.outer(projection, projection)
            mass[dofs] += present * self.density[i] * self.area[i] * length / 2
            element_data.append((dofs, projection, length, effective_e))
        return stiffness, np.diag(mass), element_data

    def solve(self, damage=None, load_scale=1.0, removed=(), forces=None):
        if not np.isfinite(load_scale):
            raise ValueError("Load scale must be finite")
        k, mass, elements = self.assemble(damage, removed)
        free = self.free
        kff = k[np.ix_(free, free)]
        if len(free) == 0:
            raise ValueError("Model has no free degrees of freedom")
        eigenvalues = np.linalg.eigvalsh(kff)
        if eigenvalues[0] <= max(eigenvalues[-1] * 1e-12, 1e-8):
            raise ValueError("Unstable structure: a mechanism or unsupported degree of freedom exists")
        force = (self.loads if forces is None else np.asarray(forces, float))*load_scale
        if force.shape != self.loads.shape or not np.all(np.isfinite(force)):
            raise ValueError("Force vector must match model DOFs and be finite")
        u = np.zeros(self.nodes.size)
        u[free] = np.linalg.solve(kff, force[free])
        strain = np.array([projection @ u[dofs] / length for dofs, projection, length, _ in elements])
        stress = strain * np.array([e for _, _, _, e in elements])
        return {"displacement": u, "reactions": k @ u-force, "strain": strain,
                "stress": stress, "axial_force": stress*self.area, "K": k, "M": mass,
                "strain_energy": float(0.5*u @ k @ u)}

    def modes(self, damage=None, count=6, removed=()):
        k, mass, _ = self.assemble(damage, removed)
        free = self.free
        if len(free) == 0 or np.any(np.diag(mass)[free] <= 0):
            raise ValueError("Modal analysis requires positive mass at free degrees of freedom")
        values, vectors = eigh(k[np.ix_(free, free)], mass[np.ix_(free, free)])
        if values[0] <= max(values[-1]*1e-12, 1e-8):
            raise ValueError("Unstable structure in modal analysis")
        count = min(int(count), len(values))
        if count < 1:
            raise ValueError("At least one mode is required")
        shapes = np.zeros((self.nodes.size, count))
        shapes[free] = vectors[:, :count]
        return {"frequencies": np.sqrt(values[:count])/(2*np.pi), "shapes": shapes}

    def solve_load_cases(self, forces, damage=None, derivatives=False, removed=()):
        """Solve independent static load vectors against one assembled stiffness.

        Returns case-major arrays. Optional exact tangents differentiate equilibrium
        with respect to member stiffness-loss fractions; they do not use labels.
        """
        forces = np.asarray(forces, float)
        if forces.ndim != 2 or forces.shape[1] != self.nodes.size or len(forces) < 1:
            raise ValueError("Load cases must have shape (cases, translational DOFs)")
        if not np.all(np.isfinite(forces)):
            raise ValueError("Load cases must be finite")
        k, _, elements = self.assemble(damage, removed)
        free = self.free
        if not len(free):
            raise ValueError("Model has no free degrees of freedom")
        kff = k[np.ix_(free, free)]
        eigenvalues = np.linalg.eigvalsh(kff)
        if eigenvalues[0] <= max(eigenvalues[-1]*1e-12, 1e-8):
            raise ValueError("Unstable structure in load-case analysis")
        factor = cho_factor(kff)
        u = np.zeros_like(forces)
        u[:, free] = cho_solve(factor, forces[:, free].T).T
        b = np.zeros((len(elements), self.nodes.size))
        for i, (dofs, projection, length, _) in enumerate(elements):
            b[i, dofs] = projection/length
        result = {"displacement": u, "strain": u @ b.T, "reactions": u @ k.T-forces}
        if derivatives:
            # K du/dd_j = k_j(healthy) u, since dK/dd_j = -k_j(healthy).
            rhs = np.zeros((len(forces), self.nodes.size, len(elements)))
            for i, (dofs, projection, length, _) in enumerate(elements):
                if i in removed:
                    continue
                extension = u[:, dofs] @ projection
                rhs[:, dofs, i] = extension[:, None]*(self.elastic_modulus[i]*self.area[i]/length)*projection
            du = np.zeros_like(rhs)
            stacked = rhs[:, free, :].transpose(1, 0, 2).reshape(len(free), -1)
            du[:, free, :] = cho_solve(factor, stacked).reshape(len(free), len(forces), -1).transpose(1, 0, 2)
            result["displacement_jacobian"] = du
            result["strain_jacobian"] = np.einsum("sn,cnm->csm", b, du)
        return result

    def transient(self, damage=None, dt=0.002, duration=2.0, damping=0.02, load_scale=1.0, removed=()):
        """Newmark average acceleration, zero initial state, known smooth load pulse."""
        if not (np.isfinite(dt) and np.isfinite(duration) and 0 < dt <= duration <= 10):
            raise ValueError("Require 0 < dt <= duration <= 10 seconds")
        if not 0 <= damping <= 0.2 or not np.isfinite(load_scale):
            raise ValueError("Invalid damping or load scale")
        if duration/dt > 20000:
            raise ValueError("Too many time steps")
        k, mass, _ = self.assemble(damage, removed)
        free = self.free
        k = k[np.ix_(free, free)]
        mass = mass[np.ix_(free, free)]
        omega = 2*np.pi*self.modes(damage, 2, removed)["frequencies"]
        if len(omega) == 1:
            alpha, beta_r = 2*damping*omega[0], 0.0
        else:
            alpha = 2*damping*omega[0]*omega[1]/sum(omega)
            beta_r = 2*damping/sum(omega)
        c = alpha*mass + beta_r*k
        time = np.arange(int(round(duration/dt))+1)*dt
        pulse = np.where(time <= 0.12, np.sin(np.pi*np.minimum(time, 0.12)/0.12)**2, 0)
        force = pulse[:, None]*self.loads[free][None, :]*load_scale
        n = len(time)
        integrated = newmark_linear(k, mass, c, force, dt)
        u, v, a = (integrated[key] for key in ('displacement', 'velocity', 'acceleration'))
        full = []
        for value in (u, v, a):
            array = np.zeros((n, self.nodes.size))
            array[:, free] = value
            full.append(array)
        return {"time": time, "displacement": full[0], "velocity": full[1], "acceleration": full[2],
                "relative_residual": integrated['relative_residual']}


def demo_truss():
    nodes = np.array([[6*i, y] for y in (0, 4) for i in range(5)], float)
    members = [[i, i+1] for i in range(4)]+[[i+5, i+6] for i in range(4)]
    members += [[i, i+5] for i in range(5)]
    members += [[i, i+6] for i in range(4)]+[[i+1, i+5] for i in range(4)]
    loads = np.zeros((10, 2))
    loads[[1, 2, 3], 1] = -75000
    return Truss(nodes, np.array(members), 0.003, 200e9, 7850, np.array([0, 1, 9]), loads,
                 np.array([200, 600, 600, 600, 200, 200, 200, 200, 200, 200]), "Cross-braced steel truss")


def space_truss():
    """24 x 4 x 4 m braced box truss, Y vertical, Z transverse.

    Each of five stations has two bottom and two top joints. All four
    longitudinal faces and every cross-section are triangulated. Six bearing
    restraints suppress rigid motion without restraining thermal-like axial
    expansion: N01 XYZ, N02 XY, N17 Y. Members remain axial-only.
    """
    nodes = np.array([[6*i, y, z] for i in range(5)
                      for y, z in ((0, -2), (0, 2), (4, -2), (4, 2))], float)
    members = []
    for i in range(4):
        a, b = 4*i, 4*(i+1)
        members.extend((a+j, b+j) for j in range(4))
        # X-bracing on the two vertical sides, bottom deck and top face.
        for p, q in ((0, 2), (1, 3), (0, 1), (2, 3)):
            members.extend(((a+p, b+q), (a+q, b+p)))
    for i in range(5):
        a = 4*i
        members.extend((a+p, a+q) for p, q in ((0, 1), (1, 3), (3, 2), (2, 0), (0, 3), (1, 2)))
    loads = np.zeros_like(nodes)
    loads[[4, 5, 8, 9, 12, 13], 1] = -37500
    nodal_mass = np.full(len(nodes), 200.0)
    nodal_mass[[4, 5, 8, 9, 12, 13]] = 600
    return Truss(nodes, members, .003, 200e9, 7850, [0, 1, 2, 3, 4, 49],
                 loads, nodal_mass, "Braced steel space truss")
