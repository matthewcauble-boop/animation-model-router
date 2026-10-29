"""ambient: gentle outdoor motion composited onto rendered frames of a painted world: a breeze in the lawn, ripples
and glints on the pond, streaks down a painted waterfall, drifting motes. $0, CPU, about 1.1-1.4 s a 1080x1920 frame.

It is world-anchored and frame-exact: the breeze is a wave field on the ground plane (z = 0) in world metres, found
through each frame's camera, so a wide and a medium of the same world sway together across a cut and nothing swims
with the camera. Timing per layer, like a Ghibli background animator: grass on threes (8 new drawings a second), water
and motes on twos (12 a second), the camera on ones; the output stays 24 fps.

Masks come from a Blender pass (ambient_masks.py: R = lawn, G = water, B = path). The path, steps, buildings and
characters never move: the lawn warp fades to zero 2-10 px inside the lawn and samples only lawn pixels.
Two lessons are built in. A per-pixel "tips move more" warp melted every brush stroke (it looked liquified), so the warp
stays rigid on the scale of a stroke (smoothed over ~7 px) and the tips move by LIGHT (a highlight shimmer) instead.
And the first amplitude was too subtle to see on a phone: 2.1 cm of sway is the default now.

    # frames of a moving camera, one mask + camera per frame
    python tools/blender/ambient.py --frames work/bw/wide --masks work/bw/masks/wide --out work/bw/wide_amb
    # a locked shot: ONE clean still moves; characters rendered on depth cards go back on top, untouched
    python tools/blender/ambient.py --still work/bw/clean/clean.png --masks work/bw/masks/med --mask-frame 96 \
           --chars work/bw/med --out work/bw/med_amb
    # the empty set, 5 s, to judge the motion on its own
    python tools/blender/ambient.py --still clean.png --masks masks/med --mask-frame 96 --seconds 5 --out amb_yard
    python tools/blender/ambient.py --demo work/amb-demo      # synthetic world: lawn moves, path and house don't
Options: --amp 0.021 (m) --wave 1.7 (m) --period 4.2 (s) --wind 18 (degrees) --grass-n 3 --water-n 2 --motes 16
--card card_rgba.png --falls-roi x0,y0,x1,y1 --falls-foam x0,y0,x1,y1 (waterfall region and foam band, card pixels).
Writes <out>/f_0001.png ... and <out>/motion/m_0001.png (where anything was allowed to move, for frozen_check.py).
Needs numpy + opencv-python-headless.
"""
import argparse, json, math, os, sys

import cv2
import numpy as np

FPS = 24


# ------------------------------------------------------------------------------------------------ camera
class Cam:
    def __init__(self, d, W, H):
        self.M = np.array(d["mw"], np.float64); self.Mi = np.linalg.inv(self.M)
        self.f = d["lens"]; self.shx, self.shy = d["shift"]; self.S = d["sensor"]; self.W, self.H = W, H
        fit = d.get("fit", "VERTICAL")
        if fit == "AUTO": fit = "HORIZONTAL" if W >= H else "VERTICAL"
        if fit == "VERTICAL": self.sh, self.sw = self.S, self.S * W / H
        else: self.sw, self.sh = self.S, self.S * H / W
        self.o = self.M[:3, 3]

    def project(self, P):
        """P (..., 3) world -> px, py, depth"""
        Pc = P @ self.Mi[:3, :3].T + self.Mi[:3, 3]
        z = -Pc[..., 2]; zs = np.maximum(z, 1e-6)
        X = self.f * Pc[..., 0] / zs; Y = self.f * Pc[..., 1] / zs
        u = (X - self.shx * self.S) / self.sw + 0.5; v = (Y - self.shy * self.S) / self.sh + 0.5
        return u * self.W, (1 - v) * self.H, z

    def rays(self, px, py):
        u = px / self.W - 0.5; v = 0.5 - py / self.H
        d = np.stack([(u * self.sw + self.shx * self.S) / self.f, (v * self.sh + self.shy * self.S) / self.f, -np.ones_like(u)], -1)
        d = d @ self.M[:3, :3].T
        return d / np.linalg.norm(d, axis=-1, keepdims=True)

    def ground(self, step=4, z0=0.0):
        """world (X, Y) of the z = z0 ground plane under every pixel (full res, from a coarse grid)"""
        gy, gx = np.mgrid[0:self.H:step, 0:self.W:step].astype(np.float64)
        d = self.rays(gx + 0.5, gy + 0.5); t = (z0 - self.o[2]) / np.where(np.abs(d[..., 2]) < 1e-6, -1e-6, d[..., 2])
        t = np.where(t > 0, t, 1e3)
        P = self.o + d * t[..., None]
        X = cv2.resize(P[..., 0].astype(np.float32), (self.W, self.H), interpolation=cv2.INTER_LINEAR)
        Y = cv2.resize(P[..., 1].astype(np.float32), (self.W, self.H), interpolation=cv2.INTER_LINEAR)
        return X, Y


