"""Virtual quasi-static sensors and explicit observation masks.

Dynamic acceleration traces are produced by fem.transient; the first ML baseline
uses quasi-static strain/displacement under a known, nonzero load pattern.
"""
import numpy as np


class SensorArray:
    def __init__(self, model):
        self.model = model
        self.dofs = model.free
        self.catalog = ([{"id": f"SG{i+1:02}", "kind": "strain", "member": i, "unit": "strain"}
                         for i in range(len(model.members))] +
                        [{"id": f"D{d//model.dim+1:02}{'XYZ'[d%model.dim]}", "kind": "displacement",
                          "node": int(d//model.dim), "axis": int(d%model.dim), "unit": "m"} for d in self.dofs])
        self.baseline = self.response(np.zeros(len(model.members)))
        split = len(model.members)
        self.scale = np.concatenate((np.full(split, max(np.max(np.abs(self.baseline[:split])), 1e-6)),
                                     np.full(len(self.dofs), max(np.max(np.abs(self.baseline[split:])), 1e-6))))

    def response(self, damage, load_scale=1):
        solution = self.model.solve(damage, load_scale)
        return np.concatenate((solution["strain"], solution["displacement"][self.dofs]))

    def observe(self, damage, count=None, noise=0, missing=0, drift=0, seed=42, load_scale=1, placement="optimal"):
        if not all(np.isfinite(x) for x in (noise, missing, drift, load_scale)) or load_scale <= 0:
            raise ValueError("Observations require a finite, known, positive load scale")
        if not 0 <= noise <= 0.2 or not 0 <= missing <= 1 or not -0.2 <= drift <= 0.2:
            raise ValueError("Invalid sensor noise, missing fraction, or drift")
        total = len(self.catalog)
        count = total if count is None else int(count)
        if not 1 <= count <= total:
            raise ValueError(f"Sensor count must be 1..{total}")
        rng = np.random.default_rng(seed)
        order = self.optimal_order() if placement == "optimal" else np.arange(total)
        mask = np.zeros(total, bool)
        mask[order[:count]] = True
        mask &= rng.random(total) >= missing
        clean = self.response(damage, load_scale)
        values = clean + (rng.normal(0, noise, total)+drift)*self.scale*load_scale
        return values, mask

    def features(self, values, mask, load_scale=1):
        values, mask = np.asarray(values, float), np.asarray(mask, bool)
        if values.shape != self.baseline.shape or mask.shape != self.baseline.shape:
            raise ValueError("Sensor channel count does not match the model")
        if not np.isfinite(load_scale) or load_scale <= 0 or not np.all(np.isfinite(values[mask])):
            raise ValueError("Observed channels and load scale must be finite")
        signature = (values/load_scale-self.baseline)/self.scale
        return np.concatenate((np.where(mask, signature, 0), mask.astype(float)))

    def sensitivity(self):
        if hasattr(self, "_sensitivity"):
            return self._sensitivity
        rows = []
        for i in range(len(self.model.members)):
            damage = np.zeros(len(self.model.members)); damage[i] = 0.1
            rows.append((self.response(damage)-self.baseline)/self.scale/0.1)
        self._sensitivity = np.array(rows).T
        return self._sensitivity

    def optimal_order(self):
        if hasattr(self, "_order"):
            return self._order
        sensitivity = self.sensitivity()
        inverse = np.eye(sensitivity.shape[1])*100
        remaining, order = list(range(len(self.catalog))), []
        while remaining:
            # Greedy D-optimal placement via matrix determinant lemma.
            gains = [sensitivity[i] @ inverse @ sensitivity[i] for i in remaining]
            chosen = remaining.pop(int(np.argmax(gains)))
            row = sensitivity[chosen]
            v = inverse @ row
            inverse -= np.outer(v, v)/(1+row @ v)
            order.append(chosen)
        self._order = np.array(order)
        return self._order
