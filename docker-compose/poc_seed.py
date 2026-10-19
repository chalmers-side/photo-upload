"""Create or refresh the POC demo project (slug "poc") with generated assets.

Run inside the POC app container: ./poc.sh seed
"""

import io
import time
import uuid

from PIL import Image, ImageDraw, ImageFont

from web import images, store

SLUG = "poc"
NAME = "POC Demo"
KUJI_TOTALS = {"A": 1, "B": 2, "C": 3, "D": 5, "E": 10}
PRIZE_COLORS = {
    "A": "#d4af37",
    "B": "#c0504d",
    "C": "#4f81bd",
    "D": "#9bbb59",
    "E": "#8064a2",
}


def font(size):
    return ImageFont.load_default(size=size)


def gradient(w, h, top, bottom):
    a = Image.new("RGB", (w, h), top)
    b = Image.new("RGB", (w, h), bottom)
    mask = Image.linear_gradient("L").resize((w, h))
    return Image.composite(b, a, mask)


def label(img, text, size, fill="#ffffff"):
    d = ImageDraw.Draw(img)
    d.text((img.width / 2, img.height / 2), text, font=font(size), fill=fill, anchor="mm")
    return img


def as_upload(img, fmt):
    buf = io.BytesIO()
    img.save(buf, fmt)
    buf.seek(0)
    return buf


def save(pid, kind, img):
    dest = store.asset_path(pid, kind)
    if store.asset_is_png(kind):
        images.save_mark(as_upload(img, "PNG"), dest)
    else:
        images.save_jpeg_and_thumb(
            as_upload(img, "JPEG"), dest, store.asset_thumb_path(pid, kind)
        )


def mark(text, color):
    img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((16, 16, 496, 496), fill=color, outline="#ffffff", width=12)
    return label(img, text, 120)


def ticket():
    img = gradient(960, 600, "#b22222", "#7a1010").convert("RGBA")
    d = ImageDraw.Draw(img)
    d.rectangle((24, 24, 936, 576), outline="#d4af37", width=10)
    d.text((480, 250), "ICHIBAN KUJI", font=font(96), fill="#ffffff", anchor="mm")
    d.text((480, 380), "pull from bottom-left", font=font(40), fill="#f4efe6", anchor="mm")
    return img


def backgrounds(prefix, top, bottom, text):
    return {
        f"{prefix}-desktop": label(gradient(1920, 1080, top, bottom), text, 120),
        f"{prefix}-mobile": label(gradient(1080, 1920, top, bottom), text, 110),
    }


def person_blob():
    img = Image.new("RGB", (640, 800), "#c8b89a")
    d = ImageDraw.Draw(img)
    d.ellipse((180, 120, 460, 420), fill="#e8c4a0")
    d.rectangle((220, 400, 420, 760), fill="#3a5a9a")
    return img


def seed_guests(pid):
    for i, name in enumerate(("Ada", "Ben")):
        did = f"poc-guest-{i}"
        store.set_nickname(did, name)
        photo_id = uuid.uuid4().hex
        dest = store.photo_path(pid, photo_id)
        images.save_jpeg(as_upload(person_blob(), "JPEG"), dest)
        with store.pg().connection() as conn:
            conn.execute(
                """
                INSERT INTO photos (
                  project_id, id, caption, device_id, ts, person, consent
                ) VALUES (%s, %s, %s, %s, %s, TRUE, TRUE)
                """,
                (pid, photo_id, name, did, time.time()),
            )
    store.rebuild_slideshow_queue(pid)


def main():
    p = store.project_by_slug(SLUG) or store.create_project(NAME, SLUG)
    pid = p["id"]

    assets = {
        "pjt-mark": mark("POC", "#d4af37"),
        "kuji-mark": mark("KUJI", "#b22222"),
        "kuji-ticket": ticket(),
    }
    assets.update(backgrounds("pjt", "#e8d9c0", "#8aa0b8", "HOME"))
    assets.update(backgrounds("bkg", "#20303f", "#5a6b7d", "SLIDESHOW"))
    assets.update(backgrounds("lot", "#3a1c4a", "#b0703a", "LOTTERY"))
    assets.update(backgrounds("kuji", "#f3e3c3", "#c0504d", "KUJI"))
    for g, color in PRIZE_COLORS.items():
        assets[f"kuji-{g.lower()}"] = label(
            gradient(800, 800, color, "#222222"), f"{g} PRIZE", 120
        )
    for kind, img in assets.items():
        save(pid, kind, img)

    form = {"per_user": "2"}
    form.update({f"total_{g}": str(n) for g, n in KUJI_TOTALS.items()})
    try:
        store.kuji_save(pid, form)
    except ValueError as e:
        print(f"kuji totals kept: {e}")

    if not store._one(
        "SELECT 1 AS n FROM photos WHERE device_id = %s LIMIT 1",
        ("poc-guest-0",),
    ):
        seed_guests(pid)

    print(f"project {NAME!r} slug={SLUG} id={pid}: {len(assets)} assets, kuji {KUJI_TOTALS}")


if __name__ == "__main__":
    main()
