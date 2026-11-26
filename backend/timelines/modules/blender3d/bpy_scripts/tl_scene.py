"""Render settings, lighting presets, aerial-perspective haze and camera presets."""
from __future__ import annotations

import math

import bpy
from mathutils import Vector

# --------------------------------------------------------------------------- lighting presets
# elevation/strength values were calibrated by eye on test renders (AgX view transform).
LIGHTING = {
    "golden_hour": dict(elev=16.0, sun_color=(1.0, 0.68, 0.42), sun_strength=10.0, sky_strength=0.11,
                        angle=1.8, haze_density=0.00036, haze_far=(0.60, 0.62, 0.66), haze_sun=(1.0, 0.72, 0.46),
                        exposure=0.0, air=1.0, aerosol=1.6, side=105.0),
    "noon": dict(elev=60.0, sun_color=(1.0, 0.97, 0.93), sun_strength=11.0, sky_strength=0.10, angle=0.9,
                 haze_density=0.00030, haze_far=(0.66, 0.74, 0.86), haze_sun=(0.80, 0.84, 0.90),
                 exposure=-0.6, air=1.0, aerosol=1.0, side=110.0),
    "overcast": dict(elev=40.0, sun_color=(0.92, 0.94, 1.0), sun_strength=0.9, sky_strength=0.0,
                     angle=40.0, haze_density=0.00065, haze_far=(0.62, 0.64, 0.66), haze_sun=(0.66, 0.67, 0.68),
                     exposure=0.4, air=1.0, aerosol=3.0, side=90.0, overcast=True),
    "dusk": dict(elev=8.0, sun_color=(1.0, 0.56, 0.30), sun_strength=11.0, sky_strength=0.16, angle=1.6,
                 haze_density=0.00050, haze_far=(0.30, 0.32, 0.42), haze_sun=(0.95, 0.52, 0.30),
                 exposure=0.35, air=1.2, aerosol=2.2, side=112.0),
}


def s2l(c):
    def f(x):
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    return (f(c[0]), f(c[1]), f(c[2]), 1.0)


def sun_vector(elev_deg, az_deg):
    e, a = math.radians(elev_deg), math.radians(az_deg)
    return Vector((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)))


def setup_render(scene, width, height, fps, nframes, quality):
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.fps = fps
    scene.render.fps_base = 1.0
    scene.frame_start = 1
    scene.frame_end = nframes
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 50 if quality == "preview" else 100
    scene.render.film_transparent = False
    scene.render.use_motion_blur = False
    ee = scene.eevee
    final = quality == "final"
    ee.taa_render_samples = 40 if final else 8
    ee.use_shadows = True
    ee.shadow_ray_count = 2 if final else 1
    ee.shadow_step_count = 8 if final else 4
    ee.shadow_resolution_scale = 1.0 if final else 0.5
    ee.use_raytracing = bool(final)
    try:
        ee.ray_tracing_method = "SCREEN"
        ee.ray_tracing_options.resolution_scale = "2"
        ee.fast_gi_method = "GLOBAL_ILLUMINATION"
    except Exception:
        pass
    ee.use_fast_gi = True
    ee.fast_gi_distance = 30.0
    ee.fast_gi_resolution = "2" if final else "4"
    try:
        scene.render.filter_size = 1.2
    except Exception:
        pass
    vs = scene.view_settings
    vs.view_transform = "AgX"
    for look in ("AgX - Medium High Contrast", "Medium High Contrast", "AgX - Base Contrast"):
        try:
            vs.look = look
            break
        except TypeError:
            continue
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.quality = 92
    try:
        scene.render.image_settings.color_management = "FOLLOW_SCENE"
    except Exception:
        pass


# CC0 Poly Haven "pure sky" HDRIs (data/textures, LICENSES.json); strength = target mean sky radiance
HDRI = {"dusk": ("qwantani_dusk_2_puresky", 0.16), "golden_hour": ("kloppenheim_06_puresky", 0.30)}


def _hdri_file(lighting):
    import glob
    import os
    from tl_materials import TEX_ROOT
    if lighting not in HDRI:
        return None
    hits = glob.glob(os.path.join(TEX_ROOT, HDRI[lighting][0], "*.hdr"))
    return hits[0] if hits else None


