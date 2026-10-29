"""actstrip: frame strips + motion measurements for an animation-acting review.

    python tools/qa/actstrip.py CLIP.mp4 [--fps 12] [--overview 6] [--out DIR]
           [--track] [--t0 S --t1 S] [--width 300]

Writes into DIR (default: actstrip-<stem>/ beside the clip):
  overview.jpg        the whole clip at --overview fps (default 6), timestamps burned in, cuts marked red
  strip_NN.jpg        --fps (default 12) frames, 24 per sheet (2 s at 12 fps), timestamps + frame numbers burned in
  motion.png          per-frame motion energy, camera shift, cuts (red), holds (blue), exact repeats (grey ticks)
  report.json/.md     cuts, holds, stepping (ones/twos/threes per shot), motion peaks (candidate contacts/accents),
                      camera-move flag, and with --track per-blob arcs/spacing/volume/contact/anticipation numbers
  key_<t>.jpg         full-size frames at every motion peak and the frame either side (contact, anticipation, settle)

It measures; it does not judge. agents/animation-director.md, ACTING.md and ACTING-MEASURES.md say what the numbers mean.
--track uses a per-shot median background, so it is only trusted on locked-off shots (the report says when the camera
moves; then use the strips and your eyes, or tracks exported by the renderer).
"""
import argparse, json, math, os, sys
import cv2
import numpy as np


def read_frames(path, t0=None, t1=None, max_w=480):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    frames, idx = [], 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        t = idx / fps
        idx += 1
        if t0 is not None and t < t0:
            continue
        if t1 is not None and t > t1:
            break
        h, w = f.shape[:2]
        if w > max_w:
            f = cv2.resize(f, (max_w, int(h * max_w / w)), interpolation=cv2.INTER_AREA)
        frames.append((idx - 1, t, f))
    cap.release()
    return fps, frames


