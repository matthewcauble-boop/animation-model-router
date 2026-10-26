"""judge: a fast, cheap yes/no judge for animation frames, tuned to your own approve/reject calls.

The pattern (see ../../LESSONS.md, "A fast judge model"):
  1. a question bank of ATOMIC, observable questions (questions/*.json, the only place wording lives);
  2. code turns the answers into verdicts (truth tables, box ratios and overlaps, or a small logistic layer
     fitted to your labels in model.json);
  3. thresholds: pass >= 0.7, fail <= 0.3, and the band in between is "unsure", which can be escalated to a
     bigger vision model.
The judge model makes observations ("box the legs", "how far apart are the hands?"). Code makes decisions.

  python tools/judge/judge.py judge IMG|VIDEO|DIR --pack onmodel --ref sheet=refs/mascot.png [--label "wide grip"]
         [--every 1.0] [--backend jev|fal|openai|ollama] [--escalate fal|openai|ollama] [--out res.json] [--dry-run]
  python tools/judge/judge.py eval  --evalset evalset/ [--split test|train|all] [--groups pose,proportion] [-v]
  python tools/judge/judge.py fit   --evalset evalset/            # logistic layer per verdict -> model.json
  python tools/judge/judge.py label IMG verdict:on_model false --evalset evalset/ --note "too-long legs"
  python tools/judge/judge.py questions [--pack onmodel]

Files (all next to this script unless overridden): --questions DIR (default questions/), --packs FILE (default
packs.example.json), --model FILE (default model.json). Refs are passed by name with --ref name=path; a question
that names `name` in backticks gets that image in its request, and only then.

Backends
  jev     TypeSafe Jev (System One): Noul / Choice / Score / Box with calibrated probabilities. Key
          TYPESAFE_API_KEY. Images need the header `TypeSafe-Danger-Zone-Images: true`; Box needs jev-1.14+.
  fal     any vision model behind fal's openrouter/router/vision (FAL_KEY), JSON answers.
  openai  any OpenAI-compatible chat endpoint with vision: JUDGE_OPENAI_BASE (e.g. https://api.openai.com/v1,
          or a local server), JUDGE_OPENAI_KEY, --model.
  ollama  local Ollama vision model (free, slow).
Every backend returns answers in the same shape, so verdicts, eval and fit do not care which one ran.

Spend: every paid call is added to a CSV ledger (AMR_LEDGER, default ./spend-ledger.csv) and --max-cost stops a run.
An HTTP 401/402/403 (key revoked, balance empty, account locked) STOPS the run with a message; it is never read as a
"no" and never silently falls back to another backend.
No third-party deps beyond Pillow and numpy (fit). ffmpeg on PATH for video input.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures as cf
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps

HERE = Path(__file__).resolve().parent
YES, NO = 0.7, 0.3
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
JEV_PRICE_PER_TOK = 0.042 / 1e6
CONTEXT = os.environ.get("JUDGE_CONTEXT", "A still frame from a cartoon video.")


class Stop(SystemExit):
    """Raised on auth / balance / lock errors: the run must stop and say why, not guess."""


# ---------------------------------------------------------------- keys + http
def env_key(name):
    v = os.environ.get(name)
    if v:
        return v.strip()
    env = Path(os.environ.get("AMR_ENV_FILE", ".env"))
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"') or None
    return None


def post(url, body, headers, timeout=180, tries=4):
    data = json.dumps(body).encode()
    last = None
    for i in range(tries):
        req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:300]
            if e.code in (401, 402, 403):
                raise Stop(f"STOP: {url.split('/')[2]} answered HTTP {e.code} (key, balance or account lock): {msg}")
            last = f"HTTP {e.code}: {msg}"
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 * (i + 1)); continue
            raise RuntimeError(last)
        except (urllib.error.URLError, TimeoutError) as e:
            last = str(e); time.sleep(2 * (i + 1))
    raise RuntimeError(f"request failed after {tries} tries: {last}")


def ledger(usd, units, note, provider, model):
    if usd <= 0:
        return
    p = Path(os.environ.get("AMR_LEDGER", "spend-ledger.csv"))
    new = not p.exists()
    with p.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        if new:
            w.writerow(["date", "tool", "provider", "model", "units", "usd", "note"])
        w.writerow([dt.date.today().isoformat(), "judge", provider, model, units, f"{usd:.5f}", note])


# ---------------------------------------------------------------- bank + packs
def load_bank(qdir):
    bank = {}
    for f in sorted(Path(qdir).glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for qid, q in d["questions"].items():
            bank[qid] = dict(q, group=d["group"])
    return bank


def load_packs(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return d["packs"], d.get("verdicts", {}), d.get("label_map", {})


def fields(q):
    """State fields a question names in backticks (`frame`, `previous_frame`, `<ref name>`, `on_screen_label`)."""
    s = json.dumps({k: q.get(k) for k in ("instructions", "criteria")})
    return set(re.findall(r"`([a-z0-9_]+)`", s)) | set(q.get("needs") or [])


def pack_ids(pack, packs, bank):
    p = packs[pack]
    ids = [k for k, q in bank.items() if q["group"] in p.get("groups", [])]
    ids += [i for i in p.get("ids", []) if i not in ids and i in bank]
    for i in list(ids):  # companions (the null case: "is the character there at all?") ride along
        c = bank[i].get("companion")
        if c and c not in ids:
            ids.append(c)
    return ids, p.get("verdicts", [])


# ---------------------------------------------------------------- images
def prep(img, max_side=1024):
    """Upright JPEG, longest side <= max_side, every side within 280..1568 px (Jev's limits; harmless elsewhere)."""
    im = img if isinstance(img, Image.Image) else Image.open(img)
    im = ImageOps.exif_transpose(im).convert("RGB")
    s = min(1.0, min(max_side, 1568) / max(im.size))
    if s < 1:
        im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
    if min(im.size) < 280:
        s = 280 / min(im.size)
        if max(im.size) * s <= 1568:
            im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        else:
            c = Image.new("RGB", (max(280, im.width), max(280, im.height)), "white"); c.paste(im, (0, 0)); im = c
    b = io.BytesIO(); im.save(b, "JPEG", quality=88)
    return b.getvalue()


# ---------------------------------------------------------------- backends
class Jev:
    provider = "TypeSafe"

    def __init__(self, model=None):
        self.model = model or os.environ.get("JUDGE_JEV_MODEL", "jev-latest")
        self.url = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai") + "/v1/systemone"

    def ask(self, imgs, questions, text_state):
        key = env_key("TYPESAFE_API_KEY")
        if not key:
            raise Stop("STOP: TYPESAFE_API_KEY not set")
        assets, state = {}, {"context": CONTEXT, **text_state}
        for name, jpg in imgs.items():
            ref = "img-" + hashlib.sha1(jpg).hexdigest()[:16]
            assets[ref] = {"type": "image", "format": "jpg", "data_base64": base64.b64encode(jpg).decode()}
            state[name] = ref
        qs = {qid: {k: v for k, v in q.items() if k in ("type", "instructions", "criteria")} for qid, q in questions.items()}
        d = post(self.url, {"model": self.model, "state": state, "questions": qs, "assets": assets},
                 {"Authorization": f"Bearer {key}", "TypeSafe-Danger-Zone-Images": "true"})
        toks = int((d.get("usage") or {}).get("input_tokens", 0))
        return d.get("answers", {}), toks * JEV_PRICE_PER_TOK


def llm_prompt(questions, image_names, text_state):
    lines = ["You are a strict visual checker for frames from a cartoon video.",
             f"Images are attached in this order: {', '.join(image_names)}.",
             *(f"{k} = {json.dumps(v)}" for k, v in text_state.items()),
             "Answer every question about what is visible. Questions:"]
    fmt = {}
    for qid, q in questions.items():
        t, c = q["type"], q.get("criteria")
        lines.append(f"- {qid} ({t}): {q['instructions']}")
        if t == "noul":
            if isinstance(c, dict):
                lines.append(f"    yes means: {c.get('true', '')} / no means: {c.get('false', '')}")
            fmt[qid] = '{"p": <probability the answer is yes, 0-1>}'
        elif t == "choice":
            for opt, desc in (c or {}).items():
                lines.append(f"    {opt}: {desc}")
            fmt[qid] = '{"probs": {"<option>": <0-1>, ...}}'
        elif t == "score":
            for i, desc in enumerate(c or []):
                lines.append(f"    {i}: {desc}")
            fmt[qid] = '{"score": <level number>}'
        elif t == "box":
            fmt[qid] = '{"box": {"left": 0-1, "top": 0-1, "right": 0-1, "bottom": 0-1}} (fractions of the image size)'
    lines.append("Reply with JSON only, one key per question id: " + json.dumps(fmt))
    return "\n".join(lines)


def llm_parse(text, questions):
    i, j = (text or "").find("{"), (text or "").rfind("}")
    try:
        d = json.loads(text[i:j + 1])
    except Exception:  # noqa: BLE001 - an unparsable reply answers nothing; never a "no"
        return {}
    out = {}
    for qid, q in questions.items():
        a = d.get(qid)
        if not isinstance(a, dict):
            continue
        t = q["type"]
        try:
            if t == "noul":
                out[qid] = {"type": "noul", "noul": float(a["p"])}
            elif t == "choice":
                pr = {k: float(v) for k, v in a["probs"].items()}
                s = sum(pr.values()) or 1
                pr = {k: v / s for k, v in pr.items()}
                out[qid] = {"type": "choice", "choice": max(pr, key=pr.get), "probabilities": pr}
            elif t == "score":
                n = len(q.get("criteria") or [0, 1, 2]); sc = int(a["score"])
                out[qid] = {"type": "score", "score": sc, "probabilities": {str(k): float(k == sc) for k in range(n)}}
            elif t == "box":
                out[qid] = {"type": "box", "box": {k: float(a["box"][k]) for k in ("left", "top", "right", "bottom")}}
        except (KeyError, TypeError, ValueError):
            pass
    return out


class LLM:
    """fal openrouter/router/vision, an OpenAI-compatible endpoint, or Ollama, all asked for JSON answers."""

    def __init__(self, kind, model=None):
        self.kind = kind
        self.model = model or {"fal": "google/gemini-3.5-flash-lite", "openai": "gpt-4.1-mini", "ollama": "qwen3-vl:8b"}[kind]
        self.provider = {"fal": "fal", "openai": "openai-compatible", "ollama": "ollama"}[kind]

    def ask(self, imgs, questions, text_state):
        prompt = llm_prompt(questions, list(imgs), text_state)
        b64 = [base64.b64encode(j).decode() for j in imgs.values()]
        if self.kind == "fal":
            key = env_key("FAL_KEY")
            if not key:
                raise Stop("STOP: FAL_KEY not set")
            body = {"model": self.model, "prompt": prompt, "image_urls": ["data:image/jpeg;base64," + b for b in b64], "temperature": 0}
            try:
                r = post("https://fal.run/openrouter/router/vision", body, {"Authorization": f"Key {key}"})
            except RuntimeError as e:
                if "easoning" not in str(e):
                    raise
                r = post("https://fal.run/openrouter/router/vision", dict(body, reasoning=True), {"Authorization": f"Key {key}"})
            return llm_parse(r.get("output", ""), questions), float((r.get("usage") or {}).get("cost") or 0)
        if self.kind == "openai":
            base, key = os.environ.get("JUDGE_OPENAI_BASE", "https://api.openai.com/v1"), env_key("JUDGE_OPENAI_KEY") or ""
            content = [{"type": "text", "text": prompt}] + [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b}} for b in b64]
            r = post(base.rstrip("/") + "/chat/completions", {"model": self.model, "temperature": 0,
                                                              "messages": [{"role": "user", "content": content}]},
                     {"Authorization": f"Bearer {key}"} if key else {})
            txt = r["choices"][0]["message"]["content"]
            return llm_parse(txt, questions), 0.0  # cost unknown for a generic endpoint: log it from the provider's bill
        host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        r = post(host + "/api/chat", {"model": self.model, "stream": False, "format": "json", "think": False, "options": {"temperature": 0},
                                      "messages": [{"role": "user", "content": prompt, "images": b64}]}, {}, timeout=600)
        return llm_parse(r.get("message", {}).get("content", ""), questions), 0.0


