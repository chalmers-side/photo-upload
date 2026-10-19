# photo-upload

Guests upload photos. Multiple screens play the same slideshow. Admins run a lottery, and guests draw Ichiban Kuji (一番賞) prizes. Only photos with a person in them earn lottery and Ichiban Kuji chances. The supported way to run it is Docker Compose: nginx + gunicorn + Postgres + Redis + a person-detector worker.

## Requirements

- Docker and Compose, **linux/arm64** images (Apple Silicon)
- A photo directory the Docker VM can mount (files stay on the host, not in the image)
- Port **8000** free
- Pull access to `ghcr.io/chalmers-side/photo-upload`, `photo-upload-nginx`, and `photo-upload-detector`
- Postgres data lives on the photo disk (`$HOST_PHOTO_DIR/postgres`). Redis is cache only (detect queue + slideshow playhead).

Flask alone does **not** serve `/photos/` — nginx does. Use Compose for local debugging too.

## Start

From `docker-compose/`:

```bash
# optional: photo path and image tag
# echo 'HOST_PHOTO_DIR=/your/photo/path' >> .env

docker compose pull
docker compose up -d
```

Open `http://localhost:8000`. The home page lists projects. Admin is `/admin` (root / `ADMIN_PASSWORD` on first boot).

Pushes to `main` or `feature/**` build `linux/arm64` on the self-hosted Mac runner (native, no QEMU), then `compose pull && compose up -d` with `:latest`. Compose only recreates a service when that image digest changed (Redis stays; nginx/detector stay on template-only app deploys). nginx still restarts when app gets a new IP so it does not 502. Rollback is revert the commit and let CI rebuild `:latest`.

### Local POC (no push, no GHCR)

```bash
docker-compose/poc.sh up     # build from source, http://localhost:8001 (+ LAN URL for phones)
docker-compose/poc.sh seed   # demo project /p/poc/ with backgrounds, marks, ticket, A–E prizes
```

Separate Compose project (`photo-upload-poc`): Postgres in `.poc/postgres`, photos in `.poc/photos` (gitignored), port `POC_PORT` (default 8001). `web/` and `config/` are bind-mounted and gunicorn runs with `--reload`, so Python and template edits apply on save. `web/detector.py` needs `poc.sh restart detector`. Rebuild (`poc.sh up`) only after changing `python/uv.lock`, the Dockerfile, or `nginx.conf`. `poc.sh reset` wipes POC data.

### Event-day private server (this Mac, no OWC)

If the usual runner or SSD is down, run the stack on this computer. JPEGs, Postgres, logs, and judge models live on the internal disk at `/opt/app/photo-upload`. Code stays in this git clone — do not `rsync --delete` the repo into that data directory (it would wipe photos and Postgres). Production compose still defaults to the OWC volume.

```bash
docker-compose/local.sh doctor   # Docker, File Sharing, disk, /health
docker-compose/local.sh up       # build from source, http://localhost:8000
docker-compose/local.sh backup   # pg_dump into /opt/app/photo-upload/backups
```

Docker Desktop does not share `/opt/app` by default (`Mounts denied`). `local.sh` adds `/opt/app` to File Sharing and restarts Docker Desktop if a bind-mount test fails. Containers use `restart: unless-stopped`. Redis is cache only: detector and judge re-queue pending photos after a Redis bounce; slideshow rebuilds from Postgres. If nginx 502s after an app recreate, `local.sh restart nginx`. If the whale icon says paused, Resume from the menu (`docker desktop restart` if the CLI says already running). Keep the Mac plugged in so it does not sleep. Admin login comes from `docker-compose/secret.env` (created on first `up` if missing). Do not use `poc.sh` on the day: that stack is port 8001, `--reload`, and `.poc/` data.

## What to change

**Almost always, when moving machines**

| Item | Where | Notes |
| --- | --- | --- |
| Photo directory | Compose `HOST_PHOTO_DIR` (or `.env`) | Default `/Volumes/OWC Envoy Pro FX/photo-upload`. Event-day private server: `/opt/app/photo-upload` via `local.sh`. Bind the same path on **app** and **nginx**. |
| App logs | `$HOST_PHOTO_DIR/logs` | One file per project per day. Deploy also symlinks `/opt/app/photo-upload/logs`. Older than 30 days are deleted. |
| Admin login | `docker-compose/secret.env` on the Mac | `ADMIN_USERNAME` / `ADMIN_PASSWORD`. Seeds root in Postgres on first boot only. Gitignored; rsync will not delete it. |
| `SECRET_KEY` | `docker-compose/secret.env` on the Mac | Signs cookies. Copy `secret.env.example`. Not in git. |

**Site-wide defaults** (Compose `app.environment`, or `config/appsetting.py`). New projects copy the slideshow/lottery values; each project can override them in Admin → Settings.