def load_cams(path):
    d = json.load(open(path)); W, H = d["size"]
    return {int(k): Cam(v, W, H) for k, v in d["frames"].items()}, d


# ------------------------------------------------------------------------------------------------ noise
class Noise2:
    """smooth value noise on a world lattice (cell metres), cubic interpolation; deterministic by seed"""
    def __init__(self, seed, cell, extent=24.0):
        rng = np.random.default_rng(seed); self.n = int(extent * 2 / cell) + 4
        self.g = rng.random((self.n, self.n)).astype(np.float32); self.cell = cell; self.ext = extent

    def __call__(self, X, Y):
        mx = ((X + self.ext) / self.cell).astype(np.float32); my = ((Y + self.ext) / self.cell).astype(np.float32)
        return cv2.remap(self.g, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_WRAP)


def masks_of(m):
    b, g, r = m[..., 0].astype(int), m[..., 1].astype(int), m[..., 2].astype(int)
    lawn = (r > 235) & (g < 20) & (b < 20); water = (g > 235) & (r < 20) & (b < 20); path = (b > 235) & (r < 20) & (g < 20)
    return lawn, water, path


def inner_fade(mask, lo=2.0, hi=10.0):
    d = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    return np.clip((d - lo) / (hi - lo), 0, 1).astype(np.float32)


