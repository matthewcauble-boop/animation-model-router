"""bounce: animate limbless "ball characters" (a sprite with a round body and maybe a leaf, stem, tuft or antenna on
top) hopping over a background plate, with the classic principles built in. $0, all code.

    python tools/edit/bounce.py scene.json -o out.mp4 [--report r.json] [--arcs arcs.jpg] [--no-audio] [--frames DIR]
    python tools/edit/bounce.py --demo DIR        # draws test sprites + a gradient plate, writes DIR/scene.json, renders

What every character gets (tuned per character by its personality):
  * squash on contact and stretch along the velocity in the air, area kept exactly (sx * sy == 1);
  * anticipation: a squash and a lean back before a hop from rest; rebound hops leave on the landing squash's up-swing;
  * arcs: a constant-gravity parabola, with extra hang time at the apex and a fast fall into the ground;
  * a damped spring on landing (overshoot, then 2-3 jiggles), stiffness and damping per character;
  * follow-through: the top of the sprite (leaf, stem, tuft) bends on a floppy spring that lags the body;
  * the face rides the squash (it is part of the sprite); blinks on big landings; a look sprite for travel and peeks;
  * tilt into travel, a small rotation kick on landing, optional spins;
  * contact shadows that shrink and fade with height, plus a dark contact core while touching;
  * dust or dew puffs per surface; synthesised boops pitched per character, pats on grass, ticks on stone;
  * timing: take-offs and impacts on ones, drift on twos, settled poses held (no micro-drift).

scene.json (paths relative to the file; coordinates are OUTPUT pixels of the bottom contact point):
  {"size": [1080, 1920], "fps": 24, "duration": 4.0, "rate": "mixed",        # mixed | ones | twos
   "plate": "plate.png" | {"gradient": ["#sky-top", "#sky-bottom"], "ground_y": 1250, "ground": ["#top", "#bottom"]},
   "tint": [1, 1, 1], "shadow_tone": [0.22, 0.2, 0.28], "depth": {"y0": 1250, "k": 0.0006},   # scale = 1 + (y-y0)k
   "characters": [
     {"name": "a", "sprites": {"front": "a.png", "left": "a_left.png", "front_blink": "a_blink.png"},
      "height": 170, "preset": "light", "params": {"squash": 0.22}, "start": [700, 1300], "t0": 0.0, "face": "front",
      "actions": [{"wait": 0.3}, {"hop": [560, 1300], "h": 60, "surface": "grass"},
                  {"hop": [420, 1310], "h": 50, "rebound": true, "spin": 1}, {"look": "left"}, {"lean": 10},
                  {"wait": 0.4}, {"lean": 0}, {"blink": true}, {"at": 2.0}]}]}

  Sprites are PNGs with alpha. "front" is required; "left", "right" and "*_blink" are optional ("right" falls back to a
  mirrored "left"). "at" moves the character's clock forward to an absolute time (for offset entrances).
  Presets: light (quick, precise, small squash), heavy (big squash, soft spring, slow low hops, deep boop),
  springy (high hops, extra mini-bounce, more tilt). Any field of Personality can be overridden in "params".

Outputs: the MP4 (48 kHz AAC when audio is on), an optional frame folder, a report (area range, held and ones
fractions, events) and an optional arcs sheet (centre trail per frame; white outlines = contact squash).
Needs numpy, opencv-python-headless, Pillow (demo only), ffmpeg on PATH.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import wave
from dataclasses import dataclass, fields, replace
from pathlib import Path

import cv2
import numpy as np

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SR = 48000


# --------------------------------------------------------------------------- personality
@dataclass
class Personality:
    squash: float = 0.25        # max landing squash (sy = 1 - squash at a full-speed landing)
    stretch: float = 0.18       # max stretch along the velocity in the air
    freq: float = 4.5           # landing spring frequency (Hz); higher = stiffer
    damp: float = 0.22          # landing spring damping ratio; lower = more jiggles
    antic: float = 0.12         # anticipation time (s) before a hop from rest
    antic_depth: float = 0.16   # anticipation squash
    hop_time: float = 1.0       # multiplier on every hop's duration (tempo)
    hop_height: float = 1.0     # multiplier on every hop's height
    hang: float = 0.3           # 0..1 extra hang time at the apex
    tilt: float = 9.0           # degrees of lean into travel
    land_kick: float = 3.0      # degrees of rotation kick on landing
    top_pivot: float = 0.70     # fraction of height (from the bottom) where the top (leaf/stem) starts to bend
    top_freq: float = 4.0       # follow-through spring frequency (Hz)
    top_damp: float = 0.16
    top_gain: float = 1.0       # 0 = rigid top
    pitch: float = 450.0        # boop base pitch (Hz)
    mini_bounce: float = 0.0    # extra little bounce after every other landing (fraction of hop height)
    blink_impact: float = 0.8   # blink when the landing impact >= this (0..1)
    boop_len: float = 0.24      # boop length (s)
    color: tuple = (255, 255, 255)  # trail colour on the arcs sheet


PRESETS = {
    "light": dict(squash=0.20, stretch=0.16, freq=5.6, damp=0.30, antic=0.10, antic_depth=0.13, hop_time=0.86,
                  hop_height=0.95, hang=0.30, tilt=9, land_kick=2.5, top_pivot=0.70, top_freq=4.6, top_damp=0.18,
                  top_gain=1.0, pitch=560, blink_impact=0.95, boop_len=0.22, color=(255, 90, 100)),
    "heavy": dict(squash=0.34, stretch=0.20, freq=3.5, damp=0.16, antic=0.20, antic_depth=0.22, hop_time=1.15,
                  hop_height=0.80, hang=0.20, tilt=6, land_kick=4.0, top_pivot=0.78, top_freq=3.4, top_damp=0.14,
                  top_gain=1.3, pitch=250, blink_impact=0.6, boop_len=0.32, color=(90, 140, 255)),
    "springy": dict(squash=0.27, stretch=0.24, freq=4.6, damp=0.21, antic=0.08, antic_depth=0.16, hop_time=1.0,
                    hop_height=1.25, hang=0.40, tilt=13, land_kick=5.0, top_pivot=0.64, top_freq=3.0, top_damp=0.12,
                    top_gain=1.5, pitch=700, mini_bounce=0.28, blink_impact=0.99, boop_len=0.22,
                    color=(255, 200, 60)),
}


def make_personality(preset=None, params=None):
    kw = dict(PRESETS.get(preset or "", {}))
    kw.update(params or {})
    if "color" in kw:
        kw["color"] = tuple(kw["color"])
    known = {f.name for f in fields(Personality)}
    bad = set(kw) - known
    if bad:
        raise SystemExit(f"unknown personality params: {sorted(bad)}")
    return Personality(**kw)


# --------------------------------------------------------------------------- maths
def smooth(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def spring(tau, w, z):
    """Decaying cosine starting at 1 (squash recovery, landing kicks)."""
    return math.exp(-z * w * tau) * math.cos(w * math.sqrt(max(1 - z * z, 1e-4)) * tau)


def step_resp(tau, w, z):
    """Under-damped step response 0 -> 1 with overshoot (leans)."""
    if tau <= 0:
        return 0.0
    wd = w * math.sqrt(1 - z * z)
    return 1 - math.exp(-z * w * tau) * (math.cos(wd * tau) + z * w / wd * math.sin(wd * tau))


@dataclass
class Seg:
    kind: str                 # 'contact' | 'air'
    t0: float
    t1: float
    x0: float
    g0: float
    x1: float = 0.0
    g1: float = 0.0
    h: float = 0.0            # apex height above the higher end
    q: float = 0.0            # landing squash at the start of a contact
    kick: float = 0.0         # landing rotation (rad)
    antic: bool = False       # this contact ends in an anticipation squash
    spin: float = 0.0         # turns during this air segment (+ = CCW)
    surface: str = "grass"
    mini: bool = False


class Track:
    """One character's performance, built like an exposure sheet. Times in seconds, positions in output px."""

    def __init__(self, name, p: Personality, height, start, t0=0.0, face="front", fps=24, scale_fn=None):
        self.name, self.p, self.height, self.fps = name, p, float(height), fps
        self.t = t0
        self.x, self.g = float(start[0]), float(start[1])
        self.segs = [Seg("contact", t0, 1e9, self.x, self.g)]
        self.faces = [(t0, face)]
        self.leans, self.blinks, self.events = [], [], []
        self.visible_from = t0
        self.scale_fn = scale_fn or (lambda g: 1.0)
        self.dir = -1
        self.nland = 0

    # actions
    def wait(self, dt):
        self.t += dt
        return self

    def at(self, t):
        self.t = max(self.t, t)
        return self

    def look(self, face, dt=0.0):
        self.faces.append((self.t + dt, face))
        return self

    def lean(self, deg, dt=0.0):
        """+ = top toward screen left. Spring-eased with overshoot, held until changed."""
        self.leans.append((self.t + dt, math.radians(deg)))
        return self

    def blink(self, frames=3):
        self.blinks.append((self.t, self.t + frames / self.fps))
        return self

    def hop(self, to, h=40.0, T=None, surface="grass", rebound=False, spin=0.0, dwell=None):
        p, last = self.p, self.segs[-1]
        dx = to[0] - self.x
        if abs(dx) > 1:
            self.dir = 1 if dx > 0 else -1
        h *= p.hop_height
        if T is None:
            T = 0.17 + 0.0008 * math.hypot(dx, to[1] - self.g) + 0.0011 * h
        T *= p.hop_time
        if rebound:   # leave on the up-swing of the landing spring
            last.t1 = max(last.t0 + (dwell if dwell is not None else 0.45 / p.freq), self.t)
        else:         # anticipation from rest
            last.antic = True
            last.t1 = max(self.t, last.t0) + (p.antic if dwell is None else dwell)
        ta, tl = last.t1, last.t1 + T
        self.segs.append(Seg("air", ta, tl, self.x, self.g, to[0], to[1], h=h, spin=spin, surface=surface))
        fall = h + max(0.0, to[1] - self.g)
        impact = min(1.0, math.sqrt(fall / (0.4 * self.height)))
        q = p.squash * (0.45 + 0.55 * impact)
        kick = math.radians(p.land_kick) * -self.dir * (0.5 + 0.5 * impact)
        self.segs.append(Seg("contact", tl, 1e9, to[0], to[1], q=q, kick=kick, surface=surface))
        self.events.append(dict(t=tl, kind="land", impact=impact, surface=surface, x=to[0], g=to[1],
                                who=self.name, mini=False))
        self.events.append(dict(t=ta, kind="takeoff", x=self.x, g=self.g, who=self.name, rebound=rebound))
        if impact >= p.blink_impact:
            self.blinks.append((tl + 1 / self.fps, tl + 4 / self.fps))
        self.x, self.g, self.t = float(to[0]), float(to[1]), tl
        self.nland += 1
        if p.mini_bounce > 0 and h > 0.1 * self.height and self.nland % 2 == 1:
            self._mini(h)
        return self

    def _mini(self, h):
        p, last = self.p, self.segs[-1]
        last.t1 = last.t0 + 0.55 / p.freq
        hm = h * p.mini_bounce
        T = 0.16 + 0.003 * hm
        to = (self.x + self.dir * 0.05 * self.height, self.g)
        self.segs.append(Seg("air", last.t1, last.t1 + T, self.x, self.g, to[0], to[1], h=hm, surface=last.surface,
                             mini=True))
        tl = last.t1 + T
        self.segs.append(Seg("contact", tl, 1e9, to[0], to[1], q=p.squash * 0.45, surface=last.surface))
        self.events.append(dict(t=tl, kind="land", impact=0.35, surface=last.surface, x=to[0], g=to[1],
                                who=self.name, mini=True))
        self.x, self.t = to[0], tl

    # evaluation
    def seg_at(self, t):
        for s in self.segs:
            if s.t0 <= t < s.t1:
                return s
        return self.segs[-1] if t >= self.segs[-1].t0 else self.segs[0]

    def lean_at(self, t):
        v, prev = 0.0, 0.0
        w = 2 * math.pi * self.p.freq * 0.55
        for tt, a in self.leans:
            v += (a - prev) * step_resp(t - tt, w, 0.32)
            prev = a
        return v

    def face_at(self, t):
        f = self.faces[0][1]
        for tt, ff in self.faces:
            if t >= tt:
                f = ff
        return f + ("_blink" if any(a <= t < b for a, b in self.blinks) else "")

    def state(self, t):
        p, s, hb = self.p, self.seg_at(t), self.height
        if s.kind == "contact":
            tau = max(0.0, t - s.t0)
            w = 2 * math.pi * p.freq
            d = -s.q * spring(tau, w, p.damp) if s.q else 0.0
            tilt = s.kick * spring(tau, w * 0.9, p.damp + 0.05) if s.kick else 0.0
            if s.antic and s.t1 < 1e8:
                rho = (t - (s.t1 - p.antic)) / max(p.antic, 1e-3)
                if rho > 0:
                    e = float(smooth(rho / 0.8))
                    d += -p.antic_depth * e
                    tilt += self.dir * math.radians(p.tilt * 0.6) * e   # lean back, away from travel
            x, g, ug, hgt, vx, vy, axis, mode = s.x0, s.g0, s.g0, 0.0, 0.0, 0.0, 0.0, "bottom"
        else:
            T = s.t1 - s.t0
            u0 = (t - s.t0) / T

            def pos(uu):
                wv = 2 * min(max(uu, 0), 1) - 1
                u = 0.5 + 0.5 * ((1 - p.hang) * wv + p.hang * wv ** 3)     # hang time at the apex
                Hp = s.h + abs(s.g1 - s.g0) * 0.5
                return s.x0 + (s.x1 - s.x0) * u, s.g0 + (s.g1 - s.g0) * u - 4 * Hp * u * (1 - u)

            x, y = pos(u0)
            e = 1e-3
            xa, ya = pos(u0 - e / T)
            xb, yb = pos(u0 + e / T)
            vx, vy = (xb - xa) / (2 * e), (yb - ya) / (2 * e)
            ug = s.g0 + (s.g1 - s.g0) * u0
            hgt = max(0.0, ug - y)
            g = y
            sp = (abs(vy) + 0.3 * abs(vx)) / hb          # body heights per second, mostly vertical
            d = p.stretch * math.tanh(sp / 6.0) * (0.5 if s.mini else 1.0)
            axis = math.atan2(-vx, -vy)
            tilt = -math.radians(p.tilt) * math.tanh(vx / hb / 4.0)
            if s.spin:
                tilt += 2 * math.pi * s.spin * float(smooth(u0))
            mode = "center"
        tilt += self.lean_at(t)
        return dict(x=x, g=g, ug=ug, hgt=hgt, d=d, axis=axis, tilt=tilt, mode=mode, scale=self.scale_fn(ug),
                    seg=s, face=self.face_at(t), visible=t >= self.visible_from)

    def fast_window(self, t):
        """True when this instant is drawn on ones (impacts, take-offs, the first jiggles)."""
        f = self.fps
        for e in self.events:
            if e["kind"] == "land" and -1.5 / f <= t - e["t"] <= 4.5 / f:
                return True
            if e["kind"] == "takeoff" and -2.5 / f <= t - e["t"] <= 1.5 / f:
                return True
        return False

    def settled(self, t, st):
        s, p = st["seg"], self.p
        if s.kind != "contact":
            return False
        if s.antic and s.t1 < 1e8 and t > s.t1 - p.antic - 0.02:
            return False
        if s.q * math.exp(-p.damp * 2 * math.pi * p.freq * (t - s.t0)) > 0.012:
            return False
        return not any(-0.02 < t - tt < 0.9 for tt, _ in self.leans)


