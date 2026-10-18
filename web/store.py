import json
import random
import re
import shutil
import time
import uuid
from pathlib import Path

import redis
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from werkzeug.security import check_password_hash, generate_password_hash

from config import admin as admin_config
from config import appsetting
from config import database as database_config
from config import msg
from config import redis as redis_config

_slug_re = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_USER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,31}$")
_GUEST_JPG = re.compile(r"^[0-9a-f]{32}\.jpg$")
ROLES = ("admin", "maintainer", "guest")
STAFF_ROLES = ("admin", "maintainer")
VISITED_MAX = 40

_ADVANCE_LUA = """
local state_key = KEYS[1]
local zkey = KEYS[2]
local now = tonumber(ARGV[1])
local interval = tonumber(ARGV[2])

local ids = redis.call('ZRANGE', zkey, 0, -1)
local n = #ids
if n == 0 then
  redis.call('DEL', state_key)
  return {'', tostring(now), tostring(now), tostring(interval), '0'}
end

local index = tonumber(redis.call('HGET', state_key, 'index') or '0')
local show_until = tonumber(redis.call('HGET', state_key, 'show_until') or '0')

if show_until == nil or show_until == 0 then
  index = 0
  show_until = now + interval
elseif now >= show_until then
  local steps = math.floor((now - show_until) / interval) + 1
  index = (index + steps) % n
  show_until = show_until + steps * interval
  if show_until <= now then
    show_until = now + interval
  end
end

if index < 0 or index >= n then
  index = index % n
end

local photo_id = ids[index + 1]
redis.call('HSET', state_key,
  'index', index,
  'photo_id', photo_id,
  'show_until', show_until,
  'interval', interval)
return {photo_id, tostring(now), tostring(show_until), tostring(interval), tostring(n)}
"""

KUJI_GRADES = ("A", "B", "C", "D", "E")
KUJI_TOTAL_MAX = 999
KUJI_PER_USER_MAX = 50
KUJI_LABEL_MAX = 40

DETECT_Q = "detect_q"
DETECT_BUSY = "detect_busy"

_redis = None
_advance = None
_pg = None
_SCHEMA = Path(__file__).with_name("schema.sql").read_text()


def r():
    global _redis
    if _redis is None:
        _redis = redis.Redis.from_url(redis_config.url, decode_responses=True)
    return _redis


def pg():
    global _pg
    if _pg is None:
        _pg = ConnectionPool(
            conninfo=database_config.url,
            min_size=1,
            max_size=8,
            kwargs={"row_factory": dict_row},
        )
        with _pg.connection() as conn:
            conn.execute("SELECT pg_advisory_lock(872634)")
            try:
                for stmt in _SCHEMA.split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        conn.execute(stmt)
            finally:
                conn.execute("SELECT pg_advisory_unlock(872634)")
    return _pg


def advance_script():
    global _advance
    if _advance is None:
        _advance = r().register_script(_ADVANCE_LUA)
    return _advance


def ttl_seconds():
    return appsetting.record_ttl_days * 86400


def _n(row, key="n"):
    return int(row[key]) if row else 0


def _one(sql, params=(), conn=None):
    if conn is not None:
        return conn.execute(sql, params).fetchone()
    with pg().connection() as c:
        return c.execute(sql, params).fetchone()


def _all(sql, params=(), conn=None):
    if conn is not None:
        return conn.execute(sql, params).fetchall()
    with pg().connection() as c:
        return c.execute(sql, params).fetchall()


def photo_dir(project_id):
    return Path(appsetting.photo_dir) / project_id


def photo_path(project_id, photo_id):
    return photo_dir(project_id) / f"{photo_id}.jpg"


def photo_url(project_id, photo_id):
    return f"/photos/{project_id}/{photo_id}.jpg"


ASSETS = {
    "pjt-mark": "pjt-mark.png",
    "pjt-desktop": "pjt-desktop.jpg",
    "pjt-mobile": "pjt-mobile.jpg",
    "bkg-desktop": "bkg-desktop.jpg",
    "bkg-mobile": "bkg-mobile.jpg",
    "lot-desktop": "lot-desktop.jpg",
    "lot-mobile": "lot-mobile.jpg",
    "kuji-mark": "kuji-mark.png",
    "kuji-ticket": "kuji-ticket.png",
    "kuji-desktop": "kuji-desktop.jpg",
    "kuji-mobile": "kuji-mobile.jpg",
    "kuji-a": "kuji-a.jpg",
    "kuji-b": "kuji-b.jpg",
    "kuji-c": "kuji-c.jpg",
    "kuji-d": "kuji-d.jpg",
    "kuji-e": "kuji-e.jpg",
}


def asset_is_png(kind):
    return ASSETS.get(kind, "").endswith(".png")


_LEGACY = {
    "pjt": "pjt-home.jpg",
    "bkg": "bkg-slideshow.jpg",
}


def asset_path(project_id, kind):
    name = ASSETS.get(kind)
    if not name:
        raise ValueError(msg.bad_asset)
    return photo_dir(project_id) / name


def asset_thumb_path(project_id, kind):
    p = asset_path(project_id, kind)
    return p.with_name(f"{p.stem}-sm.jpg")


def _file_url(project_id, path: Path):
    if not path.is_file():
        return None
    return f"/photos/{project_id}/{path.name}?t={int(path.stat().st_mtime)}"


def asset_url(project_id, kind):
    return _file_url(project_id, asset_path(project_id, kind))


def asset_thumb_url(project_id, kind):
    return _file_url(project_id, asset_thumb_path(project_id, kind)) or asset_url(
        project_id, kind
    )


