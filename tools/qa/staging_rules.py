#!/usr/bin/env python
"""staging_rules: are the characters staged like solid things in a real place?

Three P0 checks on exact per-frame character tracks (from a renderer, not from guesses):

  overlap   two characters' ON-SCREEN silhouettes overlap by more than 2% of the smaller one, AT ANY DEPTH, unless the
            beat is whitelisted in scene.json "overlap_ok" (a deliberate pass-in-front). Being at different depths does
            not excuse it: on a phone it reads as one character stuck to another.
  spacing   two characters closer than the minimum screen gap while either of them is moving (they look glued together
            even when they don't touch).
  stairs    scene.json "stairs": every landing between the top (threshold) and the bottom (lawn) sits on a marked tread
            line (within tol px, inside the tread's x span), in order top -> step 1 -> step 2 ... -> bottom, one landing per
            tread, no skips, no landing on a riser, never back up.

Why these exist (the lesson): an earlier checker passed a shot in which characters overlapped in a doorway and every
stair landing sat 14 px down the risers. It missed both because (1) it compared characters only when they were at the
SAME depth, and (2) its support boxes were drawn from the character's own track, so wherever the animation landed was
"a support" by definition. So: compare silhouettes in screen space at any depth, and measure every tread line from the
CLEAN PLATE (zoomed, by eye or by code), never from the animation.

    python tools/qa/staging_rules.py --tracks tracks.json --scene scene.json [--out DIR] [--json]
    python tools/qa/staging_rules.py --demo DIR      # writes a failing and a fixed example, runs both

tracks.json (one item per drawn character per frame; masks are bbox crops, run-length encoded, see rle_encode):
  {"fps": 24, "size": [W, H], "shots": [{"id": "A", "f0": 0, "f1": 120}],          # f1 exclusive; optional
   "frames": [{"f": 0, "items": [{"char": "red", "bbox": [x, y, w, h], "alpha": [runs], "vis": [runs],
               "anchor": [x, y], "ground": [x, y], "contact": true, "seg": 3, "exp_area": 5200.0}]}]}
  alpha = the character's full silhouette; vis = the part actually visible in the final frame (scene occluders and
  nearer characters removed); anchor = the contact (bottom) point on screen; ground = the ground point under it;
  contact = touching a surface this frame; seg = an id that changes with every new hop / step (a new landing);
  exp_area = the expected silhouette area at this scale (for thresholds).
scene.json (output pixels of "size"):
  {"size": [W, H], "min_gap_px": 24,
   "overlap_ok": [{"chars": ["a", "b"], "f0": 10, "f1": 30, "why": "deliberate pass-in-front"}],
   "stairs": [{"id": "front_steps", "tol_px": 6, "chars": "*",
               "levels": [{"id": "threshold", "kind": "band", "y": [846, 880], "x": [356, 664]},
                          {"id": "step1", "line": [[362, 905], [903, 905]]},
                          {"id": "step2", "line": [[425, 1011], [1035, 1011]]},
                          {"id": "lawn", "kind": "below", "y": 1088}]}]}
Writes DIR/report.md and DIR/findings.json; exit 1 on any P0. Needs numpy + opencv-python-headless.
"""
from __future__ import annotations

import argparse, json, math, sys
from pathlib import Path

import cv2
import numpy as np

DEFAULTS = dict(amin_px=20, ov_frac=0.02, ov_frames=1, gap_frac=0.10, gap_frames=2)


# ------------------------------------------------------------------------------------------- masks
def rle_encode(mask) -> list[int]:
    """Run lengths of a bool mask, row-major, starting with a run of zeros (may be 0)."""
    v = np.asarray(mask, bool).ravel()
    if v.size == 0: return []
    d = np.flatnonzero(np.diff(v.astype(np.int8))) + 1
    edges = np.concatenate([[0], d, [v.size]])
    runs = np.diff(edges).tolist()
    return ([0] + runs) if v[0] else runs