def simulate_top(track, t_end, rate=240):
    """Follow-through of the top (leaf/stem): a floppy spring driven by the body's acceleration, tilt and squash."""
    p = track.p
    n = int(t_end * rate) + 2
    dt = 1 / rate
    th = np.zeros(n)
    om = ang = 0.0
    w, z = 2 * math.pi * p.top_freq, p.top_damp
    prev = pv = None
    for i in range(n):
        st = track.state(i * dt)
        hb = track.height * st["scale"]
        cy = st["g"] - (hb * 0.5 if st["mode"] == "center" else hb * 0.5 * (1 + st["d"]))
        cur = (st["x"], cy, st["tilt"], st["d"])
        if prev is not None and st["visible"]:
            vx, vy = (cur[0] - prev[0]) / dt, (cur[1] - prev[1]) / dt
            vt = (cur[2] - prev[2]) / dt
            if pv is not None:
                ld = np.sign(ang) if abs(ang) > 0.03 else -track.dir
                ld = 1.0 if ld == 0 else float(ld)
                gg = p.top_gain
                om += (gg * 0.9 * (vx - pv[0]) / hb + gg * 0.35 * ld * max(-(vy - pv[1]), 0) / hb
                       - 0.55 * (vt - pv[2]) - gg * 1.6 * ld * (cur[3] - prev[3]))
            pv = (vx, vy, vt)
        om += (-w * w * ang - 2 * z * w * om) * dt
        ang = float(np.clip(ang + om * dt, -0.65, 0.65))
        th[i] = ang
        prev = cur
    return lambda t: float(th[min(n - 1, max(0, int(round(t * rate))))])