def make_backend(name, model=None):
    return Jev(model) if name == "jev" else LLM(name, model)


# ---------------------------------------------------------------- asking (cached)
class Judge:
    def __init__(self, a):
        self.bank = load_bank(a.questions)
        self.packs, self.vdefs, self.label_map = load_packs(a.packs)
        self.refs = dict(r.split("=", 1) for r in (a.ref or []))
        self.backend = make_backend(a.backend, a.model)
        self.bname = a.backend
        self.max_side, self.max_cost, self.dry = a.max_side, a.max_cost, a.dry_run
        self.cache = Path(os.environ.get("AMR_CACHE_DIR", HERE / "cache")) / "judge"
        self.spent, self.requests = 0.0, 0
        mf = Path(a.model_file)
        self.model = json.loads(mf.read_text(encoding="utf-8")) if mf.exists() else {}

    def ask_frame(self, frame, ids, prev=None, label=None, backend=None):
        """One request per set of images a question needs, so a frame-only Box never shares a request with a
        reference sheet (extra images measurably pulled box answers onto the other image)."""
        have = {"frame", "context"} | ({"previous_frame"} if prev else set()) | ({"on_screen_label"} if label else set()) | set(self.refs)
        groups = {}
        for i in ids:
            q = self.bank[i]
            if fields(q) <= have:
                extra = tuple(sorted(f for f in fields(q) if f in self.refs or f == "previous_frame"))
                groups.setdefault(extra, {})[i] = q
        answers = {}
        for extra, qs in groups.items():
            imgs = {"frame": prep(frame, self.max_side)}
            for f in extra:
                imgs[f] = prep(prev if f == "previous_frame" else self.refs[f], 768 if f != "previous_frame" else self.max_side)
            ts = {"on_screen_label": label} if label and any("on_screen_label" in fields(q) for q in qs.values()) else {}
            be = backend or self.backend
            key = hashlib.sha1(json.dumps([be.__class__.__name__, getattr(be, "model", ""), sorted(qs.items()), ts,
                                           [hashlib.sha1(v).hexdigest() for v in imgs.values()]], sort_keys=True, default=str).encode()).hexdigest()
            cfile = self.cache / key[:2] / f"{key}.json"
            if cfile.exists():
                answers.update(json.loads(cfile.read_text(encoding="utf-8"))); continue
            if self.dry:
                print(f"  [dry-run] {Path(str(frame)).name}: images {list(imgs)}; questions {list(qs)}"); continue
            if self.spent >= self.max_cost:
                raise Stop(f"STOP: --max-cost ${self.max_cost} reached")
            a, usd = be.ask(imgs, qs, ts)
            self.spent += usd; self.requests += 1
            cfile.parent.mkdir(parents=True, exist_ok=True); cfile.write_text(json.dumps(a), encoding="utf-8")
            answers.update(a)
        return answers

    # ------------------------------------------------ answers -> numbers -> verdicts
    @staticmethod
    def num(a, opt=None):
        if not a:
            return None
        t = a.get("type")
        if t == "noul":
            return float(a["noul"])
        if t == "score":
            top = max(int(k) for k in a["probabilities"]) or 1
            return float(a["score"]) / top
        if t == "choice":
            return float(a["probabilities"].get(opt, 0.0)) if opt else max(a["probabilities"].values())
        return None

    def derived(self, a):
        """Numbers computed in code from Box answers: ratio:<a>/<b> (height of a / height of b),
        overlap:<a>/<b> (share of box a inside box b) and <edge>:<a> (left/top/right/bottom as a fraction of
        the frame). A box only counts if its companion Noul is >= 0.7."""
        d = {}
        boxes = {}
        for qid, v in a.items():
            if v.get("type") == "box" and v.get("box"):
                c = self.bank.get(qid, {}).get("companion")
                if not c or (self.num(a.get(c)) or 0) >= YES:
                    boxes[qid] = v["box"]
        for x, bx in boxes.items():  # edges of one box (e.g. bottom:box_subtitle for a safe-area rule)
            for edge in ("left", "top", "right", "bottom"):
                d[f"{edge}:{x}"] = round(float(bx[edge]), 3)
        for x in boxes:
            for y in boxes:
                if x == y:
                    continue
                bx, by = boxes[x], boxes[y]
                d[f"ratio:{x}/{y}"] = round((bx["bottom"] - bx["top"]) / max(0.02, by["bottom"] - by["top"]), 3)
                w = max(0.0, min(bx["right"], by["right"]) - max(bx["left"], by["left"]))
                h = max(0.0, min(bx["bottom"], by["bottom"]) - max(bx["top"], by["top"]))
                d[f"overlap:{x}/{y}"] = round(w * h / max(1e-6, (bx["right"] - bx["left"]) * (bx["bottom"] - bx["top"])), 3)
        return d

    def value(self, a, d, name):
        return d[name] if name in d else self.num(a.get(name))

    def term(self, t, a, d, label):
        """One rule term -> p_ok in [0,1], or None if its inputs are missing."""
        if "q" in t and "want" in t:                     # a Noul: want true or false
            p = self.num(a.get(t["q"]))
            return None if p is None else (p if t["want"] else 1 - p)
        if "q" in t and "expect_from_label" in t:        # a Choice whose expected option depends on the line/label
            lab = (label or "").lower()
            opt = next((o for k, o in t["expect_from_label"].items() if k in lab), None)
            return None if opt is None or t["q"] not in a else self.num(a[t["q"]], opt)
        if "q" in t and "min" in t:                      # a Score (0..1 position) that must reach a level
            p = self.num(a.get(t["q"]))
            return None if p is None else max(0.0, min(1.0, (p - t["min"] + 0.25) / 0.5))
        if "derived" in t:                               # a ratio/overlap that must stay under max (soft edge)
            v = d.get(t["derived"])
            if v is None:
                return None
            soft = t.get("soft", 0.2)
            return max(0.0, min(1.0, 0.5 - (v - t["max"]) / (2 * soft)))
        raise ValueError(f"bad rule term {t}")

    def verdict(self, name, a, label=None):
        v = self.vdefs[name]
        if v.get("needs_label") and not label:
            return {"call": "n/a", "why": "needs a label or spoken line"}
        g = v.get("gate")
        if g and g in a and (self.num(a[g]) or 0) < NO:
            return {"call": "n/a", "why": f"gate {g} = {self.num(a[g]):.2f}"}
        d = self.derived(a)
        m = self.model.get(name)
        p, via = None, "rule"
        if m:
            x = [self.value(a, d, f) for f in m["features"]]
            if all(t is not None for t in x):
                z = m["intercept"] + sum(w * xi for w, xi in zip(m["coef"], x))
                p, via = 1 / (1 + math.exp(-z)), "fit"
        if p is None:
            ps = [self.term(t, a, d, label) for t in v.get("all_ok", [])]
            ps = [x for x in ps if x is not None]
            p = min(ps) if ps else None
        if p is None:
            return {"call": "n/a", "why": "inputs missing"}
        lo, hi = (m or {}).get("band", [NO, YES])
        return {"p_ok": round(p, 3), "call": "pass" if p >= hi else "fail" if p <= lo else "unsure", "via": via}

    def inputs_of(self, name):
        v = self.vdefs[name]
        qs = {t["q"] for t in v.get("all_ok", []) if "q" in t} | set(v.get("features", []))
        return {q for q in qs if q in self.bank and self.bank[q]["type"] == "noul"}

    # ------------------------------------------------ judge a list of frames
    def run(self, items, pack, labels=None, prev="auto", escalate=None, workers=8):
        ids, vnames = pack_ids(pack, self.packs, self.bank)
        esc = make_backend(escalate) if escalate else None

        def one(i):
            f, t = items[i]
            pv = items[i - 1][0] if prev == "auto" and i > 0 else None
            lab = labels[i] if labels else None
            a = self.ask_frame(f, ids, pv, lab)
            res = {"frame": str(f), "t": t, "label": lab, "answers": a, "derived": self.derived(a),
                   "verdicts": {n: self.verdict(n, a, lab) for n in vnames if self.vdefs[n].get("type") != "sequence"}}
            unsure = [n for n, v in res["verdicts"].items() if v["call"] == "unsure"]
            if esc and unsure and not self.dry:
                qids = sorted(set().union(*(self.inputs_of(n) for n in unsure)))
                e = self.ask_frame(f, qids, pv, lab, backend=esc)
                a2 = {**a, **e}
                for n in unsure:
                    res["verdicts"][n] = dict(self.verdict(n, a2, lab), escalated=True)
            return res

        with cf.ThreadPoolExecutor(1 if self.dry else workers) as ex:
            out = list(ex.map(one, range(len(items))))
        for n in vnames:  # sequence verdicts: a truth table over neighbouring samples, in code
            v = self.vdefs[n]
            if v.get("type") != "sequence":
                continue
            for i, r in enumerate(out):
                if i == 0:
                    r["verdicts"][n] = {"call": "n/a", "why": "first sample"}; continue
                gone, fading = [], []
                for q in v["presence"]:
                    p0, p1 = self.num(out[i - 1]["answers"].get(q)), self.num(r["answers"].get(q))
                    if p0 is None or p1 is None:
                        continue
                    if p0 >= YES and p1 <= NO:
                        gone.append(q)
                    elif p0 >= YES and p1 < YES:
                        fading.append(q)
                r["verdicts"][n] = ({"p_ok": 0.0, "call": "fail", "via": "sequence", "why": f"gone: {gone}"} if gone else
                                    {"p_ok": 0.5, "call": "unsure", "via": "sequence", "why": f"fading: {fading}"} if fading else
                                    {"p_ok": 1.0, "call": "pass", "via": "sequence"})
        ledger(self.spent, f"{self.requests} requests", f"judge --pack {pack}", self.backend.provider, getattr(self.backend, "model", ""))
        return out