def _hdri_stats(img):
    """Azimuth (deg, world convention) of the brightest pixel and mean upper-hemisphere luminance."""
    import numpy as np
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    lum = px[..., 0] * 0.2126 + px[..., 1] * 0.7152 + px[..., 2] * 0.0722
    upper = lum[h // 2:, :]
    j, i = np.unravel_index(int(np.argmax(upper)), upper.shape)
    u = (i + 0.5) / w
    phi = (u - 0.5) * 2 * math.pi          # Blender equirect: u = atan2(d.y, -d.x) / 2pi + 0.5
    az = math.degrees(math.pi - phi)
    mean = float(np.minimum(upper, 8.0).mean())
    return az, mean


def setup_world(scene, lighting, sun_az_deg):
    p = LIGHTING[lighting]
    world = bpy.data.worlds.get("TL_World") or bpy.data.worlds.new("TL_World")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    hdri = _hdri_file(lighting)
    if hdri:
        img = bpy.data.images.load(hdri, check_existing=True)
        az_h, mean = _hdri_stats(img)
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.image = img
        tc = nt.nodes.new("ShaderNodeTexCoord")
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(az_h - sun_az_deg))
        nt.links.new(tc.outputs["Generated"], mp.inputs["Vector"])
        nt.links.new(mp.outputs[0], env.inputs["Vector"])
        cl = nt.nodes.new("ShaderNodeVectorMath")        # clamp the sun hotspot (the lamp is the sun)
        cl.operation = "MINIMUM"
        cl.inputs[1].default_value = (8.0, 8.0, 8.0)
        nt.links.new(env.outputs["Color"], cl.inputs[0])
        nt.links.new(cl.outputs[0], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = HDRI[lighting][1] / max(mean, 1e-3)
        nt.links.new(bg.outputs[0], out.inputs["Surface"])
        try:
            world.sun_threshold = 1000.0
        except Exception:
            pass
        world["tl_hdri"] = HDRI[lighting][0]
        return _sun_and_haze(scene, p, sun_az_deg, clouds=False, lighting=lighting)
    sky = nt.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "MULTIPLE_SCATTERING"
    sky.sun_disc = False
    sky.sun_elevation = math.radians(max(p["elev"], 0.5))
    # Blender's sky rotation is measured from +Y towards -X (verified on test renders)
    sky.sun_rotation = math.radians(sun_az_deg - 90.0)
    sky.altitude = 120.0
    sky.air_density = p["air"]
    sky.aerosol_density = p["aerosol"]
    if p.get("overcast"):
        # overcast: desaturated, bright, soft dome
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.inputs[0].default_value = 0.85
        nt.links.new(sky.outputs[0], mix.inputs[6])
        geo = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(geo.outputs["Generated"], sep.inputs[0])
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = s2l((0.78, 0.79, 0.80))
        ramp.color_ramp.elements[1].color = s2l((0.62, 0.64, 0.67))
        nt.links.new(sep.outputs[2], ramp.inputs[0])
        mix.inputs[7].default_value = (0, 0, 0, 1)
        nt.links.new(ramp.outputs[0], mix.inputs[7])
        nt.links.new(mix.outputs[2], bg.inputs[0])
        bg.inputs[1].default_value = 1.1
    else:
        nt.links.new(sky.outputs[0], bg.inputs[0])
        bg.inputs[1].default_value = p["sky_strength"]
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    return _sun_and_haze(scene, p, sun_az_deg, clouds=p.get("clouds", True), lighting=lighting)


def _sun_and_haze(scene, p, sun_az_deg, clouds, lighting):
    sun_data = bpy.data.lights.get("TL_Sun") or bpy.data.lights.new("TL_Sun", "SUN")
    sun_data.energy = p["sun_strength"]
    sun_data.color = p["sun_color"]
    sun_data.angle = math.radians(p["angle"])
    try:
        sun_data.shadow_maximum_resolution = 0.001
        sun_data.shadow_cascade_max_distance = 3000.0
    except Exception:
        pass
    sun = bpy.data.objects.get("TL_Sun") or bpy.data.objects.new("TL_Sun", sun_data)
    if sun.name not in scene.collection.objects:
        scene.collection.objects.link(sun)
    sv = sun_vector(p["elev"], sun_az_deg)
    sun.rotation_mode = "QUATERNION"
    sun.rotation_quaternion = sv.to_track_quat("Z", "Y")
    scene.view_settings.exposure = p["exposure"]
    update_haze(p, sv)
    if clouds:
        add_clouds(scene, lighting, sv)
    return sv


# --------------------------------------------------------------------------- cloud layer
CLOUDS = {
    "golden_hour": dict(cover=0.58, opacity=0.75, base=(0.80, 0.76, 0.74), sun=(1.0, 0.78, 0.56), strength=0.9),
    "noon": dict(cover=0.62, opacity=0.8, base=(0.95, 0.96, 0.98), sun=(1.0, 1.0, 1.0), strength=1.6),
    "overcast": dict(cover=0.30, opacity=0.9, base=(0.70, 0.71, 0.73), sun=(0.75, 0.76, 0.78), strength=1.0),
    "dusk": dict(cover=0.56, opacity=0.8, base=(0.46, 0.40, 0.48), sun=(1.0, 0.56, 0.36), strength=0.75),
}


def add_clouds(scene, lighting, sun_vec, seed=0, z=2400.0, size=60000.0):
    """Thin procedural cloud deck (emission + transparency, no shadows)."""
    c = CLOUDS[lighting]
    me = bpy.data.meshes.new("TL_Clouds")
    h = size / 2
    me.from_pydata([(-h, -h, z), (h, -h, z), (h, h, z), (-h, h, z)], [], [(0, 1, 2, 3)])
    mat = bpy.data.materials.new("TL_Clouds")
    mat.use_nodes = True
    try:
        mat.surface_render_method = "DITHERED"
    except Exception:
        pass
    nt = mat.node_tree
    nt.nodes.clear()
    n, L = nt.nodes, nt.links
    geo = n.new("ShaderNodeNewGeometry")
    mapn = n.new("ShaderNodeMapping")
    mapn.inputs["Scale"].default_value = (1 / 3200.0, 1 / 1500.0, 1 / 2000.0)
    mapn.inputs["Location"].default_value = (seed * 0.37, seed * 0.11, 0.0)
    L.new(geo.outputs["Position"], mapn.inputs["Vector"])
    noi = n.new("ShaderNodeTexNoise")
    noi.inputs["Scale"].default_value = 1.0
    noi.inputs["Detail"].default_value = 8.0
    noi.inputs["Roughness"].default_value = 0.6
    noi.inputs["Distortion"].default_value = 0.3
    L.new(mapn.outputs[0], noi.inputs["Vector"])
    mr = n.new("ShaderNodeMapRange")
    mr.inputs[1].default_value = c["cover"]
    mr.inputs[2].default_value = c["cover"] + 0.18
    mr.inputs[3].default_value = 0.0
    mr.inputs[4].default_value = c["opacity"]
    L.new(noi.outputs["Fac"], mr.inputs[0])
    # fade out towards the far edge of the deck
    cam = n.new("ShaderNodeCameraData")
    fade = n.new("ShaderNodeMapRange")
    fade.inputs[1].default_value = 12000.0
    fade.inputs[2].default_value = 26000.0
    fade.inputs[3].default_value = 1.0
    fade.inputs[4].default_value = 0.0
    L.new(cam.outputs["View Distance"], fade.inputs[0])
    alpha = n.new("ShaderNodeMath")
    alpha.operation = "MULTIPLY"
    L.new(mr.outputs[0], alpha.inputs[0])
    L.new(fade.outputs[0], alpha.inputs[1])
    # colour: brighter and warmer towards the sun, denser parts slightly darker
    neg = n.new("ShaderNodeVectorMath")
    neg.operation = "SCALE"
    neg.inputs["Scale"].default_value = -1.0
    L.new(geo.outputs["Incoming"], neg.inputs[0])
    dot = n.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    L.new(neg.outputs[0], dot.inputs[0])
    dot.inputs[1].default_value = tuple(sun_vec.normalized())
    pw = n.new("ShaderNodeMath")
    pw.operation = "POWER"
    pw.use_clamp = True
    L.new(dot.outputs["Value"], pw.inputs[0])
    pw.inputs[1].default_value = 3.0
    mix = n.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    L.new(pw.outputs[0], mix.inputs[0])
    mix.inputs[6].default_value = s2l(c["base"])
    mix.inputs[7].default_value = s2l(c["sun"])
    dens = n.new("ShaderNodeMapRange")
    dens.inputs[1].default_value = c["cover"]
    dens.inputs[2].default_value = c["cover"] + 0.35
    dens.inputs[3].default_value = 1.0
    dens.inputs[4].default_value = 0.72
    L.new(noi.outputs["Fac"], dens.inputs[0])
    em = n.new("ShaderNodeEmission")
    L.new(mix.outputs[2], em.inputs["Color"])
    st = n.new("ShaderNodeMath")
    st.operation = "MULTIPLY"
    L.new(dens.outputs[0], st.inputs[0])
    st.inputs[1].default_value = c["strength"]
    L.new(st.outputs[0], em.inputs["Strength"])
    tr = n.new("ShaderNodeBsdfTransparent")
    ms = n.new("ShaderNodeMixShader")
    L.new(alpha.outputs[0], ms.inputs[0])
    L.new(tr.outputs[0], ms.inputs[1])
    L.new(em.outputs[0], ms.inputs[2])
    out = n.new("ShaderNodeOutputMaterial")
    L.new(ms.outputs[0], out.inputs["Surface"])
    me.materials.append(mat)
    ob = bpy.data.objects.new("TL_Clouds", me)
    ob.visible_shadow = False
    scene.collection.objects.link(ob)
    return ob


# --------------------------------------------------------------------------- haze (aerial perspective)
def haze_group():
    ng = bpy.data.node_groups.get("TL_Haze")
    if ng:
        return ng
    ng = bpy.data.node_groups.new("TL_Haze", "ShaderNodeTree")
    ng.interface.new_socket("Shader", in_out="INPUT", socket_type="NodeSocketShader")
    ng.interface.new_socket("Shader", in_out="OUTPUT", socket_type="NodeSocketShader")
    n = ng.nodes
    L = ng.links
    gi = n.new("NodeGroupInput")
    go = n.new("NodeGroupOutput")
    cam = n.new("ShaderNodeCameraData")
    geo = n.new("ShaderNodeNewGeometry")
    dens = n.new("ShaderNodeValue")
    dens.name = "density"
    dens.outputs[0].default_value = 0.0004
    hs = n.new("ShaderNodeValue")
    hs.name = "hscale"
    hs.outputs[0].default_value = 220.0
    sep = n.new("ShaderNodeSeparateXYZ")
    L.new(geo.outputs["Position"], sep.inputs[0])

    def m(op, a, b=None):
        nd = n.new("ShaderNodeMath")
        nd.operation = op
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, bpy.types.NodeSocket):
                L.new(v, nd.inputs[i])
            else:
                nd.inputs[i].default_value = v
        return nd.outputs[0]

    zpos = m("MAXIMUM", sep.outputs[2], 0.0)
    fall = m("EXPONENT", m("MULTIPLY", m("DIVIDE", zpos, hs.outputs[0]), -1.0))
    od = m("MULTIPLY", m("MULTIPLY", cam.outputs["View Distance"], dens.outputs[0]), fall)
    fac = m("SUBTRACT", 1.0, m("EXPONENT", m("MULTIPLY", od, -1.0)))
    fac = m("MINIMUM", fac, 0.93)
    # haze colour: brighter/warmer towards the sun
    sund = n.new("ShaderNodeCombineXYZ")
    sund.name = "sun_dir"
    neg = n.new("ShaderNodeVectorMath")
    neg.operation = "SCALE"
    L.new(geo.outputs["Incoming"], neg.inputs[0])
    neg.inputs["Scale"].default_value = -1.0
    dot = n.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    L.new(neg.outputs[0], dot.inputs[0])
    L.new(sund.outputs[0], dot.inputs[1])
    sunf = m("POWER", m("MAXIMUM", dot.outputs["Value"], 0.0), 6.0)
    mix = n.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.name = "colors"
    L.new(sunf, mix.inputs[0])
    em = n.new("ShaderNodeEmission")
    L.new(mix.outputs[2], em.inputs["Color"])
    ms = n.new("ShaderNodeMixShader")
    L.new(fac, ms.inputs[0])
    L.new(gi.outputs[0], ms.inputs[1])
    L.new(em.outputs[0], ms.inputs[2])
    L.new(ms.outputs[0], go.inputs[0])
    return ng