# --------------------------------------------------------------------------- sprites and drawing
def load_rgba(path):
    im = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if im is None:
        raise SystemExit(f"cannot read sprite {path}")
    if im.ndim == 2:
        im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGRA)
    if im.shape[2] == 3:
        raise SystemExit(f"sprite {path} has no alpha channel")
    return im[:, :, [2, 1, 0, 3]]


def sprite_meta(rgba):
    ys, xs = np.nonzero(rgba[:, :, 3] > 128)
    if len(ys) == 0:
        raise SystemExit("empty sprite")
    yb = int(ys.max())
    hgt = float(yb - ys.min())
    body = ys > ys.min() + 0.33 * hgt          # centre of the round body (skip the top third: leaf, stem)
    return dict(bx=float(xs[ys >= yb - 3].mean()), by=float(yb), h=hgt, cy=float(yb - ys[body].mean()))


class SpriteSet:
    def __init__(self, paths: dict):
        if "front" not in paths:
            raise SystemExit("every character needs a 'front' sprite")
        self.img = {k: load_rgba(v) for k, v in paths.items()}
        if "left" in self.img and "right" not in self.img:
            self.img["right"] = self.img["left"][:, ::-1].copy()
            if "left_blink" in self.img:
                self.img["right_blink"] = self.img["left_blink"][:, ::-1].copy()
        self.meta = {k: sprite_meta(v) for k, v in self.img.items()}
        self.cache = {}

    def key(self, face):
        if face in self.img:
            return face
        base = face.replace("_blink", "")
        if base in self.img:
            return base
        return "front_blink" if face.endswith("_blink") and "front_blink" in self.img else "front"

    def get(self, face, target_h):
        k = self.key(face)
        q = max(4, int(round(target_h / 4)) * 4)
        ck = (k, q)
        if ck not in self.cache:
            m = self.meta[k]
            f = q / m["h"]
            sm = cv2.resize(self.img[k], None, fx=f, fy=f, interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
            sm[:, :, :3] *= sm[:, :, 3:4]
            self.cache[ck] = (sm, m["bx"] * f, m["by"] * f, m["h"] * f, m["cy"] * f)
        return self.cache[ck]


def draw_character(canvas, sprites, track, st, top, tint=(1, 1, 1), record=None):
    """Composite one character (inverse warp: tilt, area-kept squash/stretch along the motion axis, top bend)."""
    H, W = canvas.shape[:2]
    p = track.p
    hpx = track.height * st["scale"]
    sm, bx, by, sh, scy = sprites.get(st["face"], hpx * 1.15)
    f = sh / hpx
    kk = 1 + st["d"]
    tilt = st["tilt"]
    axis_local = st["axis"] - tilt
    hc = scy / f
    if st["mode"] == "bottom":
        Px, Py, pvy = st["x"], st["g"], 0.0
    else:
        Px, Py, pvy = st["x"], st["g"] - hc, hc
    r = hpx * 1.9
    x0, x1 = int(max(0, Px - r)), int(min(W, Px + r))
    y0, y1 = int(max(0, Py - r * 1.3)), int(min(H, Py + r * 0.9))
    if x1 <= x0 or y1 <= y0:
        return
    gx, gy = np.meshgrid(np.arange(x0, x1, dtype=np.float32), np.arange(y0, y1, dtype=np.float32))
    wx, wy = gx - Px, -(gy - Py)
    c, s = math.cos(-tilt), math.sin(-tilt)
    lx, ly = c * wx - s * wy, s * wx + c * wy
    ca, sa = math.cos(axis_local), math.sin(axis_local)
    ax_, ay_ = (ca * lx + sa * ly) * kk, (-sa * lx + ca * ly) / kk
    lx, ly = ca * ax_ - sa * ay_, sa * ax_ + ca * ay_ + pvy
    if top:
        v0 = p.top_pivot * hpx
        wv = smooth((ly - v0) / (hpx * (1 - p.top_pivot) + 1e-6)) ** 1.2
        phi = -top * wv
        cp, sp_ = np.cos(phi), np.sin(phi)
        rx, ry = lx, ly - v0
        lx, ly = cp * rx - sp_ * ry, sp_ * rx + cp * ry + v0
    mapx = (bx + lx * f).astype(np.float32)
    mapy = (by - ly * f).astype(np.float32)
    patch = cv2.remap(sm, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    a = patch[:, :, 3:4]
    reg = canvas[y0:y1, x0:x1]
    reg *= (1 - a)
    reg += patch[:, :, :3] * np.array(tint, np.float32)
    if record is not None:
        cy = Py if st["mode"] == "center" else Py - hc * kk
        record.append(dict(x0=x0, y0=y0, alpha=(a[:, :, 0] > 0.5).astype(np.uint8), c=(Px, cy)))


def draw_shadow(canvas, track, st, tone=(0.22, 0.2, 0.28), strength=0.7):
    H, W = canvas.shape[:2]
    hpx = track.height * st["scale"]
    k = 1.0 / (1.0 + st["hgt"] / (0.55 * hpx))          # smaller and lighter with height
    wd = hpx * 0.40 * (1 / (1 + st["d"]) if st["mode"] == "bottom" else 1.0) * (0.55 + 0.45 * k)
    ht = wd * 0.22
    cx, cy = st["x"], st["ug"] + 1
    x0, x1 = int(max(0, cx - wd * 1.6)), int(min(W, cx + wd * 1.6))
    y0, y1 = int(max(0, cy - ht * 2.5)), int(min(H, cy + ht * 2.5))
    if x1 <= x0 or y1 <= y0:
        return
    gx, gy = np.meshgrid(np.arange(x0, x1, dtype=np.float32), np.arange(y0, y1, dtype=np.float32))
    rr = ((gx - cx) / wd) ** 2 + ((gy - cy) / ht) ** 2
    a = np.clip(1.15 - rr, 0, 1) ** 1.3 * strength * k ** 1.6
    if st["mode"] == "bottom":                            # contact core: tight dark occlusion while touching
        rr2 = ((gx - cx) / (wd * 0.5)) ** 2 + ((gy - cy) / (ht * 0.6)) ** 2
        a = np.maximum(a, np.clip(1 - rr2, 0, 1) ** 0.7 * 0.8)
    a = a[..., None]
    reg = canvas[y0:y1, x0:x1]
    reg[:] = reg * (1 - a) + reg * np.array(tone, np.float32) * a


class Particles:
    """Dew on grass, dust on stone or dirt: a few droplets with gravity plus one soft puff per landing."""

    def __init__(self, seed=3):
        self.rng = np.random.default_rng(seed)
        self.p = []

    def burst(self, t, x, y, surface, impact, scale):
        wet = surface == "grass"
        for i in range(int(4 + 7 * impact)):
            ang = self.rng.uniform(0.15, 0.85) * math.pi
            side = 1 if i % 2 else -1
            sp = self.rng.uniform(140, 320) * (0.5 + impact) * scale
            self.p.append(dict(t=t, x=x + side * self.rng.uniform(10, 26) * scale, y=y - 2,
                               vx=side * abs(math.cos(ang)) * sp * 1.4, vy=-abs(math.sin(ang)) * sp * 0.8,
                               col=(0.86, 0.95, 1.0) if wet else (0.86, 0.76, 0.6),
                               size=self.rng.uniform(2.2, 4.2) * scale if wet else self.rng.uniform(1.8, 3.2) * scale,
                               life=self.rng.uniform(0.28, 0.42) if wet else self.rng.uniform(0.22, 0.34), puff=False))
        self.p.append(dict(t=t, x=x, y=y - 4 * scale, vx=0, vy=-30, col=(1, 1, 1) if wet else (0.9, 0.8, 0.65),
                           size=26 * scale * (0.6 + impact), life=0.3, puff=True))

    def draw(self, canvas, t):
        H, W = canvas.shape[:2]
        for q in self.p:
            age = t - q["t"]
            if age < 0 or age > q["life"]:
                continue
            fr = age / q["life"]
            if q["puff"]:
                r = q["size"] * (0.6 + 1.2 * fr)
                cx, cy = q["x"], q["y"] + q["vy"] * age
                x0, x1, y0, y1 = int(max(0, cx - r * 1.6)), int(min(W, cx + r * 1.6)), int(max(0, cy - r * .8)), int(min(H, cy + r * .5))
                if x1 <= x0 or y1 <= y0:
                    continue
                gx, gy = np.meshgrid(np.arange(x0, x1, dtype=np.float32), np.arange(y0, y1, dtype=np.float32))
                al = np.clip(1 - ((gx - cx) / (r * 1.5)) ** 2 - ((gy - cy) / (r * 0.45)) ** 2, 0, 1) * 0.22 * (1 - fr) ** 2
            else:
                x = q["x"] + q["vx"] * age
                y = q["y"] + q["vy"] * age + 700 * age * age
                r = q["size"] * (1 - 0.4 * fr)
                x0, x1, y0, y1 = int(max(0, x - r - 1)), int(min(W, x + r + 2)), int(max(0, y - r - 1)), int(min(H, y + r + 2))
                if x1 <= x0 or y1 <= y0:
                    continue
                gx, gy = np.meshgrid(np.arange(x0, x1, dtype=np.float32), np.arange(y0, y1, dtype=np.float32))
                al = np.clip(1.4 - np.hypot(gx - x, gy - y) / max(r, 0.5), 0, 1) * (1 - fr ** 2) * 0.95
            al = al[..., None]
            reg = canvas[y0:y1, x0:x1]
            reg[:] = reg * (1 - al) + np.array(q["col"], np.float32) * al


# --------------------------------------------------------------------------- the render loop
def render(plate, chars, duration, fps, rate="mixed", tint=(1, 1, 1), shadow_tone=(0.22, 0.2, 0.28), record=None):
    """Yield uint8 RGB frames. chars = [(Track, SpriteSet)]. rate: mixed (impacts on ones, drift on twos, settled
    poses held), ones, or twos (everything on twos, holds included)."""
    tops = {id(tr): simulate_top(tr, duration + 0.5) for tr, _ in chars}
    parts = Particles()
    for tr, _ in chars:
        for e in tr.events:
            if e["kind"] == "land" and e["t"] < duration:
                parts.burst(e["t"], e["x"], e["g"], e["surface"], e["impact"] * (0.5 if e["mini"] else 1),
                            tr.scale_fn(e["g"]) * tr.height / 125)
    held = {id(tr): None for tr, _ in chars}
    for fi in range(int(round(duration * fps))):
        t = fi / fps
        canvas = plate.copy()
        states = []
        for tr, sp in chars:
            hs = held[id(tr)]
            now = tr.state(t)
            ts = t
            if hs is not None and rate != "ones":
                ts_prev, st_prev, age = hs
                fast = rate == "mixed" and tr.fast_window(t)
                if not fast:
                    if (rate == "mixed" and tr.settled(t, now) and tr.settled(ts_prev, st_prev)
                            and st_prev["seg"] is now["seg"]):
                        ts = ts_prev           # hold the drawing: no micro-drift at the settle
                    elif age < 1:
                        ts = ts_prev           # twos
            st = now if ts == t else tr.state(ts)
            st["face"] = tr.face_at(t)         # blinks and looks land on their own frame
            held[id(tr)] = (ts, st, 0 if ts == t else hs[2] + 1)
            states.append((tr, sp, st, tops[id(tr)](ts)))
        order = sorted(states, key=lambda a: a[2]["ug"])      # back to front by ground line
        for tr, sp, st, _ in order:
            if st["visible"]:
                draw_shadow(canvas, tr, st, shadow_tone)
        parts.draw(canvas, t)
        for tr, sp, st, top in order:
            if not st["visible"]:
                continue
            rec = [] if record is not None else None
            draw_character(canvas, sp, tr, st, top, tint, rec)
            if record is not None and rec:
                record.append(dict(f=fi, t=t, who=tr.name, sx=1 / (1 + st["d"]), sy=1 + st["d"],
                                   held=held[id(tr)][2] > 0, ones=tr.fast_window(t), mode=st["mode"], **rec[0]))
        yield (np.clip(canvas, 0, 1) * 255 + 0.5).astype(np.uint8)


# --------------------------------------------------------------------------- audio
def synth(events, duration, pers, width, seed=7):
    """Boops pitched per character (a glide into the note, a wobble at the spring's rate), a soft pat on grass,
    a tick on stone, a small fwip on take-offs from rest, under a very quiet room-tone bed."""
    rng = np.random.default_rng(seed)
    n = int(duration * SR) + SR // 2
    L, R = np.zeros(n, np.float32), np.zeros(n, np.float32)

    def add(sig, t, pan=0.0, gain=1.0):
        i = int(t * SR)
        if i >= n or i < 0:
            return
        sig = sig[: n - i] * gain
        L[i:i + len(sig)] += sig * math.cos((pan + 1) * math.pi / 4) * 1.41
        R[i:i + len(sig)] += sig * math.sin((pan + 1) * math.pi / 4) * 1.41

    def boop(f0, dur, wob_hz, depth=0.35):
        tt = np.arange(int(dur * SR)) / SR
        glide = f0 * (1 + 0.55 * np.exp(-tt / 0.018))
        wob = 1 + 0.06 * np.exp(-tt / 0.09) * np.sin(2 * np.pi * wob_hz * tt)
        ph = 2 * np.pi * np.cumsum(glide * wob) / SR
        env = (1 - np.exp(-tt / 0.003)) * np.exp(-tt / (dur * 0.28))
        am = 1 - depth * np.exp(-tt / 0.12) * (0.5 + 0.5 * np.cos(2 * np.pi * wob_hz * tt))
        s = (np.sin(ph) + 0.25 * np.sin(2 * ph) + 0.08 * np.sin(3 * ph)) * env * am
        nz = rng.standard_normal(len(tt))
        nz = np.convolve(nz, np.ones(6) / 6, "same") - np.convolve(nz, np.ones(40) / 40, "same")
        return (s + nz * np.exp(-tt / 0.012) * 0.6).astype(np.float32)

    def pat():
        m = int(0.06 * SR)
        tt = np.arange(m) / SR
        nz = rng.standard_normal(m)
        lp = np.convolve(nz, np.ones(30) / 30, "same")
        hp = nz - np.convolve(nz, np.ones(4) / 4, "same")
        return (lp * 3.0 * np.exp(-tt / 0.012) + hp * 0.15 * np.exp(-tt / 0.03)).astype(np.float32)

    def tick():
        m = int(0.03 * SR)
        tt = np.arange(m) / SR
        f = rng.uniform(2600, 3400)
        s = np.sin(2 * np.pi * f * tt) * np.exp(-tt / 0.004) + 0.5 * np.sin(2 * np.pi * f * 1.7 * tt) * np.exp(-tt / 0.0025)
        return (s + rng.standard_normal(m) * np.exp(-tt / 0.0015) * 0.4).astype(np.float32)

    def fwip(f0):
        m = int(0.07 * SR)
        tt = np.arange(m) / SR
        ph = 2 * np.pi * np.cumsum(f0 * (0.9 + 1.2 * tt / 0.07)) / SR
        return (np.sin(ph) * np.sin(np.pi * tt / 0.07) ** 2 * 0.18).astype(np.float32)

    for e in events:
        p = pers[e["who"]]
        pan = float(np.clip(e["x"] / width * 2 - 1, -0.8, 0.8))
        if e["kind"] == "land":
            imp = e["impact"]
            f0 = p.pitch * (1.18 if e["mini"] else 1.0) * rng.uniform(0.97, 1.03)
            add(boop(f0, p.boop_len, p.freq * 4), e["t"], pan, 0.30 * (0.45 + 0.55 * imp) * (0.6 if e["mini"] else 1))
            if e["surface"] == "grass":
                add(pat(), e["t"], pan, 0.35 * (0.5 + imp))
            else:
                add(tick(), e["t"], pan, 0.16 * (0.5 + imp))
        elif e["kind"] == "takeoff" and not e.get("rebound"):
            add(fwip(p.pitch * 1.6), e["t"], pan, 0.5)
    bed = np.convolve(rng.standard_normal(n), np.ones(200) / 200, "same").astype(np.float32) * 0.05
    L += bed
    R += np.roll(bed, 300)
    st = np.stack([L, R], 1)[: int(duration * SR)]
    pk = float(np.abs(st).max()) if st.size else 0
    if pk > 0.89:
        st *= 0.89 / pk
    return st


def write_wav(path, st):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(st, -1, 1) * 32767).astype(np.int16).tobytes())