# ------------------------------------------------------------------------------------------------ the module
class Ambient:
    def __init__(self, seed=11, wind_deg=18.0, wave_len=1.7, period=4.2, amp_m=0.021, grass_n=3, water_n=2,
                 card=None, card_img=None, falls_roi=None, falls_foam=None, motes=16):
        self.w = np.array([math.cos(math.radians(wind_deg)), math.sin(math.radians(wind_deg))], np.float32)
        self.wl, self.T, self.amp = wave_len, period, amp_m
        self.grass_n, self.water_n = grass_n, water_n
        self.n1 = Noise2(seed, 0.9); self.n2 = Noise2(seed + 1, 2.6); self.n3 = Noise2(seed + 2, 0.45)
        self.nw = Noise2(seed + 3, 0.6)
        rng = np.random.default_rng(seed + 9)
        self.glints = None                                   # pond glints: world points with their own rhythms (lazy)
        self.motes = [dict(u=rng.random(), v=0.15 + 0.6 * rng.random(), vu=rng.uniform(0.004, 0.011), vv=-rng.uniform(0.002, 0.007),
                           ph=rng.random() * 6.28, per=rng.uniform(2.5, 5.0), r=rng.uniform(1.4, 2.8), a=rng.uniform(0.16, 0.34))
                      for _ in range(motes)]               # screen-normalised: the same system in every shot
        self.card, self.fall = card, None
        if card is not None and card_img is not None and falls_roi: self._prep_card(card_img, falls_roi, falls_foam)

    # -------------------------------------------------------------- lawn breeze
    def breeze(self, X, Y, t):
        """signed sway (metres along the wind) at ground points X, Y and time t"""
        p = X * self.w[0] + Y * self.w[1]
        ph = 2 * np.pi * (p / self.wl - t / self.T) + 1.6 * self.n1(X, Y)
        gust = 0.55 + 0.45 * np.sin(2 * np.pi * (p / (3.1 * self.wl) - t / (2.6 * self.T)) + 2.0 * self.n2(X, Y))
        drift = self.n3(X - self.w[0] * 0.35 * t, Y - self.w[1] * 0.35 * t) - 0.5
        return self.amp * (gust * np.sin(ph) * 0.8 + 0.5 * drift)

    def lawn(self, img, lawn_mask, cam, t, X, Y):
        s = self.breeze(X, Y, t)
        P0 = np.stack([X, Y, np.zeros_like(X)], -1); P1 = P0 + np.stack([s * self.w[0], s * self.w[1], np.zeros_like(s)], -1)
        x0, y0, _ = cam.project(P0); x1, y1, _ = cam.project(P1)
        dx, dy = (x1 - x0).astype(np.float32), (y1 - y0).astype(np.float32)
        fade = inner_fade(lawn_mask)
        lum = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
        hp = lum - cv2.GaussianBlur(lum, (0, 0), 3.0)
        tip = cv2.GaussianBlur(np.clip(hp / 0.07, 0, 1), (0, 0), 1.0)          # bright stroke tips
        # the warp stays smooth (rigid at stroke scale) or the paint melts: tips lead only on the scale of a clump
        k = fade * (0.70 + 0.60 * cv2.GaussianBlur(tip, (0, 0), 7.0))
        dx *= k; dy *= k
        H, W = lum.shape
        gx, gy = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
        warped = cv2.remap(img, gx - dx, gy - dy, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
        shimmer = 1 + 0.06 * tip * (s / self.amp).astype(np.float32) * fade      # tips bend into the sun
        out = np.where(lawn_mask[..., None], np.clip(warped.astype(np.float32) * shimmer[..., None], 0, 255), img.astype(np.float32))
        return out.astype(np.uint8), (np.abs(dx) + np.abs(dy) > 0.02) | (np.abs(shimmer - 1) > 0.002)

    # -------------------------------------------------------------- pond
    def pond(self, img, water_mask, cam, t, X, Y):
        if not water_mask.any(): return img, np.zeros(water_mask.shape, bool)
        fade = inner_fade(water_mask, 1.0, 6.0)
        ph = 2 * np.pi * (Y / 0.32 + X / 1.9 - t / 2.4) + 2.2 * self.nw(X - 0.05 * t, Y)
        dz = 0.006 * np.sin(ph) * (0.6 + 0.4 * self.n2(X + 0.1 * t, Y))      # metres, along the view
        P0 = np.stack([X, Y, np.zeros_like(X)], -1); P1 = P0 + np.stack([np.zeros_like(X), dz, np.zeros_like(X)], -1)
        x0, y0, _ = cam.project(P0); x1, y1, _ = cam.project(P1)
        dy = ((y1 - y0) * fade).astype(np.float32); dx = ((x1 - x0) * fade * 0.3).astype(np.float32)
        H, W = water_mask.shape
        gx, gy = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
        warped = cv2.remap(img, gx - dx, gy - dy, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT).astype(np.float32)
        if self.glints is None:                              # world-anchored soft horizontal dashes in sunrise colours
            ys, xs = np.nonzero(water_mask[::8, ::8]); rng = np.random.default_rng(5)
            pick = rng.choice(len(ys), size=min(46, len(ys)), replace=False) if len(ys) else []
            self.glints = [dict(X=float(X[ys[i] * 8, xs[i] * 8]), Y=float(Y[ys[i] * 8, xs[i] * 8]), per=rng.uniform(2.6, 4.8),
                                ph=rng.random(), len=rng.uniform(0.06, 0.16), col=int(rng.integers(0, 3))) for i in pick]
        cols = np.array([[0.62, 0.86, 1.0], [0.70, 0.78, 1.0], [0.80, 0.90, 1.0]], np.float32)   # BGR: gold, rose-gold, pale
        add = np.zeros_like(warped)
        for g in self.glints:
            e = math.sin(math.pi * (((t / g["per"]) + g["ph"]) % 1.0)) ** 2
            if e < 0.03: continue
            Xg = g["X"] + 0.025 * t * self.w[0]; Yg = g["Y"]
            px, py, z = cam.project(np.array([Xg, Yg, 0.0])); qx, qy, _ = cam.project(np.array([Xg + g["len"], Yg, 0.0]))
            L = max(2.0, abs(qx - px)); h = max(1.0, L * 0.16)
            x0_, x1_, y0_, y1_ = int(px - L * 1.5), int(px + L * 1.5), int(py - h * 4), int(py + h * 4)
            if x1_ < 0 or y1_ < 0 or x0_ >= W or y0_ >= H: continue
            x0_, y0_, x1_, y1_ = max(0, x0_), max(0, y0_), min(W, x1_), min(H, y1_)
            yy, xx = np.mgrid[y0_:y1_, x0_:x1_].astype(np.float32)
            a = np.exp(-(((xx - px) / L) ** 2 + ((yy - py) / h) ** 2) * 2.6) * 0.30 * e
            add[y0_:y1_, x0_:x1_] += a[..., None] * cols[g["col"]] * 255
        add *= (fade * water_mask)[..., None]
        out = warped + add * (1 - warped / 255)              # screen-like add: never blows out to flat white
        out = np.where(water_mask[..., None], np.clip(out, 0, 255), img.astype(np.float32))
        return out.astype(np.uint8), water_mask & (fade > 0)

    # -------------------------------------------------------------- waterfall on a painted card
    def _prep_card(self, card_rgba, roi, foam):
        x0, y0, x1, y1 = roi
        r = card_rgba[y0:y1, x0:x1]
        hsv = cv2.cvtColor(r[..., :3], cv2.COLOR_BGR2HSV).astype(int)
        water = (r[..., 3] > 128) & (hsv[..., 1] < 95) & (hsv[..., 2] > 135)      # pale, unsaturated = painted water
        fx0, fy0, fx1, fy1 = foam or (x0, y1 - (y1 - y0) // 6, x1, y1)
        stream = water.copy(); stream[max(0, fy0 + (fy1 - fy0) // 4 - y0):] = False
        fm = np.zeros_like(water); fm[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0] = water[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0]
        self.fall = dict(off=(x0, y0), size=r.shape[:2], img_size=card_rgba.shape[:2],
                         stream=cv2.GaussianBlur(stream.astype(np.float32), (0, 0), 1.2),
                         foam=cv2.GaussianBlur(cv2.dilate(fm.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(np.float32), (0, 0), 3))

    def waterfall(self, img, cam, t):
        if self.fall is None: return img, np.zeros(img.shape[:2], bool)
        c = self.fall; x0, y0 = c["off"]; h, w = c["size"]; IH, IW = c["img_size"]
        Mw = np.array(self.card["mw"]); V = np.array(self.card["verts"])
        lx0, lx1 = V[:, 0].min(), V[:, 0].max(); ly0, ly1 = V[:, 1].min(), V[:, 1].max()

        def img2world(px, py):
            u = px / IW; v = 1 - py / IH
            return (Mw @ np.array([lx0 + u * (lx1 - lx0), ly0 + v * (ly1 - ly0), 0, 1.0]))[:3]
        src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        dst = np.float32([cam.project(img2world(x0 + sx, y0 + sy))[:2] for sx, sy in src])
        Hm = cv2.getPerspectiveTransform(src, dst)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        st = Noise2(77, 1.0, extent=400)(xx * 0.32, (yy - 300.0 * t) * 0.045) - 0.5
        gain = 1 + 0.30 * st * 2 * c["stream"]                                   # light/dark streaks running down
        hi = np.clip((st - 0.18) * 4, 0, 1) * c["stream"] * 0.35                  # a few bright streaks
        fo = (Noise2(78, 1.0, extent=400)(xx * 0.09 + 0.7 * math.sin(t * 2.1), yy * 0.16 - t * 2.4) - 0.35) * 2.2
        add = np.clip(hi + np.clip(fo, 0, 1) * c["foam"] * 0.55, 0, 0.8)
        H, W = img.shape[:2]
        G = cv2.warpPerspective(gain.astype(np.float32), Hm, (W, H), flags=cv2.INTER_LINEAR, borderValue=1.0)
        A = cv2.warpPerspective(add.astype(np.float32), Hm, (W, H), flags=cv2.INTER_LINEAR, borderValue=0.0)
        Mk = cv2.warpPerspective((c["stream"] + c["foam"]).astype(np.float32), Hm, (W, H), borderValue=0.0)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        isw = ((hsv[..., 1] < 110) & (hsv[..., 2] > 110)).astype(np.float32)   # only where painted water is what we see
        G = 1 + (G - 1) * isw; A = A * np.clip(isw + 0.6 * (Mk > 0.2), 0, 1)
        out = img.astype(np.float32) * G[..., None]
        out = out + A[..., None] * (np.array([250, 248, 240], np.float32) - out)
        return np.clip(out, 0, 255).astype(np.uint8), Mk > 0.02

    # -------------------------------------------------------------- motes
    def draw_motes(self, img, t):
        H, W = img.shape[:2]; out = img.astype(np.float32); touched = np.zeros((H, W), bool)
        for m in self.motes:
            u = (m["u"] + m["vu"] * t + 0.006 * math.sin(t * 0.9 + m["ph"])) % 1.0
            v = (m["v"] + m["vv"] * t + 0.004 * math.sin(t * 1.3 + 2 * m["ph"])) % 1.0
            x, y = u * W, v * H; r = m["r"]
            a = m["a"] * (0.55 + 0.45 * math.sin(2 * math.pi * t / m["per"] + m["ph"]))
            x0, x1, y0, y1 = max(0, int(x - 4 * r)), min(W, int(x + 4 * r) + 1), max(0, int(y - 4 * r)), min(H, int(y + 4 * r) + 1)
            if x1 <= x0 or y1 <= y0: continue
            yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
            g = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * r * r)) * a
            reg = out[y0:y1, x0:x1]; reg += g[..., None] * (np.array([200, 236, 255], np.float32) - reg)
            touched[y0:y1, x0:x1] |= g > 0.004
        return np.clip(out, 0, 255).astype(np.uint8), touched

    # -------------------------------------------------------------- one frame
    def hold(self, t, n):
        """time of the drawing on screen at t when a layer is held for n frames (n = 2: twos, 3: threes)"""
        return math.floor(t * FPS / n + 1e-6) * n / FPS

    def apply(self, img, t, mask_bgr, cam, motes=True, keep=None):
        """img: BGR uint8 frame; t: seconds; keep: bool mask of pixels that must stay exactly as they are.
        Returns (out, out_before_motes, {lawn, water, falls, motes, path} masks of what moved)."""
        lawn, water, path = masks_of(mask_bgr)
        X, Y = cam.ground()
        out, m1 = self.lawn(img, lawn, cam, self.hold(t, self.grass_n), X, Y)
        out, m2 = self.pond(out, water, cam, self.hold(t, self.water_n), X, Y)
        out, m3 = self.waterfall(out, cam, self.hold(t, self.water_n))
        if keep is not None: out[keep] = img[keep]
        pre = out.copy(); m4 = np.zeros(lawn.shape, bool)
        if motes: out, m4 = self.draw_motes(out, self.hold(t, self.water_n))
        return out, pre, dict(lawn=m1 & lawn, water=m2, falls=m3, motes=m4, path=path)


# ------------------------------------------------------------------------------------------------ CLI
def _motion(mm):
    return ((mm["lawn"] | mm["water"] | mm["falls"] | mm["motes"]).astype(np.uint8) * 255)


def run(a):
    cams, meta = load_cams(os.path.join(a.masks, "cams.json"))
    card_img = cv2.imread(a.card, cv2.IMREAD_UNCHANGED) if a.card else None
    roi = tuple(map(int, a.falls_roi.split(","))) if a.falls_roi else None
    foam = tuple(map(int, a.falls_foam.split(","))) if a.falls_foam else None
    A = Ambient(seed=a.seed, wind_deg=a.wind, wave_len=a.wave, period=a.period, amp_m=a.amp, grass_n=a.grass_n,
                water_n=a.water_n, card=meta.get("card"), card_img=card_img, falls_roi=roi, falls_foam=foam,
                motes=0 if a.no_motes else a.motes)
    os.makedirs(os.path.join(a.out, "motion"), exist_ok=True)
    mask_of = lambda f: cv2.imread(os.path.join(a.masks, f"m_{(a.mask_frame or f):04d}.png"))
    cam_of = lambda f: cams[a.mask_frame or f]
    if a.frames:
        names = sorted(x for x in os.listdir(a.frames) if x.startswith("f_") and x.endswith(".png"))
        jobs = [(int(x[2:6]), cv2.imread(os.path.join(a.frames, x))) for x in names]
        for f, img in jobs:
            out, _, mm = A.apply(img, (f - 1 + a.t_offset) / FPS, mask_of(f), cam_of(f))
            cv2.imwrite(os.path.join(a.out, f"f_{f:04d}.png"), out); cv2.imwrite(os.path.join(a.out, "motion", f"m_{f:04d}.png"), _motion(mm))
        return len(jobs)
    still = cv2.imread(a.still)
    if a.chars:
        names = sorted(x for x in os.listdir(a.chars) if x.startswith("f_") and x.endswith(".png"))
        n = len(names)
    else:
        names, n = None, int(round(a.seconds * FPS))
    for i in range(1, n + 1):
        t = (i - 1 + a.t_offset) / FPS
        if names is None:
            out, _, mm = A.apply(still, t, mask_of(i), cam_of(i))
        else:                                                   # the clean still moves; characters go back on top
            bg, _, mm = A.apply(still, t, mask_of(i), cam_of(i), motes=False)
            main = cv2.imread(os.path.join(a.chars, names[i - 1]))
            diff = np.abs(main.astype(int) - still.astype(int)).max(2)
            w = cv2.GaussianBlur(np.clip(cv2.dilate((diff > 3).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(np.float32), 0, 1), (0, 0), 1.0)
            w = np.maximum(w, (diff > 3).astype(np.float32))[..., None]
            comp = (main.astype(np.float32) * w + bg.astype(np.float32) * (1 - w) + 0.5).astype(np.uint8)
            moved = np.any(bg != still, axis=2); comp[~moved] = main[~moved]     # elsewhere the render, bit for bit
            out, mo = (A.draw_motes(comp, A.hold(t, A.water_n)) if not a.no_motes else (comp, np.zeros(diff.shape, bool)))
            mm["motes"] = mo
        cv2.imwrite(os.path.join(a.out, f"f_{i:04d}.png"), out); cv2.imwrite(os.path.join(a.out, "motion", f"m_{i:04d}.png"), _motion(mm))
    return n


def demo(d):
    """A synthetic world: a camera 1.5 m up looking along +y, a striped 'painted' lawn below the horizon, a path band
    and a pond. The lawn must move; the path and the 'house' above the horizon must not (checked by frozen_check)."""
    os.makedirs(os.path.join(d, "masks"), exist_ok=True); W, H = 360, 640
    a_ = math.radians(90 - 8)                                                   # pitch 8 degrees down
    R = np.array([[1, 0, 0], [0, math.cos(a_), -math.sin(a_)], [0, math.sin(a_), math.cos(a_)]])
    M = np.eye(4); M[:3, :3] = R; M[:3, 3] = [0, -5, 1.5]
    cams = dict(camera="Demo", size=[W, H], frames={"1": dict(mw=M.tolist(), lens=20.0, shift=[0, 0], sensor=36.0, fit="VERTICAL")})
    json.dump(cams, open(os.path.join(d, "masks", "cams.json"), "w"))
    cam = Cam(cams["frames"]["1"], W, H); X, Y = cam.ground(step=2)
    yy, xx = np.mgrid[0:H, 0:W]
    horizon = int(H * 0.42)                                                     # tan(8 deg) above the centre
    m = np.zeros((H, W, 3), np.uint8); m[:] = (128, 128, 128)
    ground = yy > horizon + 10
    path = ground & (np.abs(X) < 0.5); pond = ground & (X < -2.0) & (Y < 4); lawn = ground & ~path & ~pond
    m[lawn] = (0, 0, 255); m[path] = (255, 0, 0); m[pond] = (0, 255, 0)
    cv2.imwrite(os.path.join(d, "masks", "m_0001.png"), m)
    rng = np.random.default_rng(0)
    img = np.zeros((H, W, 3), np.uint8); img[:] = (170, 190, 215)                 # sky / house: must not move
    strokes = (np.sin(X * 40 + rng.random() * 6) * 0.5 + 0.5) * (np.sin(Y * 9) * 0.5 + 0.5)
    img[lawn] = np.stack([40 + 50 * strokes, 110 + 90 * strokes, 60 + 40 * strokes], -1)[lawn].astype(np.uint8)
    img[path] = (120, 128, 135); img[pond] = (120, 95, 60)
    cv2.imwrite(os.path.join(d, "clean.png"), img)
    return os.path.join(d, "clean.png"), os.path.join(d, "masks")


def main():
    ap = argparse.ArgumentParser(description="Breeze, pond ripples, waterfall streaks and motes on rendered frames of a painted world.")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--frames", help="folder of rendered frames f_0001.png ... (one mask + camera per frame)")
    src.add_argument("--still", help="one clean still of a locked shot (the background that moves)")
    src.add_argument("--demo", metavar="DIR", help="build a synthetic world in DIR and run on it")
    ap.add_argument("--masks", help="ambient_masks.py output (m_####.png + cams.json)")
    ap.add_argument("--mask-frame", type=int, help="use this one mask + camera for every frame (locked shot)")
    ap.add_argument("--chars", help="with --still: renders WITH characters; their pixels go back on top untouched")
    ap.add_argument("--seconds", type=float, default=5.0, help="with --still and no --chars: clip length")
    ap.add_argument("--t-offset", type=float, default=0, help="frames to add to the clock (continue the breeze across a cut)")
    ap.add_argument("--out"); ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--amp", type=float, default=0.021, help="sway amplitude, metres"); ap.add_argument("--wave", type=float, default=1.7)
    ap.add_argument("--period", type=float, default=4.2); ap.add_argument("--wind", type=float, default=18.0)
    ap.add_argument("--grass-n", type=int, default=3, help="grass held for n frames (3 = threes)")
    ap.add_argument("--water-n", type=int, default=2, help="water and motes held for n frames (2 = twos)")
    ap.add_argument("--motes", type=int, default=16); ap.add_argument("--no-motes", action="store_true")
    ap.add_argument("--card", help="RGBA of the painted card that holds a waterfall (with --falls-roi)")
    ap.add_argument("--falls-roi", help="x0,y0,x1,y1 of the waterfall on the card image")
    ap.add_argument("--falls-foam", help="x0,y0,x1,y1 of the foam band at its base (default: the bottom sixth)")
    a = ap.parse_args()
    if a.demo:
        still, masks = demo(a.demo)
        a.still, a.masks, a.mask_frame, a.seconds, a.out = still, masks, 1, 1.0, os.path.join(a.demo, "out")
        n = run(a)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import frozen_check
        rc = frozen_check.main([still, a.out, os.path.join(a.out, "motion"), os.path.join(masks, "m_0001.png"),
                                "--report", os.path.join(a.demo, "frozen.md")])
        lawn = masks_of(cv2.imread(os.path.join(masks, "m_0001.png")))[0]
        f1, f12 = (cv2.imread(os.path.join(a.out, f"f_{k:04d}.png")).astype(int) for k in (1, 12))
        moved = (np.abs(f1 - f12).max(2) > 3)[lawn].mean()
        print(f"demo: {n} frames; lawn pixels changed between f1 and f12: {moved:.1%}; frozen check exit {rc}")
        return 0 if (rc == 0 and moved > 0.05) else 2
    if not ((a.frames or a.still) and a.masks and a.out): ap.error("--frames or --still, plus --masks and --out (or --demo DIR)")
    print("wrote", run(a), "frames to", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
