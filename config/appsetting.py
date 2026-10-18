import os

# gunicorn bind address
bind = os.environ.get("BIND", "0.0.0.0")
# gunicorn port inside the container (nginx exposes 8000)
port = int(os.environ.get("PORT", "8000"))
# Flask session cookie signing key (set in docker-compose/secret.env)
secret_key = os.environ.get("SECRET_KEY") or ""

# Photo and project-asset directory (use /data/photos in the container)
photo_dir = os.environ.get(
    "PHOTO_DIR",
    "/Volumes/OWC Envoy Pro FX/photo-upload",
)
# Per-project daily logs (Compose bind: $HOST_PHOTO_DIR/logs -> /logs)
log_dir = os.environ.get("LOG_DIR", "/logs")
# Delete log files whose date in the name is older than this many days
log_keep_days = int(os.environ.get("LOG_KEEP_DAYS", "30"))
# Seconds each slideshow photo stays on screen
slideshow_interval = int(os.environ.get("SLIDESHOW_INTERVAL", "8"))
# Slideshow crossfade duration in seconds (0 = hard cut)
slideshow_fade = min(3.0, max(0.0, float(os.environ.get("SLIDESHOW_FADE", "0.8"))))
# Slideshow layout: wall (name + caption) or full (photo only, cream letterbox)
slideshow_mode = os.environ.get("SLIDESHOW_MODE", "wall")
if slideshow_mode not in ("wall", "full"):
    slideshow_mode = "wall"
# Slideshow queue max length
slideshow_queue_max = int(os.environ.get("SLIDESHOW_QUEUE_MAX", "100"))
# When total photos exceed the queue max, keep this many newest per device
slideshow_per_device = int(os.environ.get("SLIDESHOW_PER_DEVICE", "5"))
# Redis TTL in days for photo/lottery records (files are not auto-deleted)
record_ttl_days = int(os.environ.get("RECORD_TTL_DAYS", "20"))
# Max upload size per photo (MB)
max_upload_mb = int(os.environ.get("MAX_UPLOAD_MB", "20"))
# Longest edge of saved JPEGs (pixels)
jpeg_max_edge = int(os.environ.get("JPEG_MAX_EDGE", "2560"))
# gunicorn worker count
gunicorn_workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
# gunicorn timeout seconds (keep high enough for large uploads)
gunicorn_timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
# Lottery sphere spin duration (seconds)
lottery_seconds = int(os.environ.get("LOTTERY_SECONDS", "10"))
# Max photos shown on the lottery sphere
lottery_sphere_max = int(os.environ.get("LOTTERY_SPHERE_MAX", "60"))
# Max lottery tickets per device; draw uses that many newest photos (uploads stay unlimited)
lottery_chance_max = int(os.environ.get("LOTTERY_CHANCE_MAX", "10"))
# Default Ichiban Kuji draws per device (each photo with a person earns one, up to this cap)
kuji_per_user = int(os.environ.get("KUJI_PER_USER", "2"))
# Person check (detector container): YOLOX-Tiny ONNX model path inside the container
detector_model = os.environ.get("DETECTOR_MODEL", "/app/models/yolox_tiny.onnx")
# onnxruntime CPU threads for the detector
detector_threads = int(os.environ.get("DETECTOR_THREADS", "2"))
# Min person score (objectness x class) for a photo to count as having a person
person_score = float(os.environ.get("PERSON_SCORE", "0.45"))
# Min person box area as a fraction of the photo (skips tiny people far in the background)
person_min_area = float(os.environ.get("PERSON_MIN_AREA", "0.005"))
# picture-judge worker (POC): InsightFace + CLIP ONNX
judge_threads = int(os.environ.get("JUDGE_THREADS", "2"))
judge_model_dir = os.environ.get("JUDGE_MODEL_DIR", "/app/models")


def _unit(name, default):
    return min(1.0, max(0.0, float(os.environ.get(name, default))))


# Fades below are 0–1: 0 = original, 1 = fully white or fully transparent
# White overlay on the project-home pjt background
pjt_fade = _unit("PJT_FADE", "0.6")
# White overlay on the slideshow bkg background
bkg_fade = _unit("BKG_FADE", "0.6")
# Project title fade (0.3 = 30% transparent)
title_fade = _unit("TITLE_FADE", "0.3")
# Home-page button fill fade (0.4 = 40% transparent)
button_fade = _unit("BUTTON_FADE", "0.4")
# Home-page button label fade (0.3 = 30% transparent)
button_text_fade = _unit("BUTTON_TEXT_FADE", "0.3")
# Upload button fill (rice white)
upload_btn_color = os.environ.get("UPLOAD_BTN_COLOR", "#f4efe6")
# Slideshow button fill (light gray)
slideshow_btn_color = os.environ.get("SLIDESHOW_BTN_COLOR", "#d4d1cc")
# Lottery button fill (gold)
lottery_btn_color = os.environ.get("LOTTERY_BTN_COLOR", "#d4af37")
# Lottery winner screen inset from the screen edge (cm)
lottery_pad_cm = os.environ.get("LOTTERY_PAD_CM", "2")
# Glass card padding on desktop (cm)
glass_pad_cm = os.environ.get("GLASS_PAD_CM", "2")
# Glass card padding on phones (cm)
glass_pad_mobile_cm = os.environ.get("GLASS_PAD_MOBILE_CM", "1")
# Upload page inset from the screen edge (cm)
upload_pad_cm = os.environ.get("UPLOAD_PAD_CM", "1")
# Admin project list inset from the screen edge (cm)
admin_pad_cm = os.environ.get("ADMIN_PAD_CM", "1")