def rle_decode(runs, h, w):
    v = np.zeros(h * w, bool); pos = 0; val = False
    for r in runs:
        if val: v[pos:pos + r] = True
        pos += r; val = not val
    return v.reshape(h, w)


def load_tracks(path):
    d = json.loads(Path(path).read_text())
    for fr in d["frames"]:
        for it in fr["items"]:
            x, y, w, h = it["bbox"]
            it["A"] = rle_decode(it["alpha"], h, w) if w and h else np.zeros((0, 0), bool)
            it["V"] = rle_decode(it.get("vis", it["alpha"]), h, w) if w and h else np.zeros((0, 0), bool)
    return d


def finding(fault, char, f0, f1, fps, detail, box=None, **kw):
    return dict(fault=fault, sev="P0", char=char, f0=int(f0), f1=int(f1), t0=round(f0 / fps, 3), t1=round(f1 / fps, 3),
                detail=detail, box=[int(v) for v in box] if box is not None else None, **kw)


def runs_from(flags):
    """[(f0, f1_inclusive, [payload...])] for consecutive frames of a dict f -> payload."""
    out, cur = [], None
    for f in sorted(flags):
        if cur and f == cur[1] + 1: cur[1] = f; cur[2].append(flags[f])
        else:
            if cur: out.append(tuple(cur))
            cur = [f, f, [flags[f]]]
    if cur: out.append(tuple(cur))
    return out


def whitelisted(scene, c1, c2, f, fps):
    """scene.json "overlap_ok": [{"chars": ["a", "b"] | ["*"], "f0", "f1"} or {"chars", "t": [t0, t1]}]."""
    for w in scene.get("overlap_ok", []):
        cs = set(w.get("chars", ["*"]))
        if not ("*" in cs or {c1, c2} <= cs): continue
        if "t" in w and not (w["t"][0] <= f / fps <= w["t"][1]): continue
        if "f0" in w and not (w["f0"] <= f <= w.get("f1", 1 << 30)): continue
        return True
    return False


def screen_gap(a, b, lim):
    """(overlap px of the two on-screen silhouettes AT ANY DEPTH, screen gap px between them capped at lim)."""
    ax, ay, aw, ah = a["bbox"]; bx, by, bw, bh = b["bbox"]
    if ax > bx + bw + lim or bx > ax + aw + lim or ay > by + bh + lim or by > ay + ah + lim: return 0, float(lim)
    L = int(math.ceil(lim)) + 2
    x0, y0 = min(ax, bx) - L, min(ay, by) - L
    w, h = max(ax + aw, bx + bw) + L - x0, max(ay + ah, by + bh) + L - y0
    ma, mb, va, vb = (np.zeros((h, w), bool) for _ in range(4))
    ma[ay - y0:ay - y0 + ah, ax - x0:ax - x0 + aw] = a["A"]; mb[by - y0:by - y0 + bh, bx - x0:bx - x0 + bw] = b["A"]
    va[ay - y0:ay - y0 + ah, ax - x0:ax - x0 + aw] = a["V"]; vb[by - y0:by - y0 + bh, bx - x0:bx - x0 + bw] = b["V"]
    # on screen = what is visible, plus what is hidden only because the OTHER character is in front of it
    # (pixels hidden by the scene, e.g. both still behind a door jamb, are not on screen and do not count)
    ma = va | (ma & vb); mb = vb | (mb & va)
    inter = int((ma & mb).sum())
    if inter: return inter, 0.0
    if not ma.any() or not mb.any(): return 0, float(lim)
    d = cv2.distanceTransform((~ma).astype(np.uint8), cv2.DIST_L2, 5)
    return 0, float(min(lim, d[mb].min()))


def line_y(line, x):
    return float(np.interp(x, [p[0] for p in line], [p[1] for p in line]))


