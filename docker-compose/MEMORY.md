# docker-compose

## GOTCHA

- Tagging the app image with a Dockerfile hash and skipping `compose pull` when that tag already exists on the Mac leaves stale app code running. Push only `latest`; deploy compose with `IMAGE_TAG=latest` so `up -d` only recreates a service when that digest actually changed. Using a per-commit SHA as the compose tag rebuilt nginx and detector on every commit even when their layers were identical.
- `driver: docker` + two tags in one `buildx --push` 403s the second tag on GHCR (`failed commit on ref "manifest-sha256:…"`), even after `:latest` succeeded and even with a `sha-` prefix. Push only `:latest`. Do not add a second tag in that build.
- Detector image should not `COPY web` (templates/static). Copy `web/__init__.py`, `store.py`, `detector.py`, and `schema.sql` plus `config/` so a kuji.html edit does not bounce the detector container.
- Building `linux/arm64` on `ubuntu-latest` uses QEMU and is very slow. Build on the self-hosted Mac ARM64 runner instead; do not add `setup-qemu-action`. Pinning the Docker engine version does not fix that.
- `cache-from/to: type=gha` re-downloads the whole build cache every run. On the persistent Mac runner use `driver: docker` so layers stay on disk; `uv sync` only re-runs when the lockfile changes. `pull: true` still checks base images but only fetches new layers.
- `docker/login-action` on the Mac runner fails with `User interaction is not allowed` (osxkeychain). Write `auths` into `$RUNNER_TEMP/docker-config` and set `DOCKER_CONFIG`; same as deploy.
- Photo files live on the host (`/Volumes/OWC Envoy Pro FX/photo-upload`). Both `app` and `nginx` must bind-mount that path; putting photos only in the image will not work.
- Project records, users, roles, tickets, and kuji draws live in Postgres on the OWC (`$HOST_PHOTO_DIR/postgres`). Redis is cache only (`detect_q`, slideshow playhead). A Docker named volume dies when Desktop is reset; bind Postgres to the photo disk. `mkdir` `$HOST_PHOTO_DIR/postgres` in deploy. nginx must `deny` `/photos/postgres/` (same as `logs/`). POC stores Postgres in `.poc/postgres`.
- When `compose up` recreates only `app` (new IP) and leaves `nginx` running, nginx keeps the old upstream IP and returns 502 (`connect() failed (111)` to the old `172.x` address). In compose, give nginx `depends_on: app: {condition: service_started, restart: true}` so it restarts with app. That is a process restart of the same nginx image, not a rebuild.
- Docker Desktop "manually paused" cannot be resumed from the CLI (`docker desktop start` says already running). Use the whale menu, or `docker desktop restart`.
- Docker Desktop on the Mac runner does not share `/opt/app`. Bind-mounting anything from `/opt/app` (nginx.conf, `../logs`) fails with "Mounts denied". Bake nginx.conf into `photo-upload-nginx`. Logs bind `$HOST_PHOTO_DIR/logs` (OWC, already shared) to `/logs`. Postgres binds `$HOST_PHOTO_DIR/postgres`. Deploy `mkdir`s both and symlinks `/opt/app/photo-upload/logs` → that folder. nginx must `deny` `/photos/logs/` and `/photos/postgres/`.

## TASTE

- Baked `photo-upload-nginx` plus the OWC photo bind is enough for `compose up`; confirmed the stack starts on the Mac runner.
- `PHOTO_DIR=/data/photos` inside the container; host path stays in compose (`HOST_PHOTO_DIR` / default OWC volume).
- App logs: `LOG_DIR=/logs` in the container, host `$HOST_PHOTO_DIR/logs`. Files are `<project-id>_yyyyMMdd.log`; the app deletes names older than 30 days. Do not log `/api/slideshow` polls.
- Install Python deps with `uv sync --frozen` from `python/pyproject.toml` + `python/uv.lock`, not a root `requirements.txt`.
- Local POC: `docker-compose.poc.yaml` (`name: photo-upload-poc`) builds the same Dockerfile targets, bind-mounts `web/` + `config/`, photos in `.poc/photos`, Postgres in `.poc/postgres`, port 8001. gunicorn `--reload` plus `--reload-extra-file` for each `web/templates/*` (Jinja caches templates otherwise); edits apply in about 1s. First build about 45s, cached rebuild about 7s. `poc.sh seed` runs `poc_seed.py` in the app container to build the demo project.
- Dockerfile has a shared `base` stage, then `app`, `detector`, `nginx` targets. `detector` runs `uv sync --group detector` (onnxruntime + numpy stay out of the app image) and bakes YOLOX-Tiny with `ADD --checksum=sha256:...` from the GitHub release (needs `# syntax=docker/dockerfile:1`). Compose `detector` mounts the photo dir read-only and needs `REDIS_URL`, `DATABASE_URL`, and `PHOTO_DIR`. CI builds `photo-upload-detector` as `:latest` in the same workflow.