# ---------------------------------------------------------------- commands
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv"}


def sample_video(path, every, outdir):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vf", f"fps=1/{every}", "-q:v", "2",
                    str(Path(outdir) / "f_%05d.jpg")], check=True, creationflags=NOWIN)
    return [(f, round(i * every, 3)) for i, f in enumerate(sorted(Path(outdir).glob("f_*.jpg")))]


def findings_for(judge, items, packs, labels=None):
    """Hook for other gates (vosync, frameqa-style callers): a clear fail is P0, an unsure verdict is P2."""
    out = []
    for pack in [p.strip() for p in packs.split(",") if p.strip()]:
        for r in judge.run(items, pack, labels=labels):
            for n, v in r["verdicts"].items():
                if v["call"] in ("fail", "unsure"):
                    out.append({"check": f"judge:{n}", "severity": "P0" if v["call"] == "fail" else "P2", "t": r["t"],
                                "frame": r["frame"], "p_ok": v.get("p_ok"), "why": v.get("why", v.get("via", ""))})
    return out


def cmd_judge(a):
    j = Judge(a)
    p = Path(a.input)
    if p.is_dir():
        items = [(f, None) for f in sorted(list(p.glob("*.jpg")) + list(p.glob("*.png")))]
    elif p.suffix.lower() in VIDEO_EXT:
        items = sample_video(p, a.every, tempfile.mkdtemp(prefix="judge-"))
    else:
        items = [(p, None)]
    res = j.run(items, a.pack, labels=[a.label] * len(items) if a.label else None,
                prev="auto" if p.suffix.lower() in VIDEO_EXT else None, escalate=a.escalate)
    p0 = 0
    for r in res:
        fails = [n for n, v in r["verdicts"].items() if v["call"] == "fail"]
        uns = [n for n, v in r["verdicts"].items() if v["call"] == "unsure"]
        p0 += bool(fails)
        print(f"{r['t'] if r['t'] is not None else Path(r['frame']).name}: " + (f"FAIL {fails} " if fails else "ok ")
              + (f"unsure {uns}" if uns else ""))
    print(f"{len(res)} frames, {j.requests} requests, ${j.spent:.5f}" + (" (dry run)" if a.dry_run else ""))
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    sys.exit(1 if p0 else 0)


