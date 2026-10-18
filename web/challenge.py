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

from config import appsetting
from config import msg
from web import challenge_store, images, store


def register(app, load_project, current_name, device_id, login_required):
    def _edit(project):
        name = current_name()
        return bool(name and store.can_edit(name, project["id"]))

    def _god(project):
        name = current_name()
        return bool(name and store.can_lottery(name, project["id"]))

    def _json_error(err, code=400):
        g.log_err = str(err)
        return jsonify({"error": str(err)}), code

    @app.get("/p/<slug>/challenge/")
    @login_required
    def challenge_landing(slug):
        project = load_project(slug)
        if not _edit(project):
            abort(403)
        live = challenge_store.expire_if_needed(project["id"])
        waiting = []
        if live:
            live = dict(live)
            waiting = challenge_store.waiting_of(project["id"], live["id"])
            live["player_count"] = len(waiting)
            live["ready_count"] = sum(1 for w in waiting if w["ready"])
            live["all_ready"] = bool(waiting) and all(w["ready"] for w in waiting)
        return render_template(
            "challenge_landing.html",
            project=project,
            live=live,
            waiting=waiting,
            history=challenge_store.list_history(project["id"]),
            join_url=url_for("challenge_join", slug=slug, _external=True),
        )

    @app.get("/p/<slug>/challenge/qr.png")
    @login_required
    def challenge_qr(slug):
        project = load_project(slug)
        if not _edit(project):
            abort(403)
        qr = qrcode.QRCode(border=2, box_size=10)
        qr.add_data(url_for("challenge_join", slug=slug, _external=True))
        qr.make(fit=True)
        buf = io.BytesIO()
        qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png")

    @app.post("/p/<slug>/challenge/open")
    @login_required
    def challenge_open(slug):
        project = load_project(slug)
        if not _edit(project):
            abort(403)
        kind = (request.form.get("kind") or "").strip()
        try:
            challenge_store.open_lobby(project["id"], kind)
        except ValueError as e:
            g.log_err = str(e)
            flash(str(e), "error")
            return redirect(url_for("challenge_landing", slug=slug))
        return redirect(url_for("challenge_landing", slug=slug))

    @app.post("/p/<slug>/challenge/start")
    @login_required
    def challenge_start(slug):
        project = load_project(slug)
        if not _edit(project):
            abort(403)
        xhr = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        try:
            challenge_store.start_session(project["id"])
        except ValueError as e:
            if xhr:
                return _json_error(e)
            flash(str(e), "error")
            return redirect(url_for("challenge_landing", slug=slug))
        if xhr:
            return jsonify({"ok": True})
        return redirect(url_for("challenge_god", slug=slug))

    @app.get("/p/<slug>/challenge/join")
    def challenge_join(slug):
        project = load_project(slug)
        did, _ = device_id()
        try:
            challenge_store.join(project["id"], did)
        except ValueError as e:
            flash(str(e), "error")
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
        live = challenge_store.live_session(project["id"])
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
            challenge_store.submit_photo(project["id"], did, photo_id, dest.is_file())
        except ValueError as e:
            dest.unlink(missing_ok=True)
            return _json_error(e)
        return jsonify({"ok": True, "photo_id": photo_id, "message": msg.challenge_uploaded})

    @app.post("/p/<slug>/challenge/api/host")
    def challenge_host_request(slug):
        project = load_project(slug)
        did, _ = device_id()
        try:
            challenge_store.request_host(project["id"], did)
        except ValueError as e:
            return _json_error(e)
        return jsonify({"ok": True})

    @app.post("/p/<slug>/challenge/api/finish")
    def challenge_finish(slug):
        project = load_project(slug)
        did, _ = device_id()
        try:
            challenge_store.finish_player(project["id"], did)
        except ValueError as e:
            return _json_error(e)
        return jsonify({"ok": True})

    @app.get("/p/<slug>/challenge/god")
    @login_required
    def challenge_god(slug):
        project = load_project(slug)
        if not _god(project):
            abort(403)
        return render_template(
            "challenge_god.html",
            project=project,
            can_override=_edit(project),
        )

    @app.get("/p/<slug>/challenge/api/god")
    @login_required
    def challenge_god_api(slug):
        project = load_project(slug)
        if not _god(project):
            abort(403)
        return jsonify(
            challenge_store.god_payload(project["id"], g.lang, _edit(project))
        )

    @app.post("/p/<slug>/challenge/api/review")
    @login_required
    def challenge_review(slug):
        project = load_project(slug)
        if not _god(project):
            abort(403)
        data = request.get_json(silent=True) or request.form
        device = (data.get("device_id") or "").strip()
        try:
            idx = int(data.get("idx"))
        except (TypeError, ValueError):
            return _json_error(msg.challenge_no_task)
        passed = str(data.get("passed") or "") in ("1", "true", "yes")
        try:
            if _edit(project):
                challenge_store.override_review(
                    project["id"], device, idx, passed, current_name()
                )
            else:
                challenge_store.host_review(
                    project["id"], device, idx, passed, current_name()
                )
        except ValueError as e:
            return _json_error(e)
        return jsonify({"ok": True})

    @app.post("/p/<slug>/challenge/api/settle")
    @login_required
    def challenge_settle(slug):
        project = load_project(slug)
        if not _god(project):
            abort(403)
        try:
            session = challenge_store.settle(project["id"])
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
        if not _god(project):
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
