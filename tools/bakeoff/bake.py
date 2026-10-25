"""bake: a resumable, cost-capped bake-off runner for fal.ai queue models.

    python tools/bakeoff/bake.py jobs.json [--root DIR] [--only m1,m2 | take-id ...] [--workers 8]
           [--soft-cap 50] [--hard-cap 100] [--dry-run]

One job = one take: the SAME start frame / references / prompt go to every model in a "moment", so the only variable
is the model. Each job is resumable and idempotent:

  work/<id>.req.json   the queue submission (so a restart polls the same request instead of paying twice)
  work/<id>.res.json   the raw result
  takes/<moment>/<id>.<ext>   the downloaded media
  ledger.csv           one row per finished (or failed) request: model, endpoint, request id, cost, prompt
  work/STATUS.json     progress for a detached run; work/bake.log the log

jobs.json (see examples/jobs.example.json):
{
  "uploads": {"start_m2": "inputs/m2-start.png"},          <- local files, uploaded once to the fal CDN (cached)
  "jobs": [
    {"id": "m2-kling4", "moment": "m2", "model": "Kling 4.0", "endpoint": "kling/v4/image-to-video",
     "seconds": 6, "price": {"per_s": 0.157},
     "args": {"image_url": "@start_m2", "prompt": "...", "duration": 6, "aspect_ratio": "9:16"}}
  ]
}
"@name" in any string arg is replaced by the uploaded URL. "price" is {"per_s": x} or {"flat": x}; it is an
ESTIMATE from the provider's list price (check the provider's pricing page on the day you run).

The key comes from the FAL_KEY environment variable (or a .env file in the working directory). It is never printed.
On Windows, launch long runs detached with no console window (see README "Running long jobs").
"""
from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import os
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

FIELDS = ["time", "provider", "moment", "take_id", "model", "endpoint", "request_id", "cost_usd", "cost_basis",
          "seconds", "output", "url", "prompt"]
_lock = threading.Lock()


def env_key(name: str) -> str:
    v = os.environ.get(name)
    if v:
        return v.strip()
    env = Path(os.environ.get("AMR_ENV_FILE", ".env"))
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"')
    sys.exit(f"{name} is not set (environment variable or .env)")


class Bake:
    def __init__(self, root: Path, soft_cap: float, hard_cap: float):
        self.root = root
        self.work = root / "work"
        self.ledger_f = root / "ledger.csv"
        self.status_f = self.work / "STATUS.json"
        self.log_f = self.work / "bake.log"
        self.soft_cap, self.hard_cap = soft_cap, hard_cap
        self.key = None

    # ---------------------------------------------------------------- plumbing
    def log(self, m: str):
        with _lock, self.log_f.open("a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + m + "\n")

    def req(self, url, data=None, method=None, timeout=120):
        self.key = self.key or env_key("FAL_KEY")
        h = {"Authorization": "Key " + self.key, "Content-Type": "application/json"}
        r = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None, headers=h,
                                   method=method)
        with urllib.request.urlopen(r, timeout=timeout) as f:
            return json.loads(f.read().decode())

    def upload(self, path: Path) -> str:
        cache_f = self.work / "uploads.json"
        with _lock:
            cache = json.loads(cache_f.read_text()) if cache_f.exists() else {}
        k = f"{path.resolve()}|{path.stat().st_mtime_ns}"
        if k in cache:
            return cache[k]
        ct = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        init = self.req("https://rest.alpha.fal.ai/storage/upload/initiate?storage_type=fal-cdn-v3",
                        {"content_type": ct, "file_name": path.name})
        r = urllib.request.Request(init["upload_url"], data=path.read_bytes(), headers={"Content-Type": ct}, method="PUT")
        urllib.request.urlopen(r, timeout=300).read()
        with _lock:
            cache = json.loads(cache_f.read_text()) if cache_f.exists() else {}
            cache[k] = init["file_url"]
            cache_f.write_text(json.dumps(cache, indent=1))
        return init["file_url"]

    def spent(self) -> float:
        if not self.ledger_f.exists():
            return 0.0
        with self.ledger_f.open(newline="", encoding="utf-8") as f:
            return sum(float(r["cost_usd"] or 0) for r in csv.DictReader(f))

    def ledger(self, row: dict):
        with _lock:
            new = not self.ledger_f.exists()
            with self.ledger_f.open("a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                if new:
                    w.writeheader()
                w.writerow(row)

    def status(self, **k):
        with _lock:
            s = json.loads(self.status_f.read_text()) if self.status_f.exists() else {}
            s.update(k, pid=os.getpid(), updated=time.strftime("%Y-%m-%d %H:%M:%S"), spent_usd=round(self.spent(), 2))
            self.status_f.write_text(json.dumps(s, indent=1))

    # ---------------------------------------------------------------- one take
    @staticmethod
    def estimate(job) -> tuple[float, str]:
        p = job.get("price") or {}
        if "flat" in p:
            return float(p["flat"]), "flat list price"
        if "per_s" in p:
            secs = float(job.get("seconds", 0))
            return float(p["per_s"]) * secs, f"{p['per_s']}/s x {secs:g}s"
        return 0.0, "no price given"

    @staticmethod
    def media_url(res: dict) -> str:
        for k in ("video", "images", "image", "audio"):
            v = res.get(k)
            if isinstance(v, list) and v:
                return v[0]["url"]
            if isinstance(v, dict) and v.get("url"):
                return v["url"]
        if res.get("result_url"):  # some endpoints put the OUTPUT here; the first .mp4 in the JSON may be the input
            return res["result_url"]
        raise RuntimeError("no media in result: " + json.dumps(res)[:400])

    def run(self, job, dry=False) -> str:
        jid, moment, ep, args = job["id"], job["moment"], job["endpoint"], job["args"]
        reqf, resf = self.work / f"{jid}.req.json", self.work / f"{jid}.res.json"
        if list((self.root / "takes" / moment).glob(jid + ".*")):
            return "exists"
        est, basis = self.estimate(job)
        if dry:
            print(f"{jid:32s} {job.get('model', ''):24s} ~${est:.3f} ({basis})")
            return "dry"
        if reqf.exists():
            sub = json.loads(reqf.read_text())
        else:
            total = self.spent()
            if total + est > self.hard_cap:
                raise RuntimeError(f"HARD CAP: spent {total:.2f} + {est:.2f} > {self.hard_cap}")
            if total + est > self.soft_cap:
                self.log(f"over soft cap ({total:.2f} + {est:.2f} > {self.soft_cap}); continuing to hard cap")
            sub = self.req(f"https://queue.fal.run/{ep}", args)
            sub["_args"] = args
            reqf.write_text(json.dumps(sub, indent=1))
            self.log(f"submitted {jid} ({job.get('model')}) est ${est:.3f}")
        t0 = time.time()
        while True:
            try:
                st = self.req(sub["status_url"])
            except Exception as e:  # noqa: BLE001
                self.log(f"poll error {jid}: {e}")
                time.sleep(10)
                continue
            if st.get("status") == "COMPLETED":
                break
            if time.time() - t0 > 3600:
                raise RuntimeError(f"{jid} timed out")
            time.sleep(6)
        row = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "provider": "fal", "moment": moment, "take_id": jid,
               "model": job.get("model", ""), "endpoint": ep, "request_id": sub.get("request_id", ""),
               "seconds": job.get("seconds", 0), "prompt": args.get("prompt", "")}
        try:
            res = self.req(sub["response_url"])
        except urllib.error.HTTPError as e:
            body = e.read()[:600].decode("utf-8", "replace")
            (self.work / f"{jid}.err.txt").write_text(body)
            self.ledger(dict(row, cost_usd="0", cost_basis=f"FAILED {e.code} (check whether billed)", output="", url=""))
            raise RuntimeError(f"{jid} result error {e.code}: {body[:300]}")
        resf.write_text(json.dumps(res, indent=1))
        url = self.media_url(res)
        out = self.root / "takes" / moment / f"{jid}{Path(url.split('?')[0]).suffix or '.bin'}"
        out.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, out)
        self.ledger(dict(row, cost_usd=f"{est:.4f}", cost_basis=basis, output=str(out.relative_to(self.root)), url=url))
        self.log(f"done {jid} -> {out.name} (${est:.3f}; total ${self.spent():.2f})")
        return "done"


