"""Cheap vision backends shared by frameqa and continuity: ask fixed yes/no questions about frames.

Every backend takes a list of frames (PIL images) plus the question list and returns, per frame,
{qid: {"answer": "yes"|"no", "p": prob_yes, "reason": str}} and a cost estimate in USD.

Backends
  jev     TypeSafe Jev (System One), one call per frame, all questions in the call; returns a
          probability only (no reason). $0.042 per M input tokens, output free.
  gemini  Google Gemini direct (GEMINI_API_KEY), several frames per call, JSON with reasons.
  fal     fal.ai openrouter/router/vision (FAL_KEY), any OpenRouter vision model, JSON with reasons.
  ollama  local Ollama vision model (qwen3-vl:8b etc.), free but slow on a consumer GPU.
No third-party deps: urllib only.

Keys come from environment variables only (TYPESAFE_API_KEY, FAL_KEY, GEMINI_API_KEY), or from a `.env`
file in the current working directory (or the file named by AMR_ENV_FILE). Keys are never printed or logged.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from PIL import Image

ENV_FILE = Path(os.environ.get("AMR_ENV_FILE", ".env"))

# USD per million tokens (input, output). Gemini direct = Google list price; fal passes OpenRouter's.
PRICES = {
    "jev": (0.042, 0.0),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3-flash-preview": (0.50, 3.00),
}


def env_key(name: str) -> str | None:
    v = os.environ.get(name)
    if v:
        return v.strip()
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"') or None
    return None


def to_jpeg(im, max_side: int = 960, quality: int = 85) -> bytes:
    im = im.convert("RGB")
    w, h = im.size
    s = min(1.0, max_side / max(w, h))
    if s < 1:
        im = im.resize((max(1, round(w * s)), max(1, round(h * s))))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=quality)
    return b.getvalue()


def _post(url: str, body: dict, headers: dict, timeout: float = 120, tries: int = 4) -> dict:
    data = json.dumps(body).encode("utf-8")
    last = None
    for i in range(tries):
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "ignore")[:400]
            last = f"HTTP {e.code}: {msg}"
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 * (i + 1))
                continue
            raise RuntimeError(last)
        except (urllib.error.URLError, TimeoutError) as e:
            last = str(e)
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"request failed after {tries} tries: {last}")


# ---------------------------------------------------------------- Jev (TypeSafe System One)
def jev_jpeg(im, max_side: int = 1568) -> bytes:
    """Jev needs every side within 280..1568 px and does not resize; scale (and pad if very wide)."""
    im = im.convert("RGB")
    w, h = im.size
    s = min(max_side / max(w, h), 1.0)
    s = max(s, 280 / min(w, h))
    im = im.resize((max(280, round(w * s)), max(280, round(h * s))))
    w, h = im.size
    if max(w, h) > 1568:  # extreme aspect: pad the short side instead
        s = 1568 / max(w, h)
        im = im.resize((round(w * s), round(h * s)))
        c = Image.new("RGB", (max(280, im.size[0]), max(280, im.size[1])), (0, 0, 0))
        c.paste(im, (0, 0))
        im = c
    b = io.BytesIO()
    im.save(b, "JPEG", quality=85)
    return b.getvalue()


class Jev:
    name = "jev"

    def __init__(self, model: str | None = None, threshold: float = 0.5):
        self.key = env_key("TYPESAFE_API_KEY")
        if not self.key:
            raise RuntimeError("TYPESAFE_API_KEY not set")
        self.model = model or os.environ.get("FRAMEQA_JEV_MODEL", "jev-latest")
        self.url = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai") + "/v1/systemone"
        self.threshold = threshold
        self.batch = 1

    def ask(self, frames, questions, refs=None):
        """frames: list of PIL images (one call each)."""
        out, cost, toks = [], 0.0, 0
        for im in frames:
            jpg = jev_jpeg(im)
            fref = "frm-" + uuid.uuid4().hex[:12]
            assets = {fref: {"type": "image", "format": "jpg", "data_base64": base64.b64encode(jpg).decode()}}
            qs = {}
            for q in questions:
                instr = q["text"] + " Answer about the image in `frame`, a still from a cartoon video."
                if q.get("needs_refs"):
                    if not refs:
                        continue
                    rr = []
                    for r in refs:
                        k = "ref-" + uuid.uuid4().hex[:12]
                        assets[k] = {"type": "image", "format": "jpg",
                                     "data_base64": base64.b64encode(jev_jpeg(r, 1024)).decode()}
                        rr.append(k)
                    instr += " Reference model sheet(s): " + " ".join(rr)
                qs[q["id"]] = {"type": "noul", "instructions": instr}
            body = {"model": self.model, "state": {"frame": fref}, "assets": assets, "questions": qs}
            resp = _post(self.url, body, {"Authorization": f"Bearer {self.key}",
                                          "TypeSafe-Danger-Zone-Images": "true"})
            ans = {}
            for qid, a in (resp.get("answers") or {}).items():
                p = float(a.get("noul", 0.0)) if isinstance(a, dict) else float(a)
                ans[qid] = {"answer": "yes" if p >= self.threshold else "no", "p": round(p, 3), "reason": ""}
            out.append(ans)
            u = resp.get("usage") or {}
            t = int(u.get("input_tokens") or u.get("prompt_tokens") or 0)
            toks += t
            cost += t * PRICES["jev"][0] / 1e6
        return out, cost, {"input_tokens": toks}


# ---------------------------------------------------------------- JSON-answering LLMs
def _prompt(questions, n_frames, has_refs):
    lines = [
        "You are a strict video QA checker for a cartoon / animated video.",
        f"You get {n_frames} still frame(s), labelled F1..F{n_frames} in order"
        + (", followed by reference model sheet image(s) labelled REF." if has_refs else "."),
        "For EACH frame answer EACH question with yes or no. Say yes only for a clear, visible problem a viewer "
        "would notice; stylised cartoon looks are not problems.",
        "Questions:",
    ]
    for q in questions:
        if q.get("needs_refs") and not has_refs:
            continue
        lines.append(f'  {q["id"]}: {q["text"]}')
    lines.append('Reply with JSON only: {"F1": {"<question id>": {"a": "yes"|"no", "c": <confidence 0-1>, '
                 '"r": "<reason, max 15 words, say where in the frame>"}, ...}, "F2": {...}}')
    return "\n".join(lines)


def _parse(text, n, questions):
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        d = {}
    out = []
    for i in range(n):
        fd = d.get(f"F{i+1}") or {}
        ans = {}
        for q in questions:
            a = fd.get(q["id"])
            if not isinstance(a, dict):
                continue
            yes = str(a.get("a", "no")).lower().startswith("y")
            c = float(a.get("c", 0.5) or 0.5)
            ans[q["id"]] = {"answer": "yes" if yes else "no", "p": round(c if yes else 1 - c, 3),
                            "reason": str(a.get("r", ""))[:160]}
        out.append(ans)
    return out


class Gemini:
    name = "gemini"

    def __init__(self, model: str | None = None, batch: int = 4, max_side: int = 768):
        self.key = env_key("GEMINI_API_KEY") or env_key("GOOGLE_API_KEY")
        if not self.key:
            raise RuntimeError("GEMINI_API_KEY not set")
        self.model = model or "gemini-2.5-flash-lite"
        self.batch, self.max_side = batch, max_side

    def ask(self, frames, questions, refs=None):
        parts = [{"text": _prompt(questions, len(frames), bool(refs))}]
        for i, im in enumerate(frames):
            parts.append({"text": f"F{i+1}:"})
            parts.append({"inline_data": {"mime_type": "image/jpeg",
                                          "data": base64.b64encode(to_jpeg(im, self.max_side)).decode()}})
        for r in refs or []:
            parts.append({"text": "REF:"})
            parts.append({"inline_data": {"mime_type": "image/jpeg",
                                          "data": base64.b64encode(to_jpeg(r, 768)).decode()}})
        body = {"contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"temperature": 0, "response_mime_type": "application/json"}}
        if "2.5" in self.model:
            body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        resp = _post(url, body, {"x-goog-api-key": self.key})
        text = "".join(p.get("text", "") for c in resp.get("candidates", [])
                       for p in c.get("content", {}).get("parts", []))
        u = resp.get("usageMetadata", {})
        ti = u.get("promptTokenCount", 0)
        to = u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)
        pi, po = PRICES.get(self.model, (0.30, 2.50))
        return _parse(text, len(frames), questions), (ti * pi + to * po) / 1e6, {"input_tokens": ti, "output_tokens": to}


class FalRouter:
    """fal.ai openrouter/router/vision. Images must be URLs; data URIs work for small jpegs."""
    name = "fal"

    def __init__(self, model: str | None = None, batch: int = 4, max_side: int = 768):
        max_side = int(os.environ.get("FRAMEQA_MAX_SIDE", max_side))
        self.key = env_key("FAL_KEY")
        if not self.key:
            raise RuntimeError("FAL_KEY not set")
        self.model = model or "google/gemini-3.5-flash-lite"
        self.batch, self.max_side = batch, max_side
        self.reasoning = None  # set True once the endpoint says reasoning is mandatory

    def ask(self, frames, questions, refs=None):
        urls = ["data:image/jpeg;base64," + base64.b64encode(to_jpeg(im, self.max_side)).decode() for im in frames]
        urls += ["data:image/jpeg;base64," + base64.b64encode(to_jpeg(r, 768)).decode() for r in refs or []]
        body = {"model": self.model, "prompt": _prompt(questions, len(frames), bool(refs))
                + "\nImages are attached in order F1..Fn" + (" then REF." if refs else "."),
                "image_urls": urls, "temperature": 0}
        if self.reasoning:
            body["reasoning"] = True
        try:
            resp = _post("https://fal.run/openrouter/router/vision", body, {"Authorization": f"Key {self.key}"}, timeout=180)
        except RuntimeError as e:
            if "Reasoning is mandatory" not in str(e):
                raise
            body["reasoning"] = self.reasoning = True
            resp = _post("https://fal.run/openrouter/router/vision", body, {"Authorization": f"Key {self.key}"}, timeout=180)
        u = resp.get("usage") or {}
        return (_parse(resp.get("output", ""), len(frames), questions), float(u.get("cost") or 0.0),
                {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)})


class Ollama:
    name = "ollama"

    def __init__(self, model: str | None = None, batch: int = 1, max_side: int = 768):
        self.model = model or "qwen3-vl:8b"
        self.batch, self.max_side = batch, max_side
        self.url = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434") + "/api/chat"

    def ask(self, frames, questions, refs=None):
        imgs = [base64.b64encode(to_jpeg(im, self.max_side)).decode() for im in frames]
        imgs += [base64.b64encode(to_jpeg(r, 768)).decode() for r in refs or []]
        body = {"model": self.model, "stream": False, "format": "json", "options": {"temperature": 0},
                "think": False,
                "messages": [{"role": "user", "content": _prompt(questions, len(frames), bool(refs)), "images": imgs}]}
        resp = _post(self.url, body, {}, timeout=600)
        return _parse(resp.get("message", {}).get("content", ""), len(frames), questions), 0.0, {}


def make(backend: str, model: str | None = None, batch: int | None = None):
    b = backend.lower()
    if b == "jev":
        return Jev(model)
    if b == "gemini":
        return Gemini(model, batch or 4)
    if b == "fal":
        return FalRouter(model, batch or int(os.environ.get("FRAMEQA_BATCH", 4)))
    if b == "ollama":
        return Ollama(model, batch or 1)
    raise ValueError(f"unknown vision backend {backend}")