# ------------------------------------------------------------------------------------------- rules
def check(tr, scene, P=None):
    P = dict(DEFAULTS, **(P or {}))
    W, H = tr["size"]; fps = tr.get("fps", 24)
    sw, sh_ = scene.get("size", [W, H]); sx, sy = W / sw, H / sh_; k = (sx + sy) / 2
    frames = {fr["f"]: fr for fr in tr["frames"]}
    shots = tr.get("shots") or [dict(id="all", f0=min(frames), f1=max(frames) + 1)]
    out, stairs_log = [], []
    for sh in shots:
        f0s, f1s = sh["f0"], sh["f1"]
        chars = sorted({it["char"] for f in range(f0s, f1s) if f in frames for it in frames[f]["items"]})
        seqs = {c: {} for c in chars}
        for f in range(f0s, f1s):
            for it in frames.get(f, {"items": []})["items"]: seqs[it["char"]][f] = it
        _pairs(seqs, chars, f0s, f1s, scene, sh, fps, k, P, out)
        _stairs(seqs, chars, f0s, f1s, scene, sh, fps, sx, sy, k, out, stairs_log)
    return out, stairs_log


def _box2(a, b):
    x0 = min(a["bbox"][0], b["bbox"][0]); y0 = min(a["bbox"][1], b["bbox"][1])
    x1 = max(a["bbox"][0] + a["bbox"][2], b["bbox"][0] + b["bbox"][2]); y1 = max(a["bbox"][1] + a["bbox"][3], b["bbox"][1] + b["bbox"][3])
    return (x0, y0, x1 - x0, y1 - y0)


def _pairs(seqs, chars, f0s, f1s, scene, sh, fps, k, P, out):
    gap_cfg = scene.get("min_gap_px")
    for i, c1 in enumerate(chars):
        for c2 in chars[i + 1:]:
            ovf, gpf, prev = {}, {}, {}
            for f in range(f0s, f1s):
                a, b = seqs[c1].get(f), seqs[c2].get(f)
                if not a or not b or not a["A"].size or not b["A"].size: prev = {}; continue
                if max(int(a["V"].sum()), int(b["V"].sum())) < P["amin_px"]: prev = {}; continue
                na, nb = int(a["A"].sum()), int(b["A"].sum())
                if na < P["amin_px"] or nb < P["amin_px"]: prev = {}; continue
                mn = min(na, nb)
                lim = gap_cfg * k if gap_cfg is not None else P["gap_frac"] * math.sqrt(min(a.get("exp_area", na), b.get("exp_area", nb)))
                lim = max(2.0, lim)
                inter, gap = screen_gap(a, b, lim)
                moving = (not a["contact"]) or (not b["contact"]) or any(
                    c in prev and math.hypot(it["anchor"][0] - prev[c][0], it["anchor"][1] - prev[c][1]) > 1.0
                    for c, it in ((c1, a), (c2, b)))
                prev = {c1: a["anchor"], c2: b["anchor"]}
                if whitelisted(scene, c1, c2, f, fps): continue
                if inter > P["ov_frac"] * mn: ovf[f] = (inter / mn, a, b)
                elif moving and gap < lim: gpf[f] = (gap, lim, a, b)
            for a_, b_, pl in runs_from(ovf):
                if b_ - a_ + 1 < P["ov_frames"]: continue
                j = int(np.argmax([p[0] for p in pl])); mx, ia, ib = pl[j]
                dgy = abs(ia["ground"][1] - ib["ground"][1])
                out.append(finding("overlap", c1, a_, b_, fps,
                                   f"{c1} and {c2} overlap on screen by up to {mx:.0%} of the smaller silhouette (worst f{a_ + j}) "
                                   f"for {b_ - a_ + 1} frame(s); their ground rows are {dgy:.0f} px apart, and depth does not excuse "
                                   f"it. Not whitelisted in overlap_ok", box=_box2(ia, ib), shot=sh["id"], pair=[c1, c2]))
            for a_, b_, pl in runs_from(gpf):
                if b_ - a_ + 1 < P["gap_frames"]: continue
                mnp = min(p[0] for p in pl)
                out.append(finding("spacing", c1, a_, b_, fps,
                                   f"{c1} and {c2} only {mnp:.0f} px apart (min gap {pl[0][1]:.0f} px) while moving, for {b_ - a_ + 1} frame(s)",
                                   box=_box2(pl[0][2], pl[0][3]), shot=sh["id"], pair=[c1, c2]))


