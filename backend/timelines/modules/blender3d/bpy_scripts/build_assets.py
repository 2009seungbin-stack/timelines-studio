"""Blender entry point: build the reusable asset library from the SAME generator
functions the city uses (tl_buildings / tl_nature).

blender -b --factory-startup --python build_assets.py -- --out <data/assets> [--ids a,b] [--no-preview]
For every asset: <out>/<asset_id>/asset.blend, preview.jpg, meta.json
"""
from __future__ import annotations

import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bpy  # noqa: E402

try:  # no .blend1 backup copies when a file is overwritten (disk space)
    bpy.context.preferences.filepaths.save_version = 0
except Exception:
    pass
from mathutils import Vector  # noqa: E402

import tl_buildings as B  # noqa: E402
import tl_nature as N  # noqa: E402
import tl_scene  # noqa: E402
from tl_mesh import MeshBuilder  # noqa: E402

LICENSE = ("original procedural geometry (TIMELINES Studio); materials use CC0 Poly Haven textures, "
           "see data/textures/LICENSES.json")


def _aqueduct(mb, rng):
    # 26 bays crossing a valley: single tier on the flanks, two tiers in the middle
    B.aqueduct_run(mb, 166.0, lambda x: 24.0 + 0.003 * x,
                   lambda x: 6.0 - 16.0 * math.exp(-((x - 83.0) / 40.0) ** 2), span=6.4, pier=2.4)


def _walls(mb, rng):
    B.wall_run(mb, 70.0, H=8.5)
    for x in (0.0, 35.0, 70.0):
        with mb.push((x, 0, 0)):
            B.tower(mb, rng, H=14.5)


def _gate(mb, rng):
    B.gate(mb, rng)
    with mb.push((-46.5, 0, 0)):
        B.wall_run(mb, 30.0)
    with mb.push((16.5, 0, 0)):
        B.wall_run(mb, 30.0)


def _tombs(mb, rng):
    for i, x in enumerate((-12.0, 0.0, 12.0)):
        mb.var = rng.random()
        with mb.push((x, 0, 0)):
            r = random.Random(i * 7 + 1)
            B.tomb(mb, r)


def _ship(mb, rng):
    B.ship(mb, rng, L=22.0, sail_set=True)


def _props(mb, rng):
    B.fountain(mb, rng, -9.0, 0.0, 0.0)
    B.market_stall(mb, rng, -3.0, 0.0, 0.0, 0.0)
    B.cart(mb, rng, 3.5, 0.5, 0.0, 0.3)
    B.amphora_stack(mb, rng, 7.5, 0.0, 0.0, n=7)
    B.statue(mb, rng, 11.5, 0.0, 0.0, 0.0)


def _trees(mb, rng):
    N.cypress(mb, rng, -12, 0, 0, 14.0)
    N.cypress(mb, rng, -8, 3, 0, 11.0)
    N.pine(mb, rng, 2, 0, 0, 12.0)
    N.olive(mb, rng, 12, -2, 0)
    N.broadleaf(mb, rng, 20, 2, 0, 8.0)
    N.bush(mb, rng, 26, -1, 0, 1.4)


def _insula(mb, rng):
    B.insula(mb, rng, 30.0, 30.0, 4, street=(True, True, False, False), material="TL_Plaster")


def _domus(mb, rng):
    B.domus(mb, rng, 24.0, 38.0, street=(True, False, False, True))