# --------------------------------------------------------------------------- scene loading
def hex_rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.float32) / 255.0


def make_plate(spec, W, H, base: Path):
    if isinstance(spec, str):
        im = cv2.imread(str(base / spec))
        if im is None:
            raise SystemExit(f"cannot read plate {spec}")
        return cv2.resize(im[:, :, ::-1], (W, H), interpolation=cv2.INTER_LANCZOS4).astype(np.float32) / 255.0
    sky = spec.get("gradient", ["#9cc6e8", "#f3e3c4"])
    gy = int(spec.get("ground_y", H * 0.65))
    gnd = spec.get("ground", ["#7fa65a", "#4f7a3a"])
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    img = hex_rgb(sky[0]) * (1 - y) + hex_rgb(sky[1]) * y
    img = np.repeat(img, W, 1)
    gg = np.linspace(0, 1, max(1, H - gy), dtype=np.float32)[:, None, None]
    img[gy:] = hex_rgb(gnd[0]) * (1 - gg) + hex_rgb(gnd[1]) * gg
    return np.ascontiguousarray(img)


def build(scene_path):
    sc = json.loads(Path(scene_path).read_text(encoding="utf-8"))
    base = Path(scene_path).resolve().parent
    W, H = sc.get("size", [1080, 1920])
    fps = int(sc.get("fps", 24))
    dep = sc.get("depth")
    scale_fn = (lambda g, d=dep: max(0.2, 1 + (g - d["y0"]) * d["k"])) if dep else None
    chars, pers = [], {}
    for c in sc["characters"]:
        p = make_personality(c.get("preset"), c.get("params"))
        tr = Track(c["name"], p, c.get("height", 160), c["start"], c.get("t0", 0.0), c.get("face", "front"), fps,
                   scale_fn)
        for a in c.get("actions", []):
            if "wait" in a:
                tr.wait(a["wait"])
            elif "at" in a:
                tr.at(a["at"])
            elif "look" in a:
                tr.look(a["look"], a.get("dt", 0.0))
            elif "lean" in a:
                tr.lean(a["lean"], a.get("dt", 0.0))
            elif "blink" in a:
                tr.blink(a.get("frames", 3))
            elif "hop" in a:
                kw = {k: a[k] for k in ("h", "T", "surface", "rebound", "spin", "dwell") if k in a}
                tr.hop(a["hop"], **kw)
            else:
                raise SystemExit(f"unknown action {a}")
        sprites = SpriteSet({k: base / v for k, v in c["sprites"].items()})
        chars.append((tr, sprites))
        pers[c["name"]] = p
    duration = float(sc.get("duration") or max(tr.t for tr, _ in chars) + 0.8)
    plate = make_plate(sc.get("plate", {}), W, H, base)
    return sc, chars, pers, plate, duration, fps, (W, H)


