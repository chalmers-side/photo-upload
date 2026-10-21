"""Grand-challenge sessions, players, tasks, and judge queue."""
import json
import random
import re
import shutil
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from psycopg.errors import UniqueViolation

from config import challenge as challenge_cfg
from config import msg
from web import applog, store

JUDGE_Q = "judge_q"
JUDGE_BUSY = "judge_busy"
TAIPEI = ZoneInfo("Asia/Taipei")
LIVE = ("lobby", "running")
KINDS = ("demo", "adventure")
PHOTO_KINDS = ("person", "color", "couple")
NAME_MAX = 12
LIVE_ROOM_MAX = 5
PIN_RE = re.compile(r"^\d{4}$")
JUDGE_TIMEOUT = 15
JUDGE_BUSY_TIMEOUT = 60


def cfg():
    return challenge_cfg.settings()


def threshold():
    return float(cfg().get("judge_threshold") or 0.5)


def player_cap(kind):
    data = cfg()
    if kind == "demo":
        return int((data.get("demo") or {}).get("max_players") or 1)
    return int(data.get("max_players") or 4)


def submission_path(project_id, session_id, photo_id):
    return store.photo_dir(project_id) / "challenge" / session_id / f"{photo_id}.jpg"


def submission_url(project_id, session_id, photo_id):
    return f"/photos/{project_id}/challenge/{session_id}/{photo_id}.jpg"


def avatar_path(project_id, device_id):
    return store.photo_dir(project_id) / "challenge" / f"ava-{device_id}.jpg"


def _judge_job(project_id, session_id, device_id, idx, photo_id):
    return json.dumps(
        {
            "project_id": project_id,
            "session_id": session_id,
            "device_id": device_id,
            "idx": int(idx),
            "photo_id": photo_id,
        }
    )


def enqueue_judge(project_id, session_id, device_id, idx, photo_id):
    store.r().lpush(
        JUDGE_Q,
        _judge_job(project_id, session_id, device_id, idx, photo_id),
    )


def requeue_pending():
    queued = set(store.r().lrange(JUDGE_Q, 0, -1) or ())
    queued.update(store.r().lrange(JUDGE_BUSY, 0, -1) or ())
    for row in store._all(
        """
        SELECT project_id, session_id, device_id, idx, photo_id
        FROM challenge_tasks
        WHERE status = 'judging' AND photo_id IS NOT NULL
          AND judging_at IS NOT NULL AND judging_at >= %s
        """,
        (time.time() - JUDGE_TIMEOUT,),
    ):
        job = _judge_job(
            row["project_id"],
            row["session_id"],
            row["device_id"],
            row["idx"],
            row["photo_id"],
        )
        if job not in queued:
            store.r().lpush(JUDGE_Q, job)


def promote_avatar(project_id, device_id, session_id=None):
    dest = avatar_path(project_id, device_id)
    if dest.is_file():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if session_id:
        legacy = (
            store.photo_dir(project_id)
            / "challenge"
            / session_id
            / f"ava-{device_id}.jpg"
        )
        if legacy.is_file():
            shutil.copy2(legacy, dest)
            return dest
    root = store.photo_dir(project_id) / "challenge"
    if root.is_dir():
        found = sorted(root.glob(f"*/ava-{device_id}.jpg"), reverse=True)
        if found:
            shutil.copy2(found[0], dest)
    return dest


def get_profile(project_id, device_id, conn=None):
    return store._one(
        """
        SELECT display_name, avatar_id FROM challenge_profiles
        WHERE project_id = %s AND device_id = %s
        """,
        (project_id, device_id),
        conn=conn,
    )


def upsert_profile(conn, project_id, device_id, nickname=None, avatar_id=None):
    row = get_profile(project_id, device_id, conn=conn) or {}
    name = row.get("display_name") or ""
    ava = row.get("avatar_id")
    if nickname is not None:
        name = nickname
    if avatar_id:
        ava = avatar_id
    conn.execute(
        """
        INSERT INTO challenge_profiles (project_id, device_id, display_name, avatar_id)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (project_id, device_id) DO UPDATE SET
          display_name = EXCLUDED.display_name,
          avatar_id = EXCLUDED.avatar_id
        """,
        (project_id, device_id, name, ava),
    )


def carry_profile(project_id, device_id, conn):
    row = get_profile(project_id, device_id, conn=conn)
    if row and ((row.get("display_name") or "").strip() or row.get("avatar_id")):
        promote_avatar(project_id, device_id)
        return row.get("display_name") or "", row.get("avatar_id")
    prev = store._one(
        """
        SELECT p.display_name, p.avatar_id, p.session_id
        FROM challenge_players p
        JOIN challenge_sessions s
          ON s.project_id = p.project_id AND s.id = p.session_id
        WHERE p.project_id = %s AND p.device_id = %s
          AND (p.display_name <> '' OR p.avatar_id IS NOT NULL)
        ORDER BY s.created_at DESC
        LIMIT 1
        """,
        (project_id, device_id),
        conn=conn,
    )
    if not prev:
        return "", None
    name = prev.get("display_name") or ""
    ava = prev.get("avatar_id")
    promote_avatar(project_id, device_id, prev.get("session_id"))
    upsert_profile(conn, project_id, device_id, name or None, ava)
    return name, ava


def taipei_day_start():
    now = datetime.now(TAIPEI)
    return datetime(now.year, now.month, now.day, tzinfo=TAIPEI).timestamp()


def avatar_url(project_id, device_id):
    start = taipei_day_start()
    row = store._one(
        """
        SELECT id FROM photos
        WHERE project_id = %s AND device_id = %s AND ts >= %s
        ORDER BY ts ASC
        LIMIT 1
        """,
        (project_id, device_id, start),
    )
    if row:
        return store.photo_url(project_id, row["id"])
    return ""


def get_session(project_id, session_id, conn=None):
    return store._one(
        """
        SELECT * FROM challenge_sessions
        WHERE project_id = %s AND id = %s
        """,
        (project_id, session_id),
        conn=conn,
    )