VITR = "Vitruvius, De architectura (c. 30-15 BCE)"
ASSETS = {
    "roman_temple_corinthian_hexastyle": dict(
        name="Corinthian hexastyle temple on a podium (Capitolium type)", period="1st c. BCE - 4th c. CE",
        region="Roman Italy / western provinces", category="religious", fn=lambda mb, r: B.temple(mb, r),
        notes="Column height 10 lower diameters, eustyle intercolumniation (2.25 D, 3 D at the centre) and "
              "pediment rise of 1/9 of the front follow Vitruvius Book III; Corinthian capital height = 1 D "
              "(Book IV.1). v2 (2026-11-26) models attic bases, shafts with 24 flutes and entasis (straight lower "
              "third, taper to 5/6 D), capitals approximated by a bell with two rows of eight leaf patches, four "
              "corner volutes and a concave abacus with fleurons (an approximation, not carved acanthus), an "
              "entablature with three-fascia architrave, frieze, dentils, modillions, corona and sima, raking "
              "cornices, recessed tympanum, acroterion plinths, podium mouldings, bronze-doored cella. ESTIMATES: "
              "podium height (3.2 m), moulding profiles, entablature height (2.45 D), dentil/modillion spacing, "
              "24 flutes (usual for Roman Corinthian shafts).",
        refs=[VITR + ", Book III (temple proportions, eustyle) and Book IV (Corinthian order)",
              "Maison Carree, Nimes (pseudoperipteral hexastyle Corinthian temple, c. 2 CE)"],
        parts=["podium with mouldings", "frontal stairs", "6 front + 4 pronaos columns", "engaged half columns",
               "cella with door", "architrave/frieze/cornice", "tiled pediment roof"]),
    "roman_basilica_civil": dict(
        name="Civil basilica (nave, aisles, clerestory, apse)", period="1st c. BCE - 5th c. CE",
        region="Roman Empire", category="civic", fn=lambda mb, r: B.basilica(mb, r),
        notes="Timber-roofed three-aisled hall with clerestory and apse; Vitruvius (V.1) gives a width of "
              "1/3 to 1/2 of the length. All dimensions (60 x 32 m, 9/17 m heights) are estimates; arched "
              "windows are recessed openings, no interior.",
        refs=[VITR + ", Book V.1 (forum and basilica)", "Basilica of Constantine (Aula Palatina), Trier"],
        parts=["aisle walls with arched windows", "clerestory", "lean-to aisle roofs", "gable nave roof", "apse"]),
    "roman_insula_block": dict(
        name="Insula (multi-storey apartment block with shops)", period="1st - 5th c. CE (taller variant: "
        "hypothetical 1000 CE)", region="Roman Italy (Ostia type)", category="residential",
        fn=_insula,
        notes="Ground-floor tabernae and upper flats around a light court, as at Ostia. v2 (2026-11-26): street "
              "facades are modelled - shop openings 2.3-3.0 m wide and 1.7 m deep (some with masonry counters, "
              "shutter boards or amphorae), stair doors, windows recessed 0.3 m with sills and open/closed timber "
              "shutters, string course, two-step eave cornice, timber balconies (maeniana) on joists or tile pent "
              "roofs on brackets; roofs carry modelled imbrices and ridge tiles; long blocks split into two masses "
              "of different height; plaster palette (ochre, cream, faded red, grey) with brick showing through. "
              "Party walls and light-court walls keep shaded (not modelled) windows. ESTIMATES: floor heights "
              "(3.7-4.3 m ground, 2.9-3.3 m upper), opening sizes and rhythms, balcony depth (1.15 m).",
        refs=["Ostia Antica insulae (e.g. Casa di Diana, 2nd c. CE)"],
        parts=["street facades with shops", "light court", "inward/outward pitched tile roof", "timber balcony"]),
    "roman_domus": dict(
        name="Domus (atrium-peristyle house with street shops)", period="2nd c. BCE - 5th c. CE",
        region="Roman Italy", category="residential", fn=_domus,
        notes="Atrium with compluvium roof and impluvium at the front, peristyle garden with a low colonnade and "
              "a basin at the back; v2: street front modelled with a central entrance (fauces) flanked by shops, "
              "small high windows on the flanks. Proportions are estimated; no interiors.",
        refs=[VITR + ", Book VI (private houses)", "Pompeii, House of the Faun (atrium-peristyle plan)"],
        parts=["street walls with shops", "compluviate atrium roof", "peristyle colonnade", "garden"]),
    "roman_aqueduct_arcade": dict(
        name="Aqueduct arcade (single and two-tier)", period="1st c. BCE - 5th c. CE",
        region="Roman Empire", category="infrastructure", fn=_aqueduct,
        notes="Arches on piers carrying a covered channel (specus) with a gentle gradient; where the arcade "
              "exceeds ~17 m a second tier is used, the solution seen at the Pont du Gard and Segovia. Span "
              "6.4 m, pier 2.4 m and gradient 0.3 % are estimates for a generic provincial aqueduct.",
        refs=["Pont du Gard (aqueduct of Nimes, 1st c. CE)", "Aqueduct of Segovia (late 1st - early 2nd c. CE)",
              "Frontinus, De aquaeductu (c. 97 CE)"],
        parts=["piers", "semicircular arches", "impost mouldings", "second tier", "specus with cover slabs"]),
    "late_roman_wall_tower": dict(
        name="Late Roman curtain wall with projecting towers", period="3rd - 6th c. CE",
        region="Roman Empire", category="military", fn=_walls,
        notes="Brick-faced wall (~8.5 m) on a stone footing with merlons and square projecting towers with "
              "upper chambers, comparable in type to the Aurelian Walls. Tower spacing (~35 m) and heights "
              "are estimates.",
        refs=["Aurelian Walls, Rome (271-275 CE)"],
        parts=["stone footing", "brick curtain wall", "merlons", "square towers with tiled roofs"]),
    "roman_city_gate": dict(
        name="Double-arched city gate with round towers", period="3rd - 6th c. CE", region="Roman Empire",
        category="military", fn=_gate,
        notes="Two arched passages flanked by semicircular towers (cf. Porta Appia / Porta San Sebastiano in "
              "its late antique form). Dimensions are estimates.",
        refs=["Porta Appia (Porta San Sebastiano), Aurelian Walls, Rome"],
        parts=["gate block with two passages", "upper storey", "two round towers", "wall stubs"]),
    "roman_amphitheatre": dict(
        name="Amphitheatre (provincial size)", period="1st - 5th c. CE", region="Roman Empire",
        category="entertainment", fn=lambda mb, r: B.amphitheatre(mb, r),
        notes="Elliptical arena with two arcaded storeys and an attic; 112 x 88 m outside is an estimate of a "
              "mid-sized provincial amphitheatre. Cavea is simplified to six stepped bands; no vomitoria.",
        refs=["Amphitheatre of Nimes (late 1st c. CE)", "Amphitheatre of Arles (c. 90 CE)"],
        parts=["arcaded facade (2 tiers)", "attic", "cavea", "arena with podium wall"]),
    "early_christian_basilica_church": dict(
        name="Early Christian basilica church", period="4th - 6th c. CE", region="Roman Italy",
        category="religious", fn=lambda mb, r: B.basilica(mb, r, L=44.0, nave=14.0, aisle=6.0, h_aisle=8.0,
                                                          h_nave=15.0, church=True),
        notes="Timber-roofed nave and aisles with clerestory and apse, entrance on the short side; brick "
              "exterior. Dimensions estimated; no campanile (later addition in Italy).",
        refs=["Santa Sabina, Rome (c. 422-432 CE)"],
        parts=["west door facade", "aisles", "clerestory", "apse"]),
    "domed_basilica_church": dict(
        name="Centrally domed basilica church (SPECULATIVE 1000 CE type)", period="hypothetical, c. 1000 CE "
        "(precedent 537 CE)", region="alternate-history western Roman city", category="religious",
        fn=lambda mb, r: B.domed_church(mb, r),
        notes="SPECULATION. A scaled-down western counterpart of the domed basilica type: central dome (22 m) "
              "on a ring of windows, east and west half domes, aisles with galleries, buttress piers, narthex "
              "and colonnaded atrium. Precedent: Hagia Sophia, Constantinople (537 CE; dome c. 31 m). The "
              "existence of such a building in a western city is hypothetical; all dimensions are estimates; "
              "lead roofing follows the Hagia Sophia precedent.",
        refs=["Hagia Sophia, Constantinople (532-537 CE)", "Procopius, De aedificiis I.1 (description of "
              "Hagia Sophia)"],
        parts=["atrium with porticoes", "narthex", "aisles with two window tiers", "buttress piers",
               "windowed drum", "central dome", "two half domes", "apse"]),
    "barbegal_watermill_cascade": dict(
        name="Stepped water-mill cascade (Barbegal type)", period="2nd c. CE (precedent); used here for a "
        "hypothetical 1000 CE city", region="Roman Gaul / alternate-history city", category="industry",
        fn=lambda mb, r: B.watermill_cascade(mb, r, steps=8, step_drop=1.6, step_len=7.0),
        notes="Two parallel rows of eight mill houses (v2: with windows and cornices) descending a slope with "
              "overshot wheels, fed by a branch "
              "of the aqueduct, after the Barbegal complex near Arles (2nd c. CE). Building sizes, wheel "
              "diameter (2.2 m) and step drop are estimates; mill machinery is not modelled.",
        refs=["Barbegal mill complex, Fontvieille near Arles (2nd c. CE)",
              "Leveau, P. (1996) 'The Barbegal water mill in its environment', Journal of Roman Archaeology 9"],
        parts=["16 mill houses on terraces", "overshot wheels", "central race", "head race"]),
    "roman_merchant_ship_corbita": dict(
        name="Roman merchant ship (corbita type)", period="1st - 5th c. CE (and hypothetical 1000 CE)",
        region="Mediterranean", category="transport", fn=_ship,
        notes="Round-hulled sailing merchantman with a rising stern post, single square mainsail and an "
              "inclined artemon at the bow, steering oars aft. Hull lines, 22 m length and rigging are "
              "simplified estimates.",
        refs=["Torlonia relief from Portus (c. 200 CE, merchant ships in harbour)"],
        parts=["hull", "deck", "stern post", "deckhouse", "steering oars", "mast and yard", "square sail",
               "artemon"]),
    "roman_lighthouse": dict(
        name="Harbour lighthouse (stepped stages)", period="1st c. BCE - 5th c. CE", region="Roman Empire",
        category="infrastructure", fn=lambda mb, r: B.lighthouse(mb, r),
        notes="Three diminishing square stages with a lantern; type of the Portus/Ostia lighthouse known from "
              "reliefs and of the Tower of Hercules (A Coruna). Height (~33 m) is an estimate.",
        refs=["Tower of Hercules, A Coruna (late 1st - early 2nd c. CE)",
              "Torlonia relief from Portus (lighthouse depiction)"],
        parts=["three stages with windows", "cornices", "lantern"]),
    "roman_horreum": dict(
        name="Warehouse (horreum)", period="1st - 5th c. CE", region="Roman Italy", category="commerce",
        fn=lambda mb, r: B.horreum(mb, r, w=50.0, d=22.0),
        notes="Two-storey brick warehouse with inner court, shops on the quay side; dimensions estimated.",
        refs=["Horrea Epagathiana et Epaphroditiana, Ostia (c. 145-150 CE)"],
        parts=["brick facades", "inner court", "tile roof"]),
    "roman_roadside_tomb": dict(
        name="Roadside tombs (altar, drum and house types)", period="1st c. BCE - 4th c. CE",
        region="Roman Italy", category="funerary", fn=_tombs,
        notes="Three generic tomb types lining roads outside the walls (necropolis). Sizes estimated.",
        refs=["Via Appia, tomb of Caecilia Metella (drum type, 1st c. BCE)"],
        parts=["altar tomb", "drum tomb with earth mound", "house tomb"]),
    "roman_villa_rustica": dict(
        name="Farmstead (villa rustica)", period="1st c. BCE - 5th c. CE", region="Roman Italy / provinces",
        category="rural", fn=lambda mb, r: B.villa_rustica(mb, r),
        notes="Courtyard farmhouse with a barn on a levelled platform; generic, dimensions estimated.",
        refs=["Columella, De re rustica I.6 (layout of the farmstead)"],
        parts=["platform", "courtyard house", "barn"]),
    "mediterranean_trees": dict(
        name="Mediterranean trees (cypress, stone pine, olive, broadleaf)", period="any",
        region="Mediterranean", category="vegetation", fn=_trees,
        notes="v2 (2026-11-26): trees built from 150-450 small leaf cards (procedural leaf-cluster alpha, "
              "translucency, crown-depth shading, normals bent outward) on modelled trunks and limbs: Italian "
              "cypress (narrow spindle), umbrella/stone pine (bare leaning trunk, forked limbs, flat crown), olive "
              "(2-3 gnarled stems, grey-green), broadleaf, maquis shrub, grass tuft; instanced with Geometry Nodes "
              "in scenes. Shapes are stylised from the living species; leaves are not botanically modelled.",
        refs=["Pliny the Elder, Naturalis Historia XVI (trees)"],
        parts=["cypress", "stone pine", "olive", "broadleaf", "shrub"]),
    "roman_street_props": dict(
        name="Street furniture (fountain, market stall, cart, amphorae, honorific statue)", period="1st - 5th c. CE",
        region="Roman Italy", category="props", fn=lambda mb, r: _props(mb, r),
        notes="Pompeii-type street fountain (four stone slabs and a spout pillar), timber trestle stall with a "
              "cloth awning, two-wheeled cart with disc wheels, Dressel-like transport amphorae, draped honorific "
              "statue on an inscribed plinth (abstracted figure, no portrait). All dimensions are estimates; the "
              "statue is deliberately generic.",
        refs=["Pompeii: street fountains and stepping stones (e.g. Via dell'Abbondanza)",
              "Dressel, H. (1899), amphora typology table, CIL XV"],
        parts=["fountain", "market stall", "cart", "amphora stack", "statue on plinth"]),
}


