# Public research demo deployment

The public entry point serves the existing dashboard and the complete Python FEM/ML pipeline from one origin. It uses Uvicorn/Starlette rather than the local development HTTP server.

## Render

1. Put the prepared deployment source in a Git repository accessible to your Render account.
2. Create a Render Blueprint from `render.yaml`, or create a Docker web service using this Dockerfile.
3. Confirm the compute plan before creating the service. The supplied blueprint requests **Free**; no paid resources have been authorized or created. If the measured service exceeds the free tier's memory/build limits, choose a suitable plan explicitly before deploying.
4. Health path: `/api/health`. The app binds `0.0.0.0:$PORT`, default 10000. Use one serving process; multiple workers duplicate the forests in memory.

Docker builds scientific dependencies and regenerates the excitation models plus sparse-validation audit **inside Linux**. This avoids platform-dependent floating-point signature mismatches with Windows artifacts. Training happens at image-build time, not on incoming web requests. Builds therefore take longer than a static website; build resources and platform time limits still need verification on the host. Docker is not installed in the current local environment, so the Linux image has not been built here.

The new service URL and managed HTTPS are assigned by Render after successful deployment. No deployment URL exists until a service is actually created and passes its health check.

## Local serving check

```powershell
python -m pip --python .venv install -r requirements-hosting.txt
.\.venv\Scripts\python.exe -m twin.hosting_check
$env:PORT = '10000'
.\.venv\Scripts\python.exe -m twin.hosting
```

Browse `http://127.0.0.1:10000`. Stop with Ctrl+C. The existing `python -m twin serve` command remains the local hardware-capable research server.

Docker, when available:

```text
docker build -t stratum-twin .
docker run --rm -p 10000:10000 stratum-twin
```

## Public-demo behavior

- Visitors can simulate damage, inspect the structure and view the actual research reports.
- External sensor ingestion and telemetry are disabled (403); no visitor shares a hardware feed with others.
- One analysis runs at a time. Busy requests return 429 with `Retry-After: 2`.
- JSON bodies are limited to 64 KiB; nonfinite JSON numbers and non-object payloads are rejected.
- A single Uvicorn process and single-job forests bound CPU and avoid multiplying model memory.
- Startup fails if either protocol or its audited sparse policy is unavailable. The app does not silently publish an untrained version.
- Static files are served only from `web/`. Source, local spreadsheets, raw observations and desktop files are not exposed.
- Inputs remain simulation inputs: no structural safety certification or validated hardware transfer is implied.

The deployment source bundle is built with an explicit file allowlist. It excludes `.venv`, `.git`, Unity caches, local spreadsheets, credentials, local datasets and Windows model artifacts. Do not upload the entire workspace indiscriminately.

## Unity

Set the desktop client's API URL to the deployed HTTPS origin. The desktop client uses the same `/api/analyze` endpoint. A Unity WebGL build would require its own build/hosting work; the deployed browser interface is already interactive.

## Verification and references

Install `requirements-test.txt` to run the hosting contract tests. They verify lifecycle readiness, static-file boundaries, forbidden external inputs, bounded bodies and busy behavior; the numerical tests remain unchanged.

- [Render web services](https://render.com/docs/web-services)
- [Render Blueprint specification](https://render.com/docs/blueprint-spec)
- [Starlette lifespan](https://starlette.dev/lifespan/)