| Variable | Default | Purpose |
| --- | --- | --- |
| `REDIS_URL` | `redis://redis:6379/0` | Leave as-is in Compose |
| `PHOTO_DIR` | `/data/photos` | Path **inside** the container |
| `LOG_DIR` | `/logs` | Per-project daily logs inside the container (`$HOST_PHOTO_DIR/logs` on the host) |
| `LOG_KEEP_DAYS` | `30` | Delete log files older than this many days |
| `SLIDESHOW_INTERVAL` | `8` | Seconds each slideshow photo stays |
| `SLIDESHOW_FADE` | `0.8` | Slideshow crossfade seconds (0 = hard cut) |
| `SLIDESHOW_MODE` | `wall` | Default slideshow layout: `wall` (name + caption) or `full` (photo only) |
| `SLIDESHOW_QUEUE_MAX` | `100` | Slideshow queue cap |
| `SLIDESHOW_PER_DEVICE` | `5` | Newest photos per device when over the cap |
| `RECORD_TTL_DAYS` | `20` | Photo/ticket age used by sweep (files are not auto-deleted on their own) |
| `MAX_UPLOAD_MB` | `20` | Per-photo cap; batch is 5 photos; nginx `client_max_body_size` is 110m |
| `JPEG_MAX_EDGE` | `2560` | Longest edge after upload |
| `GUNICORN_WORKERS` | `2` | |
| `GUNICORN_TIMEOUT` | `120` | Keep high for large uploads |
| `LOTTERY_SECONDS` | `10` | Sphere spin duration |
| `LOTTERY_SPHERE_MAX` | `60` | Photos on the lottery sphere |
| `LOTTERY_CHANCE_MAX` | `10` | Lottery tickets per device (newest photos with people) |
| `KUJI_PER_USER` | `2` | Default Ichiban Kuji draws per device (one per photo with people, up to this cap). Per project in Admin |
| `DETECTOR_THREADS` | `2` | onnxruntime CPU threads on the `detector` service |
| `PERSON_SCORE` | `0.45` | Min person score (0–1) for a photo to count |
| `PERSON_MIN_AREA` | `0.005` | Min person box area as a fraction of the photo (ignores tiny far-away people) |

Look-and-feel (`PJT_FADE`, `BKG_FADE`, button colors, glass padding, `LOTTERY_PAD_CM`) is also in `config/appsetting.py`. Design rules for every page are in `web/STYLE.md`.

**Copy and dependencies**

- Guest-facing strings: `config/msg.py`
- Python packages: `cd python && uv add …` / `uv lock`; commit `pyproject.toml` and `uv.lock`
- nginx: `docker-compose/nginx.conf` (baked into the nginx image)

## Use

1. `/admin` — create a project (slug optional)
2. Guests: `/p/<slug>/` → upload or slideshow
3. Per project, optional covers: `pjt-mark` (home mark, PNG), `pjt-desktop`, `pjt-mobile`, `bkg-desktop`, `bkg-mobile`, `lot-desktop`, `lot-mobile`
4. Lottery is admin-only: `/p/<slug>/lottery`
5. Project settings (slideshow mode, interval, queue, lottery spin) are on the project card, bottom left
6. Ichiban Kuji: `/p/<slug>/kuji` (home button 「一番賞」 shows once any prize count is above 0). Admin → project card → 「一番賞 / Ichiban Kuji」 sets the A–E prize counts and photos, the draws per device, the ticket image (`kuji-ticket`, PNG), the page mark (`kuji-mark`), and backgrounds (`kuji-desktop`, `kuji-mobile`; fall back to the home background). 「重置一番賞」 clears draws and claims and refills stock; earned chances stay.

## Layout

```
config/           env defaults, admin login, copy
web/              Flask app, Postgres store, templates, detector worker
web/STYLE.md      design system (tokens, glass, buttons, per-page layout)
web/static/favicon.png   site icon (replace this PNG to swap)
art/              source art (favicon zip, etc.)
python/           uv lockfile only (app code is not here)
docker-compose/   Dockerfile, compose, nginx.conf, POC (`poc.sh`), event-day (`local.sh`)
```

Request flow: browser → nginx `:8000` → `/photos/*` from disk, everything else to gunicorn. Postgres holds projects, users, roles, photo records, tickets, and kuji draws (`$HOST_PHOTO_DIR/postgres`). Redis is the detect queue and slideshow playhead cache. JPEG files live on the host bind.

## Architecture notes

The split is small and enough: **routes in `web/app.py`**, **Postgres + files + Redis cache in `web/store.py`**, **resize in `web/images.py`**, **defaults in `config/`**. Do not wrap `appsetting` in a class for speed — import-time constants are already cheap.

`/p/<slug>/api/slideshow` only advances the Redis playhead (Lua). The queue is rebuilt on upload, photo drop, and settings save — not on every TV poll.

Uploads are the other cost: Pillow on the gunicorn worker. `JPEG_MAX_EDGE` 2560 and quality 80 (no `optimize=True`) are the right tradeoff. Photos themselves are served by nginx, not Flask.

Tickets live in Postgres. The slideshow playhead stays in Redis (Lua advances it atomically). Do not put the JPEGs in Redis, Postgres, or the image.

Person check runs in the `detector` service (`web/detector.py`, image target `detector`): YOLOX-Tiny ONNX (Apache-2.0, baked into the image) on onnxruntime CPU, about 20ms per photo. Upload saves the photo as `person: pending` and pushes a job on the Redis list `detect_q`; the worker moves it to `detect_busy` while it runs (re-queued on restart), then grants the lottery ticket and one Ichiban Kuji chance if a person is found. Photos without people still play in the slideshow. The upload page polls `/p/<slug>/api/photos/status` for the result. If the detector is down, photos stay pending and nothing is granted until it comes back.

Ichiban Kuji draws are one Postgres transaction (`SELECT … FOR UPDATE` on `kuji_config`, then insert the draw), so stock cannot oversell across gunicorn workers. Claims set `claimed_at` once.