def _stairs(seqs, chars, f0s, f1s, scene, sh, fps, sx, sy, k, out, log_):
    for stc in scene.get("stairs", []):
        if stc.get("shot") and stc["shot"] != sh["id"]: continue
        tol = stc.get("tol_px", 4) * k
        lv = []
        for L in stc["levels"]:
            d = dict(id=L["id"], kind=L.get("kind", "line"))
            if "line" in L: d["line"] = [(x * sx, y * sy) for x, y in L["line"]]; d["x"] = (d["line"][0][0], d["line"][-1][0])
            if "y" in L: d["y"] = [v * sy for v in L["y"]] if isinstance(L["y"], list) else L["y"] * sy
            if "x" in L: d["x"] = (L["x"][0] * sx, L["x"][1] * sx)
            d["multi"] = L.get("multi", d["kind"] in ("band", "below"))      # several hops allowed on a floor or lawn
            lv.append(d)
        th, bottom = lv[0], lv[-1]
        top = th["y"][0] if th["kind"] == "band" else min(p[1] for p in th["line"])
        bottom_y = bottom["y"] if bottom["kind"] == "below" else min(p[1] for p in bottom["line"])
        xs = [d["x"] for d in lv if "x" in d]; zx0 = min(x[0] for x in xs); zx1 = max(x[1] for x in xs)

        def classify(x, y):
            best = None
            for j, d in enumerate(lv):
                if d["kind"] == "band":
                    if d["y"][0] - tol <= y <= d["y"][1] + tol and d["x"][0] <= x <= d["x"][1]: return j, None
                elif d["kind"] == "below":
                    if y >= d["y"] - tol: return j, None
                elif d["x"][0] <= x <= d["x"][1]:
                    e = y - line_y(d["line"], x)
                    if abs(e) <= tol: return j, None
                    if best is None or abs(e) < abs(best[1]): best = (j, e)
            if th["kind"] == "band" and y <= th["y"][1] + tol and zx0 - 400 * sx <= x <= zx1 + 400 * sx:
                return "inside", None                         # the floor behind the threshold (a room, behind a jamb)
            if zx0 <= x <= zx1 and top - tol <= y < bottom_y - tol: return "off", best
            return None, None

        who = stc.get("chars", "*")
        for ch in chars:
            if who != "*" and ch not in who: continue
            lands, pc, ps = [], False, None
            for f in range(f0s, f1s):
                it = seqs[ch].get(f)
                if not it: pc, ps = False, None; continue
                if it["contact"] and (not pc or it["seg"] != ps):                # a new landing
                    x, y = it["anchor"]; c, e = classify(x, y); lands.append((f, x, y, c, e, it))
                pc, ps = it["contact"], it["seg"]
            on_stairs = any(l[3] == "off" or (isinstance(l[3], int) and 0 < l[3] < len(lv) - 1) for l in lands)
            if not on_stairs and not (any(l[3] in (0, "inside") for l in lands) and any(l[3] == len(lv) - 1 for l in lands)):
                continue                                                         # never used these stairs
            names = ["inside" if l[3] == "inside" else "OFF" if l[3] == "off" else "-" if l[3] is None else lv[l[3]]["id"] for l in lands]
            log_.append(dict(char=ch, shot=sh["id"], stairs=stc.get("id", "stairs"),
                             landings=[dict(f=l[0], x=round(l[1], 1), y=round(l[2], 1), on=n) for l, n in zip(lands, names)]))
            cur, seen = None, {}
            for (f, x, y, c, e, it) in lands:
                if c is None: continue
                if c == "off":
                    msg = (f"lands at ({x:.0f}, {y:.0f}), {abs(e[1]):.0f} px {'below' if e[1] > 0 else 'above'} the {lv[e[0]]['id']} "
                           f"tread line (tol {tol:.0f} px): on a riser or between treads") if e else \
                          f"lands at ({x:.0f}, {y:.0f}) on the stairs but off every marked tread's x span"
                    out.append(finding("stairs", ch, f, f, fps, f"{ch} {msg}", box=it["bbox"], shot=sh["id"])); continue
                c = -1 if c == "inside" else c
                if cur is None: cur = c; seen[c] = 1; continue
                if c == cur:
                    seen[c] = seen.get(c, 0) + 1
                    if c >= 0 and not lv[c]["multi"] and seen[c] == 2:
                        out.append(finding("stairs", ch, f, f, fps, f"{ch} lands twice on {lv[c]['id']} (one landing per tread)",
                                           box=it["bbox"], shot=sh["id"]))
                    continue
                if c > cur + 1:
                    miss = [lv[j]["id"] for j in range(max(cur + 1, 0), c)]
                    frm = "inside" if cur < 0 else lv[cur]["id"]
                    out.append(finding("stairs", ch, f, f, fps, f"{ch} jumps {frm} -> {lv[c]['id']} in one hop, skipping {', '.join(miss)}",
                                       box=it["bbox"], shot=sh["id"]))
                elif c < cur and cur >= 0:
                    out.append(finding("stairs", ch, f, f, fps, f"{ch} goes back up {lv[cur]['id']} -> {'inside' if c < 0 else lv[c]['id']}",
                                       box=it["bbox"], shot=sh["id"]))
                cur = c; seen[c] = seen.get(c, 0) + 1