def label(img, text, color=(255, 255, 255)):
    out = img.copy()
    cv2.rectangle(out, (0, 0), (out.shape[1], 18), (0, 0, 0), -1)
    cv2.putText(out, text, (3, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)
    return out


def tile(imgs, cols, w):
    if not imgs:
        return None
    th = int(imgs[0].shape[0] * w / imgs[0].shape[1])
    cells = [cv2.resize(i, (w, th), interpolation=cv2.INTER_AREA) for i in imgs]
    while len(cells) % cols:
        cells.append(np.zeros_like(cells[0]))
    rows = [np.hstack(cells[r:r + cols]) for r in range(0, len(cells), cols)]
    return np.vstack(rows)


def main():
    ap = argparse.ArgumentParser(description="Frame strips + motion measurements (cuts, stepping, holds, peaks) for an acting review.")
    ap.add_argument("clip")
    ap.add_argument("--fps", type=float, default=12)
    ap.add_argument("--overview", type=float, default=6)
    ap.add_argument("--out")
    ap.add_argument("--track", action="store_true")
    ap.add_argument("--t0", type=float)
    ap.add_argument("--t1", type=float)
    ap.add_argument("--width", type=int, default=300)
    a = ap.parse_args()

    stem = os.path.splitext(os.path.basename(a.clip))[0]
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.clip)), f"actstrip-{stem}")
    os.makedirs(out, exist_ok=True)
    fps, frames = read_frames(a.clip, a.t0, a.t1)
    if not frames:
        sys.exit("no frames")
    n = len(frames)
    gray = [cv2.GaussianBlur(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (5, 5), 0).astype(np.float32) for _, _, f in frames]

    # motion energy, exact repeats, camera shift (phase correlation), cut score (histogram distance)
    energy, frac, repeat, cam, cutscore = [0.0], [0.0], [False], [0.0], [0.0]
    hists = [cv2.calcHist([f], [0, 1, 2], None, [8, 8, 8], [0, 256] * 3) for _, _, f in frames]
    for h in hists:
        cv2.normalize(h, h)
    win = cv2.createHanningWindow(gray[0].shape[::-1], cv2.CV_32F)
    for i in range(1, n):
        d = np.abs(gray[i] - gray[i - 1])
        energy.append(float(d.mean()))
        frac.append(float((d > 8).mean()))
        repeat.append(bool((d > 8).mean() < 0.0002))
        (dx, dy), _ = cv2.phaseCorrelate(gray[i - 1], gray[i], win)
        cam.append(float(math.hypot(dx, dy)))
        cutscore.append(float(cv2.compareHist(hists[i - 1], hists[i], cv2.HISTCMP_BHATTACHARYYA)))
    energy = np.array(energy); cam = np.array(cam); cutscore = np.array(cutscore)
    frac = np.array(frac)
    # changed-pixel fraction over a 2-frame window, so twos/threes stepping does not read as a hold
    act = np.maximum(frac, np.concatenate([[0.0], frac[:-1]]))
    act3 = np.maximum(act, np.concatenate([[0.0], act[:-1]]))

    frac_np = np.array(frac)
    cuts = []
    for i in range(1, n):
        hist_cut = cutscore[i] > 0.35 and cutscore[i] > 3 * np.median(cutscore[max(1, i - 12):i + 12])
        # same-palette cuts (a reframe of the same set): most pixels change in ONE frame while neighbours are calm
        nb = np.concatenate([frac_np[max(1, i - 6):i], frac_np[i + 1:i + 7]])
        spike_cut = frac_np[i] > 0.25 and (nb.size == 0 or frac_np[i] > 5 * max(0.01, float(np.median(nb))))
        if hist_cut or spike_cut:
            cuts.append(i)
    shots = []
    bounds = [0] + cuts + [n]
    for s, e in zip(bounds[:-1], bounds[1:]):
        if e - s < 2:
            continue
        seg_rep = repeat[s + 1:e]
        rep_frac = float(np.mean(seg_rep)) if seg_rep else 0.0
        # stepping estimate: median run length of changes
        runs, r = [], 1
        for k in range(s + 1, e):
            if repeat[k]:
                r += 1
            else:
                runs.append(r); r = 1
        runs.append(r)
        step = float(np.median(runs)) if runs else 1.0
        rate = {1: "ones", 2: "twos", 3: "threes"}.get(int(round(step)), f"{step:.1f}s")
        cam_mean = float(np.mean(cam[s + 1:e])) if e - s > 1 else 0.0
        global_change = float(np.mean(act[s + 1:e] > 0.08)) if e - s > 1 else 0.0
        shots.append({"start_f": frames[s][0], "end_f": frames[e - 1][0], "start_s": round(frames[s][1], 3),
                      "end_s": round(frames[e - 1][1], 3), "repeat_frac": round(rep_frac, 3), "stepping": rate,
                      "camera_px_per_frame": round(cam_mean, 2),
                      "global_change_frac": round(global_change, 3),
                      "camera_moves": cam_mean > 0.6 or global_change > 0.2})

    # holds: runs of drawings where (almost) nothing changes. "dead" = every frame an exact repeat (a frozen frame);
    # "near" = under 0.03% of pixels change per drawing (a held pose, maybe with tiny living motion elsewhere)
    holds, i = [], 1
    while i < n:
        if act3[i] < 0.0003 and i not in cuts:
            j = i
            while j < n and act3[j] < 0.0003 and j not in cuts:
                j += 1
            if (j - i) / fps >= 0.25:
                holds.append({"start_s": round(frames[i - 1][1], 3), "end_s": round(frames[j - 1][1], 3),
                              "dur_s": round((j - i + 1) / fps, 3),
                              "kind": "dead (exact repeats)" if all(repeat[i:j]) else "near hold"})
            i = j
        else:
            i += 1

    # activity per half second (share of pixels changing) so the reviewer sees where the action is
    activity = []
    half = max(1, int(round(fps / 2)))
    for k in range(1, n, half):
        activity.append({"t": round(frames[k][1], 2), "changed_pct": round(float(act[k:k + half].mean()) * 100, 3),
                         "camera_px": round(float(cam[k:k + half].mean()), 2)})

    # motion peaks: local maxima of activity (candidate accents, snaps, contacts), not on cuts
    sm = np.convolve(act, np.ones(3) / 3, mode="same")
    peaks = []
    for k in range(2, n - 2):
        if any(abs(k - c) <= 1 for c in cuts):
            continue
        if sm[k] == max(sm[max(0, k - 4):k + 5]) and sm[k] > 0.002 and sm[k] > 1.3 * np.median(sm[max(1, k - 24):k + 24]):
            peaks.append(k)
    peaks = peaks[:40]

    # sheets
    def stamp(k, extra=""):
        fidx, t, f = frames[k]
        col = (80, 80, 255) if k in cuts else (255, 255, 255)
        return label(f, f"{t:5.2f}s f{fidx}{extra}", col)

    step_o = max(1, int(round(fps / a.overview)))
    ov = [stamp(k) for k in range(0, n, step_o)]
    cv2.imwrite(os.path.join(out, "overview.jpg"), tile(ov, 8, 180), [cv2.IMWRITE_JPEG_QUALITY, 85])
    step_s = max(1, int(round(fps / a.fps)))
    idxs = list(range(0, n, step_s))
    sheets = []
    for sidx, c in enumerate(range(0, len(idxs), 24)):
        imgs = [stamp(k, " PEAK" if k in peaks else "") for k in idxs[c:c + 24]]
        p = os.path.join(out, f"strip_{sidx:02d}.jpg")
        cv2.imwrite(p, tile(imgs, 6, a.width), [cv2.IMWRITE_JPEG_QUALITY, 85])
        sheets.append(os.path.basename(p))
    # key frames around peaks (full res of the read size)
    keys = []
    for k in peaks[:16]:
        trip = [stamp(max(0, k - 2)), stamp(k, " PEAK"), stamp(min(n - 1, k + 2))]
        p = os.path.join(out, f"key_{frames[k][1]:06.2f}.jpg")
        cv2.imwrite(p, np.hstack(trip), [cv2.IMWRITE_JPEG_QUALITY, 88])
        keys.append(os.path.basename(p))

    # motion plot
    H, W = 260, max(600, n * 3)
    plot = np.full((H, W, 3), 255, np.uint8)
    em = max(1e-6, float(energy.max()))
    cm = max(1e-6, float(cam.max()))
    for k in range(1, n):
        x0, x1 = int((k - 1) / n * W), int(k / n * W)
        cv2.line(plot, (x0, H - 20 - int(energy[k - 1] / em * 200)), (x1, H - 20 - int(energy[k] / em * 200)), (0, 0, 0), 1)
        cv2.line(plot, (x0, H - 20 - int(cam[k - 1] / cm * 60)), (x1, H - 20 - int(cam[k] / cm * 60)), (0, 160, 0), 1)
        if repeat[k]:
            cv2.line(plot, (x1, H - 18), (x1, H - 12), (150, 150, 150), 1)
    for h in holds:
        x0 = int(h["start_s"] * fps / n * W); x1 = int(h["end_s"] * fps / n * W)
        cv2.rectangle(plot, (x0, 2), (x1, 12), (255, 120, 0), -1)
    for c in cuts:
        x = int(c / n * W); cv2.line(plot, (x, 0), (x, H), (0, 0, 255), 1)
    for s in range(int(frames[-1][1]) + 1):
        x = int(s * fps / n * W); cv2.putText(plot, f"{s}s", (x + 2, H - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1)
    cv2.imwrite(os.path.join(out, "motion.png"), plot)

    report = {"clip": os.path.abspath(a.clip), "fps": fps, "frames": n, "duration_s": round(n / fps, 3),
              "cuts_s": [round(frames[c][1], 3) for c in cuts], "shots": shots, "holds": holds,
              "peaks_s": [round(frames[k][1], 3) for k in peaks], "activity": activity, "sheets": sheets, "keys": keys}

    if a.track:
        report["tracks"] = track(frames, gray, bounds, fps, shots)

    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(report, f, indent=1)
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as f:
        f.write(f"# actstrip {stem}\n\n{n} frames at {fps:g} fps ({n / fps:.2f} s). Cuts at {report['cuts_s']}.\n\n")
        f.write("| shot | s | stepping | repeats | camera px/f | camera moves |\n|---|---|---|---|---|---|\n")
        for i, s in enumerate(shots):
            f.write(f"| {i + 1} | {s['start_s']}-{s['end_s']} | {s['stepping']} | {s['repeat_frac']} | "
                    f"{s['camera_px_per_frame']} | {s['camera_moves']} |\n")
        f.write("\n## Holds (>= 0.25 s)\n")
        for h in holds:
            f.write(f"- {h['start_s']}-{h['end_s']} s ({h['dur_s']} s) {h['kind']}\n")
        f.write(f"\n## Motion peaks (candidate contacts / accents)\n{report['peaks_s']}\n")
        if a.track:
            f.write("\n## Tracks (locked-off shots only)\n")
            for t in report["tracks"]:
                f.write(f"- {json.dumps(t)}\n")
        f.write("\nSheets: " + ", ".join(sheets) + "\nKey triplets (peak-2, peak, peak+2 frames): " + ", ".join(keys) + "\n")
    print(json.dumps({k: report[k] for k in ("duration_s", "cuts_s", "shots", "holds", "peaks_s")}, indent=1))
    print("wrote", out)


def track(frames, gray, bounds, fps, shots):
    """EXPERIMENTAL. Largest-blob tracks per locked-off shot; only meaningful for ONE character on a still plate
    (area ratios outside 0.5-2 mean the blob is not one character: ignore the numbers): centroid path, spacing, area (volume), contacts, anticipation."""
    res = []
    for si, (s, e) in enumerate(zip(bounds[:-1], bounds[1:])):
        if e - s < 8:
            continue
        sh = next((x for x in shots if x["start_f"] == frames[s][0]), None)
        if sh and sh["camera_moves"]:
            res.append({"shot": si + 1, "skipped": "camera moves; use strips or renderer tracks"})
            continue
        bg = np.median(np.stack(gray[s:e][::max(1, (e - s) // 40)]), axis=0)
        cents, areas, bottoms, heights = [], [], [], []
        for k in range(s, e):
            m = (np.abs(gray[k] - bg) > 18).astype(np.uint8)
            m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            cnt, lab, stats, cen = cv2.connectedComponentsWithStats(m)
            if cnt <= 1:
                cents.append(None); areas.append(0); bottoms.append(None); heights.append(None); continue
            j = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            x, y, w, h, ar = stats[j]
            cents.append((float(cen[j][0]), float(cen[j][1]))); areas.append(int(ar))
            bottoms.append(int(y + h)); heights.append(int(h))
        valid = [c for c in cents if c]
        if len(valid) < 6:
            continue
        P = np.array(valid)
        steps = np.linalg.norm(np.diff(P, axis=0), axis=1)
        path = float(steps.sum()); chord = float(np.linalg.norm(P[-1] - P[0]))
        A = np.array([a for a in areas if a > 0], float)
        bots = [b for b in bottoms if b is not None]
        contacts = [i for i in range(1, len(bots) - 1) if bots[i] >= bots[i - 1] and bots[i] > bots[i + 1]]
        res.append({"shot": si + 1, "largest_blob_only": True,
                    "path_px": round(path, 1), "chord_px": round(chord, 1),
                    "straightness": round(chord / path, 3) if path else None,
                    "spacing_cv": round(float(steps.std() / steps.mean()), 3) if steps.mean() > 0 else None,
                    "area_min_max_over_median": [round(float(A.min() / np.median(A)), 3), round(float(A.max() / np.median(A)), 3)],
                    "contact_frames_rel": contacts[:30]})
    return res


if __name__ == "__main__":
    main()