def attach_assets(project):
    if not project:
        return project
    pid = project["id"]
    for kind in ASSETS:
        key = kind.replace("-", "_")
        project[f"{key}_url"] = asset_url(pid, kind)
        project[f"{key}_thumb_url"] = asset_thumb_url(pid, kind)
    if not project["pjt_mark_url"]:
        project["pjt_mark_url"] = _file_url(pid, photo_dir(pid) / "pjt-mark.jpg")
        project["pjt_mark_thumb_url"] = project["pjt_mark_url"]
    legacy_pjt = _file_url(pid, photo_dir(pid) / _LEGACY["pjt"])
    legacy_bkg = _file_url(pid, photo_dir(pid) / _LEGACY["bkg"])
    project["pjt_desktop_show"] = (
        project["pjt_desktop_url"] or project["pjt_mobile_url"] or legacy_pjt
    )
    project["pjt_mobile_show"] = (
        project["pjt_mobile_url"] or project["pjt_desktop_url"] or legacy_pjt
    )
    project["bkg_desktop_show"] = (
        project["bkg_desktop_url"] or project["bkg_mobile_url"] or legacy_bkg
    )
    project["bkg_mobile_show"] = (
        project["bkg_mobile_url"] or project["bkg_desktop_url"] or legacy_bkg
    )
    project["lot_desktop_show"] = (
        project["lot_desktop_url"] or project["lot_mobile_url"]
    )
    project["lot_mobile_show"] = (
        project["lot_mobile_url"] or project["lot_desktop_url"]
    )
    project["kuji_desktop_show"] = (
        project["kuji_desktop_url"]
        or project["kuji_mobile_url"]
        or project["pjt_desktop_show"]
    )
    project["kuji_mobile_show"] = (
        project["kuji_mobile_url"]
        or project["kuji_desktop_url"]
        or project["pjt_mobile_show"]
    )
    return project


def valid_slug(slug):
    return bool(slug) and len(slug) <= 64 and _slug_re.match(slug)


def make_slug():
    return uuid.uuid4().hex[:10]


def slug_from_name(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())[:64]


SETTINGS = {
    "slideshow_interval": "slideshow_interval",
    "slideshow_queue_max": "slideshow_queue_max",
    "slideshow_per_device": "slideshow_per_device",
    "slideshow_fade": "slideshow_fade",
    "slideshow_mode": "slideshow_mode",
    "lottery_sphere_max": "lottery_sphere_max",
    "lottery_seconds": "lottery_seconds",
}

SETTING_BOUNDS = {
    "slideshow_interval": (1, 120),
    "slideshow_queue_max": (1, 500),
    "slideshow_per_device": (1, 50),
    "slideshow_fade": (0.0, 3.0),
    "lottery_sphere_max": (1, 200),
    "lottery_seconds": (1, 60),
}

SETTING_ENUMS = {
    "slideshow_mode": ("wall", "full"),
}


def default_settings():
    return {k: getattr(appsetting, k) for k in SETTINGS}


def _parse_setting(k, v):
    allowed = SETTING_ENUMS.get(k)
    if allowed:
        s = str(v or "").strip()
        if s not in allowed:
            raise ValueError(msg.bad_setting)
        return s
    lo, hi = SETTING_BOUNDS[k]
    if isinstance(lo, float):
        n = round(float(v), 1)
    else:
        n = int(v)
    if n < lo or n > hi:
        raise ValueError(msg.bad_setting)
    return n


def settings_of(project_id, raw=None):
    if raw is None:
        raw = _one("SELECT * FROM projects WHERE id = %s", (project_id,)) or {}
    out = default_settings()
    for k in SETTINGS:
        try:
            out[k] = _parse_setting(k, raw[k])
        except (KeyError, TypeError, ValueError):
            pass
    return out


def update_project_settings(project_id, form):
    if not get_project(project_id):
        raise ValueError(msg.project_missing)
    sets = []
    args = []
    for k in SETTINGS:
        if k not in form:
            continue
        try:
            n = _parse_setting(k, form.get(k))
        except (TypeError, ValueError):
            raise ValueError(msg.bad_setting)
        sets.append(f"{k} = %s")
        args.append(n)
    if sets:
        args.append(project_id)
        with pg().connection() as conn:
            conn.execute(
                f"UPDATE projects SET {', '.join(sets)} WHERE id = %s", args
            )
    cfgp = settings_of(project_id)
    rebuild_slideshow_queue(project_id, cfgp)
    return cfgp


def _project_from_row(row):
    if not row:
        return None
    data = dict(row)
    data["created_at"] = str(int(float(data["created_at"])))
    data.update(settings_of(data["id"], raw=data))
    return attach_assets(data)


def get_project(project_id):
    return _project_from_row(_one("SELECT * FROM projects WHERE id = %s", (project_id,)))


def project_by_slug(slug):
    return _project_from_row(_one("SELECT * FROM projects WHERE slug = %s", (slug,)))


def list_projects_for_ids(ids):
    out = []
    seen = set()
    for pid in ids:
        if pid in seen:
            continue
        seen.add(pid)
        p = get_project(pid)
        if not p:
            continue
        p["photo_count"] = _n(
            _one("SELECT COUNT(*) AS n FROM photos WHERE project_id = %s", (pid,))
        )
        p["kuji"] = kuji_state(pid)
        out.append(p)
    out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return out


def list_projects():
    rows = _all("SELECT id FROM projects")
    return list_projects_for_ids([row["id"] for row in rows])


def projects_by_slugs(slugs):
    out = []
    seen = set()
    for slug in slugs:
        p = project_by_slug(slug)
        if p and p["id"] not in seen:
            seen.add(p["id"])
            out.append(p)
    return out


def parse_visited(cookie):
    slugs = []
    for s in (cookie or "").split(","):
        s = s.strip().lower()
        if valid_slug(s) and s not in slugs:
            slugs.append(s)
        if len(slugs) >= VISITED_MAX:
            break
    return slugs


