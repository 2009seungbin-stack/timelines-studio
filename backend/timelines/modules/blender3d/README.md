# Blender 3D production engine (`timelines.modules.blender3d`)

Procedural 3D scenes for TIMELINES Studio. No AI image/video generation and no
downloaded models: every mesh, light and camera is created by code through the
Blender Python API (Blender 5.1, EEVEE). Materials layer CC0 photo textures and
the sky uses CC0 HDRIs from Poly Haven (see "Textures and licences").

## API

```python
from timelines.modules.blender3d.engine import render_scene, BlenderNotFound, RenderFailed
res = render_scene(spec: Scene3DSpec, out_dir: Path, *, blender_exe=None, use_gpu_lock=True,
                   progress=lambda frac, msg: ...)
# -> {video, blend, thumb, frames, fps, width, height, render_s, engine, quality,
#     assets_used, bpy_script, log, per_frame_s, build_s, polygons, lock_wait_s, gpu_lock, spec_json}

from timelines.modules.blender3d.assets import build_asset_library, list_assets
metas = build_asset_library()          # data/assets/<asset_id>/{asset.blend, preview.jpg, meta.json}
```

Pipeline of `render_scene`:
1. writes `<scene>_<quality>.spec.json` (spec + `frame_count` + output paths);
2. inside the GPU lock runs
   `blender -b --factory-startup --python bpy_scripts/render_scene.py -- --spec <json> --out <dir>`;
3. the script builds the city, camera and lighting, **saves `<scene>_<quality>.blend`**, then renders
   JPEG frames (q 92). Progress: `TL_STAGE` lines while building (0-15 %), `TL_FRAME i n sec`
   per written frame (15-95 %);
4. FFmpeg encodes H.264 / yuv420p / crf 18; ffprobe must report exactly
   `round(duration_s * fps)` frames (round half up), otherwise `RenderFailed`;
5. thumbnail `<scene>_<quality>_thumb.jpg` from the middle frame, then the frame folder created by
   this call is deleted.

`quality="preview"`: 50 % resolution, 8 TAA samples, no ray tracing, half-res shadows, no AO node in
materials, opaque leaf shadows (`tl_materials.FAST`).
`quality="final"`: full resolution, 40 samples, screen-space ray tracing (water/glossy), full shadows,
subtle depth of field (f/2.8, focus keyed to the shot target every frame - only near foreground softens).

GPU lock: renders run inside `gpu_lock.gpu_slot` (research/portfolio_flagship_20261029); the shared
lock worked for every v2 render (`gpu_lock: "shared"`). The fallback lock
`data/dev_renders/.gpu_fallback.lock` remains for when the shared lock folder is unavailable.

## Files

| file | role |
|---|---|
| `engine.py` | host API, Blender/FFmpeg orchestration, GPU lock, progress parsing |
| `assets.py` | host API for the asset library |
| `bpy_scripts/render_scene.py` | Blender entry for scenes |
| `bpy_scripts/build_assets.py` | Blender entry for the asset library (+ asset metadata/notes) |
| `bpy_scripts/tl_city.py` | city layout for both eras (blocks, sidewalks, porticoes, street props, forum, vegetation scatter, camera POIs) |
| `bpy_scripts/tl_buildings.py` | building generators (basilica, aqueduct, walls, gate, amphitheatre, churches, watermills, ship, lighthouse, horreum, tombs, villa); re-exports the v2 generators of `tl_arch` |
| `bpy_scripts/tl_arch.py` | v2 detail: Corinthian order (attic base, fluted shaft, capital), entablature, temple, Ostia-type facades, insula, domus, props (fountain, stall, cart, amphorae, statue) |
| `bpy_scripts/tl_nature.py` | terrain height field (+ shore attribute, water grid with depth) |
| `bpy_scripts/tl_trees.py` | leaf-card trees (cypress, umbrella pine, olive, broadleaf, shrub, grass tuft, vine rows) + Geometry-Nodes instancing (`TreeScatter`) |
| `bpy_scripts/tl_materials.py` | PBR materials: Poly Haven maps + procedural tint/weathering; procedural fallback when a map is missing |
| `bpy_scripts/tl_scene.py` | render settings, lighting presets, HDRI sky aligned to the sun lamp, aerial-perspective haze, camera presets, DOF |
| `bpy_scripts/tl_mesh.py` | mesh builder (metre UVs, per-face attributes, modelled roof tiles, ridge tiles, mouldings) |
| `fetch_textures.py` | downloads the CC0 textures/HDRIs and writes `data/textures/LICENSES.json` |

