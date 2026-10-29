# The models and their audit are built inside the target Linux environment.
# Windows-trained fingerprints are never silently bypassed or reused.
FROM python:3.13-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
WORKDIR /app
COPY requirements-lock.txt requirements-hosting.txt ./
RUN python -m pip install --no-cache-dir -r requirements-hosting.txt
COPY twin ./twin
COPY web ./web
RUN python -m twin study --samples 2400 --seed 2026 --physics-cases 60 \
    && python -m twin robust-study --validation-cases 120 --test-cases 240 --workers 2 \
    && python -m twin.hosting_check

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PORT=10000
WORKDIR /app
COPY --from=builder /usr/local /usr/local
COPY --from=builder /app /app
USER 10001:10001
EXPOSE 10000
CMD ["python", "-m", "twin.hosting"]