def create_project(name, slug, owner=None):
    name = (name or "").strip()
    slug = (slug or "").strip().lower()
    if not name:
        raise ValueError(msg.need_project_name)
    auto = not slug
    if auto:
        slug = slug_from_name(name) or make_slug()
    if not valid_slug(slug):
        raise ValueError(msg.bad_slug)
    if _one("SELECT 1 AS n FROM projects WHERE slug = %s", (slug,)):
        if auto:
            slug = f"{slug[:53]}-{make_slug()}" if slug_from_name(name) else make_slug()
        else:
            raise ValueError(msg.slug_taken)
        if _one("SELECT 1 AS n FROM projects WHERE slug = %s", (slug,)):
            raise ValueError(msg.slug_taken)
    pid = uuid.uuid4().hex
    defaults = default_settings()
    with pg().connection() as conn:
        conn.execute(
            """
            INSERT INTO projects (
              id, name, slug, created_at,
              slideshow_interval, slideshow_queue_max, slideshow_per_device,
              slideshow_fade, slideshow_mode, lottery_sphere_max, lottery_seconds
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                pid,
                name,
                slug,
                time.time(),
                defaults["slideshow_interval"],
                defaults["slideshow_queue_max"],
                defaults["slideshow_per_device"],
                defaults["slideshow_fade"],
                defaults["slideshow_mode"],
                defaults["lottery_sphere_max"],
                defaults["lottery_seconds"],
            ),
        )
        conn.execute(
            """
            INSERT INTO kuji_config (project_id, per_user)
            VALUES (%s, %s)
            """,
            (pid, appsetting.kuji_per_user),
        )
    photo_dir(pid).mkdir(parents=True, exist_ok=True)
    if owner and not is_root(owner):
        set_user_role(owner, pid, "admin")
    return get_project(pid)


def wipe_tickets(project_id):
    with pg().connection() as conn:
        conn.execute("DELETE FROM tickets WHERE project_id = %s", (project_id,))
        conn.execute("DELETE FROM ticket_seq WHERE project_id = %s", (project_id,))
        conn.execute("DELETE FROM lottery_won WHERE project_id = %s", (project_id,))
    kuji_reset(project_id)


def wipe_photos(project_id, delete_files):
    with pg().connection() as conn:
        conn.execute("DELETE FROM photos WHERE project_id = %s", (project_id,))
    r().delete(f"slideshow:{project_id}", f"slideshow_q:{project_id}")
    wipe_tickets(project_id)
    if delete_files:
        d = photo_dir(project_id)
        if d.exists():
            shutil.rmtree(d)


def reset_guest_photos(project_id):
    p = get_project(project_id)
    if not p:
        raise ValueError(msg.project_missing)
    wipe_photos(project_id, delete_files=False)
    d = photo_dir(project_id)
    if d.exists():
        for path in d.iterdir():
            if path.is_file() and _GUEST_JPG.match(path.name):
                path.unlink(missing_ok=True)
    return p


def delete_project(project_id, delete_files):
    p = get_project(project_id)
    if not p:
        raise ValueError(msg.project_missing)
    wipe_photos(project_id, delete_files=delete_files)
    with pg().connection() as conn:
        conn.execute("DELETE FROM projects WHERE id = %s", (project_id,))
    r().delete(f"slideshow:{project_id}", f"slideshow_q:{project_id}")
    return p


def ensure_root():
    name = (admin_config.username or "").strip()
    password = admin_config.password or ""
    if not name or not password:
        return
    with pg().connection() as conn:
        conn.execute(
            """
            INSERT INTO users (name, password, is_root, lang, created_at)
            VALUES (%s, %s, TRUE, 'zh', %s)
            ON CONFLICT (name) DO NOTHING
            """,
            (name, generate_password_hash(password), time.time()),
        )


def valid_username(name):
    return bool(name) and bool(_USER_RE.match(name))


def get_user(name):
    if not name:
        return None
    data = _one("SELECT * FROM users WHERE name = %s", (name,))
    if not data or not data.get("password"):
        return None
    data["name"] = name
    data["is_root"] = bool(data.get("is_root"))
    data["lang"] = msg.normalize_lang(data.get("lang"))
    return data


def authenticate(name, password):
    u = get_user((name or "").strip())
    if not u or not check_password_hash(u["password"], password or ""):
        return None
    return u


def create_user(name, password):
    name = (name or "").strip()
    if not valid_username(name):
        raise ValueError(msg.bad_username)
    if not 4 <= len(password or "") <= 72:
        raise ValueError(msg.bad_password)
    if _one("SELECT 1 AS n FROM users WHERE name = %s", (name,)):
        raise ValueError(msg.username_taken)
    with pg().connection() as conn:
        conn.execute(
            """
            INSERT INTO users (name, password, is_root, lang, created_at)
            VALUES (%s, %s, FALSE, 'zh', %s)
            """,
            (name, generate_password_hash(password), time.time()),
        )
    return get_user(name)


def set_password(name, password):
    if not get_user(name):
        raise ValueError(msg.user_missing)
    if not 4 <= len(password or "") <= 72:
        raise ValueError(msg.bad_password)
    with pg().connection() as conn:
        conn.execute(
            "UPDATE users SET password = %s WHERE name = %s",
            (generate_password_hash(password), name),
        )


def change_password(name, old, new):
    if not authenticate(name, old):
        raise ValueError(msg.wrong_password)
    set_password(name, new)


def delete_user(name):
    u = get_user(name)
    if not u:
        raise ValueError(msg.user_missing)
    if u["is_root"]:
        raise ValueError(msg.cannot_delete_root)
    with pg().connection() as conn:
        conn.execute("DELETE FROM users WHERE name = %s", (name,))


def user_roles(name):
    rows = _all(
        "SELECT project_id, role FROM user_projects WHERE user_name = %s", (name,)
    )
    return {row["project_id"]: row["role"] for row in rows}


def list_users():
    rows = _all("SELECT name FROM users ORDER BY LOWER(name)")
    out = []
    for row in rows:
        u = get_user(row["name"])
        if not u:
            continue
        u["roles"] = user_roles(row["name"])
        out.append(u)
    return out


def is_root(name):
    u = get_user(name)
    return bool(u and u["is_root"])


def user_role(name, project_id):
    u = get_user(name)
    if not u:
        return None
    if u["is_root"]:
        return "root"
    row = _one(
        """
        SELECT role FROM user_projects
        WHERE user_name = %s AND project_id = %s
        """,
        (name, project_id),
    )
    role = row["role"] if row else None
    return role if role in ROLES else None


def set_user_role(name, project_id, role):
    u = get_user(name)
    if not u:
        raise ValueError(msg.user_missing)
    if u["is_root"]:
        raise ValueError(msg.cannot_assign_root)
    if not get_project(project_id):
        raise ValueError(msg.project_missing)
    role = (role or "").strip()
    with pg().connection() as conn:
        if not role:
            conn.execute(
                """
                DELETE FROM user_projects
                WHERE user_name = %s AND project_id = %s
                """,
                (name, project_id),
            )
            return
        if role not in ROLES:
            raise ValueError(msg.bad_role)
        conn.execute(
            """
            INSERT INTO user_projects (user_name, project_id, role)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_name, project_id) DO UPDATE SET role = EXCLUDED.role
            """,
            (name, project_id, role),
        )


def save_user_roles(name, form, project_ids):
    for pid in project_ids:
        set_user_role(name, pid, form.get(f"role_{pid}"))


def user_lang(name):
    row = _one("SELECT lang FROM users WHERE name = %s", (name,))
    return msg.normalize_lang(row["lang"] if row else None)


def set_user_lang(name, lang):
    if not get_user(name):
        raise ValueError(msg.user_missing)
    lang = msg.normalize_lang(lang)
    with pg().connection() as conn:
        conn.execute("UPDATE users SET lang = %s WHERE name = %s", (lang, name))
    return lang


def visible_ids(name):
    u = get_user(name)
    if not u:
        return []
    if u["is_root"]:
        return [row["id"] for row in _all("SELECT id FROM projects")]
    return list(user_roles(name).keys())


def staff_ids(name):
    u = get_user(name)
    if not u:
        return []
    if u["is_root"]:
        return [row["id"] for row in _all("SELECT id FROM projects")]
    return [pid for pid, role in user_roles(name).items() if role in STAFF_ROLES]


def can_staff(name):
    u = get_user(name)
    if not u:
        return False
    if u["is_root"]:
        return True
    return any(role in STAFF_ROLES for role in user_roles(name).values())


def can_create_project(name):
    u = get_user(name)
    if not u:
        return False
    if u["is_root"]:
        return True
    return any(role == "admin" for role in user_roles(name).values())


def can_edit(name, project_id):
    return user_role(name, project_id) in ("root", "admin", "maintainer")


def can_delete_project(name, project_id):
    return user_role(name, project_id) in ("root", "admin")


def can_lottery(name, project_id):
    return user_role(name, project_id) in ("root", "admin", "maintainer", "guest")


def chance_count(project_id, device_id, conn=None):
    return _n(
        _one(
            """
            SELECT COUNT(*) AS n FROM tickets
            WHERE project_id = %s AND device_id = %s
            """,
            (project_id, device_id),
            conn=conn,
        )
    )


def _next_serial(conn, project_id):
    row = conn.execute(
        """
        INSERT INTO ticket_seq (project_id, n) VALUES (%s, 1)
        ON CONFLICT (project_id) DO UPDATE SET n = ticket_seq.n + 1
        RETURNING n
        """,
        (project_id,),
    ).fetchone()
    return f"{row['n']:06d}"


def add_ticket(project_id, photo_id, device_id, conn=None):
    now = time.time()

    def run(c):
        serial = _next_serial(c, project_id)
        c.execute(
            """
            INSERT INTO tickets (project_id, serial, photo_id, device_id, ts)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (project_id, serial, photo_id, device_id, now),
        )
        n = chance_count(project_id, device_id, conn=c)
        return serial, n

    if conn is not None:
        return run(conn)
    with pg().connection() as c:
        return run(c)