The city and the asset library call the same generator functions, so assets and scenes never diverge.

## `Scene3DSpec` usage

* `kind`: `roman_city` (also `forum`, `aqueduct`, `harbor` = same city, camera focused on that feature;
  `harbor` implies `harbor=True`, `era="alt_1000"`). `custom` raises `ValueError`.
* `seed`: drives every random choice (lot subdivision, building types, heights, trees, ships).
* `camera`: `orbit`, `dolly_in`, `crane_down`, `flyover`, `static` - all eased (smootherstep blended with
  linear), keyed every frame, quaternions (no flips). Flyover = arc-length parametrised Catmull-Rom path
  (aqueduct -> mills -> north wall -> city centre -> harbour/forum).
* `lighting`: `golden_hour` (sun 13 deg), `noon` (60 deg), `overcast` (soft, grey dome), `dusk` (3 deg).
  Physical sky (multiple scattering) + sun lamp with soft angle, AgX "Medium High Contrast",
  height-dependent aerial-perspective haze tinted towards the sun, thin procedural cloud deck.
  No bloom (restrained by design). No text is ever rendered.
* `params`:
  * `era`: `late_antique_476` (default) | `alt_1000`
  * `harbor`: bool (sea, quay, moles, lighthouse, horrea, ships)
  * `nx`, `ny`: number of city blocks (defaults 8x6 / 10x8)
  * `camera_focus`: `forum` | `aqueduct` | `harbor` | `church`
  * camera tuning: `view_az`, `lens`, `crane_h0/h1/d0/d1`, `orbit_r/h/sweep`, `dolly_d0/d1`
  * `sun_azimuth_deg`: override the automatic sun placement
  * `camera_legacy`: true = v1 camera paths (used for the before/after sheets)
* `crane_down` with focus `forum` (v2): starts ~230 m over the forum looking north over the city and ends
  21 m high, ~65 m from the temple front, 24 m off-axis (3/4 view of front and west flank).
* `flyover` (v2): 34-82 m high - beside the mill cascade (alt_1000), along the aqueduct, over the north
  wall, past the domed church, ending on the harbour (or forum without harbour).

## Eras

* **late_antique_476** (INTERPRETATION, generic provincial/Italian city, not a real site): 8x6 grid of
  72 m insulae (2 actus), cardo/decumanus maximus, forum with Corinthian hexastyle temple (Vitruvian
  proportions) and basilica, mixed domus / 2-4 storey insulae, roofless ruins and urban gardens near the
  edges (late-antique contraction), early Christian basilica church, late Roman walls with towers and
  double gates, aqueduct on arches from the NE hills (two tiers across a valley), amphitheatre outside
  the walls, roads with a necropolis and cypresses, centuriated fields, villae rusticae.
* **alt_1000** (SPECULATION): same grammar, 10x8 blocks, 3-6 storey insulae, extramural suburbs,
  centrally domed basilica church east of the forum (precedent Hagia Sophia, 537), a Barbegal-type
  cascade of 16 water mills fed by an aqueduct branch, optional harbour with moles, lighthouse, horrea,
  merchant ships. No technology beyond these precedents.

## v2 upgrade (2026-11-26) - what changed

* **Real geometry where the camera sees it**: every sloping `TL_Tile` polygon gets modelled imbrices
  (0.42 m pitch, closed eave ends) and ridge/hip tiles; insula/domus street facades are modelled (recessed
  windows with sills and open/closed shutters, 1.7 m deep tabernae with counters/shutter boards/amphorae,
  stair doors, string course, two-step eave cornice, timber maeniana or tile pent roofs on brackets).
  Party walls and light courts keep shader windows (not visible from the street).
* **Temple**: attic bases, 24-flute shafts with entasis, approximated Corinthian capitals (2 x 8 leaves,
  4 volutes, concave abacus with fleurons), entablature with fasciae/frieze/dentils/modillions/corona/sima,
  raking cornices, recessed tympanum, acroterion plinths, podium mouldings, bronze door, moulded altar.
* **Variety**: plaster palette (ochre, cream, faded red, grey, pink, white) with fallen-plaster brick
  patches, streaks and rising damp; long insulae split into two masses of different height; hip/gable/
  courtyard roofs with random pitch; roof palette with weathered browns and lichen.
* **Street life**: raised sidewalks with kerbs, stepping stones at crossings, colonnaded porticoes along
  cardo and decumanus, Pompeii-type street fountains, amphora stacks, parked carts, forum statues on
  plinths, bronze monument, market stalls with cloth awnings.
