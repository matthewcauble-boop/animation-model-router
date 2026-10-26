"""Draw the six placeholder frames for the example storyboard (flat shapes, 720x1280, no models, no assets).

  python tools/storyboard/example/make_frames.py      -> tools/storyboard/example/frames/S1.png .. S6.png

The story: a storm over a house on a hill; the sky; a ball falls out of it; it lands in a puddle; a round character
comes out of the door and sees it; the character picks it up and heads back right, toward the door.
"""
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw

W, H = 720, 1280
OUT = Path(__file__).resolve().parent / "frames"
SKY, SKY2 = (44, 58, 92), (70, 86, 124)
HILL, HILL2 = (58, 96, 72), (46, 80, 60)
WALL, ROOF, DOOR, GLOW = (196, 170, 130), (128, 58, 52), (92, 60, 40), (255, 205, 110)
BALL, BALL2 = (230, 70, 70), (250, 240, 235)
BODY, BODY2 = (120, 190, 230), (90, 160, 205)


def base(horizon):
    im = Image.new("RGB", (W, H), SKY)
    d = ImageDraw.Draw(im)
    for i in range(0, int(H * horizon), 8):  # simple sky gradient
        k = i / (H * horizon)
        d.rectangle([0, i, W, i + 8], fill=tuple(int(a + (b - a) * k) for a, b in zip(SKY, SKY2)))
    d.rectangle([0, H * horizon, W, H], fill=HILL)
    return im, d


def rain(d, n=140, seed=1, dx=18, dy=46):
    r = random.Random(seed)
    for _ in range(n):
        x, y = r.uniform(-60, W), r.uniform(0, H)
        d.line([(x, y), (x + dx, y + dy)], fill=(170, 195, 235), width=2)


def cloud(d, cx, cy, s, col=(96, 104, 130)):
    for ox, oy, r in ((-1.0, 0.2, 0.7), (0, -0.2, 0.95), (1.0, 0.15, 0.75), (0.4, 0.4, 0.7), (-0.5, 0.45, 0.6)):
        d.ellipse([cx + (ox - r) * s, cy + (oy - r) * s, cx + (ox + r) * s, cy + (oy + r) * s], fill=col)


def house(d, x, y, w):
    h = w * 0.75
    d.rectangle([x, y, x + w, y + h], fill=WALL)
    d.polygon([(x - w * 0.1, y), (x + w / 2, y - w * 0.55), (x + w * 1.1, y)], fill=ROOF)
    d.rectangle([x + w * 0.12, y + h * 0.2, x + w * 0.38, y + h * 0.48], fill=GLOW)
    d.rectangle([x + w * 0.58, y + h * 0.35, x + w * 0.84, y + h], fill=DOOR)


def ball(d, cx, cy, r):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=BALL)
    d.arc([cx - r, cy - r * 0.35, cx + r, cy + r * 0.35], 0, 180, fill=BALL2, width=max(3, int(r * 0.18)))


def blob(d, cx, cy, s, look=0.0):
    """A round character: body, two eyes looking along `look` (-1 left .. 1 right), feet."""
    d.ellipse([cx - 0.75 * s, cy + 0.85 * s, cx - 0.15 * s, cy + 1.15 * s], fill=BODY2)
    d.ellipse([cx + 0.15 * s, cy + 0.85 * s, cx + 0.75 * s, cy + 1.15 * s], fill=BODY2)
    d.ellipse([cx - s, cy - 0.6 * s, cx + s, cy + s], fill=BODY)
    for ex in (-0.32, 0.32):
        x, y = cx + ex * s, cy - 0.05 * s
        d.ellipse([x - 0.22 * s, y - 0.26 * s, x + 0.22 * s, y + 0.26 * s], fill=(255, 255, 255))
        px = x + look * 0.1 * s
        d.ellipse([px - 0.1 * s, y - 0.08 * s, px + 0.1 * s, y + 0.14 * s], fill=(30, 30, 40))


def save(im, name):
    OUT.mkdir(parents=True, exist_ok=True)
    im.quantize(64).save(OUT / f"{name}.png", optimize=True)


def main():
    # S1 storm wide: horizon on the lower third, house on the right third, rain slants down-right
    im, d = base(0.67)
    d.ellipse([-200, H * 0.62, W * 0.7, H * 0.9], fill=HILL2)
    cloud(d, 180, 170, 120)
    cloud(d, 560, 240, 100)
    house(d, 380, 640, 240)
    rain(d, seed=1)
    save(im, "S1")

    # S2 the sky: clouds, a lightning fork at the upper-right intersection, roofline at the bottom
    im, d = base(1.0)
    cloud(d, 200, 300, 150)
    cloud(d, 520, 520, 130)
    cloud(d, 300, 760, 120, (86, 94, 122))
    pts = [(470, 380), (520, 470), (480, 480), (540, 600)]
    d.line(pts, fill=(255, 250, 200), width=10, joint="curve")
    d.polygon([(-20, H), (W * 0.45, H * 0.9), (W + 20, H)], fill=ROOF)
    rain(d, n=90, seed=2)
    save(im, "S2")

    # S3 the fall: ball high on the right third, streaks above it
    im, d = base(1.0)
    cloud(d, 160, 160, 110)
    rain(d, n=110, seed=3)
    for k in range(4):
        d.line([(480 - 6 * k, 250 - 70 * k), (480 - 6 * k, 330 - 70 * k)], fill=(250, 200, 200), width=6 - k)
    ball(d, 480, 420, 46)
    save(im, "S3")

    # S4 the landing: ground line low, puddle, ball on the lower-right intersection, splash
    im, d = base(0.72)
    d.ellipse([300, 880, 660, 960], fill=(84, 110, 150))
    ball(d, 480, 860, 50)
    for a in (-2.4, -2.0, -1.2, -0.8):
        d.line([(480 + 60 * math.cos(a), 905 + 40 * math.sin(a)), (480 + 120 * math.cos(a), 905 + 90 * math.sin(a))],
               fill=(190, 215, 245), width=6)
    rain(d, n=80, seed=4)
    save(im, "S4")

    # S5 the door opens: warm light spills out, the character on the right third looks LEFT at the ball
    im, d = base(0.67)
    d.rectangle([300, 120, W, H * 0.67], fill=WALL)
    d.rectangle([380, 300, 640, H * 0.67], fill=GLOW)
    d.polygon([(380, H * 0.67), (640, H * 0.67), (720, H), (200, H)], fill=(170, 150, 90))
    blob(d, 480, 470, 130, look=-1)
    ball(d, 150, 980, 34)
    rain(d, n=60, seed=5)
    save(im, "S5")

    # S6 at the puddle: the character beside the ball, about to pick it up and head right
    im, d = base(0.67)
    d.ellipse([60, 900, 380, 970], fill=(84, 110, 150))
    ball(d, 190, 905, 40)
    blob(d, 360, 755, 120, look=-0.6)
    rain(d, n=90, seed=6)
    save(im, "S6")
    print(f"-> {OUT} (6 frames)")


if __name__ == "__main__":
    main()