def enqueue_detect(project_id, photo_id, device_id):
    r().lpush(
        DETECT_Q,
        json.dumps(
            {"project_id": project_id, "photo_id": photo_id, "device_id": device_id}
        ),
    )


def requeue_pending():
    for row in _all(
        "SELECT project_id, id, device_id FROM photos WHERE person IS NULL"
    ):
        enqueue_detect(row["project_id"], row["id"], row["device_id"])


def add_photo(project_id, photo_id, caption, device_id, rebuild=True, consent=None):
    """Save the photo record; chances are granted later by the detector."""
    now = time.time()
    with pg().connection() as conn:
        conn.execute(
            """
            INSERT INTO photos (project_id, id, caption, device_id, ts, person, consent)
            VALUES (%s, %s, %s, %s, %s, NULL, %s)
            """,
            (project_id, photo_id, caption or "", device_id, now, consent),
        )
        conn.execute(
            """
            INSERT INTO devices (id) VALUES (%s)
            ON CONFLICT (id) DO NOTHING
            """,
            (device_id,),
        )
    enqueue_detect(project_id, photo_id, device_id)
    if rebuild:
        rebuild_slideshow_queue(project_id)


def grant_person(project_id, photo_id, device_id, ts, conn=None):
    cap = appsetting.lottery_chance_max

    def run(c):
        if chance_count(project_id, device_id, conn=c) >= cap:
            drop_oldest_ticket(project_id, device_id, conn=c)
        _, n = add_ticket(project_id, photo_id, device_id, conn=c)
        if n > cap:
            drop_oldest_ticket(project_id, device_id, conn=c)

    if conn is not None:
        return run(conn)
    with pg().connection() as c:
        run(c)