def load_labels(evalset, split="all"):
    rows = [json.loads(l) for l in (Path(evalset) / "labels.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    return [r for r in rows if split == "all" or r.get("split") == split]


def answers_for_rows(j, rows, evalset):
    """Ask, per (image, previous frame, label), every question its labels and verdicts need."""
    need = {}
    for r in rows:
        k = (r["image"], r.get("state", {}).get("previous_frame"), r.get("state", {}).get("on_screen_label"))
        s = need.setdefault(k, set())
        q = r["q"]
        if q.startswith("verdict:"):
            v = j.vdefs[q[8:]]
            s |= {t["q"] for t in v.get("all_ok", []) if "q" in t} | set(v.get("features", [])) | ({v["gate"]} if v.get("gate") else set())
            s |= {part for t in v.get("all_ok", []) if "derived" in t for part in t["derived"].split(":", 1)[1].split("/")}
            s |= {part for f in v.get("features", []) if ":" in f for part in f.split(":", 1)[1].split("/")}
        else:
            s.add(q)
    out = {}
    E = Path(evalset)
    for k, ids in need.items():
        ids = [i for i in ids if i in j.bank]
        ids += [j.bank[i]["companion"] for i in ids if j.bank[i].get("companion") and j.bank[i]["companion"] not in ids]
        out[k] = j.ask_frame(E / k[0], ids, E / k[1] if k[1] else None, k[2])
    return out


def cmd_eval(a):
    j = Judge(a)
    rows = load_labels(a.evalset, a.split)
    if a.groups:
        gs = set(a.groups.split(","))
        rows = [r for r in rows if (r["q"].startswith("verdict:") and "verdict" in gs) or j.bank.get(r["q"], {}).get("group") in gs]
    ans = answers_for_rows(j, rows, a.evalset)
    by, cal, miss = {}, [], []
    for r in rows:
        k = (r["image"], r.get("state", {}).get("previous_frame"), r.get("state", {}).get("on_screen_label"))
        a_ = ans.get(k, {})
        if r["q"].startswith("verdict:"):
            v = j.verdict(r["q"][8:], a_, k[2])
            if v["call"] == "n/a":
                continue
            got, p, g = v["p_ok"] >= 0.5, v["p_ok"], "verdict"
        elif r["q"] in a_:
            x = a_[r["q"]]
            got = x["noul"] >= 0.5 if x["type"] == "noul" else x.get("choice", x.get("score"))
            p, g = (x["noul"] if x["type"] == "noul" else None), j.bank[r["q"]]["group"]
        else:
            continue
        ok = got == r["expect"]
        by.setdefault(g, []).append(ok)
        if p is not None and isinstance(r["expect"], bool) and g != "verdict":
            cal.append((p, r["expect"]))
        if not ok:
            miss.append(f"- {r['image']} {r['q']} expect={r['expect']} got={got} p={p} {r.get('note', '')[:60]}")
    lines = [f"eval split={a.split}: {sum(len(v) for v in by.values())} labels, {j.requests} new requests, ${j.spent:.4f}", "",
             "| group | n | accuracy |", "|---|---|---|"]
    lines += [f"| {g} | {len(v)} | {sum(v) / len(v):.1%} |" for g, v in sorted(by.items())]
    allv = [o for v in by.values() for o in v]
    lines += [f"| **all** | {len(allv)} | **{sum(allv) / max(1, len(allv)):.1%}** |", "", "Noul calibration (share actually true):"]
    for lo, hi in [(0, .1), (.1, .3), (.3, .5), (.5, .7), (.7, .9), (.9, 1.01)]:
        pts = [e for p, e in cal if lo <= p < hi]
        if pts:
            lines.append(f"- p {lo:.1f}-{min(hi, 1):.1f}: n={len(pts)}, true {sum(pts) / len(pts):.0%}")
    if a.verbose:
        lines += ["", "Misses:"] + miss
    print("\n".join(lines))
    ledger(j.spent, f"{j.requests} requests", f"eval {a.split}", j.backend.provider, getattr(j.backend, "model", ""))


def logistic(X, y, C, iters=3000, lr=0.1):
    import numpy as np
    X, y = np.asarray(X, float), np.asarray(y, float)
    w = np.zeros(X.shape[1]); b = 0.0
    cw = np.where(y == 1, len(y) / (2 * max(1, y.sum())), len(y) / (2 * max(1, len(y) - y.sum())))  # balanced classes
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(X @ w + b)))
        g = (p - y) * cw
        w -= lr * (X.T @ g / len(y) + w / (C * len(y)))
        b -= lr * g.mean()
    return w, b


