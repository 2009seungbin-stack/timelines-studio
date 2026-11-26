"""Blender entry point: build a Scene3DSpec scene, save .blend, render JPEG frames.

blender -b --factory-startup --python render_scene.py -- --spec spec.json --out DIR [--no-render]
Prints ``TL_STAGE <0..1> <msg>`` while building and ``TL_FRAME <i> <n> <sec>`` per frame.
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bpy  # noqa: E402

try:  # no .blend1 backup copies when a file is overwritten (disk space)
    bpy.context.preferences.filepaths.save_version = 0
except Exception:
    pass


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = {"no_render": False}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--spec":
            out["spec"] = argv[i + 1]
            i += 2
        elif a == "--out":
            out["out"] = argv[i + 1]
            i += 2
        elif a == "--no-render":
            out["no_render"] = True
            i += 1
        elif a == "--frames":          # dev: render only selected frames, e.g. 1,90,180
            out["frames"] = [int(x) for x in argv[i + 1].split(",")]
            i += 2
        else:
            i += 1
    return out


def stage(f, msg):
    print(f"TL_STAGE {f:.3f} {msg}", flush=True)


def clear_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        for item in list(block):
            block.remove(item)


def main():
    import tl_city
    import tl_scene

    a = _args()
    with open(a["spec"], encoding="utf-8") as fh:
        spec = json.load(fh)
    out = a["out"]
    paths = spec.get("_paths", {})
    sid = spec["scene_id"]
    quality = spec.get("quality", "preview")
    base = f"{sid}_{quality}"
    blend = paths.get("blend", os.path.join(out, base + ".blend"))
    frames_dir = paths.get("frames", os.path.join(out, base + "_frames"))
    result_path = paths.get("result", os.path.join(out, base + ".result.json"))
    nframes = int(spec.get("frame_count") or max(1, int(spec["duration_s"] * spec["fps"] + 0.5)))
    params = dict(spec.get("params") or {})
    params["_kind"] = spec.get("kind", "roman_city")
    if params["_kind"] == "harbor":
        params.setdefault("harbor", True)
        params.setdefault("era", "alt_1000")

    t0 = time.time()
    import tl_materials
    tl_materials.FAST = quality == "preview"
    clear_scene()
    scene = bpy.context.scene
    scene.name = sid
    stage(0.02, "building city")
    city = tl_city.build_city(params, int(spec.get("seed", 7)), stage)
    stage(0.85, "camera and lighting")
    tl_scene.setup_render(scene, int(spec["width"]), int(spec["height"]), int(spec["fps"]), nframes, quality)
    cam, path = tl_scene.build_camera(scene, spec.get("camera", "orbit"), city.poi, nframes, int(spec.get("seed", 7)))
    # sun azimuth: preset side angle relative to the shot's mean viewing direction (overridable)
    if "sun_azimuth_deg" in params:
        sun_az = float(params["sun_azimuth_deg"])
    elif spec.get("camera") == "flyover" and "fly_sun_az" in city.poi:
        sun_az = float(city.poi["fly_sun_az"])
    else:
        import math
        l0, t0_, _ = path(0.0)
        l1, t1_, _ = path(1.0)
        d = (t0_ - l0).normalized() + (t1_ - l1).normalized()
        view = math.degrees(math.atan2(d.y, d.x))
        sun_az = view + tl_scene.LIGHTING[spec.get("lighting", "golden_hour")]["side"]
    tl_scene.setup_world(scene, spec.get("lighting", "golden_hour"), sun_az)
    scene["tl_spec"] = json.dumps({k: v for k, v in spec.items() if not k.startswith("_")})
    scene["tl_classification"] = spec.get("classification", "")
    scene["tl_era_label"] = spec.get("era_label", "")
    polys = sum(len(o.data.polygons) for o in scene.objects if o.type == "MESH")
    build_s = time.time() - t0
    stage(0.95, f"saving blend ({polys} polygons)")
    os.makedirs(os.path.dirname(blend), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=blend, compress=True, copy=True)
    stage(1.0, "rendering")

    result = {
        "engine": scene.render.engine, "assets_used": sorted(city.assets), "build_s": round(build_s, 2),
        "polygons": polys, "trees": city.stats.get("trees"), "sun_azimuth_deg": round(sun_az, 1),
        "era": city.era, "poi": {k: v for k, v in city.poi.items() if k in ("focus", "view_az")},
    }
    if not a["no_render"]:
        os.makedirs(frames_dir, exist_ok=True)
        scene.render.filepath = os.path.join(frames_dir, "f_####")
        scene.render.use_file_extension = True
        times = {"last": time.time()}
        sel = a.get("frames")
        if sel:
            for i, fr in enumerate(sel):
                scene.frame_set(fr)
                scene.render.filepath = os.path.join(frames_dir, f"f_{fr:04d}")
                bpy.ops.render.render(write_still=True)
                now = time.time()
                print(f"TL_FRAME {i + 1} {len(sel)} {now - times['last']:.3f}", flush=True)
                times["last"] = now
        else:
            def on_write(sc, *_):
                now = time.time()
                print(f"TL_FRAME {sc.frame_current - sc.frame_start + 1} {nframes} {now - times['last']:.3f}",
                      flush=True)
                times["last"] = now
            bpy.app.handlers.render_write.append(on_write)
            t_r = time.time()
            times["last"] = t_r
            bpy.ops.render.render(animation=True)
            result["render_frames_s"] = round(time.time() - t_r, 2)
    with open(result_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
    print("TL_DONE", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        sys.exit(1)