def list_live_sessions(project_id, conn=None):
    return store._all(
        """
        SELECT * FROM challenge_sessions
        WHERE project_id = %s AND status IN ('lobby', 'running')
        ORDER BY created_at DESC
        """,
        (project_id,),
        conn=conn,
    )


def player_live(project_id, device_id, conn=None):
    return store._one(
        """
        SELECT s.*
        FROM challenge_sessions s
        JOIN challenge_players p
          ON p.project_id = s.project_id AND p.session_id = s.id
        WHERE s.project_id = %s AND p.device_id = %s
          AND s.status IN ('lobby', 'running')
        ORDER BY s.created_at DESC
        LIMIT 1
        """,
        (project_id, device_id),
        conn=conn,
    )


def session_by_pin(project_id, pin, conn=None):
    return store._one(
        """
        SELECT * FROM challenge_sessions
        WHERE project_id = %s AND pin = %s AND status IN ('lobby', 'running')
        """,
        (project_id, pin),
        conn=conn,
    )


def _lobby_counts(waiting):
    n = len(waiting)
    k = sum(1 for w in waiting if w["ready"])
    return {
        "player_count": n,
        "ready_count": k,
        "waiting_count": n - k,
        "all_ready": bool(waiting) and k == n,
    }


def _room_counts(project_id, row):
    waiting = waiting_of(project_id, row["id"])
    item = dict(row)
    item.update(_lobby_counts(waiting))
    item["cap"] = player_cap(row["kind"])
    item["can_delete"] = row["status"] != "running"
    item["waiting"] = waiting
    return item


def list_rooms(project_id):
    expire_running(project_id)
    live = [_room_counts(project_id, row) for row in list_live_sessions(project_id)]
    return live, list_history(project_id)


def list_history(project_id):
    rows = store._all(
        """
        SELECT * FROM challenge_sessions
        WHERE project_id = %s AND status IN ('settling', 'done')
        ORDER BY created_at DESC
        LIMIT 20
        """,
        (project_id,),
    )
    out = []
    for row in rows:
        players = []
        for p in list_players(project_id, row["id"]):
            item = dict(p)
            item["nickname"] = _face(project_id, row["id"], p)["nickname"]
            item["score"] = p["task_score"] + p["time_score"]
            players.append(item)
        out.append({**dict(row), "players": players})
    return out


def list_players(project_id, session_id, conn=None):
    return store._all(
        """
        SELECT * FROM challenge_players
        WHERE project_id = %s AND session_id = %s
        ORDER BY slot
        """,
        (project_id, session_id),
        conn=conn,
    )


def get_player(project_id, session_id, device_id, conn=None):
    return store._one(
        """
        SELECT * FROM challenge_players
        WHERE project_id = %s AND session_id = %s AND device_id = %s
        """,
        (project_id, session_id, device_id),
        conn=conn,
    )


def list_tasks(project_id, session_id, device_id, conn=None):
    return store._all(
        """
        SELECT * FROM challenge_tasks
        WHERE project_id = %s AND session_id = %s AND device_id = %s
        ORDER BY idx
        """,
        (project_id, session_id, device_id),
        conn=conn,
    )


def get_task(project_id, session_id, device_id, idx, conn=None):
    return store._one(
        """
        SELECT * FROM challenge_tasks
        WHERE project_id = %s AND session_id = %s AND device_id = %s AND idx = %s
        """,
        (project_id, session_id, device_id, idx),
        conn=conn,
    )


def _prompt(spec):
    p = spec.get("prompt") or {}
    return p.get("zh") or "", p.get("en") or ""


def person_pool(project_id, device_id, conn=None):
    return store._all(
        """
        SELECT id, device_id FROM photos
        WHERE project_id = %s AND person IS TRUE AND consent IS TRUE
          AND device_id <> %s
        """,
        (project_id, device_id),
        conn=conn,
    )


def _used_sources(conn, project_id, session_id, except_idx=None, except_device=None):
    rows = store._all(
        """
        SELECT device_id, idx, source_photo_id, status, pass_count
        FROM challenge_tasks
        WHERE project_id = %s AND session_id = %s AND source_photo_id IS NOT NULL
        """,
        (project_id, session_id),
        conn=conn,
    )
    used = set()
    for row in rows:
        if (
            except_device
            and row["device_id"] == except_device
            and except_idx is not None
            and row["idx"] == except_idx
        ):
            continue
        used.add(row["source_photo_id"])
    return used


def _used_colors(conn, project_id, session_id, except_idx=None, except_device=None):
    rows = store._all(
        """
        SELECT device_id, idx, color FROM challenge_tasks
        WHERE project_id = %s AND session_id = %s
          AND color IS NOT NULL AND color <> ''
        """,
        (project_id, session_id),
        conn=conn,
    )
    used = set()
    for row in rows:
        if (
            except_device
            and row["device_id"] == except_device
            and except_idx is not None
            and row["idx"] == except_idx
        ):
            continue
        used.add(row["color"])
    return used


def _pick_high(project_id, device_id, n, session_id, conn):
    specs = list(cfg().get("high") or [])
    if not specs or n <= 0:
        return []
    template = next((s for s in specs if s.get("type") == "person"), specs[0])
    used = _used_sources(conn, project_id, session_id)
    pool = [p for p in person_pool(project_id, device_id, conn=conn) if p["id"] not in used]
    random.shuffle(pool)
    out = []
    for i in range(n):
        spec = dict(template)
        spec["id"] = f"{template.get('id') or 'find_person'}-{i}"
        spec["band"] = "high"
        spec["type"] = "person"
        if pool:
            src = pool.pop()
            spec["source_photo_id"] = src["id"]
        out.append(spec)
    return out


