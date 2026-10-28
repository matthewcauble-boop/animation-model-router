"""matte_gate: catch a character matte that ate part of the character (a colour key that removed green trousers on
green grass, a segmenter that dropped a hand) before it reaches the cut. Free, local, deterministic.

    python tools/qa/matte_gate.py --masks mattes/ --ref approved_mask.png [--frames frames/] [--ref-frame approved.png]
           [--color trousers=#2f8f3a~40 --color boots=#3a2a20-#6b5040] [--tol 0.10] [--color-tol 0.10]
           [--max-holes 0.01] [--min-part 0.005] [--label N] [--norm none|height] [--out matte-gate/]
    python tools/qa/matte_gate.py --demo DIR    # synthetic sequence with one eaten frame and one holed frame

Inputs
  --masks      a folder of per-frame masks: greyscale or binary PNG (white = character), RGBA cutouts (alpha is the
               mask, colours come from the same file), or SAM-style label PNGs with --label N (pixels == N).
  --ref        the mask of the approved still (same kinds as above). The reference sets every target.
  --frames     optional RGB frames, matched to the masks by file stem, else by sorted order; needed for --color
               unless the masks are RGBA cutouts.
  --ref-frame  RGB of the approved still, for --color when --ref is not an RGBA cutout.

Checks per frame (each against the reference)
  area         silhouette area / reference area, within 1 +- --tol (default 10%). --norm height divides out the
               scale change (area / bbox height^2) for shots where the character moves in depth.
  colour       pixels inside the matte that match each --color range / the same count on the reference, within
               1 +- --color-tol. NAME=#hex~T (each channel within T) or NAME=#lo-#hi (per-channel box).
               This is the check that catches "the trousers are gone".
  holes        area of interior gaps (filled silhouette minus silhouette) as a fraction of the silhouette; fails if
               it grows by more than --max-holes over the reference.
  parts        connected pieces bigger than --min-part of the silhouette; fails if there are more than the
               reference has (a floating belt, a detached hand).

Outputs: OUT/report.md, OUT/report.json, OUT/failing.jpg (each failing frame beside the reference: matte tinted,
holes red, extra parts yellow, reasons printed). Exit code 1 on any failing frame, 0 when all pass.
Needs numpy, opencv-python-headless, Pillow.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def list_images(d):
    return sorted(p for p in Path(d).iterdir() if p.suffix.lower() in IMG_EXT)


def read_any(p):
    im = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
    if im is None:
        raise SystemExit(f"cannot read {p}")
    return im


def to_mask(im, label=None):
    """Return (bool mask, rgb or None). RGBA -> alpha + its colours; label PNG -> == label; else > 127."""
    rgb = None
    if im.ndim == 3 and im.shape[2] == 4:
        m = im[:, :, 3] > 127
        rgb = im[:, :, 2::-1].copy()
    elif label is not None:
        g = im if im.ndim == 2 else im[:, :, 0]
        m = g == label
    else:
        g = im if im.ndim == 2 else cv2.cvtColor(im[:, :, :3], cv2.COLOR_BGR2GRAY)
        m = g > 127
    return m, rgb


def parse_color(spec):
    name, _, rng = spec.partition("=")
    if not rng:
        raise SystemExit(f"--color needs NAME=#hex~T or NAME=#lo-#hi, got {spec}")

    def hx(h):
        h = h.strip().lstrip("#")
        return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.int32)
    m = re.match(r"^\s*(#?[0-9a-fA-F]{6})\s*~\s*(\d+)\s*$", rng)
    if m:
        c, t = hx(m.group(1)), int(m.group(2))
        return name, np.clip(c - t, 0, 255), np.clip(c + t, 0, 255)
    m = re.match(r"^\s*(#?[0-9a-fA-F]{6})\s*-\s*(#?[0-9a-fA-F]{6})\s*$", rng)
    if m:
        a, b = hx(m.group(1)), hx(m.group(2))
        return name, np.minimum(a, b), np.maximum(a, b)
    raise SystemExit(f"bad --color range {spec}")


def fill_holes(m):
    """Silhouette with interior gaps filled (flood fill the background from the border)."""
    h, w = m.shape
    pad = np.zeros((h + 2, w + 2), np.uint8)
    pad[1:-1, 1:-1] = m.astype(np.uint8)
    ff = pad.copy()
    cv2.floodFill(ff, np.zeros((h + 4, w + 4), np.uint8), (0, 0), 2)
    return (ff[1:-1, 1:-1] != 2)


def measure(m, rgb, colors, min_part):
    area = int(m.sum())
    out = dict(area=area)
    if area == 0:
        return dict(area=0, bbox_h=0, holes=0, hole_frac=0.0, parts=0, colors={k: 0 for k, _, _ in colors},
                    hole_mask=np.zeros_like(m), labels=None, keep=[])
    ys, xs = np.nonzero(m)
    out["bbox"] = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
    out["bbox_h"] = int(ys.max() - ys.min() + 1)
    filled = fill_holes(m)
    hole = filled & ~m
    out["holes"] = int(hole.sum())
    out["hole_frac"] = out["holes"] / area
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    keep = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= min_part * area]
    out["parts"] = len(keep)
    cols = {}
    if colors:
        if rgb is None:
            cols = {k: None for k, _, _ in colors}
        else:
            px = rgb.astype(np.int32)
            for k, lo, hi in colors:
                inr = np.all((px >= lo) & (px <= hi), axis=2)
                cols[k] = int((inr & m).sum())
    out["colors"] = cols
    out["hole_mask"], out["labels"], out["keep"] = hole, lab, keep
    return out


def judge(mm, ref, a):
    reasons = []
    ratio = mm["area"] / max(1, ref["area"])
    if a.norm == "height" and mm["area"] and ref["area"]:
        ratio = (mm["area"] / mm["bbox_h"] ** 2) / (ref["area"] / ref["bbox_h"] ** 2)
    res = dict(area_ratio=round(ratio, 4))
    if abs(ratio - 1) > a.tol:
        reasons.append(f"area {ratio:.0%} of ref (tol +-{a.tol:.0%})")
    cr = {}
    for k, v in mm["colors"].items():
        rv = ref["colors"].get(k)
        if v is None or rv is None:
            cr[k] = None
            continue
        if rv == 0:
            cr[k] = None if v == 0 else float("inf")
            if v > 0.002 * max(1, ref["area"]):
                reasons.append(f"{k}: {v} px, none on ref")
            continue
        r = v / rv
        cr[k] = round(r, 4)
        if abs(r - 1) > a.color_tol:
            reasons.append(f"{k} {r:.0%} of ref (tol +-{a.color_tol:.0%})")
    res["color_ratio"] = cr
    dh = mm["hole_frac"] - ref["hole_frac"]
    res["hole_frac"] = round(mm["hole_frac"], 4)
    if dh > a.max_holes:
        reasons.append(f"holes {mm['hole_frac']:.1%} of silhouette (ref {ref['hole_frac']:.1%})")
    res["parts"] = mm["parts"]
    if mm["parts"] > ref["parts"]:
        reasons.append(f"{mm['parts']} separate parts (ref {ref['parts']})")
    if mm["area"] == 0:
        reasons = ["empty matte"]
    res["reasons"] = reasons
    res["ok"] = not reasons
    return res


def font(sz):
    for f in ("arial.ttf", "DejaVuSans.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(f, sz)
        except OSError:
            continue
    return ImageFont.load_default()


def panel(m, rgb, meas, title, lines, cell=360):
    h, w = m.shape
    base = rgb.copy() if rgb is not None else np.full((h, w, 3), 40, np.uint8)
    over = base.astype(np.float32)
    over[m] = over[m] * 0.55 + np.array([60, 200, 255]) * 0.45
    if meas.get("hole_mask") is not None:
        over[meas["hole_mask"]] = (255, 40, 40)
    lab, keep = meas.get("labels"), meas.get("keep") or []
    if lab is not None and len(keep) > 1:
        sizes = [(int((lab == i).sum()), i) for i in keep]
        biggest = max(sizes)[1]
        for _, i in sizes:
            if i != biggest:
                over[lab == i] = (255, 220, 0)
    img = Image.fromarray(over.clip(0, 255).astype(np.uint8))
    if "bbox" in meas:                                   # crop to the character with a margin
        x0, y0, x1, y1 = meas["bbox"]
        mg = int(0.15 * max(x1 - x0, y1 - y0)) + 8
        img = img.crop((max(0, x0 - mg), max(0, y0 - mg), min(w, x1 + mg), min(h, y1 + mg)))
    img.thumbnail((cell, cell))
    tile = Image.new("RGB", (cell, cell + 22 + 18 * len(lines)), (18, 18, 22))
    tile.paste(img, ((cell - img.width) // 2, 22))
    d = ImageDraw.Draw(tile)
    d.text((6, 3), title, fill=(235, 235, 235), font=font(15))
    for i, ln in enumerate(lines):
        d.text((6, cell + 24 + 18 * i), ln, fill=(255, 120, 110), font=font(13))
    return tile


def run(a):
    ref_im = read_any(a.ref)
    ref_m, ref_rgb = to_mask(ref_im, a.label)
    if a.ref_frame:
        ref_rgb = read_any(a.ref_frame)[:, :, 2::-1].copy()
    colors = [parse_color(c) for c in a.color or []]
    ref = measure(ref_m, ref_rgb, colors, a.min_part)
    if ref["area"] == 0:
        raise SystemExit("reference mask is empty")
    for k, v in ref["colors"].items():
        if v is None:
            raise SystemExit(f"--color {k}: no colours for the reference (use an RGBA cutout or --ref-frame)")
    masks = list_images(a.masks)
    if not masks:
        raise SystemExit(f"no images in {a.masks}")
    frames = {}
    if a.frames:
        fl = list_images(a.frames)
        by_stem = {p.stem: p for p in fl}
        frames = {m: by_stem.get(m.stem) for m in masks}
        if not all(frames.values()):
            if len(fl) != len(masks):
                raise SystemExit("frames do not match masks by stem or by count")
            frames = dict(zip(masks, fl))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows, fails = [], []
    for mp in masks:
        m, rgb = to_mask(read_any(mp), a.label)
        if mp in frames and frames[mp] is not None:
            rgb = read_any(frames[mp])[:, :, 2::-1].copy()
        mm = measure(m, rgb, colors, a.min_part)
        if colors and rgb is None:
            raise SystemExit(f"{mp.name}: --color needs RGBA masks or --frames")
        res = judge(mm, ref, a)
        res["frame"] = mp.name
        rows.append(res)
        if not res["ok"]:
            fails.append((mp, m, rgb, mm, res))
    ref_res = dict(area=ref["area"], hole_frac=round(ref["hole_frac"], 4), parts=ref["parts"], colors=ref["colors"])
    summary = dict(ref=str(a.ref), frames=len(rows), failing=len(fails), tol=a.tol, color_tol=a.color_tol,
                   max_holes=a.max_holes, reference=ref_res, rows=rows)
    (out / "report.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    md = [f"# Matte gate: {'FAIL' if fails else 'PASS'}", "",
          f"{len(rows)} frames against `{Path(a.ref).name}`; {len(fails)} failing. "
          f"Area tol +-{a.tol:.0%}, colour tol +-{a.color_tol:.0%}, hole growth max {a.max_holes:.1%}.", "",
          "| Frame | Area | " + " | ".join(k for k, _, _ in colors) + (" | " if colors else "") + "Holes | Parts | Result |",
          "|---|---|" + "---|" * len(colors) + "---|---|---|"]
    for r in rows:
        cs = " | ".join("-" if r["color_ratio"].get(k) is None else f"{r['color_ratio'][k]:.0%}" for k, _, _ in colors)
        md.append(f"| {r['frame']} | {r['area_ratio']:.0%} | " + (cs + " | " if colors else "")
                  + f"{r['hole_frac']:.1%} | {r['parts']} | {'ok' if r['ok'] else 'P0: ' + '; '.join(r['reasons'])} |")
    if fails:
        md += ["", "Failing frames are on `failing.jpg` beside the reference: matte tinted blue, holes red, extra parts"
               " yellow. Re-matte with a segmenter, the clip's own alpha or a difference against the clean plate; never"
               " a colour key on a character that shares the background's colours."]
    (out / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    if fails:
        tiles = [panel(ref_m, ref_rgb, ref, "REFERENCE", [])]
        for mp, m, rgb, mm, res in fails[:23]:
            tiles.append(panel(m, rgb, mm, mp.name, res["reasons"][:4]))
        cw = max(t.width for t in tiles)
        ch = max(t.height for t in tiles)
        cols = min(4, len(tiles))
        rws = (len(tiles) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * cw, rws * ch), (10, 10, 12))
        for i, t in enumerate(tiles):
            sheet.paste(t, ((i % cols) * cw, (i // cols) * ch))
        sheet.save(out / "failing.jpg", quality=90)
    print(f"matte gate: {len(rows)} frames, {len(fails)} failing -> {out / 'report.md'}")
    for mp, _, _, _, res in fails:
        print(f"  P0 {mp.name}: {'; '.join(res['reasons'])}")
    return 1 if fails else 0


def demo(d):
    """A cartoon figure (round body, green trousers, dark boots) on frames 0-11; frame 6 has the trousers keyed out
    (the floating-belt failure), frame 9 has a hole punched in the body. Both must fail; the rest must pass."""
    d = Path(d)
    md, fd = d / "mattes", d / "frames"
    md.mkdir(parents=True, exist_ok=True)
    fd.mkdir(parents=True, exist_ok=True)
    W, H = 480, 640
    BODY, TROUSERS, BOOTS, BELT = (240, 150, 40), (47, 143, 58), (70, 50, 35), (30, 30, 30)

    def figure(dx, dy, eaten=False, hole=False):
        rgb = np.zeros((H, W, 3), np.uint8)
        rgb[:] = (60, 150, 60)                                  # green grass everywhere: the trap
        rgb[:200] = (150, 200, 235)
        m = np.zeros((H, W), np.uint8)
        cx, cy = 240 + dx, 250 + dy
        cv2.circle(m, (cx, cy), 95, 1, -1)
        cv2.circle(rgb, (cx, cy), 95, BODY, -1)
        cv2.rectangle(m, (cx - 60, cy + 80), (cx + 60, cy + 98), 1, -1)       # belt
        cv2.rectangle(rgb, (cx - 60, cy + 80), (cx + 60, cy + 98), BELT, -1)
        if not eaten:
            for sx in (-35, 35):                                                # trouser legs
                cv2.rectangle(m, (cx + sx - 22, cy + 98), (cx + sx + 22, cy + 200), 1, -1)
                cv2.rectangle(rgb, (cx + sx - 22, cy + 98), (cx + sx + 22, cy + 200), TROUSERS, -1)
        for sx in (-35, 35):                                                    # boots
            cv2.rectangle(m, (cx + sx - 28, cy + 200), (cx + sx + 28, cy + 232), 1, -1)
            cv2.rectangle(rgb, (cx + sx - 28, cy + 200), (cx + sx + 28, cy + 232), BOOTS, -1)
        cv2.circle(rgb, (cx - 30, cy - 20), 12, (255, 255, 255), -1)
        cv2.circle(rgb, (cx + 30, cy - 20), 12, (255, 255, 255), -1)
        if hole:
            cv2.circle(m, (cx + 20, cy + 30), 22, 0, -1)
        return m * 255, rgb

    rm, rr = figure(0, 0)
    cv2.imwrite(str(d / "ref_mask.png"), rm)
    cv2.imwrite(str(d / "ref_frame.png"), rr[:, :, ::-1])
    for i in range(12):
        m, rgb = figure(int(6 * np.sin(i / 2)), int(3 * np.cos(i / 3)), eaten=i == 6, hole=i == 9)
        cv2.imwrite(str(md / f"f{i:03d}.png"), m)
        cv2.imwrite(str(fd / f"f{i:03d}.png"), rgb[:, :, ::-1])
    args = ["--masks", str(md), "--frames", str(fd), "--ref", str(d / "ref_mask.png"), "--ref-frame",
            str(d / "ref_frame.png"), "--color", "trousers=#2f8f3a~25", "--color", "boots=#463223~20",
            "--out", str(d / "matte-gate")]
    a = parser().parse_args(args)
    code = run(a)
    rep = json.loads((d / "matte-gate" / "report.json").read_text(encoding="utf-8"))
    bad = sorted(r["frame"] for r in rep["rows"] if not r["ok"])
    assert code == 1 and bad == ["f006.png", "f009.png"], bad
    # the good frames alone must pass
    good = d / "good"
    good.mkdir(exist_ok=True)
    for p in md.iterdir():
        if p.name not in bad:
            (good / p.name).write_bytes(p.read_bytes())
    a2 = parser().parse_args(["--masks", str(good), "--frames", str(fd), "--ref", str(d / "ref_mask.png"),
                              "--ref-frame", str(d / "ref_frame.png"), "--color", "trousers=#2f8f3a~25",
                              "--out", str(d / "matte-gate-good")])
    assert run(a2) == 0
    print("demo OK: eaten and holed frames fail, good frames pass ->", d / "matte-gate" / "failing.jpg")
    return 0


def parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--masks")
    ap.add_argument("--ref")
    ap.add_argument("--frames")
    ap.add_argument("--ref-frame")
    ap.add_argument("--color", action="append", help="NAME=#hex~T or NAME=#lo-#hi (repeatable)")
    ap.add_argument("--tol", type=float, default=0.10)
    ap.add_argument("--color-tol", type=float, default=0.10)
    ap.add_argument("--max-holes", type=float, default=0.01)
    ap.add_argument("--min-part", type=float, default=0.005)
    ap.add_argument("--label", type=int)
    ap.add_argument("--norm", choices=["none", "height"], default="none")
    ap.add_argument("--out", default="matte-gate")
    ap.add_argument("--demo", metavar="DIR")
    return ap


def main():
    a = parser().parse_args()
    if a.demo:
        return demo(a.demo)
    if not (a.masks and a.ref):
        parser().error("--masks and --ref are required (or --demo DIR)")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