def resolve(obj, uploads):
    if isinstance(obj, str) and obj.startswith("@") and obj[1:] in uploads:
        return uploads[obj[1:]]
    if isinstance(obj, list):
        return [resolve(x, uploads) for x in obj]
    if isinstance(obj, dict):
        return {k: resolve(v, uploads) for k, v in obj.items()}
    return obj


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("jobs", type=Path)
    ap.add_argument("want", nargs="*", help="moments or take ids to run (default: all)")
    ap.add_argument("--root", type=Path, help="bake-off folder (default: the jobs file's folder)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--soft-cap", type=float, default=50.0, help="USD: log a warning past this")
    ap.add_argument("--hard-cap", type=float, default=100.0, help="USD: refuse to submit past this")
    ap.add_argument("--dry-run", action="store_true", help="list takes and estimated cost, submit nothing")
    a = ap.parse_args(argv)
    spec = json.loads(a.jobs.read_text(encoding="utf-8"))
    root = (a.root or a.jobs.parent).resolve()
    b = Bake(root, a.soft_cap, a.hard_cap)
    todo = [j for j in spec["jobs"] if not a.want or j["moment"] in a.want or j["id"] in a.want]
    if a.dry_run:
        tot = 0.0
        for j in todo:
            b.run(j, dry=True)
            tot += b.estimate(j)[0]
        print(f"{len(todo)} takes, estimated ${tot:.2f} (already spent per ledger: ${b.spent():.2f})")
        return 0
    b.work.mkdir(parents=True, exist_ok=True)
    uploads = {k: b.upload((root / v) if not Path(v).is_absolute() else Path(v)) for k, v in spec.get("uploads", {}).items()}
    for j in todo:
        j["args"] = resolve(j["args"], uploads)
    b.work.mkdir(parents=True, exist_ok=True)
    b.status(state="running", total=len(todo), errors=[])
    errs, done = [], []

    def go(j):
        try:
            done.append((j["id"], b.run(j)))
        except Exception as e:  # noqa: BLE001
            errs.append(f"{j['id']}: {e}")
            b.log(f"ERROR {j['id']}: {traceback.format_exc()}")
        b.status(done=len(done), errors=errs)

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(go, todo))
    b.status(state="error" if errs else "done", done=len(done), errors=errs)
    print(json.dumps({"done": len(done), "errors": len(errs), "spent_usd": round(b.spent(), 2)}))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
