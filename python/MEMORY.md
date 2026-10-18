# python

## GOTCHA

- App code is `config/` and `web/` at the repo root, not inside `python/`. Docker must set `PYTHONPATH=/app` and put the venv on `PATH` (`/app/python/.venv/bin`).

## TASTE

- `pyproject.toml` and `uv.lock` live in `python/`. `requires-python = ">=3.12"`, `[tool.uv] package = false`.
- Change deps with `cd python && uv add …` / `uv lock`; commit both toml and lock.
- App talks to Postgres with `psycopg[binary,pool]`. Detector needs the same (it writes `set_person`).
- Admin QR codes use the `qrcode` package (Pillow already draws the PNG).
- Detector-only deps live in `[dependency-groups] detector` (`onnxruntime`, `numpy`); the app target does not install them. onnxruntime ships `manylinux_2_28_aarch64` wheels, fine on bookworm.
