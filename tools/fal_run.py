"""fal_run: one fal.ai queue call, done safely. Upload local files, submit, poll, fetch, download, log the spend.

    python tools/fal_run.py ENDPOINT --args args.json [--upload name=path ...] [--est 0.30] [--out outputs/]
           [--daily-cap 5.00] [--ledger spend-ledger.csv] [--dry-run]

    # example: Wan 3.0 image-to-video from a local keyframe (about $0.30 for 6 s)
    python tools/fal_run.py alibaba/wan-3.0/image-to-video --upload start=frames/S1.png --est 0.30 --dry-run \
        --args '{"image_url": "@start", "prompt": "Locked-off camera. ...", "duration": 6, "resolution": "1080p",
                 "aspect_ratio": "9:16", "audio": false, "enable_prompt_expansion": false}'

--args     a JSON file or an inline JSON string. Any string "@name" is replaced by the fal CDN URL of --upload name=path.
--est      your estimate of the call's cost in USD (from ROUTING.md or the model page). It is checked against
           --daily-cap BEFORE submitting and written to the ledger after.
--dry-run  print what would be uploaded and sent, with the estimate; no upload, no call, no spend.

Shape of the fal queue API (what this script does):
  1. upload:  POST https://rest.alpha.fal.ai/storage/upload/initiate?storage_type=fal-cdn-v3
              {"file_name", "content_type"} -> {"upload_url", "file_url"}; PUT the bytes to upload_url; use file_url.
  2. submit:  POST https://queue.fal.run/<endpoint>   header  Authorization: Key $FAL_KEY   body = the model's args
              -> {"request_id", "status_url", "response_url"}
  3. poll:    GET status_url until "status" is "COMPLETED" (IN_QUEUE / IN_PROGRESS before that)
  4. fetch:   GET response_url -> the model's output JSON (video/image/audio URLs)
Key: FAL_KEY from the environment or a .env file in the working directory (never committed, never printed).

Stops, with a message and a non-zero exit, on HTTP 401/402/403 or a "locked" / "balance" / "top up" answer: that
means the key is wrong or the account is locked for an empty balance. Do not retry and do not fall back to another
provider silently; top up (or turn on auto top-up) and run again. The request id is saved in <out>/<endpoint>.req.json
so a re-run polls the same request instead of paying twice.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

LOCK_WORDS = ("locked", "balance", "top up", "top_up", "insufficient", "exhausted", "billing")


def env_key(name):
    v = os.environ.get(name)
    if v:
        return v.strip()
    env = Path(os.environ.get("AMR_ENV_FILE", ".env"))
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines() if env.exists() else []:
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"') or None
    return None


def req(url, key, data=None, method=None, headers=None, timeout=120):
    body = json.dumps(data).encode() if data is not None else None
    h = {"Authorization": f"Key {key}", **({"Content-Type": "application/json"} if body else {}), **(headers or {})}
    r = urllib.request.Request(url, data=body, method=method or ("POST" if body else "GET"), headers=h)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")[:400]
        if e.code in (401, 402, 403) or any(w in msg.lower() for w in LOCK_WORDS):
            raise SystemExit(f"STOP: fal HTTP {e.code}: {msg}\n(key wrong or account locked / balance empty: top up, then re-run)")
        raise


def upload(path: Path, key: str) -> str:
    ct = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    init = req("https://rest.alpha.fal.ai/storage/upload/initiate?storage_type=fal-cdn-v3", key,
               {"file_name": path.name, "content_type": ct})
    put = urllib.request.Request(init["upload_url"], data=path.read_bytes(), method="PUT", headers={"Content-Type": ct})
    urllib.request.urlopen(put, timeout=300).read()
    return init["file_url"]


def resolve(obj, urls):
    if isinstance(obj, str) and obj.startswith("@") and obj[1:] in urls:
        return urls[obj[1:]]
    if isinstance(obj, list):
        return [resolve(x, urls) for x in obj]
    if isinstance(obj, dict):
        return {k: resolve(v, urls) for k, v in obj.items()}
    return obj


def media_urls(obj):
    """Every https URL in the output that looks like media."""
    out = []
    if isinstance(obj, dict):
        for v in obj.values():
            out += media_urls(v)
    elif isinstance(obj, list):
        for v in obj:
            out += media_urls(v)
    elif isinstance(obj, str) and obj.startswith("https://") and any(obj.split("?")[0].lower().endswith(e) for e in
                                                                     (".mp4", ".mov", ".webm", ".png", ".jpg", ".jpeg", ".webp", ".wav", ".mp3", ".glb")):
        out.append(obj)
    return out


def spent_today(ledger: Path) -> float:
    if not ledger.exists():
        return 0.0
    today = dt.date.today().isoformat()
    with ledger.open(encoding="utf-8") as f:
        return sum(float(r["usd"]) for r in csv.DictReader(f) if r.get("date") == today and r.get("usd"))


def log(ledger: Path, endpoint, usd, note):
    new = not ledger.exists()
    with ledger.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        if new:
            w.writerow(["date", "tool", "provider", "model", "units", "usd", "note"])
        w.writerow([dt.date.today().isoformat(), "fal_run", "fal", endpoint, "1 call", f"{usd:.4f}", note])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("endpoint"); ap.add_argument("--args", required=True)
    ap.add_argument("--upload", action="append", default=[], help="name=path; use \"@name\" in --args")
    ap.add_argument("--est", type=float, required=True, help="estimated USD for this call")
    ap.add_argument("--daily-cap", type=float, default=float(os.environ.get("AMR_DAILY_CAP", 5.0)))
    ap.add_argument("--ledger", default=os.environ.get("AMR_LEDGER", "spend-ledger.csv"))
    ap.add_argument("--out", default="outputs"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--poll", type=float, default=5.0); ap.add_argument("--timeout", type=float, default=1800)
    a = ap.parse_args()
    args = json.loads(Path(a.args).read_text(encoding="utf-8")) if Path(a.args).exists() else json.loads(a.args)
    ups = dict(u.split("=", 1) for u in a.upload)
    ledger, out = Path(a.ledger), Path(a.out)
    today = spent_today(ledger)
    print(f"{a.endpoint}: estimate ${a.est:.2f}; spent today ${today:.2f} of a ${a.daily_cap:.2f} cap")
    if a.dry_run:
        print("uploads:", {k: str(Path(v)) for k, v in ups.items()})
        print("args:", json.dumps(resolve(args, {k: f"<fal CDN url of {v}>" for k, v in ups.items()}), indent=1))
        print("dry run: nothing uploaded, nothing submitted, $0 spent"); return
    if today + a.est > a.daily_cap:
        raise SystemExit(f"STOP: this call (${a.est:.2f}) would pass the daily cap (${a.daily_cap:.2f}; spent ${today:.2f})")
    key = env_key("FAL_KEY")
    if not key:
        raise SystemExit("STOP: FAL_KEY not set (environment or .env)")
    out.mkdir(parents=True, exist_ok=True)
    rq_file = out / (a.endpoint.replace("/", "_") + ".req.json")
    if rq_file.exists():
        sub = json.loads(rq_file.read_text(encoding="utf-8")); print("resuming request", sub["request_id"])
    else:
        urls = {k: upload(Path(v), key) for k, v in ups.items()}
        sub = req(f"https://queue.fal.run/{a.endpoint}", key, resolve(args, urls))
        rq_file.write_text(json.dumps(sub, indent=1), encoding="utf-8")
        log(ledger, a.endpoint, a.est, f"submitted {sub.get('request_id')}")  # logged at submit: a queued call is billed
    t0 = time.time()
    while True:
        st = req(sub["status_url"], key)
        s = st.get("status")
        if s == "COMPLETED":
            break
        if s not in ("IN_QUEUE", "IN_PROGRESS"):
            raise SystemExit(f"fal request ended with status {s}: {json.dumps(st)[:400]}")
        if time.time() - t0 > a.timeout:
            raise SystemExit(f"still {s} after {a.timeout:.0f} s; re-run later to keep polling {sub['request_id']}")
        time.sleep(a.poll)
    res = req(sub["response_url"], key)
    (out / (a.endpoint.replace("/", "_") + ".result.json")).write_text(json.dumps(res, indent=1), encoding="utf-8")
    for i, u in enumerate(media_urls(res)):
        dst = out / f"{sub['request_id']}_{i}{Path(u.split('?')[0]).suffix}"
        dst.write_bytes(urllib.request.urlopen(u, timeout=600).read())
        print("saved", dst)
    rq_file.unlink()


if __name__ == "__main__":
    main()
