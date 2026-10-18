# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS base
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/app/python/.venv/bin:$PATH"

COPY python/pyproject.toml python/uv.lock python/.python-version /app/python/

FROM base AS app
RUN uv sync --frozen --no-dev --no-install-project --directory python

COPY config ./config
COPY web ./web

CMD ["sh", "-c", "gunicorn web.wsgi:app --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-2} --timeout ${GUNICORN_TIMEOUT:-120}"]

FROM base AS detector
RUN uv sync --frozen --no-dev --group detector --no-install-project --directory python
# YOLOX-Tiny (Apache-2.0), 416x416 input
ADD --checksum=sha256:427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7 \
    https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx \
    /app/models/yolox_tiny.onnx

COPY config ./config
COPY web/__init__.py web/store.py web/detector.py web/schema.sql ./web/

CMD ["python", "-m", "web.detector"]

FROM base AS judge
RUN uv sync --frozen --no-dev --group detector --no-install-project --directory python
COPY config ./config
COPY web/__init__.py web/store.py web/challenge_store.py web/judge.py web/clip_bpe.py web/schema.sql ./web/
CMD ["python", "-m", "web.judge"]

FROM nginx:1.27-alpine AS nginx
COPY docker-compose/nginx.conf /etc/nginx/conf.d/default.conf