def update_haze(p, sun_vec):
    ng = haze_group()
    ng.nodes["density"].outputs[0].default_value = p["haze_density"]
    sd = ng.nodes["sun_dir"]
    for i, v in enumerate(sun_vec.normalized()):
        sd.inputs[i].default_value = v
    mix = ng.nodes["colors"]
    k = p["sky_strength"] if p["sky_strength"] > 0 else 1.0
    mix.inputs[6].default_value = s2l(p["haze_far"])
    mix.inputs[7].default_value = s2l(p["haze_sun"])
    em = [nd for nd in ng.nodes if nd.bl_idname == "ShaderNodeEmission"][0]
    em.inputs["Strength"].default_value = p.get("haze_strength", 1.0) * (0.55 + 0.45 * k / 0.4)


def apply_haze(mat):
    nt = mat.node_tree
    out = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeOutputMaterial"), None)
    if out is None or not out.inputs["Surface"].is_linked:
        return
    if any(n.bl_idname == "ShaderNodeGroup" and n.node_tree and n.node_tree.name == "TL_Haze" for n in nt.nodes):
        return
    src = out.inputs["Surface"].links[0].from_socket
    grp = nt.nodes.new("ShaderNodeGroup")
    grp.node_tree = haze_group()
    nt.links.new(src, grp.inputs[0])
    nt.links.new(grp.outputs[0], out.inputs["Surface"])


