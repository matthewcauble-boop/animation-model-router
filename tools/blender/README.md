# tools/blender: the painted-world pipeline

Scripts for [BLENDER-WORLD.md](../../BLENDER-WORLD.md): a Blender blockout painted by an image-edit model, the paint
projected back onto real objects, 2D characters placed at real depth, gentle ambient motion, and the gates. Blender
scripts run headless (`blender -b file.blend -P script.py -- ARGS`; tested on Blender 5.1, EEVEE). The others are plain
Python 3.10+ with numpy and opencv-python-headless. Every script answers `--help` (Blender ones: `blender -b
--factory-startup -P script.py -- --help`).

| Script | Runs in | Does |
|---|---|---|
| `example_world.py` | Blender | builds a tiny blockout (terrain, path stones, pond, house face with a doorway, room, two treads; cameras `CamStart`, `CamMove` push, `CamMed` punch-in) to try everything on |
| `raycast_view.py` | Blender | per-pixel depth / object / height for a camera (`.npz` + a depth PNG): where the ground is, how 1/depth runs down the frame |
| `setup_projection.py` | Blender | projector cameras (a shot camera at a frame, N% wider) + the structure render and the flat-colour mask pass the painter starts from |
| `paint_split.py` | Python | the two masked edits for lawn and path: makes the inputs, then turns the repaints into projector textures |
| `lawnproj.py` | Blender | installs painted layers from projector cameras onto materials (later layers win, feathered); module or CLI |
| `render_frames.py` | Blender | renders a camera over a frame range (resumable, `STATUS.json`), or one still for a static background |
| `rgba_from_bw.py` | Python | straight-alpha RGBA (with the soft contact shadow) from a character rendered over black and over white |
| `depth_cards.py` | Blender | characters' RGBA sequences on camera-facing cards at the real ground depth (behind the jambs, on the treads, on the lawn), rendered with the world; `--no-chars` = the clean pass |
| `export_tracks.py` | Python | exact per-frame tracks (silhouette, visible part, contact) from the with- and without-character renders, for `tools/qa/staging_rules.py` |
| `ambient_masks.py` | Blender | flat lawn / water / path mask pass + per-frame cameras for `ambient.py` |
| `ambient.py` | Python | breeze in the lawn (threes), pond ripples and glints, waterfall streaks, motes (twos), world-anchored; `--demo` |
| `frozen_check.py` | Python | the gate after ambient motion: nothing outside the motion masks changed |
| `bw.py` | Blender | shared helpers (arguments after `--`, camera rays with lens shift, plane and raycast depth, flat mask colours) |

## Try it end to end (about 2 minutes, $0)

```bash
B=blender            # or the full path to blender.exe
W=work/bw            # any scratch folder
$B -b --factory-startup -P tools/blender/example_world.py -- --out $W/world.blend --render $W/start.png

# projectors + the renders to paint from (small sizes so it's quick)
$B -b $W/world.blend -P tools/blender/setup_projection.py -- --proj ProjA:CamStart:1:1.15 --proj ProjB:CamMed:96:1.12 \
   --mask TerrainPaint=#ff00ff --mask PathPaint=#00ffff --size 540x960 --out $W/proj --save $W/world_proj.blend
python tools/blender/paint_split.py inputs --src $W/proj/ProjB_src.png --mask $W/proj/ProjB_mask.png --out $W/paint/B
#   ... paint B_in_ground.png and B_in_path.png with your image-edit model (BLENDER-WORLD.md §10) ...
python tools/blender/paint_split.py textures --src $W/proj/ProjB_src.png --mask $W/proj/ProjB_mask.png \
   --ground-paint $W/paint/B_paint_ground.png --path-paint $W/paint/B_paint_path.png --out $W/paint/B
$B -b $W/world_proj.blend -P tools/blender/lawnproj.py -- --spec $W/layers.json --save $W/world_painted.blend \
   --check CamMed:96:$W/chk_med.png --size 540x960

# characters on depth cards (cards.json + rgba/<name>/f_0001.png ...), the clean pass, the tracks and the staging gate
$B -b $W/world_painted.blend -P tools/blender/depth_cards.py -- --config $W/cards.json --out $W/med
$B -b $W/world_painted.blend -P tools/blender/depth_cards.py -- --config $W/cards.json --out $W/clean --no-chars
python tools/blender/export_tracks.py --config $W/cards.json --frames $W/med --clean $W/clean/clean.png --out $W/tracks.json
python tools/qa/staging_rules.py --tracks $W/tracks.json --scene $W/scene.json

# ambient motion on the locked medium, then the frozen gate
$B -b $W/world_painted.blend -P tools/blender/ambient_masks.py -- --camera CamMed --f0 96 --f1 96 --out $W/masks_med --size 540x960
python tools/blender/ambient.py --still $W/clean/clean.png --masks $W/masks_med --mask-frame 96 --chars $W/med --out $W/med_amb
python tools/blender/frozen_check.py $W/med $W/med_amb $W/med_amb/motion $W/masks_med/m_0096.png

python tools/blender/ambient.py --demo work/amb-demo      # no Blender needed: a synthetic lawn moves, the path doesn't
python tools/qa/staging_rules.py --demo work/staging-demo  # a faulty and a fixed hop-out, no Blender needed
```

`layers.json`, `cards.json` and `scene.json` formats are in the docstrings of `lawnproj.py`, `depth_cards.py` and
`tools/qa/staging_rules.py`. In short:

```jsonc
// layers.json: one entry per projector, installed in order (later wins)
[{"tag": "B", "camera": "ProjB", "feather": 0.045,
  "textures": {"TerrainPaint": "paint/B_terrain.png", "PathPaint": "paint/B_path.png"}}]
// cards.json: the locked camera, the levels measured on the clean still, one track entry per frame per character
{"camera": "CamMed", "frame": 96, "scene_frame": 96, "size": [1080, 1920], "rgba": "rgba",
 "face": "HouseFace", "sill_row": 868, "foot_row": 1088, "see_through": ["Interior"],
 "characters": {"red": "track_red.json"}}
// track_red.json: [{"x": 540, "g": 860, "h": 120, "vis": true, "air": false, "contact": true, "seg": 0}, ...]
```

## Notes

- Material nodes are found by type (the emission node that carries the paint), never by name, so a localised Blender
  works. Objects and materials are addressed by name: keep the names from your blockout consistent, or pass yours.
- The camera must be **locked** while characters are on cards (a hold or a punch-in): `depth_cards.py` reads the camera
  once, at `frame`. Put character action in locked shots and camera moves in shots without characters, or cut between.
- Character RGBA frames are full frame at the output size, straight alpha, `rgba/<name>/f_0001.png ...`.
- `ambient.py` assumes the ground is the plane z = 0 (world metres) and reads the sensor fit from `cams.json`.
- Measured times and costs per step: [BLENDER-WORLD.md](../../BLENDER-WORLD.md#12-render-times-and-speed-ups).
