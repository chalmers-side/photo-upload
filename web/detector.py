"""Person check worker (detector container).

Pulls photo jobs from Redis, runs YOLOX-Tiny on CPU, and writes the result
through store.set_person, which grants lottery and Ichiban Kuji chances.
"""
import json
import logging
import time

import numpy as np
import onnxruntime as ort
import redis
from PIL import Image

from config import appsetting
from web import store

INPUT = 416
STRIDES = (8, 16, 32)
PAD = 114

log = logging.getLogger("detector")


def _strides():
    return np.concatenate(
        [np.full(((INPUT // s) ** 2, 1), s, np.float32) for s in STRIDES]
    )


class Detector:
    def __init__(self, model_path, threads):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        self.sess = ort.InferenceSession(
            model_path, opts, providers=["CPUExecutionProvider"]
        )
        self.input = self.sess.get_inputs()[0].name
        self.stride = _strides()

    def person_score(self, img: Image.Image) -> float:
        img = img.convert("RGB")
        w, h = img.size
        r = min(INPUT / w, INPUT / h)
        nw, nh = max(1, int(w * r)), max(1, int(h * r))
        canvas = np.full((INPUT, INPUT, 3), PAD, np.float32)
        canvas[:nh, :nw] = np.asarray(
            img.resize((nw, nh), Image.Resampling.BILINEAR), np.float32
        )
        x = np.ascontiguousarray(canvas[:, :, ::-1].transpose(2, 0, 1)[None])
        out = self.sess.run(None, {self.input: x})[0][0]
        score = out[:, 4] * out[:, 5]
        wh = np.exp(out[:, 2:4]) * self.stride
        area = (wh[:, 0] * wh[:, 1]) / float(nw * nh)
        ok = area >= appsetting.person_min_area
        return float(score[ok].max()) if ok.any() else 0.0


def load(path):
    img = Image.open(path)
    img.draft("RGB", (INPUT * 2, INPUT * 2))
    return img


def handle(det, job):
    pid, photo_id = job["project_id"], job["photo_id"]
    path = store.photo_path(pid, photo_id)
    if not path.is_file():
        log.info("skip %s/%s (file gone)", pid, photo_id)
        return
    t0 = time.monotonic()
    score = det.person_score(load(path))
    ms = int((time.monotonic() - t0) * 1000)
    person = score >= appsetting.person_score
    store.set_person(pid, photo_id, job.get("device_id"), person)
    log.info("%s/%s person=%s score=%.2f %dms", pid, photo_id, person, score, ms)


def run():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    det = Detector(appsetting.detector_model, appsetting.detector_threads)
    log.info("model loaded: %s", appsetting.detector_model)
    while True:
        try:
            conn = store.r()
            while conn.lmove(store.DETECT_BUSY, store.DETECT_Q, "RIGHT", "LEFT"):
                pass
            store.requeue_pending()
            while True:
                raw = conn.blmove(store.DETECT_Q, store.DETECT_BUSY, 5, "RIGHT", "LEFT")
                if raw is None:
                    continue
                job = json.loads(raw)
                try:
                    handle(det, job)
                except redis.ConnectionError:
                    raise
                except Exception as e:
                    log.error("job failed %s: %s: %s", raw, type(e).__name__, e)
                    store.set_person(
                        job["project_id"], job["photo_id"], job.get("device_id"), False
                    )
                conn.lrem(store.DETECT_BUSY, 1, raw)
        except redis.ConnectionError as e:
            log.error("redis: %s; retry in 2s", e)
            time.sleep(2)


if __name__ == "__main__":
    run()
