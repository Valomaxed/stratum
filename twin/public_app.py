"""ASGI entry point for a public simulation-only research demo.

The local server remains available for hardware work. This app never accepts or
returns external observations, and bounds concurrent CPU-intensive analyses.
"""
from contextlib import asynccontextmanager
import json
from pathlib import Path
import threading
import numpy as np
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse,FileResponse
from starlette.routing import Route,Mount
from starlette.staticfiles import StaticFiles
from threadpoolctl import threadpool_limits
from .server import TwinService,WEB
from .learning import DATA
from .experiments import STUDY
from .robust import ROBUST_DIR

MAX_BODY_BYTES=65536


class PublicHeaders(BaseHTTPMiddleware):
    async def dispatch(self,request,call_next):
        response=await call_next(request)
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["Content-Security-Policy"]=("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"]="no-store"
        return response


async def read_payload(request):
    limit=2_000_000 if request.url.path == '/api/seismic' else MAX_BODY_BYTES
    length=request.headers.get("content-length")
    if length is not None:
        try:length=int(length)
        except ValueError:raise ValueError("Invalid Content-Length")
        if length<0:raise ValueError("Invalid Content-Length")
        if length>limit:return None,413
    body=bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body)>limit:return None,413
    def reject_nonfinite(value):raise ValueError("JSON numbers must be finite")
    payload=json.loads(body,parse_constant=reject_nonfinite)
    if not isinstance(payload,dict):raise ValueError("JSON request must be an object")
    return payload,200


def ready(service):
    return all(estimator.artifact is not None and estimator.sparse_policy is not None
               for estimator in service.estimators.values())


def create_app(service_factory=TwinService,require_ready=True):
    @asynccontextmanager
    async def lifespan(app):
        limiter=threadpool_limits(limits=1)
        try:
            service=await run_in_threadpool(service_factory)
            if require_ready and not ready(service):
                raise RuntimeError("Public demo requires matching excitation forests and an audited sparse policy. Build the models first.")
            # One serving process and one job per forest bound public-request CPU/memory.
            for estimator in service.estimators.values():
                if estimator.artifact:
                    for key in ("classifier","regressor"):
                        if key in estimator.artifact:estimator.artifact[key].set_params(n_jobs=1)
            app.state.twin=service
            app.state.gate=threading.BoundedSemaphore(1)
            app.state.ready=ready(service)
            yield
        finally:
            limiter.restore_original_limits()

    async def health(request):
        return JSONResponse({"ok":request.app.state.ready,"trained":request.app.state.ready,
            "mode":"public-demo","external_observations_enabled":False,"analysis_concurrency":1},
            status_code=200 if request.app.state.ready else 503)

    async def analyze(request):
        try:
            payload,status=await read_payload(request)
            if status==413:return JSONResponse({"error":"Request exceeds the endpoint size limit"},status_code=413)
        except (ValueError,TypeError,UnicodeDecodeError) as error:
            return JSONResponse({"error":str(error)},status_code=400)
        def compute():
            gate=request.app.state.gate
            if not gate.acquire(blocking=False):
                return JSONResponse({"error":"Analysis server is busy. Please try again shortly."},status_code=429,headers={"Retry-After":"2"})
            try:
                if request.url.path == '/api/seismic':
                    from .seismic import compare
                    result=compare(payload)
                else:
                    result=request.app.state.twin.analyze(payload)
                # JSONResponse refuses nonfinite output rather than leaking invalid JSON.
                return JSONResponse(result)
            except (ValueError,TypeError,KeyError,IndexError,OverflowError,np.linalg.LinAlgError) as error:
                return JSONResponse({"error":str(error)},status_code=400)
            finally:
                gate.release()
        return await run_in_threadpool(compute)

    async def external_disabled(request):
        return JSONResponse({"error":"External sensor observations are disabled in this public research demo. Use the local server for hardware integration."},status_code=403)

    def report(path):
        async def endpoint(request):
            if not path.is_file():return JSONResponse({"available":False},status_code=404)
            media='application/json' if path.suffix=='.json' else 'image/png' if path.suffix=='.png' else 'text/markdown; charset=utf-8'
            return FileResponse(path,media_type=media,headers={"Cache-Control":"no-store"})
        return endpoint

    async def home(request):return FileResponse(WEB/"index.html",media_type="text/html")

    async def seismic_validation(request):
        from .seismic_benchmark import saved_report
        return JSONResponse(await run_in_threadpool(saved_report))

    from .seismic_benchmark import REPORT_DIR as SEISMIC_REPORT_DIR

    routes=[Route("/api/health",health),Route("/api/analyze",analyze,methods=["POST"]),
            Route('/api/seismic',analyze,methods=['POST']),
            Route('/api/seismic-validation',seismic_validation),
            Route('/api/seismic-validation/report.md',report(SEISMIC_REPORT_DIR/'report.md')),
            Route('/api/seismic-validation/comparison.png',report(SEISMIC_REPORT_DIR/'opensees-comparison.png')),
            Route('/api/seismic-validation/convergence.png',report(SEISMIC_REPORT_DIR/'time-step-convergence.png')),
            Route("/api/observations",external_disabled,methods=["GET","POST","PUT","DELETE"]),
            Route("/api/telemetry",external_disabled),
            Route("/api/metrics",report(DATA/"metrics.json")),Route("/api/study",report(STUDY/"report.json")),
            Route("/api/robust-study",report(ROBUST_DIR/"report.json")),Route("/",home),
            Mount("/",StaticFiles(directory=WEB),name="static")]
    return Starlette(routes=routes,lifespan=lifespan,middleware=[Middleware(PublicHeaders)],debug=False)
