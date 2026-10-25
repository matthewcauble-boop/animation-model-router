"""continuity: a tough-as-nails continuity checker for cartoon video, across frames AND shots.

    python tools/continuity/continuity.py VIDEO --bible continuity.json [--timeline timeline.json]
           [--fps 5] [--out DIR] [--screen jev|fal|gemini|ollama] [--confirm auto|fal|ollama|none]
           [--fal-model M] [--ollama-model M] [--track auto|color|none] [--max-confirm 60] [--max-cost 1.0]
           [--shots S1,S3]
    python tools/continuity/continuity.py --stills --bible continuity.json      # the keyframe gate

frameqa asks "is this frame broken?". This asks "is this frame still the SAME STORY as the last one?":
who is on screen, how many of them, where, facing which way, whether each character still matches its bible
(e.g. "the berry sidekick has no limbs", "the gloved character never shows fingers"), whether a held gesture is
still held, whether the props are in the state the story says, and whether screen direction survives each cut.

Stages (see README.md):
  1. sample every shot at --fps (4-6) from one decode pass; optional free colour tracker on EVERY frame
  2. screen: a cheap yes/no vision model (TypeSafe Jev by default, ~$0.0002/frame), one call per sample with every
     bible-derived question in that call
  3. temporal analysis per shot: presence runs, pop-ins, disappearances, trait runs, facing flips, gesture breaks,
     prop states, position jumps, screen direction within and across cuts -> candidate events
  4. confirm: every candidate event is re-asked on its key frames, full-res, with the character's reference sheet,
     by Gemini on fal (default) or local qwen3-vl via Ollama (free, slow) -> confirmed / P2 disagreement / dismissed
  5. report.md + report.json + flagged.jpg (contact sheet) + presence.png (lanes) + thumbs/; exit code 1 if any P0

The gate: any confirmed P0 FAILS (exit code 1). The human / LLM reviewer opens only flagged.jpg and the listed frames.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))
import vision  # noqa: E402  (shared Jev + fal + Gemini + Ollama plumbing)

CACHE = Path(os.environ.get("AMR_CACHE_DIR", HERE / "cache")) / "continuity-answers.jsonl"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SEV_ORDER = {"P0": 0, "P1": 1, "P2": 2}
_lock = threading.Lock()


# ------------------------------------------------------------------ small utils
def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def tc(t: float) -> str:
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m)}:{s:05.2f}"


def font(size):
    for f in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def probe(video: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate,nb_frames:format=duration", "-of", "json", str(video)],
                       capture_output=True, text=True, creationflags=NOWIN)
    d = json.loads(r.stdout)
    st = d["streams"][0]
    num, den = st["r_frame_rate"].split("/")
    fps = float(num) / float(den)
    dur = float(d["format"]["duration"])
    return {"w": st["width"], "h": st["height"], "fps": fps, "duration": dur, "frames": int(round(dur * fps))}


def load_cache() -> dict:
    out = {}
    if CACHE.exists():
        for line in CACHE.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                d = json.loads(line)
                out[d["k"]] = d["v"]
            except Exception:
                pass
    return out


def cache_put(cache, k, v):
    with _lock:
        cache[k] = v
        CACHE.parent.mkdir(exist_ok=True)
        with open(CACHE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"k": k, "v": v}) + "\n")


def h12(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


def img_hash(im: Image.Image) -> str:
    return hashlib.sha1(im.convert("L").resize((64, 114)).tobytes()).hexdigest()[:16]


# ------------------------------------------------------------------ bible
def load_bible(path: Path, timeline: Path | None) -> dict:
    b = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    for cid, c in b.get("characters", {}).items():
        c.setdefault("name", cid)
        c["ref_paths"] = [str((base / r).resolve()) for r in c.get("refs", [])]
        c.setdefault("traits", [])
    st = b.get("set", {})
    if st.get("master"):
        st["master_path"] = str((base / st["master"]).resolve())
    for sh in b["shots"]:
        if sh.get("keyframe"):
            sh["keyframe_path"] = str((base / sh["keyframe"]).resolve())
    if timeline:
        tl = json.loads(timeline.read_text(encoding="utf-8"))
        times = {s["id"]: (s["start"], s["end"]) for s in tl.get("shots", [])}
        for s in b["shots"]:
            if s["id"] in times:
                s["start"], s["end"] = times[s["id"]]
    b["shots"] = [s for s in b["shots"] if s.get("check", True)]
    return b


def char_could_be_there(shot, cid):
    return cid in shot.get("present", {}) or cid not in shot.get("absent", [])


def questions_for(bible, shot, t, stills=False):
    """Every yes/no question for one sample. Each q: id, text, kind, who, bad ('yes'|'no'), severity, lo, hi."""
    qs = []
    chars = bible["characters"]
    rel = t - shot["start"]
    for cid, c in chars.items():
        nm, desc = c["name"], c["desc"]
        qs.append({"id": f"vis:{cid}", "kind": "presence", "who": cid,
                   "text": f"Is {nm} ({desc}) visible anywhere in this frame, even small, partly hidden or at the edge?"})
        if not char_could_be_there(shot, cid):
            continue
        qs.append({"id": f"dup:{cid}", "kind": "count", "who": cid, "bad": "yes", "severity": "P0", "lo": 0.6, "hi": 0.9,
                   "text": f"Are there TWO OR MORE copies of {nm} ({desc}) in this frame?"})
        for tr in c["traits"]:
            qs.append({"id": f"trait:{cid}:{tr['id']}", "kind": "trait", "who": cid, "bad": tr.get("bad", "yes"),
                       "severity": tr.get("severity", "P1"), "lo": tr.get("lo", 0.5), "hi": tr.get("hi", 0.85),
                       "text": f"If {nm} ({desc}) is visible: {tr['q']} (If {nm} is not visible, answer no.)",
                       "label": tr.get("label", tr["id"])})
        exp = shot.get("present", {}).get(cid)
        if exp:
            face = exp.get("facing", c.get("facing"))
            if face == "camera":
                qs.append({"id": f"facing:{cid}", "kind": "facing", "who": cid, "bad": "yes",
                           "severity": exp.get("facing_severity", c.get("facing_severity", "P0")), "lo": 0.45, "hi": 0.8,
                           "text": f"Is {nm} ({desc}) turned away so the viewer sees their BACK and their face is "
                                   f"hidden or only partly visible? (If {nm} is not visible, answer no.)"})
            if exp.get("where"):
                qs.append({"id": f"where:{cid}", "kind": "where", "who": cid, "bad": "no", "label": "off the mark",
                           "where": exp["where"],
                           "severity": exp.get("where_severity", "P0"), "lo": 0.5, "hi": 0.85,
                           "text": f"Is {nm} ({desc}) {exp['where']}? (If {nm} is not visible, answer yes.)"})
    for g in shot.get("gestures", []):
        a = g.get("from", 0.0)
        b_ = g.get("to")
        if rel < a or (b_ is not None and rel > b_):
            continue
        nm = chars[g["who"]]["name"]
        qs.append({"id": f"gesture:{g['who']}:{g['id']}", "kind": "gesture", "who": g["who"], "bad": "no",
                   "severity": g.get("severity", "P1"), "lo": g.get("lo", 0.5), "hi": g.get("hi", 0.85),
                   "text": f"Is {nm} {g['q']}?", "label": g["id"]})
    observe = {v.get("required_when", "")[5:] for v in shot.get("present", {}).values()
               if str(v.get("required_when", "")).startswith("prop:")}
    for pid, want in list(shot.get("props", {}).items()) + [(o, None) for o in observe if o not in shot.get("props", {})]:
        if isinstance(want, dict):  # time-ranged state {"at": 3.7, "before": true, "after": false}
            want = want["before"] if rel < want["at"] else want["after"]
        p = bible["props"][pid]
        q = {"id": f"prop:{pid}", "kind": "prop" if want is not None else "observe", "who": pid,
             "bad": "no" if want else "yes", "severity": p.get("severity", "P1"), "lo": p.get("lo", 0.5),
             "hi": p.get("hi", 0.85), "text": p["q"], "label": pid, "want": want}
        qs.append(q)
    if stills:
        st = bible.get("set", {})
        if st.get("master"):
            for chk in st.get("checks", []):
                qs.append({"id": f"set:{chk['id']}", "kind": "set", "who": "set", "bad": chk.get("bad", "no"),
                           "severity": chk.get("severity", "P1"), "lo": chk.get("lo", 0.5), "hi": chk.get("hi", 0.85),
                           "text": chk["q"], "label": chk["id"], "refs": [st["master_path"]]})
    if stills or bible.get("on_model_video"):
        for cid in shot.get("present", {}):
            c = chars[cid]
            if c["ref_paths"]:
                qs.append({"id": f"model:{cid}", "kind": "on_model", "who": cid, "bad": "no",
                           "severity": c.get("on_model_severity", "P1"), "lo": 0.7, "hi": 0.92, "label": "on-model",
                           "text": f"Does {c['name']} in the frame match the reference sheet(s) (same design, colours, "
                                   f"proportions, face and features)? (If {c['name']} is not visible, answer yes.)",
                           "refs": c["ref_paths"][:2]})
    return qs


# ------------------------------------------------------------------ decode + colour tracker
def colour_track(frame_rgb: np.ndarray, spec: dict):
    """Largest blob in an HSV range (OpenCV units). Optional shape filter 'round'. Returns (cx, cy, area, box) in
    0-1 frame units or None."""
    import cv2
    hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV)
    lo, hi = spec["hsv"]
    m = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats(m)
    H, W = m.shape
    best = None
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a / m.size < spec.get("min_area", 0.002):
            continue
        if spec.get("shape") == "round":
            ar = w / max(1, h)
            fill = a / max(1, w * h)
            if not (0.7 <= ar <= 1.45 and fill >= 0.5):
                continue
        if best is None or a > best[2]:
            best = ((x + w / 2) / W, (y + h / 2) / H, a / m.size, (x / W, y / H, (x + w) / W, (y + h) / H), None)
    if best and spec.get("face_hsv"):  # share of face pixels (eye whites, cheeks) inside the silhouette box
        x0, y0, x1, y1 = best[3]
        sub = hsv[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)]
        fm = np.zeros(sub.shape[:2], np.uint8)
        for lo2, hi2 in spec["face_hsv"]:
            fm |= cv2.inRange(sub, np.array(lo2, np.uint8), np.array(hi2, np.uint8))
        best = best[:4] + (float(fm.mean() / 255),)
    return best


def decode_and_sample(video, info, samples, outdir, bible, track_colour):
    """One ffmpeg pass at 540 px wide. Saves sampled frames as JPEG; colour-tracks every frame if asked."""
    W = 540
    H = int(round(info["h"] * W / info["w"] / 2) * 2)
    want = {s["frame"]: s for s in samples}
    cols = {cid: c["color"] for cid, c in bible["characters"].items() if c.get("color")} if track_colour else {}
    track = {cid: {} for cid in cols}
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"scale={W}:{H}", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, creationflags=NOWIN)
    n = W * H * 3
    i = 0
    small = None
    while True:
        buf = p.stdout.read(n)
        if len(buf) < n:
            break
        if i in want or cols:
            fr = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
            if i in want:
                Image.fromarray(fr).save(outdir / f"f{i:05d}.jpg", quality=90)
            if cols:
                for cid, spec in cols.items():
                    track[cid][i] = colour_track(fr, spec)
        i += 1
    p.wait()
    return track


# ------------------------------------------------------------------ vision backends
class Confirmer:
    """Single-frame, single-question re-ask with reference sheets. fal (Gemini) or Ollama (qwen3-vl)."""

    def __init__(self, kind, fal_model, ollama_model):
        self.kind, self.cost, self.calls, self.note = kind, 0.0, 0, ""
        self.fal_model, self.ollama_model = fal_model, ollama_model
        self.fal_key = vision.env_key("FAL_KEY")

    def name(self):
        return {"fal": f"fal:{self.fal_model}", "ollama": f"ollama:{self.ollama_model}"}.get(self.kind, "none")

    def _prompt(self, q, nrefs, crop=False):
        bad = q["bad"]
        k = 3 if crop else 2
        return ("You are a strict continuity checker for a 2D cartoon. Image 1 is a frame from the video"
                + ("; image 2 is a close-up crop of the same frame around the character, so you can see it clearly"
                   if crop else "")
                + (f"; images {k}-{nrefs + k - 1} are the character's official reference sheet(s)" if nrefs else "")
                + f".\nQuestion: {q['text']}\nLook carefully at the whole frame. Answer about what is actually drawn in "
                  "image 1 (stylised cartoon drawing is normal; judge only the question).\n"
                  'Reply JSON only: {"answer": "yes"|"no", "confidence": 0-1, "reason": "<max 20 words, say where>"}'
                + f"  (for this check, '{bad}' means a problem)")

    def ask(self, im: Image.Image, q: dict, refs: list[Image.Image], crop: Image.Image | None = None):
        if self.kind == "none":
            return None
        prompt = self._prompt(q, len(refs), crop is not None)
        if crop is not None:
            refs = [crop] + list(refs)
        if self.kind == "fal":
            urls = ["data:image/jpeg;base64," + base64.b64encode(vision.to_jpeg(x, 1024 if j == 0 else 640)).decode()
                    for j, x in enumerate([im] + refs)]
            body = {"model": self.fal_model, "prompt": prompt, "image_urls": urls, "temperature": 0}
            if getattr(self, "reasoning", False):
                body["reasoning"] = True
            try:
                try:
                    r = vision._post("https://fal.run/openrouter/router/vision", body,
                                     {"Authorization": f"Key {self.fal_key}"}, timeout=180, tries=3)
                except RuntimeError as e:
                    if "Reasoning is mandatory" not in str(e):
                        raise
                    self.reasoning = body["reasoning"] = True
                    r = vision._post("https://fal.run/openrouter/router/vision", body,
                                     {"Authorization": f"Key {self.fal_key}"}, timeout=240, tries=3)
            except RuntimeError as e:
                if "locked" in str(e).lower() or "balance" in str(e).lower() or "403" in str(e):
                    self.note = f"fal unavailable ({str(e)[:90]}); switched to Ollama"
                    log(self.note)
                    self.kind = "ollama"
                    return self.ask(im, q, refs[1:] if crop is not None else refs, crop)
                raise
            self.cost += float((r.get("usage") or {}).get("cost") or 0)
            text = r.get("output", "")
        else:
            imgs = [base64.b64encode(vision.to_jpeg(x, 896 if j == 0 else 512)).decode() for j, x in enumerate([im] + refs)]
            body = {"model": self.ollama_model, "stream": False, "format": "json", "think": False,
                    "options": {"temperature": 0, "num_ctx": 8192},
                    "messages": [{"role": "user", "content": prompt, "images": imgs}]}
            r = vision._post(os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434") + "/api/chat", body, {}, timeout=900, tries=2)
            text = r.get("message", {}).get("content", "")
        self.calls += 1
        try:
            d = json.loads(text[text.index("{"): text.rindex("}") + 1])
        except Exception:
            return {"answer": "?", "confidence": 0, "reason": "unparsed: " + text[:80]}
        a = str(d.get("answer", "")).lower()
        return {"answer": "yes" if a.startswith("y") else "no", "confidence": float(d.get("confidence") or 0.5),
                "reason": str(d.get("reason", ""))[:200]}


def detect_confirm_backend(choice):
    if choice != "auto":
        return choice
    k = vision.env_key("FAL_KEY")
    if k:
        try:  # free probe: queue status of a bogus id answers 403 'locked' when the balance is empty
            vision._post("https://fal.run/openrouter/router/vision", {"model": "google/gemini-3.5-flash-lite",
                         "prompt": "Reply OK", "image_urls": [], "temperature": 0}, {"Authorization": f"Key {k}"},
                         timeout=60, tries=1)
            return "fal"
        except RuntimeError as e:
            log("fal probe:", str(e)[:120])
            if "locked" not in str(e).lower() and "balance" not in str(e).lower():
                return "fal"
    try:
        vision._post(os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434") + "/api/show", {"model": "qwen3-vl:8b"}, {},
                     timeout=10, tries=1)
        return "ollama"
    except Exception:
        return "none"


# ------------------------------------------------------------------ analysis
def runs_of(mask):
    out, start = [], None
    for i, v in enumerate(list(mask) + [False]):
        if v and start is None:
            start = i
        if not v and start is not None:
            out.append((start, i - 1))
            start = None
    return out


def analyse(bible, samples, answers, track, info, args):
    """Build candidate events from per-sample answers + colour tracks."""
    events = []
    chars = bible["characters"]
    by_shot = {}
    for s in samples:
        by_shot.setdefault(s["shot"], []).append(s)
    shots = {sh["id"]: sh for sh in bible["shots"]}

    def p(s, qid):
        a = answers.get(s["frame"], {}).get(qid)
        return None if a is None else a["p"]

    for sid, ss in by_shot.items():
        sh = shots[sid]
        # ---- presence
        for cid, c in chars.items():
            pv = [p(s, f"vis:{cid}") for s in ss]
            if all(v is None for v in pv):
                continue
            pres = [v is not None and v >= args.vis_yes for v in pv]
            absn = [v is not None and v < args.vis_no for v in pv]
            exp = sh.get("present", {}).get(cid)
            if exp and str(exp.get("required_when", "")).startswith("prop:"):
                pq = "prop:" + exp["required_when"][5:]   # only required while that prop is in frame
                absn = [x and (p(s, pq) is None or p(s, pq) >= 0.5) for x, s in zip(absn, ss)]
            if exp:
                for a, b in runs_of(absn):
                    if b - a + 1 < args.min_run:
                        continue
                    if exp.get("required_when"):
                        what_extra = f" while the {exp['required_when'][5:]} is in frame"
                    else:
                        what_extra = ""
                    whole = a == 0 and b == len(ss) - 1
                    if whole:
                        what = f"{c['name']} is missing for the whole shot (the bible says they must be visible: {exp.get('where', 'in frame')})"
                    elif a == 0:
                        what = f"{c['name']} pops in late: absent for the first {ss[b]['t'] - ss[0]['t'] + 1 / args.fps:.2f} s"
                    elif b == len(ss) - 1:
                        what = f"{c['name']} disappears mid-shot and does not come back"
                    else:
                        what = f"{c['name']} disappears mid-shot for {ss[b]['t'] - ss[a]['t'] + 1 / args.fps:.2f} s, then pops back"
                    what += what_extra
                    if (a == 0 and exp.get("enters")) or (b == len(ss) - 1 and exp.get("exits")):
                        continue
                    events.append({"kind": "presence", "who": cid, "shot": sid, "severity": exp.get("severity", "P0"),
                                   "a": a, "b": b, "samples": ss, "qid": f"vis:{cid}", "bad": "no",
                                   "check": "disappear" if not whole else "missing", "what": what})
            elif cid in sh.get("absent", []):
                for a, b in runs_of(pres):
                    if b - a + 1 < args.min_run:
                        continue
                    events.append({"kind": "presence", "who": cid, "shot": sid, "severity": sh.get("absent_severity", "P1"),
                                   "a": a, "b": b, "samples": ss, "qid": f"vis:{cid}", "bad": "yes", "check": "unexpected",
                                   "what": f"{c['name']} appears, but the bible says this shot has no {c['name']}"})
        # ---- per-question bad runs (count, traits, facing, where, gesture, props)
        qids = sorted({q for s in ss for q, v in answers.get(s["frame"], {}).items()
                       if not q.startswith("vis:") and v.get("kind") != "observe"})
        for qid in qids:
            meta = next(answers[s["frame"]][qid] for s in ss if qid in answers.get(s["frame"], {}))
            badp = []
            for s in ss:
                a = answers.get(s["frame"], {}).get(qid)
                if a is None:
                    badp.append(None)
                    continue
                badp.append(a["p"] if meta["bad"] == "yes" else 1 - a["p"])
            # a trait only counts on frames where the character is visible
            who = meta.get("who")
            vis = [p(s, f"vis:{who}") for s in ss] if who in chars and meta["kind"] != "presence" else [1.0] * len(ss)
            cand = [bp is not None and bp >= meta["lo"] and (v is None or v >= args.vis_no) for bp, v in zip(badp, vis)]
            for a, b in runs_of(cand):
                peak = max(badp[a:b + 1])
                n = b - a + 1
                if n < args.min_run and peak < meta["hi"]:
                    continue  # a lone grey-band frame is noise; a lone hard hit is not
                events.append({"kind": meta["kind"], "who": who, "shot": sid, "severity": meta["severity"], "a": a, "b": b,
                               "samples": ss, "qid": qid, "bad": meta["bad"], "peak": round(peak, 3), "hard": peak >= meta["hi"],
                               "check": meta.get("label", meta["kind"]), "what": describe(meta, chars, bible)})
        # ---- colour-track position jumps + in-shot screen direction
        f0, f1 = sh.get("_f") or (int(round(sh["start"] * info["fps"])), int(round(sh["end"] * info["fps"])))
        for cid, tr in track.items():
            pts = [(i, tr.get(i)) for i in range(f0 + 2, f1 - 1)]
            for (i, a), (j, b) in zip(pts, pts[1:]):
                # a pop = a move bigger than --jump of the frame AND bigger than 0.6x the character's own size in one
                # frame (a fast bounce in a close-up moves a lot of frame, but not a body-length per frame)
                if not (a and b):
                    continue
                size = math.sqrt(max(1e-6, (a[3][2] - a[3][0]) * (a[3][3] - a[3][1])))
                mv = math.hypot(a[0] - b[0], (a[1] - b[1]) * info["h"] / info["w"])
                if mv > args.jump and mv > 0.6 * size:
                    s_near = min(range(len(ss)), key=lambda k: abs(ss[k]["frame"] - j))
                    events.append({"kind": "jump", "who": cid, "shot": sid, "severity": "P1", "a": s_near, "b": s_near,
                                   "samples": ss, "qid": None, "check": "position jump", "frame_exact": j,
                                   "what": f"{chars[cid]['name']} jumps {math.hypot(a[0] - b[0], a[1] - b[1]):.2f} of the frame "
                                           f"between two consecutive frames ({tc(i / info['fps'])} -> {tc(j / info['fps'])})"})
        # face visibility by code: a character that should face camera but shows no face pixels = their back is turned
        for cid, tr in track.items():
            spec = chars[cid].get("color", {})
            exp = sh.get("present", {}).get(cid)
            if not (spec.get("face_hsv") and exp and exp.get("facing", chars[cid].get("facing")) == "camera"
                    and exp.get("face_code", True)):
                continue
            fids = list(range(f0 + 2, f1 - 1))
            hidden = [bool(tr.get(i)) and tr[i][4] is not None and tr[i][4] < spec.get("face_min", 0.015) for i in fids]
            for a_, b_ in runs_of(hidden):
                if b_ - a_ + 1 < spec.get("face_frames", 3):
                    continue
                fa, fb = fids[a_], fids[b_]
                ka = min(range(len(ss)), key=lambda k: abs(ss[k]["frame"] - fa))
                kb = min(range(len(ss)), key=lambda k: abs(ss[k]["frame"] - fb))
                events.append({"kind": "facing", "who": cid, "shot": sid, "severity": exp.get("facing_severity", "P0"),
                               "a": ka, "b": kb, "samples": ss, "qid": None, "check": "back to camera (code)",
                               "frame_exact": (fa + fb) // 2, "t0x": fa / info["fps"], "t1x": fb / info["fps"],
                               "what": f"{chars[cid]['name']} shows their back: no eye or cheek pixels inside the silhouette "
                                       f"for {b_ - a_ + 1} frames (min face share {min(tr[i][4] for i in fids[a_:b_ + 1]):.4f})"})
        for rule in bible.get("screen_direction", []):
            L, R = rule["left"], rule["right"]
            if L in track and R in track:
                flips = [i for i in range(f0, f1) if track[L].get(i) and track[R].get(i) and track[L][i][0] > track[R][i][0] + 0.05]
                if len(flips) >= args.min_run * info["fps"] / args.fps:
                    s_near = min(range(len(ss)), key=lambda k: abs(ss[k]["frame"] - flips[0]))
                    events.append({"kind": "direction", "who": L, "shot": sid, "severity": rule.get("severity", "P1"),
                                   "a": s_near, "b": s_near, "samples": ss, "qid": None, "check": "screen direction",
                                   "what": f"{chars[L]['name']} should stay screen-left of {chars[R]['name']}, but is right of them "
                                           f"on {len(flips)} frames"})
    # ---- screen direction across cuts (side of frame per character, from colour track medians)
    side = {}
    for sh in bible["shots"]:
        f0, f1 = sh.get("_f") or (int(round(sh["start"] * info["fps"])), int(round(sh["end"] * info["fps"])))
        for cid, tr in track.items():
            xs = [tr[i][0] for i in range(f0, f1) if tr.get(i)]
            if len(xs) > (0 if args.stills else 6):
                side[(sh["id"], cid)] = float(np.median(xs))
        for cid, want in (sh.get("side") or {}).items():
            x = side.get((sh["id"], cid))
            if x is not None and ((want == "left" and x > 0.55) or (want == "right" and x < 0.45)):
                ss = by_shot.get(sh["id"], [])
                if ss:
                    events.append({"kind": "direction", "who": cid, "shot": sh["id"], "severity": "P1", "a": 0, "b": 0,
                                   "samples": ss, "qid": None, "check": "screen side",
                                   "what": f"{chars[cid]['name']} should be frame-{want} in {sh['id']} (median x {x:.2f})"})
    return events


def describe(meta, chars, bible):
    k, who = meta["kind"], meta.get("who")
    nm = chars[who]["name"] if who in chars else who
    if k == "trait":
        return f"{nm} breaks the bible: {meta.get('label')}"
    if k == "count":
        return f"more than one {nm} on screen"
    if k == "facing":
        return f"{nm} turns away and shows their back (bible: faces camera)"
    if k == "where":
        return f"{nm} leaves their mark (bible: {meta.get('where')})"
    if k == "gesture":
        return f"{nm}'s held gesture breaks: {meta.get('label')}"
    if k == "on_model":
        return f"{nm} does not match the reference sheet"
    if k == "set":
        return f"set check: {meta.get('label')} (vs the master plate)"
    if k == "prop":
        return f"prop state wrong: {meta.get('label')} should be {'on/visible' if meta.get('want') else 'off/not visible'}"
    return k


# ------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path, nargs="?", help="the cut (omit with --stills)")
    ap.add_argument("--stills", action="store_true",
                    help="keyframe gate: check every shot's start frame (bible shots[].keyframe) as one still set")
    ap.add_argument("--bible", type=Path, required=True)
    ap.add_argument("--keyframe", action="append", default=[], metavar="SHOT=PATH",
                    help="stills mode: try a different start frame for a shot (path relative to the bible)")
    ap.add_argument("--timeline", type=Path, help="JSON with shots[{id,start,end}] that overrides the bible's shot times")
    ap.add_argument("--fps", type=float, default=5.0, help="samples per second for the Jev screen (4-6)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--screen", default=os.environ.get("CONTINUITY_SCREEN", "jev"),
                    help="cheap per-sample screen: jev (TypeSafe, default) | fal | gemini | ollama")
    ap.add_argument("--confirm", default="auto", choices=["auto", "fal", "ollama", "none"])
    ap.add_argument("--fal-model", default=os.environ.get("CONTINUITY_FAL_MODEL", "google/gemini-3.5-flash"))
    ap.add_argument("--ollama-model", default=os.environ.get("CONTINUITY_OLLAMA_MODEL", "qwen3-vl:8b"))
    ap.add_argument("--track", default="auto", choices=["auto", "color", "none"])
    ap.add_argument("--max-confirm", type=int, default=60, help="max confirmer calls (Ollama ~20-60 s each)")
    ap.add_argument("--frames-per-event", type=int, default=2)
    ap.add_argument("--max-cost", type=float, default=1.0)
    ap.add_argument("--shots", help="only these shot ids, comma separated")
    ap.add_argument("--min-run", type=int, default=2, help="samples a grey-band problem must persist")
    ap.add_argument("--vis-yes", type=float, default=0.5)
    ap.add_argument("--vis-no", type=float, default=0.35)
    ap.add_argument("--jump", type=float, default=0.12, help="max centroid move between consecutive frames (frame units)")
    ap.add_argument("--edge", type=float, default=0.1, help="seconds skipped at each end of a shot (cut blur)")
    ap.add_argument("--dry-run", action="store_true", help="print the questions per shot and the sample count, call no model")
    args = ap.parse_args(argv)
    t_start = time.time()

    bible = load_bible(args.bible.resolve(), args.timeline.resolve() if args.timeline else None)
    for kv in args.keyframe:
        sid, path = kv.split("=", 1)
        for sh in bible["shots"]:
            if sh["id"] == sid:
                sh["keyframe"], sh["keyframe_path"] = path, str((args.bible.resolve().parent / path).resolve())
    if args.stills:
        args.min_run, args.edge = 1, 0.0
        video = args.bible.resolve()
        info = {"w": 1080, "h": 1920, "fps": 1.0, "duration": float(len(bible["shots"])), "frames": len(bible["shots"])}
    else:
        video = args.video.resolve()
        info = probe(video)
    if args.shots:
        keep = set(args.shots.split(","))
        bible["shots"] = [s for s in bible["shots"] if s["id"] in keep]
    out = (args.out or video.parent / (f"continuity-stills-{bible.get('name', 'set')}" if args.stills
                                       else f"continuity-{video.stem}")).resolve()
    for d in ("frames", "thumbs", "confirm"):
        (out / d).mkdir(parents=True, exist_ok=True)
    status_f = out / "STATUS.json"

    def status(stage, **kw):
        status_f.write_text(json.dumps({"stage": stage, "t": time.strftime("%H:%M:%S"), **kw}, indent=1))

    # 1. samples
    samples = []
    if args.stills:  # one sample per shot: its start frame; each still is its own 1-frame "shot" at t = shot start
        track = {cid: {} for cid, c in bible["characters"].items() if c.get("color")} if args.track != "none" else {}
        for i, sh in enumerate(bible["shots"]):
            if not sh.get("keyframe_path") or not Path(sh["keyframe_path"]).exists():
                log("no keyframe for", sh["id"])
                continue
            im = Image.open(sh["keyframe_path"]).convert("RGB")
            info["w"], info["h"] = im.size
            im = im.resize((540, int(540 * im.height / im.width)))
            im.save(out / "frames" / f"f{i:05d}.jpg", quality=90)
            im.save(out / "confirm" / f"c{i:05d}.jpg", quality=92)
            Image.open(sh["keyframe_path"]).convert("RGB").save(out / "confirm" / f"c{i:05d}.jpg", quality=92)
            samples.append({"t": sh["start"], "frame": i, "shot": sh["id"]})
            for cid in track:
                track[cid][i] = colour_track(np.ascontiguousarray(np.asarray(im)[::2, ::2]), bible["characters"][cid]["color"])
            sh["_f"] = (i, i + 1)
    for sh in bible["shots"] if not args.stills else []:
        t = sh["start"] + args.edge
        while t <= sh["end"] - args.edge + 1e-6:
            fr = min(info["frames"] - 1, int(round(t * info["fps"])))
            samples.append({"t": round(fr / info["fps"], 3), "frame": fr, "shot": sh["id"]})
            t += 1.0 / args.fps
    status("decode", samples=len(samples))
    log(f"{len(samples)} samples over {len(bible['shots'])} shots; decoding")
    if not args.stills:
        do_colour = args.track in ("auto", "color") and any(c.get("color") for c in bible["characters"].values())
        track = decode_and_sample(video, info, samples, out / "frames", bible, do_colour)

    if args.dry_run:
        shots_ = {s["id"]: s for s in bible["shots"]}
        seen = set()
        for smp in samples:
            if smp["shot"] in seen:
                continue
            seen.add(smp["shot"])
            qs = questions_for(bible, shots_[smp["shot"]], smp["t"], args.stills)
            print(f"--- {smp['shot']} @ {smp['t']:.2f}s: {len(qs)} questions")
            for q in qs:
                print(f"  [{q.get('severity', '-')}] {q['id']}: {q['text']}")
        print(json.dumps({"dry_run": True, "samples": len(samples), "shots": len(bible["shots"])}))
        return 0

    # 2. Jev screen
    cache = load_cache()
    jev = vision.make(args.screen)
    shots = {s["id"]: s for s in bible["shots"]}
    answers, cost = {}, {"jev": 0.0}
    calls = {"jev": 0, "jev_cached": 0, "screen_name": f"{jev.name}:{getattr(jev, 'model', '')}"}

    def screen(s):
        im = Image.open(out / "frames" / f"f{s['frame']:05d}.jpg")
        qs = questions_for(bible, shots[s["shot"]], s["t"], args.stills)
        hsh = img_hash(im)
        res, todo = {}, []
        for q in qs:
            k = f"{calls['screen_name']}|{hsh}|{h12(q['text'] + '|'.join(q.get('refs', [])))}"
            if k in cache:
                res[q["id"]] = dict(q, p=cache[k])
            else:
                todo.append((q, k))
        groups = {}
        for q, k in todo:  # one Jev call per reference-image group (most questions have none)
            groups.setdefault(tuple(q.get("refs", [])), []).append((q, k))
        for refs, items in groups.items():
            rims = [Image.open(r) for r in refs]
            a, c, _ = jev.ask([im], [{"id": q["id"], "text": q["text"] + (" Compare with the reference image(s)." if refs else ""),
                                      "needs_refs": bool(refs)} for q, _ in items], rims or None)
            with _lock:
                cost["jev"] += c
                calls["jev"] += 1
            for q, k in items:
                pv = a[0].get(q["id"], {}).get("p")
                if pv is None:
                    continue
                cache_put(cache, k, pv)
                res[q["id"]] = dict(q, p=pv)
        if not todo:
            with _lock:
                calls["jev_cached"] += 1
        answers[s["frame"]] = res

    status("screen", samples=len(samples))
    log("Jev screen")
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(screen, samples))

    # 3-4. analysis
    events = analyse(bible, samples, answers, track, info, args)
    log(f"{len(events)} candidate events")

    # 5. confirm
    backend = detect_confirm_backend(args.confirm)
    conf = Confirmer(backend, args.fal_model, args.ollama_model)
    log("confirmer:", conf.name())
    refs_cache = {}

    def refs_for(who, q=None):
        if q and q.get("refs"):
            return [Image.open(r) for r in q["refs"]]
        if who not in bible["characters"]:
            return []
        if who not in refs_cache:
            refs_cache[who] = [Image.open(r) for r in bible["characters"][who]["ref_paths"][:2] if Path(r).exists()]
        return refs_cache[who]

    def fullres(frame):
        p = out / "confirm" / f"c{frame:05d}.jpg"
        if not p.exists() and not args.stills:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{frame / info['fps']:.4f}", "-i", str(video), "-frames:v", "1",
                            "-q:v", "2", str(p)], creationflags=NOWIN)
        return Image.open(p)

    budget = args.max_confirm
    events.sort(key=lambda e: (SEV_ORDER[e["severity"]], e["shot"]))
    for n_ev, e in enumerate(events):
        ss = e["samples"]
        e["t0"], e["t1"] = e.get("t0x", ss[e["a"]]["t"]), e.get("t1x", ss[e["b"]]["t"])
        idx = sorted({e["a"], (e["a"] + e["b"]) // 2, e["b"]})
        if e.get("qid") and e["kind"] not in ("presence",):
            idx.sort(key=lambda k: -(answers[ss[k]["frame"]].get(e["qid"], {}).get("p", 0) if e["bad"] == "yes"
                                     else 1 - answers[ss[k]["frame"]].get(e["qid"], {}).get("p", 1)))
        e["key_frames"] = [ss[k]["frame"] for k in idx][: args.frames_per_event]
        if e.get("frame_exact") is not None:
            e["key_frames"] = [e["frame_exact"]]
        e["confirm"] = []
        if e.get("qid") is None or conf.kind == "none" or budget <= 0:
            e["verdict"] = "unconfirmed" if e.get("qid") else "code"
            continue
        q = dict(next(a for a in (answers[f].get(e["qid"]) for f in [ss[k]["frame"] for k in range(e["a"], e["b"] + 1)]) if a),
                 bad=e["bad"])
        if e["kind"] == "facing":  # positive phrasing confirms far better than "are they turned away"
            nm = bible["characters"][e["who"]]["name"]
            q["text"] = (f"Look at {nm} ({bible['characters'][e['who']]['desc']}). Can you see their FACE (eyes and "
                         f"mouth) in this frame? Answer no if they are turned so we see their back.")
            q["bad"] = "no"
            e["bad"] = "no"
        for fr in e["key_frames"]:
            if budget <= 0 or conf.cost + cost["jev"] > args.max_cost:
                break
            im = fullres(fr)
            crop = None
            box = track.get(e.get("who"), {}).get(fr) if not args.stills else None
            if box:  # zoom the confirmer in on the character (small characters in wides get misjudged)
                x0, y0, x1, y1 = box[3]
                cx, cy, hw = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, (y1 - y0) * info["h"] / info["w"]) * 1.4
                W_, H_ = im.size
                crop = im.crop((int(max(0, (cx - hw) * W_)), int(max(0, cy * H_ - hw * W_)),
                                int(min(W_, (cx + hw) * W_)), int(min(H_, cy * H_ + hw * W_))))
                if min(crop.size) < 40:
                    crop = None
            k = f"conf|{conf.name()}|{img_hash(im)}|{h12(q['text'])}|{'crop' if crop else ''}"
            r = cache.get(k)
            if r is None:
                status("confirm", event=n_ev + 1, of=len(events), backend=conf.name())
                try:
                    r = conf.ask(im, q, refs_for(e["who"], q), crop)
                except Exception as ex:
                    r = {"answer": "?", "confidence": 0, "reason": f"error {str(ex)[:100]}"}
                if r and r["answer"] != "?":
                    cache_put(cache, k, r)
                budget -= 1
            if r:
                e["confirm"].append(dict(r, frame=fr))
        bad = [c for c in e["confirm"] if c["answer"] == e["bad"]]
        if not e["confirm"] or all(c["answer"] == "?" for c in e["confirm"]):
            e["verdict"] = "unconfirmed"
        elif bad:
            e["verdict"] = "confirmed"
        elif e.get("hard") or e["kind"] == "presence" and e["check"] == "missing":
            e["verdict"] = "disputed"
            e["severity"] = "P2" if e["kind"] != "presence" else e["severity"]
        else:
            e["verdict"] = "dismissed"
        log(f"event {n_ev + 1}/{len(events)} {e['shot']} {e['check']} -> {e['verdict']}")

    findings = [e for e in events if e["verdict"] != "dismissed"]
    # an unconfirmed grey-band hit (no confirmer ran) keeps its severity but is marked for the reviewer's eyes
    findings.sort(key=lambda e: (SEV_ORDER[e["severity"]], e["t0"]))
    report(out, video, info, bible, samples, answers, track, findings, [e for e in events if e["verdict"] == "dismissed"],
           cost, conf, calls, time.time() - t_start, args)
    p0 = sum(1 for f in findings if f["severity"] == "P0")
    summ = {"gate": "FAIL" if p0 else "PASS", "P0": p0, "P1": sum(1 for f in findings if f["severity"] == "P1"),
            "P2": sum(1 for f in findings if f["severity"] == "P2"), "samples": len(samples),
            "cost_usd": round(cost["jev"] + conf.cost, 4), "confirmer": conf.name(), "seconds": round(time.time() - t_start, 1),
            "report": str(out / "report.md")}
    status("done", **summ)
    print(json.dumps(summ))
    return 1 if p0 else 0


# ------------------------------------------------------------------ report
def thumb(out, fr, label, sev, box=None, w=300):
    src = out / "confirm" / f"c{fr:05d}.jpg"
    if not src.exists():
        src = out / "frames" / f"f{fr:05d}.jpg"
    if not src.exists():
        return None
    im = Image.open(src).convert("RGB")
    im = im.resize((w, int(im.height * w / im.width)))
    d = ImageDraw.Draw(im)
    col = {"P0": (230, 40, 40), "P1": (255, 160, 0), "P2": (90, 170, 255)}[sev]
    if box:
        d.rectangle([box[0] * im.width, box[1] * im.height, box[2] * im.width, box[3] * im.height], outline=col, width=3)
    d.rectangle([0, 0, im.width, 40], fill=(0, 0, 0))
    d.text((5, 3), label[:44], fill=col, font=font(15))
    d.rectangle([0, 0, im.width - 1, im.height - 1], outline=col, width=4)
    p = out / "thumbs" / f"{sev}_{fr:05d}_{h12(label)}.jpg"
    im.save(p, quality=85)
    return p


def presence_png(out, bible, samples, answers, info):
    chars = list(bible["characters"])
    dur = max(s["t"] for s in samples) + 0.5
    W, lane, top = 1400, 26, 30
    im = Image.new("RGB", (W, top + lane * len(chars) + 30), (24, 24, 32))
    d = ImageDraw.Draw(im)
    f = font(13)
    x0 = 110
    sx = (W - x0 - 10) / dur
    for sh in bible["shots"]:
        d.line([x0 + sh["start"] * sx, 0, x0 + sh["start"] * sx, im.height], fill=(80, 80, 100))
        d.text((x0 + sh["start"] * sx + 3, 4), sh["id"], fill=(200, 200, 220), font=f)
    shots = {s["id"]: s for s in bible["shots"]}
    for li, cid in enumerate(chars):
        y = top + li * lane
        d.text((6, y + 5), bible["characters"][cid]["name"], fill=(230, 230, 230), font=f)
        for s in samples:
            pv = answers.get(s["frame"], {}).get(f"vis:{cid}", {}).get("p")
            if pv is None:
                continue
            sh = shots[s["shot"]]
            exp = cid in sh.get("present", {})
            nexp = cid in sh.get("absent", [])
            if pv >= 0.5:
                col = (60, 200, 90) if not nexp else (255, 160, 0)
            else:
                col = (230, 40, 40) if exp else (70, 70, 80)
            x = x0 + s["t"] * sx
            d.rectangle([x - sx / 10, y + 4, x + sx / 10 + 1, y + lane - 4], fill=col)
    d.text((x0, im.height - 22), "green = visible, red = MISSING where the bible needs them, orange = visible where they "
           "should not be, grey = absent (fine)", fill=(180, 180, 190), font=f)
    p = out / "presence.png"
    im.save(p)
    return p


def report(out, video, info, bible, samples, answers, track, findings, dismissed, cost, conf, calls, secs, args):
    thumbs = []
    for i, e in enumerate(findings):
        e["id"] = f"C{i + 1:02d}"
        box = None
        tr = track.get(e["who"]) if e.get("who") in track else None
        fr = e["key_frames"][0] if e.get("key_frames") else e["samples"][e["a"]]["frame"]
        if tr and tr.get(fr):
            box = tr[fr][3]
        p = thumb(out, fr, f"{e['id']} {e['severity']} {tc(e['t0'])} {e['shot']} {e['check']}", e["severity"], box)
        e["thumb"] = str(p.relative_to(out)).replace("\\", "/") if p else ""
        if p:
            thumbs.append(p)
    if thumbs:
        cols = 5
        tw, th = Image.open(thumbs[0]).size
        sheet = Image.new("RGB", (cols * tw, ((len(thumbs) + cols - 1) // cols) * th), (0, 0, 0))
        for i, p in enumerate(thumbs):
            sheet.paste(Image.open(p).resize((tw, th)), ((i % cols) * tw, (i // cols) * th))
        sheet.save(out / "flagged.jpg", quality=82)
    elif (out / "flagged.jpg").exists():
        (out / "flagged.jpg").unlink()
    presence_png(out, bible, samples, answers, info)
    p0 = sum(1 for f in findings if f["severity"] == "P0")
    L = [f"# Continuity report: {video.name}", "",
         f"**Gate: {'FAIL' if p0 else 'PASS'}** ({p0} P0, {sum(1 for f in findings if f['severity'] == 'P1')} P1, "
         f"{sum(1 for f in findings if f['severity'] == 'P2')} P2). Any confirmed P0 fails the gate.", "",
         f"- Bible: `{args.bible}`" + (f", shot times from `{args.timeline}`" if args.timeline else ""),
         f"- {len(samples)} samples at {args.fps:g} fps over {len(bible['shots'])} shots; "
         f"screen = {calls['screen_name']} ({calls['jev']} calls, {calls['jev_cached']} cached); confirmer = {conf.name()} "
         f"({conf.calls} calls){'; ' + conf.note if conf.note else ''}",
         f"- Colour tracker: {', '.join(track) if track else 'off'}",
         f"- Cost ${cost['jev'] + conf.cost:.4f}; {secs:.0f} s",
         "- Files: `flagged.jpg` (contact sheet), `presence.png` (who is on screen when), `thumbs/`, `report.json`", "",
         "Verdicts: **confirmed** = the confirmer agreed on a full-res frame with the reference sheet; **disputed** = "
         "Jev was sure, the confirmer was not (kept, look at it); **unconfirmed** = no confirmer ran (look at it); "
         "**code** = measured, no model.", "",
         "| ID | Time | Shot | Sev | Check | Finding | Screen | Verdict | Confirmer says |",
         "|---|---|---|---|---|---|---|---|---|"]
    for e in findings:
        cs = "; ".join(f"{c['answer']} ({c['confidence']:.2f}) {c['reason']}" for c in e.get("confirm", []))[:220]
        L.append(f"| {e['id']} | {tc(e['t0'])}-{tc(e['t1'])} | {e['shot']} | **{e['severity']}** | {e['check']} | "
                 f"{e['what']} | {e.get('peak', '')} | {e['verdict']} | {cs.replace('|', '/')} |")
    if not findings:
        L.append("| - | - | - | - | - | no continuity problems found | - | - | - |")
    if dismissed:
        L += ["", f"## Dismissed by the confirmer ({len(dismissed)})", ""]
        for e in dismissed:
            cs = "; ".join(f"{c['answer']} {c['reason']}" for c in e.get("confirm", []))[:160]
            L.append(f"- {tc(e['t0'])}-{tc(e['t1'])} {e['shot']} {e['check']}: {e['what']} (Jev {e.get('peak', '')}; {cs})")
    L += ["", "## Per-shot bible", ""]
    for sh in bible["shots"]:
        pres = ", ".join(f"{bible['characters'][c]['name']} ({v.get('where', 'visible')})" for c, v in sh.get("present", {}).items())
        L.append(f"- **{sh['id']}** {tc(sh['start'])}-{tc(sh['end'])}: present {pres or 'nobody'}; absent "
                 f"{', '.join(sh.get('absent', [])) or '-'}; gestures {', '.join(g['id'] for g in sh.get('gestures', [])) or '-'}; "
                 f"props {', '.join(f'{k}={v}' for k, v in sh.get('props', {}).items()) or '-'}")
    (out / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    js = {"video": str(video), "info": info, "findings": [{k: v for k, v in e.items() if k != "samples"} for e in findings],
          "dismissed": [{k: v for k, v in e.items() if k != "samples"} for e in dismissed],
          "samples": [dict(s, answers={k: v["p"] for k, v in answers.get(s["frame"], {}).items()}) for s in samples],
          "cost_usd": cost["jev"] + conf.cost, "confirmer": conf.name()}
    (out / "report.json").write_text(json.dumps(js, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
