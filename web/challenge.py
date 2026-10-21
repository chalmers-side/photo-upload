"""Grand-challenge routes. Registered from create_app."""
import io
import uuid

import qrcode
from flask import (
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from config import msg
from web import challenge_store, images, store


def register(app, load_project, current_name, device_id, login_required):
    def _host(_project=None):
        return bool(current_name())

    def _json_error(err, code=400):
        g.log_err = str(err)
        return jsonify({"error": str(err)}), code

    def _room(project, session_id):
        row = challenge_store.get_session(project["id"], session_id)
        if not row:
            abort(404)
        return row

    @app.get("/p/<slug>/challenge/")
    def challenge_landing(slug):
        if not _host():
            return redirect(url_for("challenge_join", slug=slug))
        project = load_project(slug)
        live, history = challenge_store.list_rooms(project["id"])
        return render_template(
            "challenge_rooms.html",
            project=project,
            live=live,
            history=history,
            can_create=len(live) < challenge_store.LIVE_ROOM_MAX,
        )

    @app.post("/p/<slug>/challenge/rooms")
    @login_required
    def challenge_create_room(slug):
        project = load_project(slug)
        if not _host():
            abort(403)
        kind = (request.form.get("kind") or "").strip()
        try:
            room = challenge_store.create_room(
                project["id"],
                request.form.get("name"),
                request.form.get("pin"),
                kind,
            )
        except ValueError as e:
            g.log_err = str(e)
            flash(str(e), "error")
            return redirect(url_for("challenge_landing", slug=slug))
        return redirect(url_for("challenge_room", slug=slug, session_id=room["id"]))

    @app.post("/p/<slug>/challenge/rooms/<session_id>/delete")
    @login_required
    def challenge_delete_room(slug, session_id):
        project = load_project(slug)
        if not _host():
            abort(403)
        try:
            challenge_store.delete_room(project["id"], session_id)
        except ValueError as e:
            g.log_err = str(e)
            flash(str(e), "error")
        return redirect(url_for("challenge_landing", slug=slug))

    @app.get("/p/<slug>/challenge/rooms/<session_id>")
    @login_required
    def challenge_room(slug, session_id):
        project = load_project(slug)
        if not _host():
            abort(403)
        live = challenge_store.expire_if_needed(project["id"], session_id=session_id)
        if not live:
            abort(404)
        if live["status"] not in challenge_store.LIVE:
            return redirect(
                url_for("challenge_results", slug=slug, session_id=session_id)
            )
        live = challenge_store._room_counts(project["id"], live)
        return render_template(
            "challenge_landing.html",
            project=project,
            live=live,
            waiting=live["waiting"],
        )

    @app.post("/p/<slug>/challenge/rooms/<session_id>/clear")
    @login_required
    def challenge_clear(slug, session_id):
        project = load_project(slug)
        if not _host():
            abort(403)
        try:
            challenge_store.clear_players(project["id"], session_id)
        except ValueError as e:
            g.log_err = str(e)
            flash(str(e), "error")
        return redirect(url_for("challenge_room", slug=slug, session_id=session_id))

    @app.get("/p/<slug>/challenge/rooms/<session_id>/qr.png")
    @login_required
    def challenge_qr(slug, session_id):
        project = load_project(slug)
        if not _host():
            abort(403)
        live = challenge_store.get_session(project["id"], session_id)
        if not live or live["status"] not in challenge_store.LIVE:
            abort(404)
        qr = qrcode.QRCode(border=2, box_size=10)
        qr.add_data(
            url_for("challenge_join", slug=slug, pin=live["pin"], _external=True)
        )
        qr.make(fit=True)
        buf = io.BytesIO()
        qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png")

    @app.post("/p/<slug>/challenge/rooms/<session_id>/start")
    @login_required
    def challenge_start(slug, session_id):
        project = load_project(slug)
        if not _host():
            abort(403)
        xhr = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        try:
            challenge_store.start_session(project["id"], session_id)
        except ValueError as e:
            if xhr:
                return _json_error(e)
            flash(str(e), "error")
            return redirect(url_for("challenge_room", slug=slug, session_id=session_id))
        if xhr:
            return jsonify(
                {"ok": True, "url": url_for("challenge_god", slug=slug, session_id=session_id)}
            )
        return redirect(url_for("challenge_god", slug=slug, session_id=session_id))

    @app.get("/p/<slug>/challenge/join")
    def challenge_join(slug):
        project = load_project(slug)
        did, _ = device_id()
        live = challenge_store.player_live(project["id"], did)
        if live:
            return redirect(url_for("challenge_play", slug=slug))
        pin = (request.args.get("pin") or "").strip()
        if not challenge_store.PIN_RE.fullmatch(pin):
            pin = ""
        return render_template("challenge_join.html", project=project, pin=pin)

    @app.post("/p/<slug>/challenge/join")
    def challenge_join_post(slug):
        project = load_project(slug)
        did, _ = device_id()
        pin = request.form.get("pin")
        try:
            challenge_store.join_by_pin(project["id"], did, pin)
        except ValueError as e:
            g.log_err = str(e)
            flash(str(e), "error")
            kwargs = {"slug": slug}
            if challenge_store.PIN_RE.fullmatch((pin or "").strip()):
                kwargs["pin"] = (pin or "").strip()
            return redirect(url_for("challenge_join", **kwargs))
        return redirect(url_for("challenge_play", slug=slug))

    @app.get("/p/<slug>/challenge/play")
    def challenge_play(slug):
        project = load_project(slug)
        return render_template("challenge_play.html", project=project)

    @app.get("/p/<slug>/challenge/api/me")
    def challenge_me(slug):
        project = load_project(slug)
        did, _ = device_id()
        return jsonify(challenge_store.player_payload(project["id"], did, g.lang))

    @app.post("/p/<slug>/challenge/api/profile")
    def challenge_profile(slug):
        project = load_project(slug)
        did, _ = device_id()
        live = challenge_store.player_live(project["id"], did)
        if not live or live["status"] != "lobby":
            return _json_error(msg.challenge_not_open)
        payload = request.get_json(silent=True) or request.form
        nickname = payload.get("nickname") if "nickname" in payload else None
        avatar_id = None
        dest = None
        f = request.files.get("photo")
        if f and f.filename:
            avatar_id = uuid.uuid4().hex
            dest = challenge_store.avatar_path(project["id"], did)
            try:
                images.save_jpeg(f, dest)
            except Exception as e:
                dest.unlink(missing_ok=True)
                g.log_err = f"{type(e).__name__}: {e}"
                return _json_error(msg.bad_image)
        try:
            challenge_store.set_lobby_profile(
                project["id"], did, nickname, avatar_id
            )
        except ValueError as e:
            if dest:
                dest.unlink(missing_ok=True)
            return _json_error(e)
        return jsonify({"ok": True})

    @app.post("/p/<slug>/challenge/api/ready")
    def challenge_ready(slug):
        project = load_project(slug)
        did, _ = device_id()
        try:
            challenge_store.set_ready(project["id"], did)
        except ValueError as e:
            return _json_error(e)
        return jsonify({"ok": True})

    @app.post("/p/<slug>/challenge/api/upload")
    def challenge_upload(slug):
        project = load_project(slug)
        did, _ = device_id()
        live = challenge_store.player_live(project["id"], did)
        if not live or live["status"] != "running":
            return _json_error(msg.challenge_not_running)
        player = challenge_store.get_player(project["id"], live["id"], did)
        if not player:
            return _json_error(msg.challenge_not_player)
        f = request.files.get("photo")
        if not f or not f.filename:
            return _json_error(msg.need_photo)
        photo_id = uuid.uuid4().hex
        dest = challenge_store.submission_path(project["id"], live["id"], photo_id)
        try:
            images.save_jpeg(f, dest)
        except Exception as e:
            dest.unlink(missing_ok=True)
            g.log_err = f"{type(e).__name__}: {e}"
            return _json_error(msg.bad_image)
        try:
            idx = request.form.get("idx")
            idx = int(idx) if idx not in (None, "") else None
            challenge_store.submit_photo(
                project["id"], did, photo_id, dest.is_file(), idx=idx
            )
        except ValueError as e:
            dest.unlink(missing_ok=True)
            return _json_error(e)
        return jsonify({"ok": True, "photo_id": photo_id, "message": msg.challenge_uploaded})

    @app.post("/p/<slug>/challenge/api/host")
    def challenge_host_request(slug):
        project = load_project(slug)
        did, _ = device_id()
        try:
            idx = request.form.get("idx") or (request.get_json(silent=True) or {}).get(
                "idx"
            )
            idx = int(idx) if idx not in (None, "") else None
            challenge_store.request_host(project["id"], did, idx=idx)
        except (TypeError, ValueError) as e:
            return _json_error(e)
        return jsonify({"ok": True})

    @app.post("/p/<slug>/challenge/api/refresh")
    def challenge_refresh(slug):
        project = load_project(slug)
        did, _ = device_id()
        data = request.get_json(silent=True) or request.form
        band = (data.get("band") or "").strip()
        try:
            task = challenge_store.refresh_band(project["id"], did, band)
        except ValueError as e:
            return _json_error(e)
        return jsonify({"ok": True, "task": task["idx"] if task else None})

    @app.post("/p/<slug>/challenge/api/finish")
    def challenge_finish(slug):
        project = load_project(slug)
        did, _ = device_id()
        try:
            challenge_store.finish_player(project["id"], did)
        except ValueError as e:
            return _json_error(e)
        return jsonify({"ok": True})

    @app.get("/p/<slug>/challenge/rooms/<session_id>/god")
    @login_required
    def challenge_god(slug, session_id):
        project = load_project(slug)
        if not _host():
            abort(403)
        _room(project, session_id)
        return render_template(
            "challenge_god.html",
            project=project,
            session_id=session_id,
            can_override=True,
        )

    @app.get("/p/<slug>/challenge/rooms/<session_id>/api/god")
    @login_required
    def challenge_god_api(slug, session_id):
        project = load_project(slug)
        if not _host():
            abort(403)
        return jsonify(
            challenge_store.god_payload(project["id"], session_id, g.lang, True)
        )

    @app.post("/p/<slug>/challenge/rooms/<session_id>/api/review")
    @login_required
    def challenge_review(slug, session_id):
        project = load_project(slug)
        if not _host():
            abort(403)
        data = request.get_json(silent=True) or request.form
        device = (data.get("device_id") or "").strip()
        try:
            idx = int(data.get("idx"))
        except (TypeError, ValueError):
            return _json_error(msg.challenge_no_task)
        passed = str(data.get("passed") or "") in ("1", "true", "yes")
        live = challenge_store.get_session(project["id"], session_id)
        if not live:
            return _json_error(msg.challenge_not_open)
        task = challenge_store.get_task(project["id"], live["id"], device, idx)
        try:
            if task and task["kind"] == "host":
                challenge_store.host_review(
                    project["id"], session_id, device, idx, passed, current_name()
                )
            else:
                challenge_store.override_review(
                    project["id"], session_id, device, idx, passed, current_name()
                )
        except ValueError as e:
            return _json_error(e)
        return jsonify({"ok": True})

    @app.post("/p/<slug>/challenge/rooms/<session_id>/api/settle")
    @login_required
    def challenge_settle(slug, session_id):
        project = load_project(slug)
        if not _host():
            abort(403)
        try:
            session = challenge_store.settle(project["id"], session_id)
        except ValueError as e:
            return _json_error(e)
        return jsonify(
            {
                "ok": True,
                "url": url_for(
                    "challenge_results", slug=slug, session_id=session["id"]
                ),
            }
        )

    @app.get("/p/<slug>/challenge/results/<session_id>")
    @login_required
    def challenge_results(slug, session_id):
        project = load_project(slug)
        if not _host():
            abort(403)
        data = challenge_store.results_payload(project["id"], session_id, g.lang)
        if not data:
            abort(404)
        return render_template(
            "challenge_results.html",
            project=project,
            payload=data,
        )

    @app.post("/admin/projects/<project_id>/challenge/wipe")
    @login_required
    def admin_wipe_challenge(project_id):
        name = current_name()
        if not store.can_edit(name, project_id):
            abort(403)
        p = store.get_project(project_id)
        if not p:
            abort(404)
        challenge_store.wipe(project_id)
        flash(msg.challenge_wiped.format(name=p["name"]), "ok")
        return redirect(url_for("admin_home"))

    @app.post("/admin/projects/<project_id>/challenge/history")
    @login_required
    def admin_wipe_challenge_history(project_id):
        name = current_name()
        if not store.can_edit(name, project_id):
            abort(403)
        p = store.get_project(project_id)
        if not p:
            abort(404)
        challenge_store.wipe_history(project_id)
        flash(msg.challenge_history_wiped.format(name=p["name"]), "ok")
        return redirect(url_for("admin_home"))