def write_report(out_dir, tracks_path, findings, stairs_log):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "findings.json").write_text(json.dumps(dict(findings=findings, stairs=stairs_log), indent=1))
    p0 = [f for f in findings if f["sev"] == "P0"]
    L = [f"# staging rules: {Path(tracks_path).name}", "",
         f"**{'FAIL' if p0 else 'PASS'}**: {len(p0)} P0 ({sum(f['fault'] == 'overlap' for f in p0)} overlap, "
         f"{sum(f['fault'] == 'spacing' for f in p0)} spacing, {sum(f['fault'] == 'stairs' for f in p0)} stairs)", ""]
    for f in findings:
        L.append(f"- **{f['sev']} {f['fault']}** f{f['f0']}-{f['f1']} ({f['t0']}-{f['t1']} s, shot {f['shot']}): {f['detail']}")
    if stairs_log:
        L += ["", "## Stair landings (check them against the plate)"]
        for s in stairs_log:
            L.append(f"- {s['char']} ({s['stairs']}, shot {s['shot']}): " + " -> ".join(f"{l['on']}@f{l['f']}" for l in s["landings"]))
    (out_dir / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return len(p0)


# ------------------------------------------------------------------------------------------- demo
def _disc(r):
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    return (xx * xx + yy * yy) <= r * r


def _demo_tracks(fixed):
    """Two ball characters (r = 30 px) come out of a doorway, down two treads, onto a lawn. In the faulty version the
    second one follows too close (overlap + spacing) and the first one lands on a riser, then skips step 2."""
    fps, r = 24, 30
    ladder = [(300, 200), (300, 300), (300, 400), (300, 520)]        # threshold, step1, step2, lawn (bottom points)
    if not fixed: ladder = [(300, 200), (300, 314), (300, 520)]      # 14 px down the step-1 riser, then step 2 skipped

    def path(t0, lands, x_off=0):
        keys, t = [], t0
        for (x0, y0), (x1, y1) in zip(lands[:-1], lands[1:]):
            keys.append((t, t + 6, (x0 + x_off, y0), "hold")); t += 6
            keys.append((t, t + 12, ((x0 + x_off, y0), (x1 + x_off, y1)), "hop")); t += 12
        keys.append((t, t + 200, (lands[-1][0] + x_off, lands[-1][1]), "hold"))
        return keys

    def at(keys, f):
        for seg, (a, b, p, kind) in enumerate(keys):
            if a <= f < b:
                if kind == "hold": return p, True, seg
                u = (f - a) / (b - a); (x0, y0), (x1, y1) = p
                return (x0 + (x1 - x0) * u, y0 + (y1 - y0) * u - 60 * math.sin(math.pi * u)), False, seg
        return None, False, None

    chars = {"red": path(0, ladder), "blue": path(24 if fixed else 6, ladder, x_off=80 if fixed else 20)}
    frames = []
    for f in range(0, 140):
        items = []
        for ch, keys in chars.items():
            p, contact, seg = at(keys, f)
            if p is None: continue
            m = _disc(r); x, y = int(round(p[0])) - r, int(round(p[1])) - 2 * r
            items.append(dict(char=ch, bbox=[x, y, 2 * r + 1, 2 * r + 1], alpha=rle_encode(m), vis=rle_encode(m),
                              anchor=[p[0], p[1]], ground=[p[0], p[1]], contact=contact, seg=seg, exp_area=float(m.sum())))
        frames.append(dict(f=f, items=items))
    tracks = dict(fps=fps, size=[600, 700], shots=[dict(id="demo", f0=0, f1=140)], frames=frames)
    scene = dict(size=[600, 700], min_gap_px=20, overlap_ok=[],
                 stairs=[dict(id="steps", tol_px=6, levels=[dict(id="threshold", kind="band", y=[180, 205], x=[200, 460]),
                                                             dict(id="step1", line=[[200, 300], [460, 300]]),
                                                             dict(id="step2", line=[[200, 400], [460, 400]]),
                                                             dict(id="lawn", kind="below", y=500)])])
    return tracks, scene


def main(argv=None):
    ap = argparse.ArgumentParser(description="Staging rules on exact character tracks: screen-space overlap at any depth, "
                                             "spacing while moving, stairs one tread at a time. Exit 1 on any P0.")
    ap.add_argument("--tracks"); ap.add_argument("--scene")
    ap.add_argument("--out", help="output folder (default staging-<tracks stem>/)")
    ap.add_argument("--json", action="store_true", help="print the findings as JSON")
    ap.add_argument("--demo", metavar="DIR", help="write a faulty and a fixed example into DIR and run both")
    a = ap.parse_args(argv)
    if a.demo:
        d = Path(a.demo); d.mkdir(parents=True, exist_ok=True); res = {}
        for name, fixed in (("faulty", False), ("fixed", True)):
            t, s = _demo_tracks(fixed)
            (d / f"{name}_tracks.json").write_text(json.dumps(t, separators=(",", ":"))); (d / f"{name}_scene.json").write_text(json.dumps(s, indent=1))
            fs, log_ = check(load_tracks(d / f"{name}_tracks.json"), s)
            res[name] = write_report(d / name, d / f"{name}_tracks.json", fs, log_)
            print(f"{name}: {res[name]} P0 -> {d / name / 'report.md'}")
        ok = res["faulty"] > 0 and res["fixed"] == 0
        print("demo", "OK (faulty fails, fixed passes)" if ok else "UNEXPECTED")
        return 0 if ok else 2
    if not (a.tracks and a.scene): ap.error("--tracks and --scene are required (or --demo DIR)")
    scene = json.loads(Path(a.scene).read_text())
    fs, log_ = check(load_tracks(a.tracks), scene)
    out = Path(a.out or f"staging-{Path(a.tracks).stem}")
    n = write_report(out, a.tracks, fs, log_)
    if a.json: print(json.dumps(fs, indent=1))
    print(f"{'FAIL' if n else 'PASS'}: {n} P0 -> {out / 'report.md'}")
    return 1 if n else 0


if __name__ == "__main__":
    sys.exit(main())