def clear():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights,
                  bpy.data.node_groups, bpy.data.worlds):
        for item in list(block):
            block.remove(item)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)


def build_one(asset_id, out_root, preview=True):
    a = ASSETS[asset_id]
    clear()
    sc = bpy.context.scene
    rng = random.Random(1234)
    mb = MeshBuilder(asset_id)
    mb.var = 0.45
    a["fn"](mb, rng)
    ob = mb.to_object(sc.collection, name=asset_id)
    ob["tl_asset_id"] = asset_id
    polys = len(ob.data.polygons)
    mats = [m.name for m in ob.data.materials]
    d = os.path.join(out_root, asset_id)
    os.makedirs(d, exist_ok=True)
    try:
        ob.asset_mark()
        ob.asset_data.description = a["name"]
    except Exception:
        pass
    blend = os.path.join(d, "asset.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend, compress=True, copy=True)
    prev = os.path.join(d, "preview.jpg")
    if preview:
        _preview(ob, prev)
    meta = {
        "asset_id": asset_id, "name": a["name"], "historical_period": a["period"],
        "geographic_region": a["region"], "category": a["category"], "polygon_count": polys,
        "material_list": mats, "license": LICENSE,
        "source": "procedural bpy generator tl_buildings.py / tl_nature.py (via build_assets.py)",
        "historical_accuracy_notes": a["notes"], "references": a["refs"], "estimated_parts": a["parts"],
        "preview_image": prev if preview else None, "file_path": blend,
    }
    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, ensure_ascii=False)
    print(f"TL_ASSET {asset_id} {polys}", flush=True)
    return meta