def cmd_fit(a):
    """Logistic layer per verdict over the judge's answers, fitted on the train split only, L2 chosen by
    k-fold log loss. Verdicts with fewer than --min-rows labels keep their hand rule."""
    import numpy as np
    j = Judge(a)
    rows = [r for r in load_labels(a.evalset, "train") if r["q"].startswith("verdict:")]
    ans = answers_for_rows(j, rows, a.evalset)
    model = {}
    for name, v in j.vdefs.items():
        feats = v.get("features")
        if not feats:
            continue
        X, y = [], []
        for r in rows:
            if r["q"] != f"verdict:{name}":
                continue
            k = (r["image"], r.get("state", {}).get("previous_frame"), r.get("state", {}).get("on_screen_label"))
            a_ = ans.get(k, {}); d = j.derived(a_)
            x = [j.value(a_, d, f) for f in feats]
            if all(t is not None for t in x):
                X.append(x); y.append(int(bool(r["expect"])))
        if len(y) < a.min_rows or len(set(y)) < 2:
            print(f"{name}: {len(y)} usable rows -> keep the hand rule"); continue
        X_, y_ = np.array(X), np.array(y)
        best = (1e9, 1.0)
        k = min(5, int(y_.sum()), int(len(y_) - y_.sum()))
        for C in [0.3, 1, 3, 10, 30]:
            if k < 3:
                break
            loss = 0.0
            for f in range(k):
                te = np.arange(len(y_)) % k == f
                w, b = logistic(X_[~te], y_[~te], C)
                p = np.clip(1 / (1 + np.exp(-(X_[te] @ w + b))), 1e-6, 1 - 1e-6)
                loss -= np.sum(y_[te] * np.log(p) + (1 - y_[te]) * np.log(1 - p))
            best = min(best, (loss, C))
        C = best[1]
        w, b = logistic(X_, y_, C)
        acc = float(np.mean(((1 / (1 + np.exp(-(X_ @ w + b)))) >= .5) == y_))
        model[name] = {"features": feats, "coef": [round(float(c), 4) for c in w], "intercept": round(float(b), 4),
                       "band": [NO, YES], "n_train": len(y), "pos_train": int(sum(y)), "acc_train": round(acc, 3), "C": C,
                       "fitted": dt.datetime.now().isoformat(timespec="seconds")}
        print(f"{name}: n={len(y)} acc_train={acc:.0%} C={C} coef={dict(zip(feats, model[name]['coef']))}")
    ledger(j.spent, f"{j.requests} requests", "fit", j.backend.provider, getattr(j.backend, "model", ""))
    Path(a.model_file).write_text(json.dumps(model, indent=1), encoding="utf-8")
    print("wrote", a.model_file)


