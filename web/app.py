import io
import time
import uuid
from datetime import timedelta
from functools import wraps

import qrcode
from werkzeug.exceptions import HTTPException
from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from config import appsetting
from config import msg
from web import applog, images, store
from web.challenge import register as register_challenge


def create_app():
    app = Flask(__name__)
    app.secret_key = appsetting.secret_key
    app.config["MAX_CONTENT_LENGTH"] = appsetting.max_upload_mb * 5 * 1024 * 1024
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    store.ensure_root()

    def current_name():
        return session.get("user")

    def login_required(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not current_name():
                return redirect(url_for("admin_login", next=request.path))
            return fn(*args, **kwargs)

        return wrapped

    def staff_required(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            name = current_name()
            if not name:
                return redirect(url_for("admin_login", next=request.path))
            if not store.can_staff(name):
                flash(msg.staff_only, "error")
                return redirect(url_for("index"))
            return fn(*args, **kwargs)

        return wrapped

    def root_required(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            name = current_name()
            if not name:
                return redirect(url_for("admin_login", next=request.path))
            if not store.is_root(name):
                flash(msg.staff_only, "error")
                return redirect(url_for("admin_home" if store.can_staff(name) else "index"))
            return fn(*args, **kwargs)

        return wrapped

    def edit_required(fn):
        @wraps(fn)
        def wrapped(project_id, *args, **kwargs):
            name = current_name()
            if not name:
                return redirect(url_for("admin_login", next=request.path))
            if not store.can_edit(name, project_id):
                flash(msg.staff_only, "error")
                return redirect(url_for("admin_home" if store.can_staff(name) else "index"))
            return fn(project_id, *args, **kwargs)

        return wrapped

    def delete_required(fn):
        @wraps(fn)
        def wrapped(project_id, *args, **kwargs):
            name = current_name()
            if not name:
                return redirect(url_for("admin_login", next=request.path))
            if not store.can_delete_project(name, project_id):
                flash(msg.staff_only, "error")
                return redirect(url_for("admin_home" if store.can_staff(name) else "index"))
            return fn(project_id, *args, **kwargs)

        return wrapped

    def load_project(slug):
        p = store.project_by_slug(slug)
        if not p:
            abort(404)
        g.project_id = p["id"]
        g.project_slug = p["slug"]
        return p

    def device_id():
        if getattr(g, "device_id", None):
            return g.device_id, g.device_id_new
        did = request.cookies.get("device_id") or ""
        if did and len(did) <= 64:
            g.device_id = did
            g.device_id_new = False
            return did, False
        g.device_id = uuid.uuid4().hex
        g.device_id_new = True
        return g.device_id, True

    def with_device_cookie(resp, did, is_new):
        if is_new:
            resp.set_cookie(
                "device_id",
                did,
                max_age=60 * 60 * 24 * 400,
                httponly=True,
                samesite="Lax",
            )
        return resp

    def resolve_lang():
        name = current_name()
        if name:
            return store.user_lang(name)
        did, _ = device_id()
        return store.device_lang(did) or msg.normalize_lang(request.cookies.get("lang"))

    @app.context_processor
    def inject_admin():
        name = current_name()
        pid = getattr(g, "project_id", None)
        lang = getattr(g, "lang", None) or resolve_lang()
        return {
            "msg": msg,
            "cfg": appsetting,
            "current_user": name,
            "ui_lang": lang,
            "html_lang": "en" if lang == "en" else "zh-Hant",
            "is_root": store.is_root(name) if name else False,
            "can_staff": store.can_staff(name) if name else False,
            "can_create_project": store.can_create_project(name) if name else False,
            "can_lottery": store.can_lottery(name, pid) if name and pid else False,
            "can_edit": store.can_edit(name, pid) if name and pid else False,
            "is_admin": store.can_staff(name) if name else False,
        }

    @app.before_request
    def log_start():
        g.log_t0 = time.monotonic()
        store.ensure_root()
        name = current_name()
        if name and not store.get_user(name):
            session.clear()
        args = request.view_args or {}
        if args.get("project_id"):
            g.project_id = args["project_id"]
        g.lang = resolve_lang()

    @app.after_request
    def remember_device(resp):
        did, is_new = device_id()
        resp = with_device_cookie(resp, did, is_new)
        lang = getattr(g, "lang", None)
        if lang:
            resp.set_cookie(
                "lang",
                lang,
                max_age=60 * 60 * 24 * 400,
                samesite="Lax",
            )
        slug = getattr(g, "project_slug", None)
        if slug:
            slugs = store.parse_visited(request.cookies.get("visited"))
            if slug in slugs:
                slugs.remove(slug)
            slugs.insert(0, slug)
            resp.set_cookie(
                "visited",
                ",".join(slugs[: store.VISITED_MAX]),
                max_age=60 * 60 * 24 * 400,
                httponly=True,
                samesite="Lax",
            )
        return resp

    @app.after_request
    def write_project_log(resp):
        if request.endpoint in ("health", "slideshow_api", "challenge_me", "challenge_god_api"):
            return resp
        err = getattr(g, "log_err", None)
        pid = getattr(g, "project_id", None)
        if not pid and not err:
            return resp
        ms = int((time.monotonic() - getattr(g, "log_t0", time.monotonic())) * 1000)
        ip = request.headers.get("X-Real-IP") or request.remote_addr or "-"
        line = f"{ip} {request.method} {request.path} {resp.status_code} {ms}ms"
        if err:
            line += f" ERROR {err}"
        elif resp.status_code >= 400:
            line += " ERROR"
        applog.write(pid or "app", line)
        return resp

    @app.errorhandler(Exception)
    def log_unhandled(err):
        if isinstance(err, HTTPException):
            if err.code and err.code >= 400:
                g.log_err = err.name
            return err
        g.log_err = f"{type(err).__name__}: {err}"
        return "Internal Server Error", 500

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/api/profile")
    def profile_get():
        did, _ = device_id()
        return {
            "nickname": store.nickname_of(did),
            "lang": store.device_lang(did) or g.lang,
        }

    @app.post("/api/profile")
    def profile_post():
        did, _ = device_id()
        payload = request.get_json(silent=True) or request.form
        try:
            name = store.set_nickname(did, payload.get("nickname"))
            if not current_name() and payload.get("lang"):
                g.lang = store.set_device_lang(did, payload.get("lang"))
        except ValueError as e:
            g.log_err = str(e)
            return jsonify({"error": str(e)}), 400
        return jsonify({"nickname": name, "lang": g.lang})

    @app.get("/")
    def index():
        name = current_name()
        if name:
            projects = store.list_projects_for_ids(store.visible_ids(name))
        else:
            projects = store.projects_by_slugs(
                store.parse_visited(request.cookies.get("visited"))
            )
        return render_template("index.html", projects=projects)

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        store.ensure_root()
        nxt = request.args.get("next") or url_for("admin_home")
        if current_name():
            if store.can_staff(current_name()):
                return redirect(nxt)
            return redirect(url_for("index"))
        error = None
        if request.method == "POST":
            u = store.authenticate(
                request.form.get("username"),
                request.form.get("password"),
            )
            if u:
                session.clear()
                session["user"] = u["name"]
                session.permanent = True
                if store.can_staff(u["name"]):
                    return redirect(nxt)
                return redirect(url_for("index"))
            error = msg.login_failed
        return render_template("admin_login.html", error=error)

    @app.post("/admin/logout")
    @login_required
    def admin_logout():
        session.clear()
        return redirect(url_for("index"))

    @app.post("/account/lang")
    @login_required
    def account_lang():
        try:
            g.lang = store.set_user_lang(current_name(), request.form.get("lang"))
        except ValueError as e:
            g.log_err = str(e)
            flash(str(e), "error")
            return redirect(request.referrer or url_for("index"))
        flash(msg.lang_saved, "ok")
        return redirect(request.referrer or url_for("index"))

    @app.post("/admin/users/<username>/lang")
    @root_required
    def admin_set_lang(username):
        try:
            lang = store.set_user_lang(username, request.form.get("lang"))
        except ValueError as e:
            g.log_err = str(e)
            flash(str(e), "error")
            return redirect(url_for("admin_accounts"))
        if username == current_name():
            g.lang = lang
        flash(msg.lang_saved, "ok")
        return redirect(url_for("admin_accounts"))

    @app.post("/account/password")
    @login_required
    def account_password():
        new = request.form.get("new") or ""
        again = request.form.get("again") or ""
        if new != again:
            flash(msg.password_mismatch, "error")
            return redirect(request.referrer or url_for("index"))
        try:
            store.change_password(current_name(), request.form.get("old"), new)
        except ValueError as e:
            g.log_err = str(e)
            flash(str(e), "error")
            return redirect(request.referrer or url_for("index"))
        flash(msg.password_changed, "ok")
        return redirect(request.referrer or url_for("index"))

    @app.get("/admin")
    @staff_required
    def admin_home():
        name = current_name()
        projects = store.list_projects_for_ids(store.staff_ids(name))
        for p in projects:
            p["can_delete"] = store.can_delete_project(name, p["id"])
        return render_template("admin.html", projects=projects)

    @app.get("/admin/accounts")
    @root_required
    def admin_accounts():
        users = [u for u in store.list_users() if not u["is_root"]]
        return render_template(
            "admin_accounts.html",
            users=users,
            root_user=store.get_user(current_name()),
            all_projects=store.list_projects(),
        )

    @app.post("/admin/projects")
    @login_required
    def admin_create_project():
        name = current_name()
        if not store.can_create_project(name):
            flash(msg.staff_only, "error")
            return redirect(url_for("admin_home" if store.can_staff(name) else "index"))
        try:
            p = store.create_project(
                request.form.get("name"),
                request.form.get("slug"),
                owner=name,
            )
        except ValueError as e:
            g.log_err = str(e)
            flash(str(e), "error")
            return redirect(url_for("admin_home"))
        g.project_id = p["id"]
        flash(msg.project_created.format(name=p["name"]), "ok")
        return redirect(url_for("admin_home"))

    @app.post("/admin/users")
    @root_required
    def admin_create_user():
        try:
            u = store.create_user(
                request.form.get("username"),
                request.form.get("password"),
            )
        except ValueError as e:
            g.log_err = str(e)
            flash(str(e), "error")
            return redirect(url_for("admin_accounts"))
        flash(msg.user_created.format(name=u["name"]), "ok")
        return redirect(url_for("admin_accounts"))

    @app.post("/admin/users/<username>/roles")
    @root_required
    def admin_save_roles(username):
        try:
            ids = [p["id"] for p in store.list_projects()]
            store.save_user_roles(username, request.form, ids)
        except ValueError as e:
            g.log_err = str(e)
            flash(str(e), "error")
            return redirect(url_for("admin_accounts"))
        flash(msg.roles_saved.format(name=username), "ok")
        return redirect(url_for("admin_accounts"))

    @app.post("/admin/users/<username>/password")
    @root_required
    def admin_reset_password(username):
        new = request.form.get("new") or ""
        again = request.form.get("again") or ""
        if new != again:
            flash(msg.password_mismatch, "error")
            return redirect(url_for("admin_accounts"))
        try:
            store.set_password(username, new)
        except ValueError as e:
            g.log_err = str(e)
            flash(str(e), "error")
            return redirect(url_for("admin_accounts"))
        flash(msg.password_changed, "ok")
        return redirect(url_for("admin_accounts"))

    @app.post("/admin/users/<username>/delete")
    @root_required
    def admin_delete_user(username):
        try:
            store.delete_user(username)
        except ValueError as e:
            g.log_err = str(e)
            flash(str(e), "error")
            return redirect(url_for("admin_accounts"))
        flash(msg.user_deleted.format(name=username), "ok")
        return redirect(url_for("admin_accounts"))

    @app.post("/admin/projects/<project_id>/delete")
    @delete_required
    def admin_delete_project(project_id):
        try:
            p = store.delete_project(project_id, delete_files=True)
        except ValueError as e:
            g.log_err = str(e)
            flash(str(e), "error")
            return redirect(url_for("admin_home"))
        flash(msg.project_deleted.format(name=p["name"]), "ok")
        return redirect(url_for("admin_home"))

    @app.post("/admin/projects/<project_id>/reset-photos")
    @edit_required
    def admin_reset_photos(project_id):
        try:
            p = store.reset_guest_photos(project_id)
        except ValueError as e:
            g.log_err = str(e)
            flash(str(e), "error")
            return redirect(url_for("admin_home"))
        flash(msg.reset_photos_ok.format(name=p["name"]), "ok")
        return redirect(url_for("admin_home"))

    @app.post("/admin/projects/<project_id>/asset/<kind>")
    @edit_required
    def admin_save_asset(project_id, kind):
        xhr = request.headers.get("X-Requested-With") == "XMLHttpRequest"

        def reply(text, error=False):
            if error:
                g.log_err = getattr(g, "log_err", None) or text
            if xhr:
                key = "error" if error else "ok"
                return jsonify({key: text}), (400 if error else 200)
            flash(text, "error" if error else "ok")
            return redirect(url_for("admin_home"))

        if not store.get_project(project_id):
            return reply(msg.project_missing, error=True)
        f = request.files.get("photo")
        if not f or not f.filename:
            return reply(msg.need_photo, error=True)
        try:
            dest = store.asset_path(project_id, kind)
            if store.asset_is_png(kind):
                images.save_mark(f, dest)
            else:
                thumb = store.asset_thumb_path(project_id, kind)
                images.save_jpeg_and_thumb(f, dest, thumb)
        except ValueError as e:
            return reply(str(e), error=True)
        except Exception as e:
            g.log_err = f"{type(e).__name__}: {e}"
            return reply(msg.bad_image, error=True)
        flash(msg.asset_saved, "ok")
        if xhr:
            return jsonify({"ok": True})
        return redirect(url_for("admin_home"))

    @app.post("/admin/projects/<project_id>/asset/<kind>/delete")
    @edit_required
    def admin_delete_asset(project_id, kind):
        if not store.get_project(project_id):
            flash(msg.project_missing, "error")
            return redirect(url_for("admin_home"))
        try:
            store.asset_path(project_id, kind).unlink(missing_ok=True)
            store.asset_thumb_path(project_id, kind).unlink(missing_ok=True)
            if kind == "pjt-mark":
                (store.photo_dir(project_id) / "pjt-mark.jpg").unlink(missing_ok=True)
        except ValueError as e:
            g.log_err = str(e)
            flash(str(e), "error")
            return redirect(url_for("admin_home"))
        flash(msg.asset_removed, "ok")
        return redirect(url_for("admin_home"))

    @app.post("/admin/projects/<project_id>/settings")
    @edit_required
    def admin_save_settings(project_id):
        try:
            store.update_project_settings(project_id, request.form)
        except ValueError as e:
            g.log_err = str(e)
            flash(str(e), "error")
            return redirect(url_for("admin_home"))
        flash(msg.settings_saved, "ok")
        return redirect(url_for("admin_home"))

    @app.post("/admin/projects/<project_id>/kuji")
    @edit_required
    def admin_save_kuji(project_id):
        try:
            store.kuji_save(project_id, request.form)
        except ValueError as e:
            g.log_err = str(e)
            flash(str(e), "error")
            return redirect(url_for("admin_home"))
        flash(msg.kuji_saved, "ok")
        return redirect(url_for("admin_home"))

    @app.post("/admin/projects/<project_id>/kuji/reset")
    @edit_required
    def admin_reset_kuji(project_id):
        p = store.get_project(project_id)
        if not p:
            flash(msg.project_missing, "error")
            return redirect(url_for("admin_home"))
        store.kuji_reset(project_id)
        flash(msg.kuji_reset_ok.format(name=p["name"]), "ok")
        return redirect(url_for("admin_home"))

    @app.post("/admin/projects/<project_id>/lottery/reset")
    @edit_required
    def admin_reset_lottery(project_id):
        p = store.get_project(project_id)
        if not p:
            flash(msg.project_missing, "error")
            return redirect(url_for("admin_home"))
        store.reset_lottery_winners(project_id)
        flash(msg.lottery_reset.format(name=p["name"]), "ok")
        return redirect(url_for("admin_home"))

    @app.post("/p/<slug>/lottery/reset")
    @login_required
    def lottery_reset(slug):
        project = load_project(slug)
        if not store.can_edit(current_name(), project["id"]):
            abort(403)
        store.reset_lottery_winners(project["id"])
        return redirect(url_for("lottery", slug=slug))

    _qr_pages = {
        "home": "project_home",
        "upload": "upload",
        "slideshow": "slideshow",
    }

    @app.get("/admin/projects/<project_id>/qr/<kind>.png")
    @edit_required
    def admin_qr(project_id, kind):
        endpoint = _qr_pages.get(kind)
        p = store.get_project(project_id)
        if not endpoint or not p:
            abort(404)
        qr = qrcode.QRCode(border=2, box_size=10)
        qr.add_data(url_for(endpoint, slug=p["slug"], _external=True))
        qr.make(fit=True)
        buf = io.BytesIO()
        qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png")

    @app.get("/p/<slug>/")
    def project_home(slug):
        project = load_project(slug)
        return render_template(
            "project_home.html",
            project=project,
            kuji_total=store.kuji_state(project["id"])["total"],
        )

    def kuji_unlimited():
        name = current_name()
        return bool(name and store.is_root(name))

    @app.get("/p/<slug>/kuji")
    def kuji(slug):
        project = load_project(slug)
        did, _ = device_id()
        return render_template(
            "kuji.html",
            project=project,
            me=store.kuji_me(project["id"], did, unlimited=kuji_unlimited()),
            kuji_total=store.kuji_state(project["id"])["total"],
        )

    @app.get("/p/<slug>/api/kuji/status")
    def kuji_status(slug):
        project = load_project(slug)
        did, _ = device_id()
        state = store.kuji_state(project["id"])
        state["me"] = store.kuji_me(project["id"], did, unlimited=kuji_unlimited())
        return jsonify(state)

    @app.post("/p/<slug>/api/kuji/draw")
    def kuji_draw(slug):
        project = load_project(slug)
        did, _ = device_id()
        try:
            return jsonify(store.kuji_draw(project["id"], did, unlimited=kuji_unlimited()))
        except ValueError as e:
            g.log_err = str(e)
            return jsonify({"error": str(e)}), 400

    @app.get("/p/<slug>/api/kuji/mine")
    def kuji_mine(slug):
        project = load_project(slug)
        did, _ = device_id()
        return jsonify({"prizes": store.kuji_mine(project["id"], did)})

    @app.post("/p/<slug>/api/kuji/claim/<draw_id>")
    def kuji_claim(slug, draw_id):
        project = load_project(slug)
        did, _ = device_id()
        try:
            at = store.kuji_claim(project["id"], did, draw_id)
        except ValueError as e:
            g.log_err = str(e)
            return jsonify({"error": str(e)}), 400
        return jsonify({"claimed_at": at})

    @app.route("/p/<slug>/upload", methods=["GET", "POST"])
    def upload(slug):
        project = load_project(slug)
        if request.method == "POST":
            xhr = request.headers.get("X-Requested-With") == "XMLHttpRequest"

            def reply(text, error=False):
                if error:
                    g.log_err = getattr(g, "log_err", None) or text
                if xhr:
                    key = "error" if error else "message"
                    return jsonify({key: text}), (400 if error else 200)
                flash(text, "error" if error else "ok")
                return redirect(request.path)

            files = [f for f in request.files.getlist("photo") if f and f.filename]
            caption = (request.form.get("caption") or "").strip()
            if not files:
                return reply(msg.need_photo, error=True)
            if len(files) > 5:
                return reply(msg.upload_too_many, error=True)
            if len(caption) > 500:
                return reply(msg.caption_too_long, error=True)
            consent_raw = (request.form.get("consent") or "").strip()
            if consent_raw not in ("yes", "no"):
                return reply(msg.upload_need_consent, error=True)
            consent = consent_raw == "yes"
            did, _ = device_id()
            saved = []
            for f in files:
                photo_id = uuid.uuid4().hex
                dest = store.photo_path(project["id"], photo_id)
                try:
                    images.save_jpeg(f, dest)
                except Exception as e:
                    dest.unlink(missing_ok=True)
                    g.log_err = f"{type(e).__name__}: {e}"
                    continue
                store.add_photo(
                    project["id"], photo_id, caption, did, rebuild=False, consent=consent
                )
                saved.append(photo_id)
            if not saved:
                return reply(msg.bad_image, error=True)
            store.rebuild_slideshow_queue(project["id"])
            text = msg.upload_checking.format(n=len(saved))
            if xhr:
                return jsonify({"message": text, "photo_ids": saved})
            return reply(text)
        return render_template("upload.html", project=project)

    @app.get("/p/<slug>/api/photos/status")
    def photo_status(slug):
        project = load_project(slug)
        did, _ = device_id()
        ids = [x for x in (request.args.get("ids") or "").split(",") if x]
        return jsonify(store.photo_status(project["id"], did, ids))

    @app.get("/p/<slug>/slideshow")
    def slideshow(slug):
        return render_template("slideshow.html", project=load_project(slug))

    @app.get("/p/<slug>/api/slideshow")
    def slideshow_api(slug):
        project = load_project(slug)
        return jsonify(store.slideshow_state(project["id"]))

    @app.get("/p/<slug>/lottery")
    @login_required
    def lottery(slug):
        project = load_project(slug)
        if not store.can_lottery(current_name(), project["id"]):
            abort(403)
        return render_template(
            "lottery.html",
            project=project,
            seconds=project["lottery_seconds"],
        )

    @app.post("/p/<slug>/api/lottery/draw")
    @login_required
    def lottery_draw(slug):
        project = load_project(slug)
        if not store.can_lottery(current_name(), project["id"]):
            abort(403)
        try:
            return jsonify(store.draw_lottery(project["id"]))
        except ValueError as e:
            g.log_err = str(e)
            return jsonify({"error": str(e)}), 400

    register_challenge(app, load_project, current_name, device_id, login_required)
    return app
