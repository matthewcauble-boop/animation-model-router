"""render_frames: render a camera over a frame range, resumable (existing frames are skipped). The world-only pass.

    blender -b world.blend -P tools/blender/render_frames.py -- --camera CamMove --f0 1 --f1 96 --out work/bw/wide \
            [--size 1080x1920] [--samples 16] [--hide Spill,RoomHaze] [--still 96 --out-still work/bw/med_clean.png]

--still F renders ONE frame (for a locked camera on a static world: render the background once, never per frame; then
animate only what moves on top, e.g. depth_cards.py for characters or ambient.py for grass and water).
Writes f_0001.png ... and STATUS.json (phase, last frame, seconds per frame) in --out, so a detached job can be
watched and restarted.
"""
import argparse, json, os, sys, time

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bw  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Render a camera over a frame range (resumable), or one still.")
    ap.add_argument("--camera", required=True)
    ap.add_argument("--f0", type=int, default=1); ap.add_argument("--f1", type=int)
    ap.add_argument("--out", help="frame folder"); ap.add_argument("--size", default="1080x1920")
    ap.add_argument("--samples", type=int, default=16, help="EEVEE samples (16 matched 32 within 0.05%% of pixels)")
    ap.add_argument("--hide", default="", help="comma-separated objects hidden in this pass")
    ap.add_argument("--still", type=int, help="render only this frame, to --out-still")
    ap.add_argument("--out-still")
    a = bw.args(ap)
    s = bw.scene(); s.camera = bpy.data.objects[a.camera]
    W, H = map(int, a.size.lower().split("x")); bw.set_output(W, H, a.samples)
    for n in filter(None, a.hide.split(",")): bpy.data.objects[n].hide_render = True
    if a.still is not None:
        if not a.out_still: ap.error("--still needs --out-still")
        s.frame_set(a.still); bw.render_to(a.out_still); print("DONE still", a.out_still); return
    if not a.out: ap.error("--out is required")
    os.makedirs(a.out, exist_ok=True); f1 = a.f1 or s.frame_end; t0 = time.time(); n = 0
    for fr in range(a.f0, f1 + 1):
        o = os.path.join(a.out, f"f_{fr:04d}.png")
        if os.path.exists(o): continue
        s.frame_set(fr); bw.render_to(o); n += 1
        json.dump(dict(phase="render", frame=fr, of=f1, s_per_frame=round((time.time() - t0) / n, 2)),
                  open(os.path.join(a.out, "STATUS.json"), "w"))
        print("FRAME", fr, flush=True)
    json.dump(dict(phase="done", frames=f1 - a.f0 + 1, rendered=n, s_per_frame=round((time.time() - t0) / max(1, n), 2)),
              open(os.path.join(a.out, "STATUS.json"), "w"))
    print("DONE render_frames", a.out)


if __name__ == "__main__":
    main()
