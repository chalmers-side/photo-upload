"""picture-judge worker: face match (InsightFace) and CLIP couple/color.

Pulls jobs from Redis judge_q. Models download into JUDGE_MODEL_DIR on first run.
Falls back to 2-face / HSV color if CLIP weights are missing.
"""
import json
import logging
import time
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import onnxruntime as ort
import redis
from PIL import Image

from config import appsetting
from web import applog, challenge_store, store

log = logging.getLogger("judge")

DET_ZIP = (
    "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_sc.zip"
)
CLIP_VISION = (
    "https://huggingface.co/Qdrant/clip-ViT-B-32-vision/resolve/main/model.onnx"
)
CLIP_TEXT = "https://huggingface.co/Qdrant/clip-ViT-B-32-text/resolve/main/model.onnx"
BPE_URL = "https://openaipublic.azureedge.net/clip/bpe_simple_vocab_16e6.txt.gz"

CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)
ARC_SIZE = 112
SCRFD_SIZE = 640
FACE_THRESH = 0.5

COLOR_HSV = {
    "red": ((0, 10), (160, 180)),
    "orange": ((10, 25),),
    "yellow": ((25, 40),),
    "green": ((40, 85),),
    "blue": ((85, 130),),
    "purple": ((130, 160),),
    "white": None,
    "black": None,
}

COUPLE_POS = "a wedding photo of a bride and groom together"
COUPLE_NEG = "a photo of random people, not a wedding couple"


def model_dir():
    path = Path(appsetting.judge_model_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _download(url, dest, timeout=120):
    if dest.is_file() and dest.stat().st_size > 1000:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    log.info("download %s", url)
    req = urllib.request.Request(url, headers={"User-Agent": "photo-upload-judge"})
    with urllib.request.urlopen(req, timeout=timeout) as src, tmp.open("wb") as out:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(dest)
    return dest


def _session(path, threads):
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = 1
    return ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])


def ensure_insightface():
    root = model_dir()
    det = root / "det_500m.onnx"
    rec = root / "w600k_mbf.onnx"
    if det.is_file() and rec.is_file():
        return det, rec
    zpath = root / "buffalo_sc.zip"
    try:
        _download(DET_ZIP, zpath)
        with zipfile.ZipFile(zpath) as zf:
            for name in zf.namelist():
                base = Path(name).name
                if base in ("det_500m.onnx", "w600k_mbf.onnx"):
                    with zf.open(name) as src, (root / base).open("wb") as out:
                        out.write(src.read())
    except Exception as e:
        log.error("insightface download failed: %s", e)
    return det, rec


def ensure_clip():
    root = model_dir()
    vision = root / "clip_vision.onnx"
    text = root / "clip_text.onnx"
    try:
        if not vision.is_file():
            _download(CLIP_VISION, vision, timeout=300)
        if not text.is_file():
            _download(CLIP_TEXT, text, timeout=300)
    except Exception as e:
        log.error("clip download failed: %s", e)
    return vision, text


def load_rgb(path, max_edge=1280):
    img = Image.open(path)
    img.draft("RGB", (max_edge, max_edge))
    img = img.convert("RGB")
    img.thumbnail((max_edge, max_edge), Image.Resampling.BILINEAR)
    return img


