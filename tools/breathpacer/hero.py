"""Hero breath pacer: the big guided-breathing circle as a reusable panel or overlay.

A soft glowing matte disc (lighter inner glow, soft outer halo, no outline) grows on the in-breath and shrinks on the
out-breath, inside a thin full-circle guide ring. A progress arc sweeps the ring once per phase with a bright dot at
its head, a big countdown numeral sits inside the disc, "Breathe in" / "Breathe out" sits above it with a smaller
sub-line (cross-fading at the turn), and a small footnote sits below. Our own code; it copies a common guided-
breathing format, not anyone's assets.

Library:
    from hero import Hero
    h = Hero(1080, 960, color="red", t0=3.4, cycles=4)   # t0 = start of the first in-breath (s)
    img = h.render(t)                                       # PIL RGBA panel at time t (opaque navy unless bg=None)
    h.phase(t) -> ("in"|"out"|"pre"|"post", seconds into phase, phase length)

CLI (a standalone panel video, or overlaid on a video):
    python tools/breathpacer/hero.py -o panel.mp4 --w 1080 --h 960 --dur 30 [--color red|gold|#hex] [--t0 1]
           [--cycles 2] [--inhale 5.5 --exhale 5.5] [--font-title path.ttf]
    python tools/breathpacer/hero.py --overlay in.mp4 -o out.mp4 --x 0 --y 960 --w 1080 --h 960 [--transparent]

Colours: "red" = record-button red #E8171C (default), "gold" = a warm pale gold. Panel default deep navy.
Motion: a smoothed triangle (--sharp 0 = sine, 0.97 = the small overlay pacer); default 0.85 keeps an even, calm
pace with a soft turn, so it never appears to stop. Countdown: N..1 per phase (--count, default 5).
Fonts: any rounded bold face for the title and a light face for numbers and sub-lines; pass --font-title /
--font-light / --font-num, or let it pick the first system font it finds. Never over a character (see pacer.py).
"""
import argparse, json, math, random, subprocess
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import os