def _pick_mid(n, used_colors=None):
    specs = [dict(s) for s in (cfg().get("mid") or []) if s.get("type") == "color"]
    used = set(used_colors or ())
    available = [s for s in specs if s.get("color") not in used]
    random.shuffle(available)
    n = min(n, len(available))
    out = []
    for spec in available[:n]:
        spec["band"] = "mid"
        out.append(spec)
    return out


def _pick_counts(kind):
    data = cfg()
    pick = (data.get(kind) or {}).get("pick") or (data.get("adventure") or {}).get("pick") or {}
    return (
        int(pick.get("high") or pick.get("hard") or 1),
        int(pick.get("mid") or 1),
        int(pick.get("low") or pick.get("easy") or 2),
    )


def _demo_couple_mid():
    for spec in (cfg().get("demo") or {}).get("tasks") or []:
        if spec.get("type") == "couple":
            item = dict(spec)
            item["band"] = "mid"
            return item
    return None


def _pick_mids(kind, n, used_colors):
    out = []
    if kind == "demo":
        couple = _demo_couple_mid()
        if couple and n > 0:
            out.append(couple)
            n -= 1
    if n > 0:
        colors = _pick_mid(n, used_colors)
        out.extend(colors)
        used_colors.update(c.get("color") for c in colors if c.get("color"))
    return out


def _pick_low(n):
    specs = list(cfg().get("low") or cfg().get("easy") or [])
    if not specs:
        return []
    n = min(n, len(specs))
    out = []
    for spec in random.sample(specs, n):
        item = dict(spec)
        item["band"] = "low"
        out.append(item)
    return out


def _rotate_low(conn, project_id, session_id, device_id, idx):
    specs = list(cfg().get("low") or cfg().get("easy") or [])
    task = get_task(project_id, session_id, device_id, idx, conn=conn)
    if not task or task.get("band") != "low" or not specs:
        return
    held = {
        t["task_id"]
        for t in list_tasks(project_id, session_id, device_id, conn=conn)
        if t.get("band") == "low"
    }
    available = [s for s in specs if (s.get("id") or "") not in held]
    if not available:
        available = [s for s in specs if (s.get("id") or "") != task["task_id"]]
    if not available:
        return
    spec = dict(random.choice(available))
    zh, en = _prompt(spec)
    conn.execute(
        """
        UPDATE challenge_tasks
        SET task_id = %s, prompt_zh = %s, prompt_en = %s, points = %s,
            status = 'pending', reviewed_by = NULL
        WHERE project_id = %s AND session_id = %s AND device_id = %s AND idx = %s
        """,
        (
            spec.get("id") or task["task_id"],
            zh,
            en,
            int(spec.get("points") or task["points"]),
            project_id,
            session_id,
            device_id,
            idx,
        ),
    )


def _insert_tasks(conn, project_id, session_id, device_id, specs):
    for i, spec in enumerate(specs):
        zh, en = _prompt(spec)
        kind = spec.get("type")
        if kind not in ("person", "color", "host", "couple"):
            continue
        band = spec.get("band") or ("solo" if kind == "couple" else "")
        conn.execute(
            """
            INSERT INTO challenge_tasks (
              project_id, session_id, device_id, idx, task_id, kind,
              prompt_zh, prompt_en, points, source_photo_id, color, status,
              pass_count, band
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', 0, %s)
            """,
            (
                project_id,
                session_id,
                device_id,
                i,
                spec.get("id") or f"task-{i}",
                kind,
                zh,
                en,
                int(spec.get("points") or 0),
                spec.get("source_photo_id"),
                spec.get("color"),
                band,
            ),
        )


def normalize_name(name):
    text = (name or "").strip()
    if not text:
        raise ValueError(msg.challenge_need_name)
    return text[:NAME_MAX]


def normalize_pin(pin):
    text = (pin or "").strip()
    if not PIN_RE.fullmatch(text):
        raise ValueError(msg.challenge_bad_pin)
    return text


def create_room(project_id, name, pin, kind):
    if kind not in KINDS:
        raise ValueError(msg.challenge_bad_kind)
    name = normalize_name(name)
    pin = normalize_pin(pin)
    duration = int(cfg().get("duration_seconds") or 600)
    now = time.time()
    sid = uuid.uuid4().hex
    with store.pg().connection() as conn:
        with conn.transaction():
            n = store._n(
                store._one(
                    """
                    SELECT COUNT(*) AS n FROM challenge_sessions
                    WHERE project_id = %s AND status IN ('lobby', 'running')
                    """,
                    (project_id,),
                    conn=conn,
                )
            )
            if n >= LIVE_ROOM_MAX:
                raise ValueError(msg.challenge_room_cap)
            try:
                conn.execute(
                    """
                    INSERT INTO challenge_sessions (
                      project_id, id, kind, status, name, pin,
                      duration_seconds, created_at
                    ) VALUES (%s, %s, %s, 'lobby', %s, %s, %s, %s)
                    """,
                    (project_id, sid, kind, name, pin, duration, now),
                )
            except UniqueViolation as e:
                c = (e.diag.constraint_name or "") if e.diag else ""
                if "live_pin" in c:
                    raise ValueError(msg.challenge_pin_taken) from e
                raise ValueError(msg.challenge_name_taken) from e
            return get_session(project_id, sid, conn=conn)


def _leave_other_rooms(conn, project_id, device_id, keep_session_id):
    conn.execute(
        """
        DELETE FROM challenge_players p
        USING challenge_sessions s
        WHERE p.project_id = s.project_id AND p.session_id = s.id
          AND p.project_id = %s AND p.device_id = %s
          AND s.status IN ('lobby', 'running')
          AND p.session_id <> %s
        """,
        (project_id, device_id, keep_session_id),
    )