def set_person(project_id, photo_id, device_id, person):
    """Record the detector result once; a person grants lottery + kuji chances."""
    with pg().connection() as conn:
        with conn.transaction():
            row = conn.execute(
                """
                SELECT * FROM photos
                WHERE project_id = %s AND id = %s
                FOR UPDATE
                """,
                (project_id, photo_id),
            ).fetchone()
            if not row or row.get("person") is not None:
                return
            conn.execute(
                """
                UPDATE photos SET person = %s
                WHERE project_id = %s AND id = %s
                """,
                (bool(person), project_id, photo_id),
            )
            if person:
                grant_person(
                    project_id,
                    photo_id,
                    row.get("device_id") or device_id,
                    row.get("ts") or time.time(),
                    conn=conn,
                )


def photo_status(project_id, device_id, photo_ids):
    out = {}
    for pid in photo_ids[:20]:
        item = load_photo(project_id, pid)
        if not item or item.get("device_id") != device_id:
            continue
        out[pid] = item.get("person")
    return {
        "photos": out,
        "chances": chance_count(project_id, device_id),
        "kuji": kuji_me(project_id, device_id),
    }


def nickname_of(device_id):
    if not device_id:
        return ""
    row = _one("SELECT nickname FROM devices WHERE id = %s", (device_id,))
    return (row["nickname"] if row else "") or ""


def set_nickname(device_id, name):
    name = (name or "").strip()
    if not name or len(name) > 20:
        raise ValueError(msg.nickname_bad)
    with pg().connection() as conn:
        conn.execute(
            """
            INSERT INTO devices (id, nickname) VALUES (%s, %s)
            ON CONFLICT (id) DO UPDATE SET nickname = EXCLUDED.nickname
            """,
            (device_id, name),
        )
    return name


def device_lang(device_id):
    row = _one("SELECT lang FROM devices WHERE id = %s", (device_id,))
    raw = row["lang"] if row else ""
    if not raw:
        return ""
    return msg.normalize_lang(raw)


def set_device_lang(device_id, lang):
    lang = msg.normalize_lang(lang)
    with pg().connection() as conn:
        conn.execute(
            """
            INSERT INTO devices (id, lang) VALUES (%s, %s)
            ON CONFLICT (id) DO UPDATE SET lang = EXCLUDED.lang
            """,
            (device_id, lang),
        )
    return lang


def load_photo(project_id, photo_id):
    row = _one(
        "SELECT * FROM photos WHERE project_id = %s AND id = %s",
        (project_id, photo_id),
    )
    if not row:
        return None
    data = dict(row)
    data["id"] = photo_id
    data["url"] = photo_url(project_id, photo_id)
    data["nickname"] = nickname_of(data.get("device_id"))
    return data


def drop_photo(project_id, photo_id, rebuild=True):
    with pg().connection() as conn:
        conn.execute(
            "DELETE FROM photos WHERE project_id = %s AND id = %s",
            (project_id, photo_id),
        )
    photo_path(project_id, photo_id).unlink(missing_ok=True)
    if rebuild:
        rebuild_slideshow_queue(project_id)


def sweep_expired(project_id):
    cutoff = time.time() - ttl_seconds()
    rows = _all(
        "SELECT id FROM photos WHERE project_id = %s AND ts < %s",
        (project_id, cutoff),
    )
    kept = []
    for row in rows:
        drop_photo(project_id, row["id"], rebuild=False)
    for row in _all(
        "SELECT id FROM photos WHERE project_id = %s ORDER BY ts",
        (project_id,),
    ):
        item = load_photo(project_id, row["id"])
        if item:
            kept.append(item)
    rebuild_slideshow_queue(project_id)
    return kept


def rebuild_slideshow_queue(project_id, cfgp=None):
    qkey = f"slideshow_q:{project_id}"
    cfgp = cfgp or settings_of(project_id)
    cap = cfgp["slideshow_queue_max"]
    per = cfgp["slideshow_per_device"]
    total = _n(_one("SELECT COUNT(*) AS n FROM photos WHERE project_id = %s", (project_id,)))
    if total <= cap:
        rows = _all(
            "SELECT id, ts FROM photos WHERE project_id = %s",
            (project_id,),
        )
    else:
        rows = _all(
            """
            SELECT id, ts FROM (
              SELECT id, ts,
                ROW_NUMBER() OVER (PARTITION BY device_id ORDER BY ts DESC) AS rn
              FROM photos WHERE project_id = %s
            ) x
            WHERE rn <= %s
            ORDER BY ts DESC
            LIMIT %s
            """,
            (project_id, per, cap),
        )
    mapping = {row["id"]: float(row["ts"]) for row in rows}
    pipe = r().pipeline()
    pipe.delete(qkey)
    if mapping:
        pipe.zadd(qkey, mapping)
    pipe.execute()


def _empty_state(server_now, interval):
    return {
        "photo_id": None,
        "url": None,
        "caption": "",
        "server_now": float(server_now),
        "show_until": float(server_now),
        "interval": int(interval),
    }