* **Vegetation**: card-based cypress/umbrella pine/olive/broadleaf/shrub/grass (150-450 cards each,
  procedural leaf alpha, translucency, outward normals) instanced via Geometry Nodes (~17k instances in S06);
  vineyards (trained rows), more hedgerows/olive groves, maquis around walls, mills and aqueduct.
* **Materials**: Poly Haven CC0 maps (UV-in-metres for walls/roofs, world XY for terrain/paving, box
  projection for marble/bark) layered with procedural colour variation, AO, weathering.
* **Light**: CC0 "pure sky" HDRIs for dusk and golden hour, rotated so the HDRI sun matches the sun lamp,
  hotspot clamped (the lamp casts the sharp shadow); dusk sun 8 deg from the WSW (raking light on the temple
  front), golden hour 16 deg; near hills cast shadows (the far mountain ring does not).
* **Terrain**: shore sand band along the coast, water grid with a depth attribute (lighter shallows, foam
  line), greener patchy ground with maquis patches, fields reaching closer to the walls.
* Comparison sheets (same camera, v1 thumbnail vs v2): `data/dev_renders/upgrade/compare_*.jpg`.

## Measured timings (GTX 1080 8 GB, EEVEE, v2, 2026-11-26, shared GPU lock)

| scene | quality | output | build (geometry) | per frame (avg) | total Blender wall time |
|---|---|---|---|---|---|
| S01 476 CE, crane_down, dusk, 240 f | preview | 960x540 | 13 s (1.01 M polys + ~9k tree instances) | 0.23 s | 68 s |
| S06 1000 CE, flyover, golden_hour, harbour, 360 f | preview | 960x540 | 27 s (2.13 M polys + ~17k instances) | 0.30 s | 137 s |
| S01 | final | 1920x1080 | 13 s | 10.2 s (6 s wide -> ~13 s on the close temple frames) | 2471 s |
| S06 | final | 1920x1080 | 27 s | 7.0 s | 2567 s |

v1 for reference: preview 0.23/0.24 s, final 1.69/2.06 s per frame, 0.46-0.59 M polys. Finals are ~4-6x
slower (modelled detail, leaf cards with transparent shadows, AO, DOF, HDRI). Cycles was not adopted: at
these polygon/instance counts an 8 s/frame budget on a GTX 1080 is not realistic. First frame includes
shader compilation; dev single-frame renders (`--frames`) are slower than animation renders because each
frame re-syncs the scene. Textures: 36 MB (`data/textures`). Samples: `data/dev_renders/samples_v2/`.

## Textures and licences

`python -m timelines.modules.blender3d.fetch_textures` (from `backend/`) downloads, and
`data/textures/LICENSES.json` records, Poly Haven assets (CC0, https://polyhaven.com/license):
clay_roof_tiles_02, plastered_wall_04, red_brick_plaster_patch_02, medieval_red_brick,
large_sandstone_blocks_01, marble_01, cobblestone_large_01, aerial_grass_rock, aerial_rocks_02,
coast_sand_01, dirt, weathered_brown_planks, bark_brown_02 (1K JPG, roof 2K) and the HDRIs
qwantani_dusk_2_puresky, kloppenheim_06_puresky (2K .hdr). No other third-party assets.

## Known limitations (v2)

* Close-up limits: capitals are leaf patches + volutes (no carved acanthus), statues are abstract draped
  figures, no people/animals/laundry/smoke; shop interiors are dark recesses.
* Party walls and light-court walls still use shader windows; roofs of neighbouring buildings abut
  without valleys/flashing; tegulae are a photo map under modelled imbrices.
* Plaster weathering and brick patches come from tiling maps; they repeat on large flat walls.
* Leaf-card trees read well from >20 m; closer they show card edges. Grass tufts are too small to
  matter above ~30 m.
* Water: flat plane with procedural waves; no wakes, no animated surf; harbour moles/quays are plain.
* Aqueduct: plain ashlar arcade; where the ground rises to the channel it becomes a long solid wall
  that reads as a bright wedge at dusk. Mill wheels are mostly hidden in their pits.
* No river (S01 landscape has none); layout is still a generic orthogonal colonia without theatre,
  baths or circus.
* Final render time 7-10 s/frame (see table).
* Historical content is approximate; dimensions not attributed to Vitruvius or a named monument in
  `data/assets/*/meta.json` are estimates.
