"""Loopback HTTP API and static viewer. Not a public production server."""
import json
import mimetypes
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from datetime import datetime, timezone
import threading
import socket
import numpy as np
from .models import FACTORIES, CASE_FACTORIES, describe_model, model_catalog
from .learning import DamageEstimator, DATA, ARTIFACT
from .load_cases import LoadCaseSensors, rank_report
from .experiments import STUDY
from .robust import ROBUST_DIR
from .bridge import bridge_context, bridge_report, prepare_playback
from .bridge_dynamics import prepare_dynamic_playback
from .bridge_learning import BridgeDamageEstimator
from .bridge_sparse import SparseBridgeDamageEstimator

WEB = Path(__file__).resolve().parents[1]/"web"


class LocalTwinHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # Windows SO_REUSEADDR can let two servers share one port, leaving
        # clients on an older process after a restart.
        if hasattr(socket,"SO_EXCLUSIVEADDRUSE"):
            self.allow_reuse_address = False
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()


class TwinService:
    def __init__(self, model_id="planar"):
        if model_id not in FACTORIES:
            raise ValueError("Unknown structural model")
        self.model_id = model_id
        self.model = FACTORIES[model_id]()
        self.metadata = describe_model(model_id, self.model)
        cases = CASE_FACTORIES[model_id](self.model)
        self.protocol_sensors = {p:LoadCaseSensors(self.model,p,cases=cases) for p in ("single","multi")}
        order = self.protocol_sensors["multi"].optimal_order()
        self.protocol_sensors["single"]._order = order.copy()
        self.estimators = {p:DamageEstimator(s, STUDY/f"{p}.joblib" if (STUDY/f"{p}.joblib").exists() or p == "multi" else ARTIFACT)
                           for p,s in self.protocol_sensors.items()} if model_id == "planar" else {}
        self.sensors = self.protocol_sensors["single"]
        self.estimator = self.estimators.get("single")
        self.baseline_modes = self.model.modes()["frequencies"]
        self.telemetry = None
        self.lock = threading.Lock()
        self.model_lock = threading.Lock()
        self.other_models = {}
        self.bridge_estimator=None
        self.bridge_sparse_estimator=None

    def for_model(self, model_id):
        if model_id not in FACTORIES:
            raise ValueError("Unknown structural model")
        if model_id == self.model_id:
            return self
        with self.model_lock:
            if model_id not in self.other_models:
                self.other_models[model_id] = TwinService(model_id)
            return self.other_models[model_id]

    def analyze(self, request):
        service = self.for_model(request.get("model_id", self.model_id))
        if service is not self:
            return service.analyze(request)
        bridge = bridge_context(request.get("bridge")) if self.model_id == "bridge" else None
        model = bridge["model"] if bridge else self.model
        protocol = request.get("protocol", "single")
        if protocol not in self.protocol_sensors:
            raise ValueError("Protocol must be single or multi")
        array = LoadCaseSensors(model,protocol,cases=bridge["cases"]) if bridge else self.protocol_sensors[protocol]
        case_id = request.get("display_case", "LC1")
        case_index = next((i for i,c in enumerate(array.cases) if c["id"] == case_id),None)
        if case_index is None:
            raise ValueError("Display case is not part of the selected protocol")
        force_pattern = array.forces[case_index]
        damage = np.asarray(request.get("damage", np.zeros(len(model.members))), float)
        load = float(request.get("load_scale", 1))
        if not np.isfinite(load) or not 0.1 <= load <= 3:
            raise ValueError("Load scale must be between 0.1 and 3")
        removed = request.get("removed", [])
        if not isinstance(removed, list) or any(type(i) is not int for i in removed):
            raise ValueError("Removed members must be an array of integer indices")
        result = model.solve(damage, load, removed, forces=force_pattern)
        effective_loss = damage.copy()
        effective_loss[removed] = 1.0
        modes = model.modes(damage, removed=removed)
        noise = float(request.get("noise", 0.005)); missing = float(request.get("missing", 0))
        drift = float(request.get("drift", 0)); count = int(request.get("sensor_count", len(self.sensors.catalog)))
        seed = int(request.get("seed", 42))
        values, mask = array.observe(damage, count, noise, missing, drift, seed, load)
        if removed:
            noise_delta = values-array.response(damage, load)
            removed_response = model.solve_load_cases(array.forces*load,damage,removed=removed)
            values = np.concatenate((removed_response["strain"], removed_response["displacement"][:,model.free]),axis=1).ravel()+noise_delta
            prediction = {"available": False, "reason": "Member removal is outside the stiffness-loss model's training distribution"}
        elif not self.estimators:
            prediction = {"available": False, "reason": "Bridge static inference is not enabled. Dynamic crossing ML is reported separately after acquisition." if bridge else "3D inference is not trained or validated yet. Configured loss is simulation ground truth; planar ML results do not apply."}
        else:
            prediction = self.estimators[protocol].predict(values, mask, load, bool(request.get("physics", False)),
                         refinement=request.get("refinement","legacy"),noise_std=noise)
        u = result["displacement"].reshape(-1, model.dim)
        nodes = [{"id": i, "x": float(p[0]), "y": float(p[1]), "z": float(p[2]) if model.dim == 3 else 0.0,
                  "ux": float(u[i, 0]), "uy": float(u[i, 1]), "uz": float(u[i, 2]) if model.dim == 3 else 0.0} for i, p in enumerate(model.nodes)]
        members = []
        for i, (a, b) in enumerate(model.members):
            stress = float(result["stress"][i])
            members.append({"id": i, "name": f"M{i+1:02}", "a": int(a), "b": int(b),
                "kind": self.metadata["member_kinds"][i], "length": float(model.lengths[i]), "area": float(model.area[i]),
                "elastic_modulus": float(model.elastic_modulus[i]), "effective_modulus": float(model.elastic_modulus[i]*(1-effective_loss[i])),
                "damage": float(effective_loss[i]), "removed": i in removed,
                "stress": stress, "strain": float(result["strain"][i]), "axial_force": float(result["axial_force"][i]),
                "stress_ratio": abs(stress)/250e6})
        dynamic = model.transient(damage, duration=1.5, load_scale=load, removed=removed)
        sensor_node = 8 if model.dim == 3 else 2
        sensor_dof = sensor_node*model.dim+1  # centre-bottom vertical accelerometer
        trajectory = dynamic["acceleration"][:, sensor_dof]
        spectrum = np.abs(np.fft.rfft((trajectory-trajectory.mean())*np.hanning(len(trajectory))))
        spectrum_frequency = np.fft.rfftfreq(len(trajectory), 0.002)
        band = spectrum_frequency <= 80
        readings = values.reshape(array.case_count,-1)
        observed = mask.reshape(array.case_count,-1)
        sensors = [{**channel, "value": float(readings[case_index,i]) if observed[case_index,i] else None,
                    "active": bool(observed[case_index,i]), "selected": i in array.optimal_order()[:count],
                    "case_values":[float(readings[c,i]) if observed[c,i] else None for c in range(array.case_count)]}
                   for i, channel in enumerate(array.catalog)]
        response = {"schema_version": 1, "source": "simulated", "model_id": self.model_id, "dimension": model.dim,
                "model": self.metadata, "model_name": model.name, "nodes": nodes,
                "members": members, "supports": self.metadata["supports"],
                "loads": [{"node": i, "fx": float(f[0]*load), "fy": float(f[1]*load), "fz": float(f[2]*load) if model.dim == 3 else 0.0}
                          for i, f in enumerate(force_pattern.reshape(-1, model.dim)) if np.any(f)],
                "sensors": sensors, "prediction": prediction,
                "excitation": {"protocol":protocol,"case_count":array.case_count,"display_case":case_id,
                    "cases":[{"id":c["id"],"name":c["name"]} for c in array.cases],
                    "active_observations":int(mask.sum()),
                    "observability":rank_report(array.sensitivity()[mask]),
                    "note":"Same physical sensors reused for independent settled load cases; unchanged damage and known loads assumed."},
                "summary": {"stiffness_index": float(100*(1-np.mean(effective_loss))),
                    "max_displacement_mm": float(np.max(np.linalg.norm(u, axis=1))*1000),
                    "max_stress_mpa": float(np.max(np.abs(result["stress"]))/1e6),
                    "active_sensors": int(observed[case_index].sum()), "sensor_capacity": len(sensors),
                    "strain_energy_j": result["strain_energy"], "dynamic_equilibrium_residual": dynamic["relative_residual"]},
                "reactions": result["reactions"].reshape(-1, model.dim).tolist(),
                "modal": {"frequencies": modes["frequencies"].tolist(), "baseline": (model.modes()["frequencies"] if bridge else self.baseline_modes).tolist(),
                          "shapes": modes["shapes"].T.reshape(-1, len(nodes), model.dim).tolist()},
                "signal": {"time": dynamic["time"][::3].tolist(), "acceleration": trajectory[::3].tolist(),
                           "frequency": spectrum_frequency[band].tolist(), "spectrum": spectrum[band].tolist(),
                           "sensor_id": f"A{sensor_node+1:02}Y", "node": sensor_node, "axis": 1,
                           "label": f"A{sensor_node+1:02}Y · LC1 simulated pulse response", "load_case":"LC1", "unit": "m/s²"},
                "notes": ["Stiffness index is the arithmetic mean of configured stiffness retention, not a safety rating.",
                          "Stress ratio uses a nominal 250 MPa reference; no buckling, fatigue or code checks.",
                          "ML consumes quasi-static strain/displacement, not the displayed acceleration trace."]}
        if bridge:
            response["bridge"] = bridge_report(model,bridge["config"],damage,load,removed,result,force_pattern,case_id)
            response["signal"]["label"] = f"A{sensor_node+1:02}Y · LC1 dead-load pulse (not vehicle dynamics)"
            response["notes"].extend(response["bridge"]["assumptions"])
        return response

    def ingest(self, request):
        # External inference remains bound to the calibrated planar catalog.
        if request.get("model_id", "planar") != "planar" or self.model_id != "planar":
            raise ValueError("External inference is currently supported only for the planar model")
        protocol = request.get("protocol", "single")
        if protocol not in self.protocol_sensors:
            raise ValueError("Protocol must be single or multi")
        array = self.protocol_sensors[protocol]
        load = float(request.get("load_scale", 1))
        channels = request.get("measurements")
        if not isinstance(channels, dict) or not channels:
            raise ValueError("Supply measurements as an object keyed by catalog sensor ID")
        known = {s["id"] for s in array.catalog}
        if protocol == "single":
            by_case={"LC1":channels}
        else:
            if set(channels) != {c["id"] for c in array.cases}:
                raise ValueError("Multi protocol requires a measurements object for each of LC1, LC2, LC3")
            by_case=channels
        values = np.zeros(array.observation_count); mask = np.zeros(array.observation_count,bool)
        for c,case in enumerate(array.cases):
            readings=by_case[case["id"]]
            if not isinstance(readings,dict) or set(readings)-known:
                raise ValueError("Unknown sensor IDs or invalid per-case measurements")
            for i,channel in enumerate(array.catalog):
                value=readings.get(channel["id"])
                if value is not None:
                    values[c*array.physical_count+i]=float(value);mask[c*array.physical_count+i]=True
        array.features(values, mask, load)  # validate even before training
        prediction = self.estimators[protocol].predict(values, mask, load, bool(request.get("physics", False)),
                     refinement=request.get("refinement","legacy"),noise_std=request.get("noise_std"))
        packet = {"received_at": datetime.now(timezone.utc).isoformat(), "source": "external",
                  "measurements": channels,"protocol":protocol,"active_observations":int(mask.sum()),
                  "active_sensors": int(mask.reshape(array.case_count,-1).any(axis=0).sum()),
                  "load_scale": load, "prediction": prediction}
        with self.lock:
            self.telemetry = packet
        return packet

    def playback(self, request):
        if request.get("model_id") != "bridge":
            raise ValueError("Moving-load playback requires the bridge model")
        removed = request.get("removed", [])
        if not isinstance(removed,list) or any(type(i) is not int for i in removed):
            raise ValueError("Removed members must be an array of integer indices")
        method=request.get('method','quasi-static')
        args=(request.get("bridge"),request.get("damage"),float(request.get("load_scale",1)),removed)
        if method == 'dynamic-moving-force':
            ml_options=request.get('bridge_ml',{})
            if not isinstance(ml_options,dict) or set(ml_options)-{'sensor_count','placement'}:
                raise ValueError('Bridge ML options require sensor_count and placement only')
            bundle=prepare_dynamic_playback(*args,dynamic=request.get('dynamic'))
            # This predictor sees measured response fields and known acquisition
            # settings only; configured damage and comparison labels are excluded.
            with self.model_lock:
                if self.bridge_estimator is None:self.bridge_estimator=BridgeDamageEstimator()
                if self.bridge_sparse_estimator is None:self.bridge_sparse_estimator=SparseBridgeDamageEstimator(self.bridge_estimator)
                bundle['ml']=self.bridge_sparse_estimator.predict(bundle,noise=float(request.get('noise',0)),
                    seed=int(request.get('seed',42)),sensor_count=int(ml_options.get('sensor_count',request.get('sensor_count',131))),
                    placement=ml_options.get('placement','guided'),missing=float(request.get('missing',0)),drift=float(request.get('drift',0)))
            return bundle
        if method != 'quasi-static':
            raise ValueError('Unknown bridge playback method')
        return prepare_playback(*args)