def cmd_label(a):
    """Turn one approve/reject note into an eval row: copies the frame into <evalset>/frames/, splits by a
    stable hash (30% test), appends to labels.jsonl."""
    import shutil
    E = Path(a.evalset); (E / "frames").mkdir(parents=True, exist_ok=True)
    exp = {"true": True, "yes": True, "false": False, "no": False}.get(a.answer.lower(), a.answer)

    def stash(p):
        p = Path(p); h = hashlib.sha1(p.read_bytes()).hexdigest()[:10]
        dst = E / "frames" / f"{h}{p.suffix.lower()}"
        if not dst.exists():
            shutil.copy(p, dst)
        return f"frames/{dst.name}"

    st = {}
    if a.prev:
        st["previous_frame"] = stash(a.prev)
    if a.label:
        st["on_screen_label"] = a.label
    img = stash(a.image)
    split = "test" if int(hashlib.sha1(img.encode()).hexdigest(), 16) % 10 < 3 else "train"
    row = {"image": img, "q": a.question, "expect": exp, "state": st, "note": a.note, "split": split, "added": dt.date.today().isoformat()}
    with (E / "labels.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("added", row)


def cmd_questions(a):
    bank = load_bank(a.questions)
    packs, _, _ = load_packs(a.packs)
    ids = pack_ids(a.pack, packs, bank)[0] if a.pack else list(bank)
    for i in ids:
        print(f"[{bank[i]['group']}] {i} ({bank[i]['type']}): {bank[i]['instructions']}")


def main():
    c = argparse.ArgumentParser(add_help=False)
    c.add_argument("--questions", default=str(HERE / "questions"))
    c.add_argument("--packs", default=str(HERE / "packs.example.json"))
    c.add_argument("--model-file", default=str(HERE / "model.json"))
    c.add_argument("--ref", action="append", help="name=path of a reference sheet a question names as `name`")
    c.add_argument("--backend", default="jev", choices=["jev", "fal", "openai", "ollama"])
    c.add_argument("--model"); c.add_argument("--max-side", type=int, default=1024)
    c.add_argument("--max-cost", type=float, default=1.0); c.add_argument("--dry-run", action="store_true")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    j = sp.add_parser("judge", parents=[c]); j.add_argument("input"); j.add_argument("--pack", default="all"); j.add_argument("--label")
    j.add_argument("--every", type=float, default=1.0); j.add_argument("--escalate", choices=["fal", "openai", "ollama"])
    j.add_argument("--out"); j.set_defaults(f=cmd_judge)
    e = sp.add_parser("eval", parents=[c]); e.add_argument("--evalset", required=True); e.add_argument("--split", default="test")
    e.add_argument("--groups"); e.add_argument("-v", "--verbose", action="store_true"); e.set_defaults(f=cmd_eval)
    f = sp.add_parser("fit", parents=[c]); f.add_argument("--evalset", required=True); f.add_argument("--min-rows", type=int, default=20)
    f.set_defaults(f=cmd_fit)
    lb = sp.add_parser("label", parents=[c]); lb.add_argument("image"); lb.add_argument("question"); lb.add_argument("answer")
    lb.add_argument("--evalset", required=True); lb.add_argument("--note", required=True); lb.add_argument("--prev"); lb.add_argument("--label")
    lb.set_defaults(f=cmd_label)
    q = sp.add_parser("questions", parents=[c]); q.add_argument("--pack"); q.set_defaults(f=cmd_questions)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
