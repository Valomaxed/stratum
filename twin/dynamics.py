"""Shared linear Newmark average-acceleration integration (SI units)."""
import numpy as np
from scipy.linalg import cho_factor, cho_solve


def newmark_linear(stiffness, mass, damping, force, dt):
    """Zero initial displacement/velocity; initial acceleration satisfies equilibrium.

    Force is sample-major on a uniform grid. beta=1/4 and gamma=1/2.
    """
    k, m, c, f = (np.asarray(x, float) for x in (stiffness, mass, damping, force))
    n = len(k)
    if (k.shape != (n, n) or m.shape != k.shape or c.shape != k.shape
            or f.ndim != 2 or f.shape[1] != n or len(f) < 2
            or not np.isfinite(dt) or dt <= 0
            or not all(np.all(np.isfinite(x)) for x in (k, m, c, f))):
        raise ValueError('Invalid Newmark matrices, force history or time step')
    u, v, a = (np.zeros_like(f) for _ in range(3))
    a[0] = cho_solve(cho_factor(m), f[0])
    b0, b1, b2 = 4/dt**2, 2/dt, 4/dt
    factor = cho_factor(k+b0*m+b1*c)
    for j in range(1, len(f)):
        effective = f[j]+m @ (b0*u[j-1]+b2*v[j-1]+a[j-1])+c @ (b1*u[j-1]+v[j-1])
        u[j] = cho_solve(factor, effective)
        a[j] = b0*(u[j]-u[j-1])-b2*v[j-1]-a[j-1]
        v[j] = v[j-1]+dt/2*(a[j-1]+a[j])
    residual = a @ m.T+v @ c.T+u @ k.T-f
    return {'displacement': u, 'velocity': v, 'acceleration': a,
            'relative_residual': float(np.linalg.norm(residual)/max(np.linalg.norm(f), 1e-12))}
