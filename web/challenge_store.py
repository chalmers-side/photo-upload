"""Grand-challenge sessions, players, tasks, and judge queue."""
import json
import random
import shutil
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from config import challenge as challenge_cfg
from config import msg
from web import store

JUDGE_Q = "judge_q"
JUDGE_BUSY = "judge_busy"
TAIPEI = ZoneInfo("Asia/Taipei")
LIVE = ("lobby", "running")
KINDS = ("demo", "adventure")
PHOTO_KINDS = ("person", "color", "couple")


def cfg():
    return challenge_cfg.settings()


def threshold():
    return float(cfg().get("judge_threshold") or 0.6)


def player_cap(kind):
    data = cfg()
    if kind == "demo":
        return int((data.get("demo") or {}).get("max_players") or 1)
    return int(data.get("max_players") or 4)


def submission_path(project_id, session_id, photo_id):
    return store.photo_dir(project_id) / "challenge" / session_id / f"{photo_id}.jpg"


def submission_url(project_id, session_id, photo_id):
    return f"/photos/{project_id}/challenge/{session_id}/{photo_id}.jpg"


def enqueue_judge(project_id, session_id, device_id, idx, photo_id):
    store.r().lpush(
        JUDGE_Q,
        json.dumps(
            {
                "project_id": project_id,
                "session_id": session_id,
                "device_id": device_id,
                "idx": idx,
                "photo_id": photo_id,
            }
        ),
    )


def requeue_pending():
    for row in store._all(
        """
        SELECT project_id, session_id, device_id, idx, photo_id
        FROM challenge_tasks
        WHERE status = 'judging' AND photo_id IS NOT NULL
        """
    ):
        enqueue_judge(
            row["project_id"],
            row["session_id"],
            row["device_id"],
            row["idx"],
            row["photo_id"],
        )


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
    row = store._one(
        """
        SELECT t.session_id, t.photo_id
        FROM challenge_tasks t
        JOIN challenge_sessions s
          ON s.project_id = t.project_id AND s.id = t.session_id
        WHERE t.project_id = %s AND t.device_id = %s
          AND t.photo_id IS NOT NULL AND s.created_at >= %s
        ORDER BY s.created_at, t.idx
        LIMIT 1
        """,
        (project_id, device_id, start),
    )
    if row:
        return submission_url(project_id, row["session_id"], row["photo_id"])
    return ""


def live_session(project_id, conn=None):
    return store._one(
        """
        SELECT * FROM challenge_sessions
        WHERE project_id = %s AND status IN ('lobby', 'running')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (project_id,),
        conn=conn,
    )


def get_session(project_id, session_id, conn=None):
    return store._one(
        """
        SELECT * FROM challenge_sessions
        WHERE project_id = %s AND id = %s
        """,
        (project_id, session_id),
        conn=conn,
    )


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
            item["nickname"] = store.nickname_of(p["device_id"]) or msg.guest_name
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


def _color_fallback(specs, used_ids):
    colors = [s for s in specs if s.get("type") == "color" and s.get("id") not in used_ids]
    if colors:
        return dict(random.choice(colors))
    return {
        "id": "wear_red",
        "type": "color",
        "color": "red",
        "points": 10,
        "prompt": {
            "zh": "與穿著紅色衣服的賓客合照",
            "en": "Take a photo with a guest wearing red",
        },
    }


def _pick_hard(project_id, device_id, n, conn):
    specs = list(cfg().get("hard") or [])
    if not specs:
        return []
    n = min(n, len(specs))
    chosen = [dict(s) for s in random.sample(specs, n)]
    used = {s["id"] for s in chosen}
    out = []
    for spec in chosen:
        if spec.get("type") == "person":
            pool = person_pool(project_id, device_id, conn=conn)
            if pool:
                src = random.choice(pool)
                spec["source_photo_id"] = src["id"]
                out.append(spec)
                continue
            spec = _color_fallback(specs, used)
            used.add(spec["id"])
        out.append(spec)
    return out


def _pick_easy(n):
    specs = list(cfg().get("easy") or [])
    if not specs:
        return []
    n = min(n, len(specs))
    return [dict(s) for s in random.sample(specs, n)]


def _insert_tasks(conn, project_id, session_id, device_id, specs):
    for i, spec in enumerate(specs):
        zh, en = _prompt(spec)
        kind = spec.get("type")
        if kind not in ("person", "color", "host", "couple"):
            continue
        conn.execute(
            """
            INSERT INTO challenge_tasks (
              project_id, session_id, device_id, idx, task_id, kind,
              prompt_zh, prompt_en, points, source_photo_id, color, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
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
            ),
        )