def arcs_sheet(plate, record, chars, path):
    img = (plate * 0.45 * 255).astype(np.uint8).copy()
    trails = {}
    cols = {tr.name: tr.p.color for tr, _ in chars}
    for r in record:
        squash = r["mode"] == "bottom" and r["sy"] < 0.86
        if (r["f"] % 3 == 0 and not r["held"]) or squash:
            cnts, _ = cv2.findContours(r["alpha"], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            for cn in cnts:
                cn = cn + np.array([[r["x0"], r["y0"]]])
                col = (255, 255, 255) if squash else tuple(int(v * 0.6) for v in cols[r["who"]])
                cv2.polylines(img, [cn], True, col, 2 if squash else 1, cv2.LINE_AA)
        trails.setdefault(r["who"], []).append((int(r["c"][0]), int(r["c"][1]), r["held"]))
    for k, pts in trails.items():
        for i in range(1, len(pts)):
            cv2.line(img, pts[i - 1][:2], pts[i][:2], cols[k], 2, cv2.LINE_AA)
        for p in pts:
            cv2.circle(img, p[:2], 2 if p[2] else 4, cols[k] if p[2] else (255, 255, 255), -1, cv2.LINE_AA)
    cv2.putText(img, "centre per frame: big dot = new drawing, small = held; white outline = contact squash",
                (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (235, 235, 235), 1, cv2.LINE_AA)
    cv2.imwrite(str(path), img[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, 90])


def run(scene_path, out, report=None, arcs=None, audio=True, frames_dir=None):
    sc, chars, pers, plate, duration, fps, (W, H) = build(scene_path)
    rate = sc.get("rate", "mixed")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    events = sorted((e for tr, _ in chars for e in tr.events if e["t"] < duration), key=lambda e: e["t"])
    wav = None
    if audio:
        wav = out.with_suffix(".wav")
        write_wav(wav, synth(events, duration, pers, W))
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(fps), "-i", "-"]
    if wav:
        cmd += ["-i", str(wav), "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, creationflags=NOWIN)
    if frames_dir:
        Path(frames_dir).mkdir(parents=True, exist_ok=True)
    record = []
    nf = 0
    for fr in render(plate, chars, duration, fps, rate, tuple(sc.get("tint", (1, 1, 1))),
                     tuple(sc.get("shadow_tone", (0.22, 0.2, 0.28))), record):
        proc.stdin.write(fr.tobytes())
        if frames_dir:
            cv2.imwrite(str(Path(frames_dir) / f"f{nf:04d}.png"), fr[:, :, ::-1])
        nf += 1
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg failed")
    if wav:
        wav.unlink(missing_ok=True)
    if arcs:
        arcs_sheet(plate, record, chars, arcs)
    area = [r["sx"] * r["sy"] for r in record]
    rep = dict(out=str(out), frames=nf, fps=fps, duration=round(duration, 3), rate=rate,
               area_min=round(min(area), 6) if area else None, area_max=round(max(area), 6) if area else None,
               sy_min=round(min(r["sy"] for r in record), 3) if record else None,
               sy_max=round(max(r["sy"] for r in record), 3) if record else None,
               held_frac=round(sum(r["held"] for r in record) / max(1, len(record)), 3),
               ones_frac=round(sum(r["ones"] for r in record) / max(1, len(record)), 3),
               landings=sum(e["kind"] == "land" for e in events), audio=bool(wav),
               events=[dict(t=round(e["t"], 3), kind=e["kind"], who=e["who"]) for e in events])
    if report:
        Path(report).write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "events"}, indent=1))
    return rep