def _preview(ob, path):
    sc = bpy.context.scene
    bb = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
    lo = Vector((min(v.x for v in bb), min(v.y for v in bb), min(v.z for v in bb)))
    hi = Vector((max(v.x for v in bb), max(v.y for v in bb), max(v.z for v in bb)))
    c = (lo + hi) / 2
    size = max((hi - lo).length, 10.0)
    gm = MeshBuilder("ground")
    gm.poly([(c.x - 2000, c.y - 2000, lo.z + 0.01), (c.x + 2000, c.y - 2000, lo.z + 0.01),
             (c.x + 2000, c.y + 2000, lo.z + 0.01), (c.x - 2000, c.y + 2000, lo.z + 0.01)], "TL_Earth")
    g = gm.to_object(sc.collection)
    tl_scene.setup_render(sc, 960, 600, 30, 1, "final")
    sc.eevee.taa_render_samples = 32
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.lens = 35
    cam.data.clip_end = 50000
    az = math.radians(-58)
    dist = size * 1.05
    loc = c + Vector((math.cos(az) * dist, math.sin(az) * dist, size * 0.42))
    cam.location = loc
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = (c - loc).to_track_quat("-Z", "Y")
    tl_scene.LIGHTING["golden_hour"]["clouds"] = False
    tl_scene.setup_world(sc, "golden_hour", math.degrees(az) + 75)
    tl_scene.update_haze(dict(tl_scene.LIGHTING["golden_hour"], haze_density=0.0), tl_scene.sun_vector(13, 0))
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(g, do_unlink=True)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = None
    ids = list(ASSETS)
    preview = True
    i = 0
    while i < len(argv):
        if argv[i] == "--out":
            out = argv[i + 1]
            i += 2
        elif argv[i] == "--ids":
            ids = [x for x in argv[i + 1].split(",") if x]
            i += 2
        elif argv[i] == "--no-preview":
            preview = False
            i += 1
        else:
            i += 1
    if not out:
        raise SystemExit("--out required")
    for aid in ids:
        if aid not in ASSETS:
            raise SystemExit(f"unknown asset id {aid}")
        build_one(aid, out, preview)
    print("TL_DONE", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