# --------------------------------------------------------------------------- camera
def ease(t, k=0.65):
    t = min(max(t, 0.0), 1.0)
    s = t * t * t * (t * (t * 6 - 15) + 10)
    return (1 - k) * t + k * s


def catmull(pts, t):
    n = len(pts) - 1
    f = min(max(t, 0.0), 1.0) * n
    i = min(int(f), n - 1)
    u = f - i
    p0 = pts[max(i - 1, 0)]
    p1, p2 = pts[i], pts[i + 1]
    p3 = pts[min(i + 2, n)]
    return 0.5 * ((2 * p1) + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u +
                  (-p0 + 3 * p1 - 3 * p2 + p3) * u * u * u)


def arc_param(pts, samples=400):
    """Reparametrise a Catmull-Rom path by arc length (constant speed)."""
    P = [catmull(pts, i / samples) for i in range(samples + 1)]
    acc = [0.0]
    for a, b in zip(P, P[1:]):
        acc.append(acc[-1] + (b - a).length)
    total = acc[-1]

    def f(s):
        target = min(max(s, 0.0), 1.0) * total
        lo, hi = 0, samples
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if acc[mid] < target:
                lo = mid
            else:
                hi = mid
        seg = acc[hi] - acc[lo]
        u = 0.0 if seg <= 0 else (target - acc[lo]) / seg
        return catmull(pts, (lo + u) / samples)
    return f, total