def slideshow_state(project_id):
    cfgp = settings_of(project_id)
    interval = cfgp["slideshow_interval"]
    qkey = f"slideshow_q:{project_id}"
    conn = r()
    if conn.zcard(qkey) == 0:
        n = _n(
            _one("SELECT COUNT(*) AS n FROM photos WHERE project_id = %s", (project_id,))
        )
        if n > 0:
            rebuild_slideshow_queue(project_id, cfgp)
    for _ in range(8):
        now = time.time()
        result = advance_script()(
            keys=[f"slideshow:{project_id}", qkey],
            args=[now, interval],
        )
        photo_id, server_now, show_until, interval, n = result
        if not photo_id or n == "0":
            return _empty_state(server_now, interval)
        item = load_photo(project_id, photo_id)
        if item is None:
            drop_photo(project_id, photo_id)
            continue
        return {
            "photo_id": photo_id,
            "url": item["url"],
            "caption": item.get("caption") or "",
            "nickname": item.get("nickname") or "",
            "server_now": float(server_now),
            "show_until": float(show_until),
            "interval": int(float(interval)),
        }
    return _empty_state(time.time(), interval)


def _ticket(project_id, serial, conn=None):
    row = _one(
        "SELECT * FROM tickets WHERE project_id = %s AND serial = %s",
        (project_id, serial),
        conn=conn,
    )
    if not row:
        return None
    data = dict(row)
    data["serial"] = serial
    return data


def drop_ticket(project_id, serial, conn=None):
    def run(c):
        c.execute(
            "DELETE FROM tickets WHERE project_id = %s AND serial = %s",
            (project_id, serial),
        )

    if conn is not None:
        return run(conn)
    with pg().connection() as c:
        run(c)


def drop_oldest_ticket(project_id, device_id, conn=None):
    def run(c):
        row = c.execute(
            """
            SELECT serial FROM tickets
            WHERE project_id = %s AND device_id = %s
            ORDER BY ts ASC
            LIMIT 1
            """,
            (project_id, device_id),
        ).fetchone()
        if not row:
            return False
        drop_ticket(project_id, row["serial"], conn=c)
        return True

    if conn is not None:
        return run(conn)
    with pg().connection() as c:
        return run(c)


def latest_photo_ids(project_id, device_id, n):
    rows = _all(
        """
        SELECT id FROM photos
        WHERE project_id = %s AND device_id = %s AND person IS TRUE
        ORDER BY ts DESC
        LIMIT %s
        """,
        (project_id, device_id, n),
    )
    return {row["id"] for row in rows}


def device_photos(project_id, device_id, exclude=None, limit=None):
    sql = """
        SELECT id FROM photos
        WHERE project_id = %s AND device_id = %s
        ORDER BY ts DESC
    """
    params = [project_id, device_id]
    if limit is not None:
        sql += " LIMIT %s"
        params.append(max(0, limit))
    out = []
    for row in _all(sql, params):
        if exclude and row["id"] == exclude:
            continue
        item = load_photo(project_id, row["id"])
        if item is None:
            continue
        out.append({"id": item["id"], "url": item["url"]})
    return out


def won_devices(project_id):
    return {row["device_id"] for row in _all(
        "SELECT device_id FROM lottery_won WHERE project_id = %s", (project_id,)
    )}