def join(project_id, device_id, session_id):
    with store.pg().connection() as conn:
        with conn.transaction():
            live = get_session(project_id, session_id, conn=conn)
            if not live or live["status"] != "lobby":
                raise ValueError(msg.challenge_not_open)
            existing = player_live(project_id, device_id, conn=conn)
            if existing and existing["id"] == live["id"]:
                return dict(existing), get_player(
                    project_id, existing["id"], device_id, conn=conn
                )
            if existing:
                _leave_other_rooms(conn, project_id, device_id, live["id"])
            cap = player_cap(live["kind"])
            n = store._n(
                store._one(
                    """
                    SELECT COUNT(*) AS n FROM challenge_players
                    WHERE project_id = %s AND session_id = %s
                    """,
                    (project_id, live["id"]),
                    conn=conn,
                )
            )
            if n >= cap:
                raise ValueError(
                    msg.challenge_demo_full
                    if live["kind"] == "demo"
                    else msg.challenge_full
                )
            row = store._one(
                """
                SELECT COALESCE(MAX(slot), -1) + 1 AS n
                FROM challenge_players
                WHERE project_id = %s AND session_id = %s
                """,
                (project_id, live["id"]),
                conn=conn,
            )
            slot = int(row["n"]) if row else 0
            conn.execute(
                """
                INSERT INTO devices (id) VALUES (%s)
                ON CONFLICT (id) DO NOTHING
                """,
                (device_id,),
            )
            name, ava = carry_profile(project_id, device_id, conn)
            conn.execute(
                """
                INSERT INTO challenge_players (
                  project_id, session_id, slot, device_id, display_name, avatar_id
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (project_id, live["id"], slot, device_id, name, ava),
            )
            return dict(live), get_player(project_id, live["id"], device_id, conn=conn)


def join_by_pin(project_id, device_id, pin):
    pin = (pin or "").strip()
    if not PIN_RE.fullmatch(pin):
        raise ValueError(msg.challenge_bad_pin)
    found = session_by_pin(project_id, pin)
    if not found:
        raise ValueError(msg.challenge_pin_wrong)
    live = player_live(project_id, device_id)
    if live and live["id"] == found["id"]:
        return dict(live), get_player(project_id, live["id"], device_id)
    if found["status"] != "lobby":
        raise ValueError(msg.challenge_already_started)
    return join(project_id, device_id, found["id"])


def clear_players(project_id, session_id):
    with store.pg().connection() as conn:
        with conn.transaction():
            live = get_session(project_id, session_id, conn=conn)
            if not live or live["status"] != "lobby":
                raise ValueError(msg.challenge_not_open)
            conn.execute(
                """
                DELETE FROM challenge_players
                WHERE project_id = %s AND session_id = %s
                """,
                (project_id, session_id),
            )
            return get_session(project_id, session_id, conn=conn)


def delete_room(project_id, session_id):
    folder = store.photo_dir(project_id) / "challenge" / session_id
    with store.pg().connection() as conn:
        with conn.transaction():
            live = get_session(project_id, session_id, conn=conn)
            if not live:
                return
            if live["status"] == "running":
                raise ValueError(msg.challenge_cant_delete_live)
            conn.execute(
                """
                DELETE FROM challenge_sessions
                WHERE project_id = %s AND id = %s
                """,
                (project_id, session_id),
            )
    if folder.exists():
        shutil.rmtree(folder)


def _letter(nickname):
    text = (nickname or "?").strip()
    return text[0] if text else "?"


def _face(project_id, session_id, p):
    did = p["device_id"]
    name = (p.get("display_name") or "").strip() or store.nickname_of(did) or msg.guest_name
    ava = ""
    if p.get("avatar_id"):
        path = promote_avatar(project_id, did, session_id)
        if path.is_file():
            ava = f"/photos/{project_id}/challenge/ava-{did}.jpg?v={p['avatar_id']}"
        else:
            ava = avatar_url(project_id, did)
    else:
        ava = avatar_url(project_id, did)
    return {
        "device_id": did,
        "nickname": name,
        "avatar_url": ava,
        "letter": _letter(name),
    }


def waiting_of(project_id, session_id, conn=None):
    out = []
    for p in list_players(project_id, session_id, conn=conn):
        face = _face(project_id, session_id, p)
        out.append(
            {
                **face,
                "slot": p["slot"],
                "ready": bool(p.get("ready_at")),
            }
        )
    return out


def all_ready(project_id, session_id, conn=None):
    players = list_players(project_id, session_id, conn=conn)
    return bool(players) and all(p.get("ready_at") for p in players)


def set_ready(project_id, device_id):
    now = time.time()
    with store.pg().connection() as conn:
        with conn.transaction():
            live = player_live(project_id, device_id, conn=conn)
            if not live or live["status"] != "lobby":
                raise ValueError(msg.challenge_not_open)
            player = get_player(project_id, live["id"], device_id, conn=conn)
            if not player:
                raise ValueError(msg.challenge_not_player)
            if player.get("ready_at"):
                return dict(player)
            conn.execute(
                """
                UPDATE challenge_players SET ready_at = %s
                WHERE project_id = %s AND session_id = %s AND device_id = %s
                """,
                (now, project_id, live["id"], device_id),
            )
            return get_player(project_id, live["id"], device_id, conn=conn)


def set_lobby_profile(project_id, device_id, nickname=None, avatar_id=None):
    with store.pg().connection() as conn:
        with conn.transaction():
            live = player_live(project_id, device_id, conn=conn)
            if not live or live["status"] != "lobby":
                raise ValueError(msg.challenge_not_open)
            player = get_player(project_id, live["id"], device_id, conn=conn)
            if not player:
                raise ValueError(msg.challenge_not_player)
            if player.get("ready_at"):
                raise ValueError(msg.challenge_profile_locked)
            sets = []
            args = []
            if nickname is not None:
                name = (nickname or "").strip()
                if not name or len(name) > 20:
                    raise ValueError(msg.nickname_bad)
                sets.append("display_name = %s")
                args.append(name)
            if avatar_id:
                sets.append("avatar_id = %s")
                args.append(avatar_id)
            if not sets:
                return dict(player)
            args.extend([project_id, live["id"], device_id])
            conn.execute(
                f"""
                UPDATE challenge_players SET {", ".join(sets)}
                WHERE project_id = %s AND session_id = %s AND device_id = %s
                """,
                args,
            )
            upsert_profile(conn, project_id, device_id, nickname, avatar_id)
            return get_player(project_id, live["id"], device_id, conn=conn)


def start_session(project_id, session_id):
    now = time.time()
    with store.pg().connection() as conn:
        with conn.transaction():
            live = get_session(project_id, session_id, conn=conn)
            if not live:
                raise ValueError(msg.challenge_not_open)
            if live["status"] != "lobby":
                raise ValueError(msg.challenge_already_started)
            players = list_players(project_id, live["id"], conn=conn)
            if not players:
                raise ValueError(msg.challenge_need_player)
            if not all(p.get("ready_at") for p in players):
                raise ValueError(msg.challenge_need_ready)
            high_n, mid_n, low_n = _pick_counts(live["kind"])
            low_specs = _pick_low(low_n)
            used_colors = set()
            for p in players:
                specs = _pick_high(
                    project_id, p["device_id"], high_n, live["id"], conn
                )
                specs.extend(_pick_mids(live["kind"], mid_n, used_colors))
                specs.extend(dict(s) for s in low_specs)
                _insert_tasks(conn, project_id, live["id"], p["device_id"], specs)
            ends = now + int(live["duration_seconds"] or 600)
            conn.execute(
                """
                UPDATE challenge_sessions
                SET status = 'running', started_at = %s, ends_at = %s
                WHERE project_id = %s AND id = %s
                """,
                (now, ends, project_id, live["id"]),
            )
            return get_session(project_id, live["id"], conn=conn)


def _refresh_task_score(conn, project_id, session_id, device_id):
    row = store._one(
        """
        SELECT COALESCE(SUM(pass_count * points), 0) AS n FROM challenge_tasks
        WHERE project_id = %s AND session_id = %s AND device_id = %s
        """,
        (project_id, session_id, device_id),
        conn=conn,
    )
    conn.execute(
        """
        UPDATE challenge_players SET task_score = %s
        WHERE project_id = %s AND session_id = %s AND device_id = %s
        """,
        (store._n(row), project_id, session_id, device_id),
    )


def _finish_player(conn, session, device_id, now, expired):
    player = get_player(session["project_id"], session["id"], device_id, conn=conn)
    if not player or player.get("finished_at"):
        return
    every = int(cfg().get("time_bonus_every") or 20) or 20
    if expired:
        time_score = 0
        finished_at = session.get("ends_at") or now
    else:
        remain = max(0, int((session.get("ends_at") or now) - now))
        time_score = remain // every
        finished_at = now
    _refresh_task_score(conn, session["project_id"], session["id"], device_id)
    conn.execute(
        """
        UPDATE challenge_players
        SET finished_at = %s, time_score = %s
        WHERE project_id = %s AND session_id = %s AND device_id = %s
        """,
        (finished_at, time_score, session["project_id"], session["id"], device_id),
    )


def maybe_auto_finish(conn, session, device_id, now):
    return


def _expire_one(conn, live, now):
    if not live or live["status"] != "running":
        return live
    if now < (live.get("ends_at") or 0):
        return live
    for p in list_players(live["project_id"], live["id"], conn=conn):
        _finish_player(conn, live, p["device_id"], now, expired=True)
    return get_session(live["project_id"], live["id"], conn=conn)


def expire_if_needed(project_id, session_id=None, session=None):
    now = time.time()
    with store.pg().connection() as conn:
        with conn.transaction():
            live = session
            if live is None and session_id:
                live = get_session(project_id, session_id, conn=conn)
            return _expire_one(conn, live, now)


def expire_running(project_id):
    now = time.time()
    with store.pg().connection() as conn:
        with conn.transaction():
            for live in store._all(
                """
                SELECT * FROM challenge_sessions
                WHERE project_id = %s AND status = 'running'
                """,
                (project_id,),
                conn=conn,
            ):
                _expire_one(conn, live, now)


def finish_player(project_id, device_id):
    now = time.time()
    with store.pg().connection() as conn:
        with conn.transaction():
            live = player_live(project_id, device_id, conn=conn)
            if not live or live["status"] != "running":
                raise ValueError(msg.challenge_not_running)
            player = get_player(project_id, live["id"], device_id, conn=conn)
            if not player:
                raise ValueError(msg.challenge_not_player)
            if player.get("finished_at"):
                return get_player(project_id, live["id"], device_id, conn=conn)
            _finish_player(conn, live, device_id, now, expired=False)
            return get_player(project_id, live["id"], device_id, conn=conn)


def current_task(tasks):
    for t in tasks:
        if t["status"] != "passed":
            return t
    return None


def submit_photo(project_id, device_id, upload_id, dest_exists, idx=None):
    if not dest_exists:
        raise ValueError(msg.bad_image)
    with store.pg().connection() as conn:
        with conn.transaction():
            live = player_live(project_id, device_id, conn=conn)
            if not live or live["status"] != "running":
                raise ValueError(msg.challenge_not_running)
            player = get_player(project_id, live["id"], device_id, conn=conn)
            if not player or player.get("finished_at"):
                raise ValueError(msg.challenge_not_player)
            tasks = list_tasks(project_id, live["id"], device_id, conn=conn)
            if idx is None:
                task = current_task(tasks)
            else:
                task = get_task(project_id, live["id"], device_id, idx, conn=conn)
            if not task or task["kind"] not in PHOTO_KINDS:
                raise ValueError(msg.challenge_no_upload)
            if task["status"] == "passed":
                raise ValueError(msg.challenge_no_upload)
            if task["status"] == "judging":
                raise ValueError(msg.challenge_judging)
            conn.execute(
                """
                UPDATE challenge_tasks
                SET photo_id = %s, status = 'judging', judging_at = %s,
                    judge_score = NULL, judge_detail = NULL, reviewed_by = NULL
                WHERE project_id = %s AND session_id = %s
                  AND device_id = %s AND idx = %s
                """,
                (upload_id, time.time(), project_id, live["id"], device_id, task["idx"]),
            )
            live_id = live["id"]
            idx = task["idx"]
            out = get_task(project_id, live_id, device_id, idx, conn=conn)
    enqueue_judge(project_id, live_id, device_id, idx, upload_id)
    return out


def request_host(project_id, device_id, idx=None):
    with store.pg().connection() as conn:
        with conn.transaction():
            live = player_live(project_id, device_id, conn=conn)
            if not live or live["status"] != "running":
                raise ValueError(msg.challenge_not_running)
            player = get_player(project_id, live["id"], device_id, conn=conn)
            if not player or player.get("finished_at"):
                raise ValueError(msg.challenge_not_player)
            if idx is None:
                task = current_task(list_tasks(project_id, live["id"], device_id, conn=conn))
            else:
                task = get_task(project_id, live["id"], device_id, idx, conn=conn)
            if not task or task["kind"] != "host":
                raise ValueError(msg.challenge_no_host)
            conn.execute(
                """
                UPDATE challenge_tasks SET status = 'awaiting_host'
                WHERE project_id = %s AND session_id = %s
                  AND device_id = %s AND idx = %s
                """,
                (project_id, live["id"], device_id, task["idx"]),
            )
            return get_task(project_id, live["id"], device_id, task["idx"], conn=conn)


def _set_status(conn, session, device_id, idx, status, reviewed_by, score=None, detail=None):
    extra = ""
    args = [
        status,
        reviewed_by,
        score,
        detail,
        session["project_id"],
        session["id"],
        device_id,
        idx,
    ]
    if status == "passed":
        extra = ", pass_count = pass_count + 1"
    conn.execute(
        f"""
        UPDATE challenge_tasks
        SET status = %s, reviewed_by = %s,
            judge_score = COALESCE(%s, judge_score),
            judge_detail = COALESCE(%s, judge_detail)
            {extra}
        WHERE project_id = %s AND session_id = %s AND device_id = %s AND idx = %s
        """,
        args,
    )
    _refresh_task_score(conn, session["project_id"], session["id"], device_id)
    maybe_auto_finish(conn, session, device_id, time.time())


def host_review(project_id, session_id, device_id, idx, passed, reviewer):
    with store.pg().connection() as conn:
        with conn.transaction():
            live = get_session(project_id, session_id, conn=conn)
            if not live or live["status"] != "running":
                raise ValueError(msg.challenge_not_running)
            task = get_task(project_id, live["id"], device_id, idx, conn=conn)
            if not task or task["kind"] != "host":
                raise ValueError(msg.challenge_no_host)
            if task["status"] != "awaiting_host":
                raise ValueError(msg.challenge_bad_review)
            if passed:
                conn.execute(
                    """
                    UPDATE challenge_tasks
                    SET status = 'pending', reviewed_by = %s,
                        pass_count = pass_count + 1
                    WHERE project_id = %s AND session_id = %s
                      AND device_id = %s AND idx = %s
                    """,
                    (reviewer, project_id, live["id"], device_id, idx),
                )
                conn.execute(
                    """
                    UPDATE challenge_players
                    SET refresh_left = refresh_left + 1
                    WHERE project_id = %s AND session_id = %s AND device_id = %s
                    """,
                    (project_id, live["id"], device_id),
                )
                _rotate_low(conn, project_id, live["id"], device_id, idx)
                _refresh_task_score(conn, project_id, live["id"], device_id)
                maybe_auto_finish(conn, live, device_id, time.time())
            else:
                _set_status(conn, live, device_id, idx, "failed", reviewer)
            return get_task(project_id, live["id"], device_id, idx, conn=conn)


def override_review(project_id, session_id, device_id, idx, passed, reviewer):
    with store.pg().connection() as conn:
        with conn.transaction():
            live = get_session(project_id, session_id, conn=conn)
            if not live:
                raise ValueError(msg.challenge_not_open)
            task = get_task(project_id, live["id"], device_id, idx, conn=conn)
            if not task:
                raise ValueError(msg.challenge_no_task)
            _set_status(
                conn,
                live,
                device_id,
                idx,
                "passed" if passed else "failed",
                reviewer,
            )
            return get_task(project_id, live["id"], device_id, idx, conn=conn)


def expire_stale_judging(project_id, session_id, conn=None):
    now = time.time()
    busy = set(store.r().lrange(JUDGE_BUSY, 0, -1) or ())
    queued = set(store.r().lrange(JUDGE_Q, 0, -1) or ())
    working = bool(busy)

    def stale(row):
        job = _judge_job(
            row["project_id"],
            row["session_id"],
            row["device_id"],
            row["idx"],
            row["photo_id"],
        )
        started = float(row.get("judging_at") or 0)
        age = now - started if started else now
        if job in busy:
            return age >= JUDGE_BUSY_TIMEOUT
        if job in queued:
            return (not working) and age >= JUDGE_TIMEOUT
        return (not started) or age >= JUDGE_TIMEOUT

    def run(c):
        rows = [
            row
            for row in store._all(
                """
                SELECT project_id, session_id, device_id, idx, photo_id, judging_at
                FROM challenge_tasks
                WHERE project_id = %s AND session_id = %s
                  AND status = 'judging' AND photo_id IS NOT NULL
                """,
                (project_id, session_id),
                conn=c,
            )
            if stale(row)
        ]
        seen = set()
        for row in rows:
            c.execute(
                """
                UPDATE challenge_tasks
                SET status = 'failed', judge_score = 0, judge_detail = 'timeout',
                    judging_at = NULL
                WHERE project_id = %s AND session_id = %s
                  AND device_id = %s AND idx = %s AND status = 'judging'
                """,
                (
                    project_id,
                    session_id,
                    row["device_id"],
                    row["idx"],
                ),
            )
            applog.write(
                "game",
                f"{project_id} {session_id} idx={row['idx']} timeout",
            )
            did = row["device_id"]
            if did not in seen:
                seen.add(did)
                _refresh_task_score(c, project_id, session_id, did)
        return rows

    if conn is not None:
        return run(conn)
    with store.pg().connection() as c:
        with c.transaction():
            return run(c)


def apply_judge(project_id, session_id, device_id, idx, score, detail, photo_id=None):
    ok = float(score) >= threshold()
    with store.pg().connection() as conn:
        with conn.transaction():
            session = get_session(project_id, session_id, conn=conn)
            if not session:
                return
            task = get_task(project_id, session_id, device_id, idx, conn=conn)
            if not task or task["status"] != "judging":
                return
            if photo_id and task.get("photo_id") != photo_id:
                return
            conn.execute(
                """
                UPDATE challenge_tasks
                SET status = %s, judge_score = %s, judge_detail = %s,
                    pass_count = CASE WHEN %s THEN GREATEST(pass_count, 1) ELSE pass_count END
                WHERE project_id = %s AND session_id = %s
                  AND device_id = %s AND idx = %s
                """,
                (
                    "passed" if ok else "failed",
                    float(score),
                    detail or "",
                    ok,
                    project_id,
                    session_id,
                    device_id,
                    idx,
                ),
            )
            _refresh_task_score(conn, project_id, session_id, device_id)
            maybe_auto_finish(conn, session, device_id, time.time())


def all_finished(project_id, session_id, conn=None):
    players = list_players(project_id, session_id, conn=conn)
    return bool(players) and all(p.get("finished_at") for p in players)


def settle(project_id, session_id):
    with store.pg().connection() as conn:
        with conn.transaction():
            live = get_session(project_id, session_id, conn=conn)
            if not live:
                raise ValueError(msg.challenge_not_open)
            if live["status"] != "running":
                raise ValueError(msg.challenge_not_running)
            if not all_finished(project_id, live["id"], conn=conn):
                raise ValueError(msg.challenge_not_all_done)
            conn.execute(
                """
                UPDATE challenge_sessions SET status = 'done'
                WHERE project_id = %s AND id = %s
                """,
                (project_id, live["id"]),
            )
            return get_session(project_id, live["id"], conn=conn)


def refresh_band(project_id, device_id, band):
    if band not in ("high", "mid"):
        raise ValueError(msg.challenge_no_task)
    with store.pg().connection() as conn:
        with conn.transaction():
            live = player_live(project_id, device_id, conn=conn)
            if not live or live["status"] != "running":
                raise ValueError(msg.challenge_not_running)
            player = get_player(project_id, live["id"], device_id, conn=conn)
            if not player or player.get("finished_at"):
                raise ValueError(msg.challenge_not_player)
            left = int(player.get("refresh_left") or 0)
            if left < 1:
                raise ValueError(msg.challenge_need_refresh)
            task = None
            for t in list_tasks(project_id, live["id"], device_id, conn=conn):
                if t.get("band") != band:
                    continue
                if t["status"] in ("pending", "failed", "passed"):
                    task = t
                    break
            if not task:
                raise ValueError(msg.challenge_no_task)
            if band == "high":
                used = _used_sources(
                    conn,
                    project_id,
                    live["id"],
                    except_idx=task["idx"],
                    except_device=device_id,
                )
                current = task.get("source_photo_id")
                pool = person_pool(project_id, device_id, conn=conn)
                fresh = [
                    p for p in pool if p["id"] not in used and p["id"] != current
                ]
                if not fresh:
                    fresh = [p for p in pool if p["id"] != current]
                if not fresh:
                    raise ValueError(msg.challenge_no_task)
                src = random.choice(fresh)
                conn.execute(
                    """
                    UPDATE challenge_tasks
                    SET source_photo_id = %s, status = 'pending', judging_at = NULL,
                        photo_id = NULL, judge_score = NULL, judge_detail = NULL
                    WHERE project_id = %s AND session_id = %s
                      AND device_id = %s AND idx = %s
                    """,
                    (src["id"], project_id, live["id"], device_id, task["idx"]),
                )
            else:
                used_colors = _used_colors(
                    conn,
                    project_id,
                    live["id"],
                    except_idx=task["idx"],
                    except_device=device_id,
                )
                current_color = task.get("color") or ""
                if current_color:
                    used_colors.add(current_color)
                nxt = _pick_mid(1, used_colors)
                if not nxt:
                    nxt = _pick_mid(1, {current_color} if current_color else set())
                if not nxt:
                    raise ValueError(msg.challenge_no_task)
                spec = nxt[0]
                zh, en = _prompt(spec)
                conn.execute(
                    """
                    UPDATE challenge_tasks
                    SET task_id = %s, kind = %s, prompt_zh = %s, prompt_en = %s,
                        color = %s, points = %s, source_photo_id = NULL,
                        status = 'pending', judging_at = NULL, photo_id = NULL,
                        judge_score = NULL, judge_detail = NULL
                    WHERE project_id = %s AND session_id = %s
                      AND device_id = %s AND idx = %s
                    """,
                    (
                        spec.get("id") or task["task_id"],
                        spec.get("type") or "color",
                        zh,
                        en,
                        spec.get("color"),
                        int(spec.get("points") or task["points"]),
                        project_id,
                        live["id"],
                        device_id,
                        task["idx"],
                    ),
                )
            conn.execute(
                """
                UPDATE challenge_players
                SET refresh_left = refresh_left - 1
                WHERE project_id = %s AND session_id = %s AND device_id = %s
                  AND refresh_left > 0
                """,
                (project_id, live["id"], device_id),
            )
            return get_task(project_id, live["id"], device_id, task["idx"], conn=conn)


def wipe_history(project_id):
    root = store.photo_dir(project_id) / "challenge"
    with store.pg().connection() as conn:
        with conn.transaction():
            rows = store._all(
                """
                SELECT id FROM challenge_sessions
                WHERE project_id = %s AND status IN ('settling', 'done')
                """,
                (project_id,),
                conn=conn,
            )
            conn.execute(
                """
                DELETE FROM challenge_sessions
                WHERE project_id = %s AND status IN ('settling', 'done')
                """,
                (project_id,),
            )
    for row in rows:
        folder = root / row["id"]
        if folder.exists():
            shutil.rmtree(folder)


def wipe(project_id):
    folder = store.photo_dir(project_id) / "challenge"
    with store.pg().connection() as conn:
        conn.execute(
            "DELETE FROM challenge_sessions WHERE project_id = %s",
            (project_id,),
        )
        conn.execute(
            "DELETE FROM challenge_profiles WHERE project_id = %s",
            (project_id,),
        )
    if folder.exists():
        shutil.rmtree(folder)


def public_task(project_id, session_id, task, lang, with_photo=True):
    prompt = task["prompt_en"] if lang == "en" else task["prompt_zh"]
    data = {
        "idx": task["idx"],
        "task_id": task["task_id"],
        "kind": task["kind"],
        "prompt": prompt,
        "points": task["points"],
        "status": task["status"],
        "band": task.get("band") or "",
        "pass_count": int(task.get("pass_count") or 0),
        "color": task.get("color") or "",
        "judge_score": task.get("judge_score"),
        "source_url": (
            store.photo_url(project_id, task["source_photo_id"])
            if task.get("source_photo_id")
            else ""
        ),
        "photo_url": "",
    }
    if with_photo and task.get("photo_id"):
        data["photo_url"] = submission_url(project_id, session_id, task["photo_id"])
    return data


def player_payload(project_id, device_id, lang):
    now = time.time()
    live = player_live(project_id, device_id)
    if live:
        live = expire_if_needed(project_id, session=live)
        if live and live["status"] not in LIVE:
            live = None
        elif live and live["status"] == "running":
            expire_stale_judging(project_id, live["id"])
    if not live:
        return {"session": None, "player": None, "tasks": [], "current": None, "now": now}
    player = get_player(project_id, live["id"], device_id)
    tasks = list_tasks(project_id, live["id"], device_id) if player else []
    cur = current_task(tasks) if player and not player.get("finished_at") else None
    remain = 0
    if live["status"] == "running" and live.get("ends_at"):
        remain = max(0, int(live["ends_at"] - now))
        if player and player.get("finished_at"):
            remain = max(0, int(live["ends_at"] - player["finished_at"]))
    waiting = (
        waiting_of(project_id, live["id"]) if live["status"] == "lobby" else []
    )
    return {
        "session": {
            "id": live["id"],
            "kind": live["kind"],
            "status": live["status"],
            "started_at": live.get("started_at"),
            "ends_at": live.get("ends_at"),
            "remain": remain,
        },
        "player": (
            None
            if not player
            else {
                **_face(project_id, live["id"], player),
                "slot": player["slot"],
                "task_score": player["task_score"],
                "time_score": player["time_score"],
                "score": player["task_score"] + player["time_score"],
                "finished": bool(player.get("finished_at")),
                "ready": bool(player.get("ready_at")),
                "can_edit": live["status"] == "lobby" and not player.get("ready_at"),
                "refresh_left": int(player.get("refresh_left") or 0),
                "can_finish": bool(
                    live["status"] == "running" and not player.get("finished_at")
                ),
            }
        ),
        "tasks": [public_task(project_id, live["id"], t, lang) for t in tasks],
        "current": (
            public_task(project_id, live["id"], cur, lang) if cur else None
        ),
        "waiting": waiting,
        **_lobby_counts(waiting),
        "now": now,
    }


def god_payload(project_id, session_id, lang, can_override):
    live = expire_if_needed(project_id, session_id=session_id)
    if live and live["status"] not in LIVE:
        live = None
    elif live and live["status"] == "running":
        expire_stale_judging(project_id, live["id"])
    now = time.time()
    slots = [None, None, None, None]
    can_start = False
    can_settle = False
    waiting = []
    if live:
        waiting = waiting_of(project_id, live["id"])
        can_start = live["status"] == "lobby" and all_ready(project_id, live["id"])
        can_settle = live["status"] == "running" and all_finished(project_id, live["id"])
        remain = 0
        if live["status"] == "running" and live.get("ends_at"):
            remain = max(0, int(live["ends_at"] - now))
        for p in list_players(project_id, live["id"]):
            if p["slot"] > 3:
                continue
            tasks = list_tasks(project_id, live["id"], p["device_id"])
            slots[p["slot"]] = {
                **_face(project_id, live["id"], p),
                "slot": p["slot"],
                "score": p["task_score"] + p["time_score"],
                "task_score": p["task_score"],
                "time_score": p["time_score"],
                "finished": bool(p.get("finished_at")),
                "ready": bool(p.get("ready_at")),
                "tasks": [
                    public_task(project_id, live["id"], t, lang) for t in tasks
                ],
            }
        session = {
            "id": live["id"],
            "kind": live["kind"],
            "status": live["status"],
            "remain": remain,
            "ends_at": live.get("ends_at"),
        }
    else:
        session = None
    return {
        "session": session,
        "slots": slots,
        "waiting": waiting,
        **_lobby_counts(waiting),
        "can_start": can_start,
        "can_settle": can_settle,
        "can_override": can_override,
        "now": now,
        "empty": msg.challenge_empty_slot,
    }


def results_payload(project_id, session_id, lang):
    session = get_session(project_id, session_id)
    if not session:
        return None
    players = []
    for p in list_players(project_id, session_id):
        players.append(
            {
                **_face(project_id, session_id, p),
                "slot": p["slot"],
                "score": p["task_score"] + p["time_score"],
                "task_score": p["task_score"],
                "time_score": p["time_score"],
            }
        )
    return {"session": dict(session), "players": players, "now": time.time()}