class FaceModels:
    def __init__(self, threads):
        det, rec = ensure_insightface()
        self.det = _session(det, threads) if det.is_file() else None
        self.rec = _session(rec, threads) if rec.is_file() else None
        if self.det:
            self.det_in = self.det.get_inputs()[0].name
        if self.rec:
            self.rec_in = self.rec.get_inputs()[0].name

    def _blob(self, img: Image.Image):
        w, h = img.size
        r = min(SCRFD_SIZE / w, SCRFD_SIZE / h)
        nw, nh = max(1, int(w * r)), max(1, int(h * r))
        canvas = np.full((SCRFD_SIZE, SCRFD_SIZE, 3), 127, np.uint8)
        resized = np.asarray(img.resize((nw, nh), Image.Resampling.BILINEAR))
        canvas[:nh, :nw] = resized[:, :, ::-1]
        blob = ((canvas.astype(np.float32) - 127.5) / 128.0).transpose(2, 0, 1)[None]
        return blob, r

    def boxes(self, img: Image.Image):
        if not self.det:
            return []
        blob, r = self._blob(img)
        outs = self.det.run(None, {self.det_in: blob})
        scores, dists = [], []
        strides = (8, 16, 32)
        n_out = len(outs)
        # buffalo: score, bbox per stride (and optional kps)
        groups = 3 if n_out in (6, 9) else max(1, n_out // 2)
        for i, stride in enumerate(strides[:groups]):
            score = outs[i].reshape(-1)
            bbox = outs[i + groups].reshape(-1, 4)
            fmc = SCRFD_SIZE // stride
            anchors = 2
            ys, xs = np.mgrid[:fmc, :fmc]
            centers = np.stack((xs, ys), axis=-1).reshape(-1, 2)
            centers = np.repeat(centers, anchors, axis=0).astype(np.float32)
            centers = (centers + 0.5) * stride
            keep = score >= FACE_THRESH
            if not keep.any():
                continue
            scores.append(score[keep])
            dist = bbox[keep]
            x1 = centers[keep, 0] - dist[:, 0] * stride
            y1 = centers[keep, 1] - dist[:, 1] * stride
            x2 = centers[keep, 0] + dist[:, 2] * stride
            y2 = centers[keep, 1] + dist[:, 3] * stride
            dists.append(np.stack([x1, y1, x2, y2], axis=1) / r)
        if not scores:
            return []
        sc = np.concatenate(scores)
        bb = np.concatenate(dists)
        order = sc.argsort()[::-1][:8]
        boxes = []
        for i in order:
            x1, y1, x2, y2 = bb[i]
            boxes.append(
                (
                    int(max(0, x1)),
                    int(max(0, y1)),
                    int(x2),
                    int(y2),
                )
            )
        return boxes

    def embed(self, img: Image.Image, box):
        if not self.rec:
            return None
        crop = img.crop(box).resize((ARC_SIZE, ARC_SIZE), Image.Resampling.BILINEAR)
        arr = (np.asarray(crop, np.float32) - 127.5) / 127.5
        x = arr.transpose(2, 0, 1)[None]
        vec = self.rec.run(None, {self.rec_in: x})[0][0]
        n = np.linalg.norm(vec) or 1.0
        return vec / n

    def embeddings(self, img: Image.Image):
        boxes = self.boxes(img)
        out = []
        for box in boxes:
            vec = self.embed(img, box)
            if vec is not None:
                out.append(vec)
        return out, boxes


class ClipModels:
    def __init__(self, threads):
        vision, text = ensure_clip()
        self.vision = _session(vision, threads) if vision.is_file() else None
        self.text = _session(text, threads) if text.is_file() else None
        self.tok = None
        if self.vision:
            self.v_in = self.vision.get_inputs()[0].name
        if self.text:
            self.t_in = self.text.get_inputs()[0].name
            try:
                from web.clip_bpe import Tokenizer

                self.tok = Tokenizer()
            except Exception as e:
                log.error("clip tokenizer: %s", e)

    def image_vec(self, img: Image.Image):
        if not self.vision:
            return None
        im = img.copy()
        im.thumbnail((224, 224), Image.Resampling.BICUBIC)
        canvas = Image.new("RGB", (224, 224), (0, 0, 0))
        canvas.paste(im, ((224 - im.width) // 2, (224 - im.height) // 2))
        arr = np.asarray(canvas, np.float32) / 255.0
        arr = (arr - CLIP_MEAN) / CLIP_STD
        x = arr.transpose(2, 0, 1)[None]
        vec = self.vision.run(None, {self.v_in: x})[0][0]
        n = np.linalg.norm(vec) or 1.0
        return vec / n

    def text_vec(self, prompt):
        if not self.text or not self.tok:
            return None
        ids = np.array([self.tok.encode(prompt)], np.int64)
        feeds = {self.t_in: ids}
        # optional attention mask
        for inp in self.text.get_inputs()[1:]:
            if "mask" in inp.name.lower():
                feeds[inp.name] = (ids != 0).astype(np.int64)
        vec = self.text.run(None, feeds)[0][0]
        n = np.linalg.norm(vec) or 1.0
        return vec / n

    def softmax_match(self, img, pos, neg):
        iv = self.image_vec(img)
        pv = self.text_vec(pos)
        nv = self.text_vec(neg)
        if iv is None or pv is None or nv is None:
            return None
        logits = np.array([float(iv @ pv), float(iv @ nv)], np.float32) * 100
        logits -= logits.max()
        ex = np.exp(logits)
        return float(ex[0] / ex.sum())


def hsv_color_score(img: Image.Image, color):
    arr = np.asarray(img.convert("RGB"), np.float32) / 255.0
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    df = mx - mn
    h = np.zeros_like(mx)
    mask = df > 1e-5
    rc = ((g - b) / df) % 6
    gc = (b - r) / df + 2
    bc = (r - g) / df + 4
    h = np.where(mask & (mx == r), rc, h)
    h = np.where(mask & (mx == g), gc, h)
    h = np.where(mask & (mx == b), bc, h)
    hue = (h * 60) % 360
    sat = np.where(mx > 1e-5, df / np.maximum(mx, 1e-5), 0)
    val = mx
    color = (color or "red").lower()
    if color == "white":
        hit = (sat < 0.2) & (val > 0.75)
    elif color == "black":
        hit = val < 0.2
    else:
        bands = COLOR_HSV.get(color) or COLOR_HSV["red"]
        hue180 = hue / 2
        hit = np.zeros(hue.shape, dtype=bool)
        for lo, hi in bands:
            hit |= (hue180 >= lo) & (hue180 < hi)
        hit &= sat > 0.25
        hit &= val > 0.2
    return float(hit.mean())


def cosine_max(a, b):
    if not a or not b:
        return 0.0
    best = 0.0
    for x in a:
        for y in b:
            best = max(best, float(x @ y))
    return best


class Judge:
    def __init__(self, threads):
        self.face = FaceModels(threads)
        self.clip = ClipModels(threads)

    def score(self, task, src_path, dst_path):
        dst = load_rgb(dst_path)
        kind = task["kind"]
        if kind == "person":
            if not src_path or not Path(src_path).is_file():
                return 0.0, "no source"
            src = load_rgb(src_path)
            se, _ = self.face.embeddings(src)
            de, _ = self.face.embeddings(dst)
            s = cosine_max(se, de)
            return s, f"face {s:.2f}"
        if kind == "couple":
            clip_s = self.clip.softmax_match(dst, COUPLE_POS, COUPLE_NEG)
            if clip_s is not None:
                return clip_s, f"clip {clip_s:.2f}"
            _, boxes = self.face.embeddings(dst)
            s = 1.0 if len(boxes) >= 2 else 0.0
            return s, f"faces {len(boxes)}"
        if kind == "color":
            color = task.get("color") or "red"
            pos = f"a photo of a person wearing {color} clothes"
            neg = "a photo of a person not wearing that color of clothes"
            clip_s = self.clip.softmax_match(dst, pos, neg)
            if clip_s is not None:
                return clip_s, f"clip {clip_s:.2f}"
            s = hsv_color_score(dst, color)
            return s, f"hsv {s:.2f}"
        return 0.0, "unknown"


def handle(judge, job):
    pid = job["project_id"]
    sid = job["session_id"]
    did = job["device_id"]
    idx = int(job["idx"])
    photo_id = job["photo_id"]
    task = challenge_store.get_task(pid, sid, did, idx)
    if not task:
        log.info("skip missing task %s/%s/%s", pid, sid, idx)
        return
    if task["status"] != "judging" or task.get("photo_id") != photo_id:
        return
    dst = challenge_store.submission_path(pid, sid, photo_id)
    if not dst.is_file():
        challenge_store.apply_judge(pid, sid, did, idx, 0.0, "no upload", photo_id=photo_id)
        applog.write("game", f"{pid} {sid} idx={idx} no upload")
        return
    src = ""
    if task.get("source_photo_id"):
        src = str(store.photo_path(pid, task["source_photo_id"]))
    t0 = time.monotonic()
    score, detail = judge.score(task, src, dst)
    ms = int((time.monotonic() - t0) * 1000)
    challenge_store.apply_judge(pid, sid, did, idx, score, detail, photo_id=photo_id)
    line = (
        f"{pid} {sid} idx={idx} kind={task['kind']} "
        f"score={score:.2f} {detail} {ms}ms"
    )
    log.info(line)
    applog.write("game", line)


def run():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    threads = appsetting.judge_threads
    log.info("loading judge models threads=%s dir=%s", threads, appsetting.judge_model_dir)
    judge = Judge(threads)
    log.info(
        "face det=%s rec=%s clip vis=%s text=%s",
        bool(judge.face.det),
        bool(judge.face.rec),
        bool(judge.clip.vision),
        bool(judge.clip.text),
    )
    while True:
        try:
            conn = store.r()
            while conn.lmove(challenge_store.JUDGE_BUSY, challenge_store.JUDGE_Q, "RIGHT", "LEFT"):
                pass
            challenge_store.requeue_pending()
            while True:
                raw = conn.blmove(
                    challenge_store.JUDGE_Q,
                    challenge_store.JUDGE_BUSY,
                    5,
                    "RIGHT",
                    "LEFT",
                )
                if raw is None:
                    challenge_store.requeue_pending()
                    continue
                job = json.loads(raw)
                try:
                    handle(judge, job)
                except redis.ConnectionError:
                    raise
                except Exception as e:
                    log.error("job failed %s: %s: %s", raw, type(e).__name__, e)
                    try:
                        challenge_store.apply_judge(
                            job["project_id"],
                            job["session_id"],
                            job["device_id"],
                            int(job["idx"]),
                            0.0,
                            f"error {type(e).__name__}",
                            photo_id=job.get("photo_id"),
                        )
                    except Exception:
                        pass
                conn.lrem(challenge_store.JUDGE_BUSY, 1, raw)
        except redis.ConnectionError as e:
            log.error("redis: %s; retry in 2s", e)
            time.sleep(2)


if __name__ == "__main__":
    run()