# --------------------------------------------------------------------------- demo (synthetic test media)
def demo(d):
    from PIL import Image, ImageDraw
    d = Path(d)
    (d / "sprites").mkdir(parents=True, exist_ok=True)

    def ball(path, body, top, look=0, blink=False):
        S = 4                                     # draw large, downsample = clean edges
        w, h = 200 * S, 240 * S
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        g = ImageDraw.Draw(im)
        g.polygon([(100 * S, 70 * S), (70 * S, 10 * S), (92 * S, 6 * S), (112 * S, 66 * S)], fill=top,
                  outline=(30, 30, 30, 255))     # a leaf on top: the follow-through part
        g.ellipse((10 * S, 60 * S, 190 * S, 236 * S), fill=body, outline=(30, 30, 30, 255), width=5 * S)
        for ex in (72, 128):
            ex += look
            if blink:
                g.arc(((ex - 14) * S, 128 * S, (ex + 14) * S, 150 * S), 20, 160, fill=(30, 25, 25, 255), width=5 * S)
            else:
                g.ellipse(((ex - 15) * S, 115 * S, (ex + 15) * S, 155 * S), fill=(255, 255, 255, 255))
                g.ellipse(((ex - 8 + look // 3) * S, 128 * S, (ex + 6 + look // 3) * S, 150 * S), fill=(25, 25, 30, 255))
        g.arc((80 * S, 160 * S, 120 * S, 190 * S), 20, 160, fill=(30, 25, 25, 255), width=4 * S)
        im.resize((w // S, h // S), Image.LANCZOS).save(path)

    looks = {"a": ((220, 70, 80, 255), (70, 150, 60, 255)), "b": ((70, 95, 200, 255), (60, 120, 70, 255)),
             "c": ((240, 180, 50, 255), (90, 160, 60, 255))}
    for k, (body, top) in looks.items():
        ball(d / "sprites" / f"{k}.png", body, top)
        ball(d / "sprites" / f"{k}_left.png", body, top, look=-16)
        ball(d / "sprites" / f"{k}_blink.png", body, top, blink=True)
        ball(d / "sprites" / f"{k}_left_blink.png", body, top, look=-16, blink=True)

    def spr(k):
        return {"front": f"sprites/{k}.png", "left": f"sprites/{k}_left.png", "front_blink": f"sprites/{k}_blink.png",
                "left_blink": f"sprites/{k}_left_blink.png"}

    def lane(xs, y, spin_at=None):
        acts = [{"look": "left"}]
        for i, x in enumerate(xs):
            acts.append({"hop": [x, y + (i % 2) * 6 - 3], "h": 70, "surface": "grass", "rebound": i > 0,
                         **({"spin": 1} if i == spin_at else {})})
        return acts + [{"lean": 7, "dt": 0.05}, {"wait": 0.35}, {"lean": 0}, {"look": "front", "dt": 0.2}]

    scene = {
        "size": [720, 1280], "fps": 24, "duration": 4.2, "rate": "mixed",
        "plate": {"gradient": ["#a9cbe6", "#f4e6c8"], "ground_y": 820, "ground": ["#86ad5e", "#557d3c"]},
        "depth": {"y0": 900, "k": 0.0012},
        "characters": [
            {"name": "light", "preset": "light", "height": 110, "start": [640, 900], "t0": 0.0,
             "sprites": spr("a"), "actions": [{"wait": 0.25}] + lane([540, 440, 340, 240, 140], 900)},
            {"name": "heavy", "preset": "heavy", "height": 120, "start": [660, 980], "t0": 0.0,
             "sprites": spr("b"), "actions": [{"at": 0.55}] + lane([560, 460, 370, 285], 980)},
            {"name": "springy", "preset": "springy", "height": 105, "start": [650, 1060], "t0": 0.0,
             "sprites": spr("c"), "actions": [{"at": 0.9}] + lane([540, 420, 300], 1060, spin_at=1)},
        ]}
    sp = d / "scene.json"
    sp.write_text(json.dumps(scene, indent=1), encoding="utf-8")
    rep = run(sp, d / "bounce-demo.mp4", d / "report.json", d / "arcs.jpg", True, None)
    assert abs(rep["area_min"] - 1) < 1e-6 and abs(rep["area_max"] - 1) < 1e-6, "squash/stretch must keep area"
    assert rep["landings"] >= 10 and 0 < rep["ones_frac"] < 1 and rep["held_frac"] > 0.3, rep
    print("demo OK:", d / "bounce-demo.mp4")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("scene", nargs="?")
    ap.add_argument("-o", "--out", default="bounce.mp4")
    ap.add_argument("--report")
    ap.add_argument("--arcs", help="write an arcs sheet (JPG)")
    ap.add_argument("--frames", help="also write PNG frames here")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--demo", metavar="DIR", help="draw test sprites + a gradient plate and render them")
    a = ap.parse_args()
    if a.demo:
        demo(a.demo)
    elif a.scene:
        run(a.scene, a.out, a.report, a.arcs, not a.no_audio, a.frames)
    else:
        ap.error("give a scene.json or --demo DIR")


if __name__ == "__main__":
    sys.exit(main())