def serve(host="127.0.0.1", port=8766):
    service = TwinService()
    class Handler(BaseHTTPRequestHandler):
        def send_json(self, value, code=200):
            body = json.dumps(value, allow_nan=False).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/health":
                return self.send_json({"ok": True, "trained": service.estimator.artifact is not None})
            if path == "/api/models":
                return self.send_json({"models": model_catalog(), "default": "bridge"})
            if path == '/api/seismic-validation':
                from .seismic_benchmark import saved_report
                return self.send_json(saved_report())
            if path.startswith('/api/seismic-validation/'):
                from .seismic_benchmark import REPORT_DIR
                filenames={'report.md':'report.md','comparison.png':'opensees-comparison.png',
                           'convergence.png':'time-step-convergence.png'}
                name=filenames.get(path.removeprefix('/api/seismic-validation/'))
                file=REPORT_DIR/name if name else None
                if file is None or not file.is_file():
                    return self.send_json({'error':'Verification artifact not found'},404)
                body=file.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type',mimetypes.guess_type(file.name)[0] or 'text/plain; charset=utf-8')
                self.send_header('Content-Length',str(len(body)))
                self.send_header('Cache-Control','no-store')
                self.end_headers();self.wfile.write(body)
                return
            if path == "/api/metrics":
                file = DATA/"metrics.json"
                return self.send_json(json.loads(file.read_text()) if file.exists() else {"available": False})
            if path == '/api/bridge-ml-report':
                file=DATA/'bridge-ml'/'report.json'
                return self.send_json(json.loads(file.read_text(encoding='utf8')) if file.exists() else {'available':False})
            if path == '/api/bridge-sparse-report':
                file=DATA/'bridge-sparse'/'report.json'
                return self.send_json(json.loads(file.read_text(encoding='utf8')) if file.exists() else {'available':False})
            if path == "/api/study":
                file=STUDY/"report.json"
                return self.send_json(json.loads(file.read_text()) if file.exists() else {"available":False})
            if path == "/api/robust-study":
                file=ROBUST_DIR/"report.json"
                return self.send_json(json.loads(file.read_text()) if file.exists() else {"available":False})
            if path == "/api/telemetry":
                with service.lock:
                    packet = service.telemetry
                return self.send_json(packet or {"available": False})
            file = (WEB/("index.html" if path == "/" else path.lstrip("/"))).resolve()
            if not file.is_relative_to(WEB) or not file.is_file():
                return self.send_json({"error": "Not found"}, 404)
            body = file.read_bytes()
            self.send_response(200); self.send_header("Content-Type", mimetypes.guess_type(file.name)[0] or "application/octet-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def do_POST(self):
            try:
                path = urlparse(self.path).path
                size = int(self.headers.get("Content-Length", 0))
                limit = 2_000_000 if path == '/api/seismic' else 65536
                if size < 1 or size > limit:
                    raise ValueError(f"Request must be 1..{limit} bytes")
                request = json.loads(self.rfile.read(size))
                if not isinstance(request, dict):
                    raise ValueError("JSON request must be an object")
                path = urlparse(self.path).path
                if path == "/api/analyze":
                    result = service.analyze(request)
                elif path == '/api/seismic':
                    from .seismic import compare
                    result = compare(request)
                elif path == "/api/bridge-playback":
                    result = service.playback(request)
                elif path == "/api/observations":
                    result = service.ingest(request)
                else:
                    return self.send_json({"error": "Not found"}, 404)
                return self.send_json(result)
            except (ValueError, TypeError, KeyError, IndexError, OverflowError, np.linalg.LinAlgError) as error:
                return self.send_json({"error": str(error)}, 400)

    httpd = LocalTwinHTTPServer((host, port), Handler)
    print(f"Structural twin running at http://{host}:{port}", flush=True)
    print("Ctrl+C to stop. Research prototype; local connections only by default.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