def open_lobby(project_id, kind):
    if kind not in KINDS:
        raise ValueError(msg.challenge_bad_kind)
    duration = int(cfg().get("duration_seconds") or 600)
    now = time.time()
    with store.pg().connection() as conn:
        with conn.transaction():
            live = live_session(project_id, conn=conn)
            if live:
                if live["kind"] == kind and live["status"] == "lobby":
                    return dict(live)
                raise ValueError(msg.challenge_busy)
            sid = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO challenge_sessions (
                  project_id, id, kind, status, duration_seconds, created_at
                ) VALUES (%s, %s, %s, 'lobby', %s, %s)
                """,
                (project_id, sid, kind, duration, now),
            )
            return get_session(project_id, sid, conn=conn)


def join(project_id, device_id):
    with store.pg().connection() as conn:
        with conn.transaction():
            live = live_session(project_id, conn=conn)
            if not live:
                raise ValueError(msg.challenge_not_open)
            existing = get_player(project_id, live["id"], device_id, conn=conn)
            if existing:
                return dict(live), dict(existing)
            if live["status"] != "lobby":
                raise ValueError(msg.challenge_not_open)
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
            conn.execute(
                """
                INSERT INTO challenge_players (
                  project_id, session_id, slot, device_id
                ) VALUES (%s, %s, %s, %s)
                """,
                (project_id, live["id"], slot, device_id),
            )
            return dict(live), get_player(project_id, live["id"], device_id, conn=conn)


def waiting_of(project_id, session_id, conn=None):
    out = []
    for p in list_players(project_id, session_id, conn=conn):
        out.append(
            {
                "device_id": p["device_id"],
                "slot": p["slot"],
                "nickname": store.nickname_of(p["device_id"]) or msg.guest_name,
                "avatar_url": avatar_url(project_id, p["device_id"]),
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
            live = live_session(project_id, conn=conn)
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


def start_session(project_id):
    now = time.time()
    with store.pg().connection() as conn:
        with conn.transaction():
            live = live_session(project_id, conn=conn)
            if not live:
                raise ValueError(msg.challenge_not_open)
            if live["status"] != "lobby":
                raise ValueError(msg.challenge_already_started)
            players = list_players(project_id, live["id"], conn=conn)
            if not players:
                raise ValueError(msg.challenge_need_player)
            if not all(p.get("ready_at") for p in players):
                raise ValueError(msg.challenge_need_ready)
            pick = (cfg().get("adventure") or {}).get("pick") or {}
            hard_n = int(pick.get("hard") or 2)
            easy_n = int(pick.get("easy") or 2)
            demo_specs = list((cfg().get("demo") or {}).get("tasks") or [])
            for p in players:
                if live["kind"] == "demo":
                    specs = [dict(s) for s in demo_specs]
                else:
                    specs = _pick_hard(project_id, p["device_id"], hard_n, conn)
                    specs.extend(_pick_easy(easy_n))
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
        SELECT COALESCE(SUM(points), 0) AS n FROM challenge_tasks
        WHERE project_id = %s AND session_id = %s AND device_id = %s
          AND status = 'passed'
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


def _all_passed(conn, project_id, session_id, device_id):
    tasks = list_tasks(project_id, session_id, device_id, conn=conn)
    return bool(tasks) and all(t["status"] == "passed" for t in tasks)


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
    if session["status"] != "running":
        return
    if _all_passed(conn, session["project_id"], session["id"], device_id):
        _finish_player(conn, session, device_id, now, expired=False)


def expire_if_needed(project_id, session=None):
    now = time.time()
    with store.pg().connection() as conn:
        with conn.transaction():
            live = session or live_session(project_id, conn=conn)
            if not live or live["status"] != "running":
                return live
            if now < (live.get("ends_at") or 0):
                return live
            for p in list_players(project_id, live["id"], conn=conn):
                _finish_player(conn, live, p["device_id"], now, expired=True)
            return get_session(project_id, live["id"], conn=conn)


def finish_player(project_id, device_id):
    now = time.time()
    with store.pg().connection() as conn:
        with conn.transaction():
            live = live_session(project_id, conn=conn)
            if not live or live["status"] != "running":
                raise ValueError(msg.challenge_not_running)
            player = get_player(project_id, live["id"], device_id, conn=conn)
            if not player:
                raise ValueError(msg.challenge_not_player)
            if player.get("finished_at"):
                return get_player(project_id, live["id"], device_id, conn=conn)
            if not _all_passed(conn, project_id, live["id"], device_id):
                raise ValueError(msg.challenge_not_done)
            _finish_player(conn, live, device_id, now, expired=False)
            return get_player(project_id, live["id"], device_id, conn=conn)


def current_task(tasks):
    for t in tasks:
        if t["status"] != "passed":
            return t
    return None


def submit_photo(project_id, device_id, upload_id, dest_exists):
    if not dest_exists:
        raise ValueError(msg.bad_image)
    with store.pg().connection() as conn:
        with conn.transaction():
            live = live_session(project_id, conn=conn)
            if not live or live["status"] != "running":
                raise ValueError(msg.challenge_not_running)
            player = get_player(project_id, live["id"], device_id, conn=conn)
            if not player or player.get("finished_at"):
                raise ValueError(msg.challenge_not_player)
            tasks = list_tasks(project_id, live["id"], device_id, conn=conn)
            task = current_task(tasks)
            if not task or task["kind"] not in PHOTO_KINDS:
                raise ValueError(msg.challenge_no_upload)
            if task["status"] == "judging":
                raise ValueError(msg.challenge_judging)
            conn.execute(
                """
                UPDATE challenge_tasks
                SET photo_id = %s, status = 'judging',
                    judge_score = NULL, judge_detail = NULL, reviewed_by = NULL
                WHERE project_id = %s AND session_id = %s
                  AND device_id = %s AND idx = %s
                """,
                (upload_id, project_id, live["id"], device_id, task["idx"]),
            )
            enqueue_judge(project_id, live["id"], device_id, task["idx"], upload_id)
            return get_task(project_id, live["id"], device_id, task["idx"], conn=conn)


def request_host(project_id, device_id):
    with store.pg().connection() as conn:
        with conn.transaction():
            live = live_session(project_id, conn=conn)
            if not live or live["status"] != "running":
                raise ValueError(msg.challenge_not_running)
            player = get_player(project_id, live["id"], device_id, conn=conn)
            if not player or player.get("finished_at"):
                raise ValueError(msg.challenge_not_player)
            task = current_task(list_tasks(project_id, live["id"], device_id, conn=conn))
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
    conn.execute(
        """
        UPDATE challenge_tasks
        SET status = %s, reviewed_by = %s,
            judge_score = COALESCE(%s, judge_score),
            judge_detail = COALESCE(%s, judge_detail)
        WHERE project_id = %s AND session_id = %s AND device_id = %s AND idx = %s
        """,
        (
            status,
            reviewed_by,
            score,
            detail,
            session["project_id"],
            session["id"],
            device_id,
            idx,
        ),
    )
    _refresh_task_score(conn, session["project_id"], session["id"], device_id)
    maybe_auto_finish(conn, session, device_id, time.time())


def host_review(project_id, device_id, idx, passed, reviewer):
    with store.pg().connection() as conn:
        with conn.transaction():
            live = live_session(project_id, conn=conn)
            if not live or live["status"] != "running":
                raise ValueError(msg.challenge_not_running)
            task = get_task(project_id, live["id"], device_id, idx, conn=conn)
            if not task or task["kind"] != "host":
                raise ValueError(msg.challenge_no_host)
            if task["status"] not in ("awaiting_host", "failed", "pending"):
                raise ValueError(msg.challenge_bad_review)
            _set_status(
                conn,
                live,
                device_id,
                idx,
                "passed" if passed else "failed",
                reviewer,
            )
            return get_task(project_id, live["id"], device_id, idx, conn=conn)


def override_review(project_id, device_id, idx, passed, reviewer):
    with store.pg().connection() as conn:
        with conn.transaction():
            live = live_session(project_id, conn=conn)
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


def apply_judge(project_id, session_id, device_id, idx, score, detail):
    ok = float(score) >= threshold()
    with store.pg().connection() as conn:
        with conn.transaction():
            session = get_session(project_id, session_id, conn=conn)
            if not session:
                return
            task = get_task(project_id, session_id, device_id, idx, conn=conn)
            if not task or task["status"] != "judging":
                return
            conn.execute(
                """
                UPDATE challenge_tasks
                SET status = %s, judge_score = %s, judge_detail = %s
                WHERE project_id = %s AND session_id = %s
                  AND device_id = %s AND idx = %s
                """,
                (
                    "passed" if ok else "failed",
                    float(score),
                    detail or "",
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


def settle(project_id):
    with store.pg().connection() as conn:
        with conn.transaction():
            live = live_session(project_id, conn=conn)
            if not live:
                raise ValueError(msg.challenge_not_open)
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


def wipe(project_id):
    folder = store.photo_dir(project_id) / "challenge"
    with store.pg().connection() as conn:
        conn.execute(
            "DELETE FROM challenge_sessions WHERE project_id = %s",
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
    live = expire_if_needed(project_id)
    now = time.time()
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
                "slot": player["slot"],
                "nickname": store.nickname_of(device_id) or msg.guest_name,
                "task_score": player["task_score"],
                "time_score": player["time_score"],
                "score": player["task_score"] + player["time_score"],
                "finished": bool(player.get("finished_at")),
                "ready": bool(player.get("ready_at")),
                "can_finish": bool(
                    live["status"] == "running"
                    and not player.get("finished_at")
                    and tasks
                    and all(t["status"] == "passed" for t in tasks)
                ),
            }
        ),
        "tasks": [public_task(project_id, live["id"], t, lang) for t in tasks],
        "current": (
            public_task(project_id, live["id"], cur, lang) if cur else None
        ),
        "waiting": waiting,
        "player_count": len(waiting) if waiting else len(list_players(project_id, live["id"])),
        "ready_count": sum(1 for w in waiting if w["ready"]),
        "all_ready": all_ready(project_id, live["id"]) if live["status"] == "lobby" else False,
        "now": now,
    }


def god_payload(project_id, lang, can_override):
    live = expire_if_needed(project_id)
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
                "slot": p["slot"],
                "device_id": p["device_id"],
                "nickname": store.nickname_of(p["device_id"]) or msg.guest_name,
                "avatar_url": avatar_url(project_id, p["device_id"]),
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
        "player_count": len(waiting),
        "ready_count": sum(1 for w in waiting if w["ready"]),
        "all_ready": bool(waiting) and all(w["ready"] for w in waiting),
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
                "slot": p["slot"],
                "nickname": store.nickname_of(p["device_id"]) or msg.guest_name,
                "avatar_url": avatar_url(project_id, p["device_id"]),
                "score": p["task_score"] + p["time_score"],
                "task_score": p["task_score"],
                "time_score": p["time_score"],
            }
        )
    return {"session": dict(session), "players": players, "now": time.time()}