def camera_path(preset, poi, seed=0):
    """Return f(t) -> (location, target, lens) for t in [0, 1]."""
    F = Vector(poi["focus"])
    view_az = math.radians(poi.get("view_az", 60.0))   # direction the camera looks (from camera to focus)
    fwd = Vector((math.cos(view_az), math.sin(view_az), 0.0))
    up = Vector((0, 0, 1))
    if preset == "crane_down":
        d0, h0 = poi.get("crane_d0", 240.0), poi.get("crane_h0", 270.0)
        d1, h1 = poi.get("crane_d1", 260.0), poi.get("crane_h1", 55.0)
        if "crane_t1" in poi:
            T0, T1 = Vector(poi.get("crane_t0", F)), Vector(poi["crane_t1"])
            side = fwd.cross(up) * poi.get("crane_side", 0.0)

            def f(t):
                e = ease(t, 0.8)
                loc = T0.lerp(T1, e) - fwd * (d0 + (d1 - d0) * e) + up * (h0 + (h1 - h0) * ease(t, 0.9)) + side * e
                return loc, T0.lerp(T1, ease(t, 0.85)), poi.get("lens", 30.0)
            return f
        T1 = F + fwd * poi.get("crane_look", 420.0) + up * poi.get("crane_look_h", 25.0)

        def f(t):
            e = ease(t)
            d = d0 + (d1 - d0) * e
            h = h0 + (h1 - h0) * ease(t, 0.85)
            loc = F - fwd * d + up * h
            tgt = F.lerp(T1, ease(t, 0.7))
            return loc, tgt, poi.get("lens", 30.0)
        return f
    if preset == "orbit":
        R, H = poi.get("orbit_r", 520.0), poi.get("orbit_h", 170.0)
        sweep = math.radians(poi.get("orbit_sweep", 40.0))

        def f(t):
            a = view_az + math.pi - sweep / 2 + sweep * ease(t, 0.4)
            loc = F + Vector((math.cos(a), math.sin(a), 0)) * R + up * H
            return loc, F + up * 8.0, poi.get("lens", 35.0)
        return f
    if preset == "dolly_in":
        D0, D1 = poi.get("dolly_d0", 900.0), poi.get("dolly_d1", 380.0)
        H0, H1 = poi.get("dolly_h0", 210.0), poi.get("dolly_h1", 120.0)

        def f(t):
            e = ease(t, 0.5)
            loc = F - fwd * (D0 + (D1 - D0) * e) + up * (H0 + (H1 - H0) * e)
            return loc, F + up * 10.0, poi.get("lens", 35.0)
        return f
    if preset == "flyover":
        pts = [Vector(p) for p in poi["fly_path"]]
        tg = [Vector(p) for p in poi["fly_targets"]]
        pf, _ = arc_param(pts)
        tf, _ = arc_param(tg)

        def f(t):
            s = ease(t, 0.35)
            return pf(s), tf(s), poi.get("lens", 32.0)
        return f
    # static: locked-off with a barely perceptible drift (avoids a frozen still)
    D, H = poi.get("static_d", 600.0), poi.get("static_h", 160.0)

    def f(t):
        loc = F - fwd * D + up * H + fwd.cross(up) * (6.0 * (t - 0.5))
        return loc, F + up * 10.0, poi.get("lens", 35.0)
    return f