def mark_won(project_id, device_id):
    if not device_id:
        return
    with pg().connection() as conn:
        conn.execute(
            """
            INSERT INTO lottery_won (project_id, device_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (project_id, device_id),
        )


def reset_lottery_winners(project_id):
    if not get_project(project_id):
        raise ValueError(msg.project_missing)
    with pg().connection() as conn:
        conn.execute("DELETE FROM lottery_won WHERE project_id = %s", (project_id,))


def lottery_pool(project_id):
    cap = appsetting.lottery_chance_max
    won = won_devices(project_id)
    rows = _all(
        """
        SELECT id, device_id FROM (
          SELECT id, device_id, ts,
            ROW_NUMBER() OVER (PARTITION BY device_id ORDER BY ts DESC) AS rn
          FROM photos
          WHERE project_id = %s AND person IS TRUE
        ) x
        WHERE rn <= %s
        """,
        (project_id, cap),
    )
    out = []
    for row in rows:
        if row["device_id"] in won:
            continue
        item = load_photo(project_id, row["id"])
        if item:
            out.append(item)
    return out


def sphere_photos(project_id, limit):
    items = lottery_pool(project_id)
    if not items:
        return []
    if len(items) > limit:
        items = random.sample(items, limit)
    photos = [{"id": i["id"], "url": i["url"]} for i in items]
    i = 0
    while len(photos) < limit:
        src = photos[i % len(photos)]
        photos.append(src)
        i += 1
    return photos


def draw_lottery(project_id):
    cap = appsetting.lottery_chance_max
    won = won_devices(project_id)
    serials = [
        row["serial"]
        for row in _all(
            "SELECT serial FROM tickets WHERE project_id = %s ORDER BY ts",
            (project_id,),
        )
    ]
    random.shuffle(serials)
    winner = None
    for serial in serials:
        t = _ticket(project_id, serial)
        if not t:
            drop_ticket(project_id, serial)
            continue
        if t.get("device_id") in won:
            continue
        latest = latest_photo_ids(project_id, t.get("device_id"), cap)
        if t.get("photo_id") not in latest:
            drop_ticket(project_id, serial)
            continue
        photo = load_photo(project_id, t["photo_id"])
        if photo is None:
            drop_ticket(project_id, serial)
            continue
        winner = (t, photo)
        break
    if not winner:
        raise ValueError(msg.lottery_empty)
    t, photo = winner
    others = device_photos(
        project_id, t["device_id"], exclude=photo["id"], limit=cap
    )
    total = _n(
        _one(
            """
            SELECT COUNT(*) AS n FROM photos
            WHERE project_id = %s AND device_id = %s
            """,
            (project_id, t["device_id"]),
        )
    )
    cfgp = settings_of(project_id)
    sphere = sphere_photos(project_id, cfgp["lottery_sphere_max"])
    mark_won(project_id, t.get("device_id"))
    return {
        "serial": t["serial"],
        "seconds": cfgp["lottery_seconds"],
        "winner": {
            "id": photo["id"],
            "url": photo["url"],
            "caption": photo.get("caption") or "",
            "nickname": photo.get("nickname") or "",
            "upload_count": total or len(others) + 1,
        },
        "device_photos": others,
        "sphere": sphere,
    }


def kuji_label_part(raw, key, fallback):
    s = (raw.get(key) or "").strip()
    if not s or len(s) > KUJI_LABEL_MAX:
        return "", fallback
    return s, s


def kuji_names_of(raw, grade):
    zh_raw, zh = kuji_label_part(
        raw, f"label_{grade}", msg.kuji_grade_zh.format(grade=grade)
    )
    en_raw, en = kuji_label_part(
        raw, f"label_en_{grade}", msg.kuji_grade_en.format(grade=grade)
    )
    return {
        "label": f"{zh} / {en}",
        "label_zh": zh,
        "label_en": en,
        "label_raw": zh_raw,
        "label_en_raw": en_raw,
    }


def _kuji_raw(project_id, conn=None):
    row = _one("SELECT * FROM kuji_config WHERE project_id = %s", (project_id,), conn=conn)
    if not row:
        return {}
    raw = {
        "per_user": row["per_user"],
    }
    for g in KUJI_GRADES:
        raw[g] = row[f"total_{g.lower()}"]
        raw[f"label_{g}"] = row[f"label_{g.lower()}"]
        raw[f"label_en_{g}"] = row[f"label_en_{g.lower()}"]
    return raw


def kuji_settings(project_id, conn=None):
    raw = _kuji_raw(project_id, conn=conn)
    out = {
        "per_user": appsetting.kuji_per_user,
        "totals": {},
        "names": {},
    }
    try:
        out["per_user"] = int(raw["per_user"])
    except (KeyError, TypeError, ValueError):
        pass
    for g in KUJI_GRADES:
        try:
            out["totals"][g] = int(raw.get(g) or 0)
        except (TypeError, ValueError):
            out["totals"][g] = 0
        out["names"][g] = kuji_names_of(raw, g)
    return out


def kuji_save(project_id, form):
    if not get_project(project_id):
        raise ValueError(msg.project_missing)
    try:
        per = int(form.get("per_user"))
        totals = [int(form.get(f"total_{g}") or 0) for g in KUJI_GRADES]
    except (TypeError, ValueError):
        raise ValueError(msg.bad_setting)
    if not 0 <= per <= KUJI_PER_USER_MAX:
        raise ValueError(msg.bad_setting)
    if any(not 0 <= t <= KUJI_TOTAL_MAX for t in totals):
        raise ValueError(msg.bad_setting)
    labels = {}
    for g in KUJI_GRADES:
        zh = (form.get(f"label_{g}") or "").strip()
        en = (form.get(f"label_en_{g}") or "").strip()
        if len(zh) > KUJI_LABEL_MAX or len(en) > KUJI_LABEL_MAX:
            raise ValueError(msg.kuji_label_too_long)
        labels[g] = (zh, en)
    with pg().connection() as conn:
        with conn.transaction():
            conn.execute(
                "SELECT 1 FROM kuji_config WHERE project_id = %s FOR UPDATE",
                (project_id,),
            )
            drawn = {
                row["grade"]: int(row["n"])
                for row in conn.execute(
                    """
                    SELECT grade, COUNT(*) AS n FROM kuji_draws
                    WHERE project_id = %s GROUP BY grade
                    """,
                    (project_id,),
                ).fetchall()
            }
            for g, total in zip(KUJI_GRADES, totals):
                if total < drawn.get(g, 0):
                    raise ValueError(msg.kuji_total_below_drawn.format(grade=g))
            conn.execute(
                """
                INSERT INTO kuji_config (
                  project_id, per_user,
                  total_a, total_b, total_c, total_d, total_e,
                  label_a, label_b, label_c, label_d, label_e,
                  label_en_a, label_en_b, label_en_c, label_en_d, label_en_e
                ) VALUES (
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (project_id) DO UPDATE SET
                  per_user = EXCLUDED.per_user,
                  total_a = EXCLUDED.total_a, total_b = EXCLUDED.total_b,
                  total_c = EXCLUDED.total_c, total_d = EXCLUDED.total_d,
                  total_e = EXCLUDED.total_e,
                  label_a = EXCLUDED.label_a, label_b = EXCLUDED.label_b,
                  label_c = EXCLUDED.label_c, label_d = EXCLUDED.label_d,
                  label_e = EXCLUDED.label_e,
                  label_en_a = EXCLUDED.label_en_a, label_en_b = EXCLUDED.label_en_b,
                  label_en_c = EXCLUDED.label_en_c, label_en_d = EXCLUDED.label_en_d,
                  label_en_e = EXCLUDED.label_en_e
                """,
                (
                    project_id,
                    per,
                    *totals,
                    *[labels[g][0] for g in KUJI_GRADES],
                    *[labels[g][1] for g in KUJI_GRADES],
                ),
            )


def kuji_reset(project_id):
    with pg().connection() as conn:
        conn.execute("DELETE FROM kuji_draws WHERE project_id = %s", (project_id,))
        conn.execute(
            "UPDATE kuji_config SET seq = 0 WHERE project_id = %s", (project_id,)
        )


def _prize_urls(project_id, grade):
    kind = f"kuji-{grade.lower()}"
    return asset_url(project_id, kind), asset_thumb_url(project_id, kind)


def kuji_state(project_id):
    cfgk = kuji_settings(project_id)
    drawn_rows = _all(
        """
        SELECT grade, COUNT(*) AS n FROM kuji_draws
        WHERE project_id = %s GROUP BY grade
        """,
        (project_id,),
    )
    drawn = {row["grade"]: int(row["n"]) for row in drawn_rows}
    grades = []
    for g in KUJI_GRADES:
        total = cfgk["totals"][g]
        d = min(total, drawn.get(g, 0))
        url, thumb = _prize_urls(project_id, g)
        grades.append(
            {"grade": g, **cfgk["names"][g],
             "total": total, "drawn": d, "left": total - d,
             "url": url, "thumb": thumb}
        )
    return {
        "per_user": cfgk["per_user"],
        "grades": grades,
        "total": sum(x["total"] for x in grades),
        "left": sum(x["left"] for x in grades),
    }


def kuji_me(project_id, device_id, unlimited=False, conn=None):
    per = kuji_settings(project_id, conn=conn)["per_user"]
    earned = _n(
        _one(
            """
            SELECT COUNT(*) AS n FROM photos
            WHERE project_id = %s AND device_id = %s AND person IS TRUE
            """,
            (project_id, device_id),
            conn=conn,
        )
    )
    used = _n(
        _one(
            """
            SELECT COUNT(*) AS n FROM kuji_draws
            WHERE project_id = %s AND device_id = %s
            """,
            (project_id, device_id),
            conn=conn,
        )
    )
    pending = _n(
        _one(
            """
            SELECT COUNT(*) AS n FROM photos
            WHERE project_id = %s AND device_id = %s AND person IS NULL
            """,
            (project_id, device_id),
            conn=conn,
        )
    )
    left = 1 if unlimited else max(0, min(earned, per) - used)
    return {
        "earned": earned,
        "used": used,
        "per_user": per,
        "left": left,
        "unlimited": bool(unlimited),
        "pending": pending,
    }


def kuji_draw(project_id, device_id, unlimited=False):
    with pg().connection() as conn:
        with conn.transaction():
            cfg = conn.execute(
                "SELECT * FROM kuji_config WHERE project_id = %s FOR UPDATE",
                (project_id,),
            ).fetchone()
            if not cfg:
                conn.execute(
                    "INSERT INTO kuji_config (project_id, per_user) VALUES (%s, %s)",
                    (project_id, appsetting.kuji_per_user),
                )
                cfg = conn.execute(
                    "SELECT * FROM kuji_config WHERE project_id = %s FOR UPDATE",
                    (project_id,),
                ).fetchone()
            me = kuji_me(project_id, device_id, unlimited=unlimited, conn=conn)
            if not unlimited and me["used"] >= min(me["earned"], me["per_user"]):
                if me["used"] >= me["per_user"]:
                    raise ValueError(msg.kuji_cap_reached.format(n=me["per_user"]))
                if me["pending"]:
                    raise ValueError(msg.kuji_pending)
                raise ValueError(msg.kuji_need_photo)
            left = []
            for g in KUJI_GRADES:
                total = int(cfg[f"total_{g.lower()}"] or 0)
                drawn = _n(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS n FROM kuji_draws
                        WHERE project_id = %s AND grade = %s
                        """,
                        (project_id, g),
                    ).fetchone()
                )
                left.append(max(0, total - drawn))
            total_left = sum(left)
            if total_left == 0:
                raise ValueError(msg.kuji_sold_out)
            pick = int(random.random() * total_left)
            if pick >= total_left:
                pick = total_left - 1
            grade = None
            for g, n in zip(KUJI_GRADES, left):
                if pick < n:
                    grade = g
                    break
                pick -= n
            row = conn.execute(
                """
                UPDATE kuji_config SET seq = seq + 1
                WHERE project_id = %s RETURNING seq
                """,
                (project_id,),
            ).fetchone()
            draw_id = str(row["seq"])
            conn.execute(
                """
                INSERT INTO kuji_draws (project_id, id, grade, device_id, ts)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (project_id, draw_id, grade, device_id, time.time()),
            )
    url, thumb = _prize_urls(project_id, grade)
    names = kuji_settings(project_id)["names"][grade]
    return {
        "id": draw_id,
        "grade": grade,
        "label": names["label"],
        "label_zh": names["label_zh"],
        "label_en": names["label_en"],
        "url": url,
        "thumb": thumb,
        "me": kuji_me(project_id, device_id, unlimited=unlimited),
    }


def kuji_mine(project_id, device_id):
    rows = _all(
        """
        SELECT id, grade, ts, claimed_at FROM kuji_draws
        WHERE project_id = %s AND device_id = %s
        ORDER BY ts
        """,
        (project_id, device_id),
    )
    if not rows:
        return []
    names = kuji_settings(project_id)["names"]
    out = []
    for row in rows:
        url, thumb = _prize_urls(project_id, row["grade"])
        n = names.get(row["grade"]) or kuji_names_of({}, row["grade"])
        claimed = row.get("claimed_at")
        out.append(
            {"id": row["id"], "grade": row["grade"],
             "label": n["label"], "label_zh": n["label_zh"], "label_en": n["label_en"],
             "ts": row.get("ts"),
             "url": url, "thumb": thumb,
             "claimed_at": int(claimed) if claimed else None}
        )
    return out


def kuji_claim(project_id, device_id, draw_id):
    now = int(time.time())
    with pg().connection() as conn:
        row = conn.execute(
            """
            SELECT device_id, claimed_at FROM kuji_draws
            WHERE project_id = %s AND id = %s
            """,
            (project_id, draw_id),
        ).fetchone()
        if not row or row["device_id"] != device_id:
            raise ValueError(msg.kuji_claim_missing)
        if row["claimed_at"]:
            raise ValueError(msg.kuji_already_claimed)
        updated = conn.execute(
            """
            UPDATE kuji_draws SET claimed_at = %s
            WHERE project_id = %s AND id = %s AND claimed_at IS NULL
            """,
            (now, project_id, draw_id),
        )
        if updated.rowcount != 1:
            raise ValueError(msg.kuji_already_claimed)
    return now