def _first(*paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


# Title: a rounded bold face reads friendliest (any you have a licence for). Light: a thin sans for numbers.
F_LABEL = _first(os.environ.get("PACER_FONT_TITLE"), "C:/Windows/Fonts/seguisb.ttf", "C:/Windows/Fonts/arialbd.ttf",
                 "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
F_LIGHT = _first(os.environ.get("PACER_FONT_LIGHT"), "C:/Windows/Fonts/segoeuisl.ttf", "C:/Windows/Fonts/arial.ttf",
                 "/System/Library/Fonts/Helvetica.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
F_NUM = _first(os.environ.get("PACER_FONT_NUM"), "C:/Windows/Fonts/segoeuil.ttf", F_LIGHT)
PRESETS = {"red": "#E8171C", "gold": "#E9CF96"}  # red = record-button red
NAVY_C, NAVY_E = (27, 41, 86), (9, 15, 38)      # panel: centre glow -> edge


def hexrgb(h):
    h = PRESETS.get(h, h); return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def smooth_tri(u, sharp):
    """u in [0,1) over a full cycle -> k in [0,1]: 0 at u=0, 1 at u=.5, eased reversal; sharp 0 = cosine."""
    th = 2 * math.pi * u - math.pi / 2
    if sharp <= 0: return .5 + .5 * math.sin(th)
    return .5 + math.asin(sharp * math.sin(th)) / (2 * math.asin(sharp))


class Hero:
    def __init__(self, w=1080, h=960, color="red", bg="navy", t0=0.0, cycles=None, inhale=5.5, exhale=5.5, count=5,
                 sharp=0.85, cy=None, ring_r=None, labels=("Breathe in", "Breathe out"),
                 subs=("through your nose", "slow and soft, let it go"), footnote="5.5 in · 5.5 out", fade_in=0.6, fade_out=1.2,
                 label_y=None, foot_y=None, seed=7):
        self.W, self.H, self.col = w, h, hexrgb(color)
        self.t0, self.cycles, self.Li, self.Lo, self.count, self.sharp = t0, cycles, inhale, exhale, count, sharp
        self.labels, self.subs, self.footnote, self.fade_in, self.fade_out = labels, subs, footnote, fade_in, fade_out
        self.R = ring_r or int(min(w, h) * .29)                     # guide ring radius
        self.cx, self.cy = w / 2, (cy if cy is not None else h * .54)
        self.rmin, self.rmax = .46 * self.R, .86 * self.R
        self.label_y = label_y * h if label_y is not None else self.cy - self.R - h * .17   # label centre (px in panel)
        self.foot_y = foot_y * h if foot_y is not None else self.cy + self.R + h * .075             # disc radius range
        lum = sum(c * k for c, k in zip(self.col, (.299, .587, .114)))
        self.num_col = (60, 52, 34) if lum > 150 else (255, 255, 255)   # dark numeral on gold, white on red
        self.bg = self._panel() if bg == "navy" else None
        self.disc = self._disc_sprite(int(self.rmax * 2))             # 2x supersampled
        self.halo = self._halo_sprite()
        self.f_label, self.f_sub = ImageFont.truetype(F_LABEL, int(h * .072)), ImageFont.truetype(F_LIGHT, int(h * .034))
        self.f_num, self.f_foot = ImageFont.truetype(F_NUM, int(self.R * .62)), ImageFont.truetype(F_LIGHT, int(h * .026))
        rnd = random.Random(seed)
        self.specks = [(rnd.random() * w, rnd.random() * h, rnd.random() * 2 * math.pi, .6 + rnd.random() * 1.2) for _ in range(38)]

    # ---------- timing
    def phase(self, t):
        if t < self.t0: return "pre", t - self.t0, self.Li
        c = self.Li + self.Lo; k = math.floor((t - self.t0) / c)
        if self.cycles is not None and k >= self.cycles: return "post", t - (self.t0 + self.cycles * c), self.Lo
        u = (t - self.t0) - k * c
        return ("in", u, self.Li) if u < self.Li else ("out", u - self.Li, self.Lo)

    def k(self, t):
        """0 = smallest (breathed out), 1 = largest (breathed in). Uses the smoothed triangle, split at the turn."""
        ph, u, L = self.phase(t)
        if ph == "pre": return 0.0
        if ph == "post": return 0.0
        half = u / L * .5 if ph == "in" else .5 + u / L * .5
        return smooth_tri(half, self.sharp)

    # ---------- sprites
    def _panel(self):
        yy, xx = np.mgrid[0:self.H, 0:self.W].astype(np.float32)
        d = np.sqrt(((xx - self.cx) / (self.W * .62)) ** 2 + ((yy - self.cy) / (self.H * .62)) ** 2)
        a = np.clip(d, 0, 1)[..., None] ** 1.2
        img = np.array(NAVY_C, np.float32) * (1 - a) + np.array(NAVY_E, np.float32) * a
        return Image.fromarray(np.dstack([img, np.full((self.H, self.W), 255, np.float32)]).astype(np.uint8), "RGBA")

    def _disc_sprite(self, R):
        """Matte disc, radius R: warm inner glow (lighter centre-top), gently deeper rim, soft antialiased edge, no outline."""
        N = 2 * R; yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
        dx, dy = (xx - R + .5) / R, (yy - R + .5) / R; d = np.sqrt(dx * dx + dy * dy)
        edge = np.clip((1 - d) * R * .5, 0, 1)
        c = np.array(self.col, np.float32)
        hi = np.minimum(c + (255 - c) * .30, 255); lo = c * .86
        core = np.clip(1 - np.sqrt(dx ** 2 + (dy + .18) ** 2) / 1.25, 0, 1) ** 1.3
        body = lo + (hi - lo) * core[..., None]
        body = body * (1 - .06 * np.clip((d - .85) / .15, 0, 1))[..., None]
        return Image.fromarray(np.dstack([np.clip(body, 0, 255), edge * 255]).astype(np.uint8), "RGBA")

    def _halo_sprite(self):
        s = int(self.rmax * 3.2); im = Image.new("RGBA", (s, s), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        r = self.rmax * 1.05; d.ellipse([s / 2 - r, s / 2 - r, s / 2 + r, s / 2 + r], fill=self.col + (150,))
        return im.filter(ImageFilter.GaussianBlur(self.rmax * .28))

    # ---------- draw
    def render(self, t, alpha=1.0):
        im = self.bg.copy() if self.bg is not None else Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        ph, u, L = self.phase(t)
        fin = min(1.0, max(0.0, (t - (self.t0 - self.fade_in - .4)) / self.fade_in)) * alpha
        if ph == "post": fin *= max(0.0, 1 - u / self.fade_out)    # after the last out-breath the circle fades away
        sl = Image.new("RGBA", im.size, (0, 0, 0, 0)); sd = ImageDraw.Draw(sl)
        for x, y, p0, sz in self.specks:      # faint twinkle specks
            a = int(28 + 22 * math.sin(t * .7 + p0)); sd.ellipse([x - sz, y - sz, x + sz, y + sz], fill=(200, 215, 255, max(0, a)))
        im.alpha_composite(sl); d = ImageDraw.Draw(im)
        if fin <= 0: return im
        k = self.k(t); r = self.rmin + (self.rmax - self.rmin) * k
        # halo (soft, breathes with the disc)
        hs = self.halo.resize((max(2, int(self.halo.width * r / self.rmax)),) * 2, Image.BILINEAR)
        ha = hs.getchannel("A").point(lambda v: int(v * (.55 + .25 * k) * fin)); hs.putalpha(ha)
        im.alpha_composite(hs, (int(self.cx - hs.width / 2), int(self.cy - hs.height / 2)))
        # guide ring + progress arc (2x supersampled on a local tile)
        pad = 24; T = int(2 * (self.R + pad)); SS = 2
        tile = Image.new("RGBA", (T * SS, T * SS), (0, 0, 0, 0)); td = ImageDraw.Draw(tile)
        c0 = T * SS / 2; RR = self.R * SS; lw = max(2, int(self.H * .0035)) * SS
        td.ellipse([c0 - RR, c0 - RR, c0 + RR, c0 + RR], outline=(255, 255, 255, int(40 * fin)), width=lw)
        if ph in ("in", "out"):
            frac = u / L; ang = -90 + 360 * frac
            td.arc([c0 - RR, c0 - RR, c0 + RR, c0 + RR], -90, ang, fill=(255, 255, 255, int(230 * fin)), width=lw)
            hx, hy = c0 + RR * math.cos(math.radians(ang)), c0 + RR * math.sin(math.radians(ang)); dr = lw * 2.6
            td.ellipse([hx - dr * 2.2, hy - dr * 2.2, hx + dr * 2.2, hy + dr * 2.2], fill=(255, 255, 255, int(40 * fin)))
            td.ellipse([hx - dr, hy - dr, hx + dr, hy + dr], fill=(255, 255, 255, int(255 * fin)))
        tile = tile.resize((T, T), Image.LANCZOS)
        im.alpha_composite(tile, (int(self.cx - T / 2), int(self.cy - T / 2)))
        # disc, sub-pixel exact size
        ds = self.disc.resize((max(2, int(round(2 * r))),) * 2, Image.LANCZOS)
        if fin < 1: ds.putalpha(ds.getchannel("A").point(lambda v: int(v * fin)))
        im.alpha_composite(ds, (int(round(self.cx - ds.width / 2)), int(round(self.cy - ds.height / 2))))
        # countdown numeral
        if ph in ("in", "out"):
            n = max(1, min(self.count, math.ceil((L - u) / (L / self.count) - 1e-9)))
            uu = (L - u) % (L / self.count); age = (L / self.count) - uu          # seconds since this number appeared
            pop = min(1.0, age / .18); na = int(255 * fin * (.4 + .6 * pop))   # never blank between numbers
            f = self.f_num if pop >= 1 else ImageFont.truetype(F_NUM, int(self.R * .62 * (.9 + .1 * pop)))
            lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
            ImageDraw.Draw(lay).text((self.cx, self.cy + self.R * .02), str(n), font=f, fill=self.num_col + (na,), anchor="mm"); im.alpha_composite(lay)
        # labels: cross-fade at each turn (old fades out over .3 s, new fades in from the turn)
        self._labels(im, t, fin)
        if self.footnote:
            lay = Image.new("RGBA", im.size, (0, 0, 0, 0))
            ImageDraw.Draw(lay).text((self.cx, self.foot_y), self.footnote, font=self.f_foot, fill=(200, 210, 235, int(150 * fin)), anchor="mm"); im.alpha_composite(lay)
        return im

    def _labels(self, im, t, fin):
        ph, u, L = self.phase(t)
        if ph not in ("in", "out"): return
        i = 0 if ph == "in" else 1
        a_new = min(1.0, u / .3)
        layers = [(i, a_new)]
        if u < .3 and not (ph == "in" and t - self.t0 < .3): layers.append((1 - i, 1 - u / .3))
        for j, a in layers: self.text_block(im, self.labels[j], self.subs[j] if self.subs else "", a * fin)

    def text_block(self, im, title, sub="", alpha=1.0):
        """Title + sub-line in the label slot (also used by callers for a hook or outro line)."""
        if alpha <= 0: return
        lay = Image.new("RGBA", im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
        if title: d.text((self.cx, self.label_y), title, font=self.f_label, fill=(255, 255, 255, int(255 * alpha)), anchor="mm")
        if sub: d.text((self.cx, self.label_y + self.H * .068), sub, font=self.f_sub, fill=(205, 215, 240, int(210 * alpha)), anchor="mm")
        im.alpha_composite(lay)


def _probe(p):
    pr = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate",
                                    "-show_entries", "format=duration", "-of", "json", p], capture_output=True, text=True, check=True).stdout)
    n, d = map(int, pr["streams"][0]["r_frame_rate"].split("/")); return n / d, float(pr["format"]["duration"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", required=True); ap.add_argument("--overlay")
    ap.add_argument("--w", type=int, default=1080); ap.add_argument("--h", type=int, default=960)
    ap.add_argument("--x", type=int, default=0); ap.add_argument("--y", type=int, default=0)
    ap.add_argument("--dur", type=float, default=23); ap.add_argument("--fps", type=float, default=30)
    ap.add_argument("--color", default="red"); ap.add_argument("--t0", type=float, default=1.0)
    ap.add_argument("--cycles", type=int); ap.add_argument("--inhale", type=float, default=5.5); ap.add_argument("--exhale", type=float, default=5.5)
    ap.add_argument("--count", type=int, default=5); ap.add_argument("--sharp", type=float, default=.85)
    ap.add_argument("--transparent", action="store_true"); ap.add_argument("--no-text", action="store_true")
    ap.add_argument("--font-title"); ap.add_argument("--font-light"); ap.add_argument("--font-num")
    a = ap.parse_args()
    F_LABEL = a.font_title or F_LABEL; F_LIGHT = a.font_light or F_LIGHT; F_NUM = a.font_num or F_NUM
    fn = f"{a.inhale:g} in · {a.exhale:g} out"
    kw = dict(color=a.color, t0=a.t0, cycles=a.cycles, inhale=a.inhale, exhale=a.exhale, count=a.count, sharp=a.sharp, footnote=fn,
              bg=None if a.transparent else "navy")
    if a.no_text: kw.update(labels=("", ""), subs=None, footnote="")
    h = Hero(a.w, a.h, **kw)
    if a.overlay: fps, dur = _probe(a.overlay)
    else: fps, dur = a.fps, a.dur
    NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if a.overlay:
        ov = Path(a.out).with_suffix(".ov.mov")
        p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{a.w}x{a.h}", "-r", f"{fps}", "-i", "-",
                              "-c:v", "qtrle", str(ov)], stdin=subprocess.PIPE, creationflags=NOWIN)
    else:
        p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{a.w}x{a.h}", "-r", f"{fps}", "-i", "-",
                              "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", a.out], stdin=subprocess.PIPE, creationflags=NOWIN)
    for i in range(int(math.ceil(dur * fps))): p.stdin.write(h.render(i / fps).tobytes())
    p.stdin.close(); p.wait()
    if a.overlay:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.overlay, "-i", str(ov), "-filter_complex", f"[0:v][1:v]overlay={a.x}:{a.y}:shortest=1[v]",
                        "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy", a.out], check=True, creationflags=NOWIN)
        ov.unlink(missing_ok=True)
    print(a.out)