def build_camera(scene, preset, poi, nframes, seed=0):
    cam_data = bpy.data.cameras.new("TL_Camera")
    cam_data.sensor_width = 36.0
    cam_data.clip_start = 1.0
    cam_data.clip_end = 45000.0
    cam = bpy.data.objects.new("TL_Camera", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.rotation_mode = "QUATERNION"
    path = camera_path(preset, poi, seed)
    prev = None
    for fr in range(1, nframes + 1):
        t = 0.0 if nframes == 1 else (fr - 1) / (nframes - 1)
        loc, tgt, lens = path(t)
        q = (tgt - loc).to_track_quat("-Z", "Y")
        if prev is not None and prev.dot(q) < 0:
            q.negate()
        prev = q
        cam.location = loc
        cam.rotation_quaternion = q
        cam_data.lens = lens
        cam.keyframe_insert("location", frame=fr)
        cam.keyframe_insert("rotation_quaternion", frame=fr)
        cam_data.keyframe_insert("lens", frame=fr)
    if scene.render.resolution_percentage == 100:
        # subtle depth of field on finals: focus on the shot target, only near foreground softens
        cam_data.dof.use_dof = True
        cam_data.dof.aperture_fstop = 2.8
        for fr in range(1, nframes + 1):
            t = 0.0 if nframes == 1 else (fr - 1) / (nframes - 1)
            loc, tgt, _ = path(t)
            cam_data.dof.focus_distance = (tgt - loc).length
            cam_data.dof.keyframe_insert("focus_distance", frame=fr)
    for ad in (cam.animation_data, cam_data.animation_data):
        if ad and ad.action:
            _set_linear(ad.action)
    return cam, path


def _set_linear(action):
    curves = []
    try:
        curves = list(action.fcurves)
    except Exception:
        pass
    if not curves:
        try:  # layered actions (Blender 4.4+)
            for layer in action.layers:
                for strip in layer.strips:
                    for bag in strip.channelbags:
                        curves.extend(bag.fcurves)
        except Exception:
            pass
    for fc in curves:
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
