"""BES (Vietcong / Ptero-Engine) -> Blender jednim skriptem.

Pouziti:
  * v Blenderu: Text Editor -> otevrit tento soubor -> nastavit BES_PATH -> Run Script
  * z prikazove radky:  blender --python bes_import.py --"C:/.../LEVELS/RADIORELAY/04.BES"

Stoji na addonu `vietcong_bes` (scripts/addons/vietcong_bes) a opravuje jeho slabiny:
  0. Vertexy: addon pozna skeletalni vertex podle velikosti (40 B = 1 vaha), jenze 40 B ma
     i bezny vertex se 2 UV sadami (FVF 0x212). Pak cte normalu i UV posunute o 8 B
     a jako "UVMap" importuje ve skutecnosti druhou sadu. Tady rozhoduje FVF typ pozice.
  1. Textury: addon hleda rekurzivne a bere prvni shodu jmena. Kdyz je model mimo slozku
     levelu (napr. meshes/04.BES), najde TLT_RADIO_ZEM.DDS v LEVELS/CONQUEST_F (krater)
     misto LEVELS/RADIORELAY. Tady se kandidati se stejnym jmenem rozhoduji podle toho,
     ktera slozka obsahuje nejvic textur tehoz modelu (+ blizkost k modelu).
  2. UV: addon importuje jen 1. UV sadu. Vertexy maji tolik UV sad, kolik ma material map,
     v pevnem poradi slotu (vc-spec bes.md, Standard 0x1001 / PteroMat 0x1002).
     Tady se importuji vsechny (UVMap, UVMap2, ...) a kazda textura dostane svou sadu.
  3. Material: druha mapa Standard materialu (u terenu TLT_BIG_PIK, velka barevna mapa
     pres UV2) se v addonu veze na Alpha -> pruhledny kopec. Tady jde jako modulace 2x
     detailni textury (D3DTOP_MODULATE2X), stejne jako PteroMat Multitexture.
  4. Kolize a pomocne objekty (!, ^K, ^SF, ^SK, @) a LOD se NEMAZOU: jdou do vlastnich
     podkolekci, ktere jsou ve vychozim stavu skryte (oko v Outlineru) a nerenderuji se.
"""

import bpy
import os
import sys
import importlib
import addon_utils

# --- nastaveni -------------------------------------------------------------
BES_PATH = r"C:\Program Files (x86)\Autodesk\3dsMax8\meshes\LEVELS\RADIORELAY\04.BES"
GAME_ROOT = None        # None = najit automaticky (predek se slozkou LEVELS nebo G)
MODULATE_2X = True      # druha barevna mapa: base * map * 2 (False = prosty multiply)
NEW_SCENE = False       # True = importovat do nove sceny
ADDON = "vietcong_bes"

IMAGE_EXTS = (".dds", ".tga", ".bmp", ".png", ".jpg", ".jpeg")
EXT_RANK = {e: i for i, e in enumerate(IMAGE_EXTS)}   # engine bere DDS

# Standard material: flag -> nazev slotu (shodne s addonem) a poradi UV sad ve vertexech
STD_SLOT_FLAG = {
    'diffuse': 0x001, 'opacity': 0x002, 'bump': 0x004, 'ambient': 0x008,
    'specular': 0x010, 'specular_level': 0x020, 'glossiness': 0x040,
    'self_illum': 0x080, 'displacement': 0x200, 'filter': 0x400, 'reflection': 0x800,
}
STD_UV_ORDER = [0x008, 0x001, 0x010, 0x020, 0x040, 0x080, 0x400, 0x004, 0x800, 0x002, 0x200]

# PteroMat: poradi UV sad (dvojice sdileji jednu sadu)
PTERO_UV_ORDER = [
    ('diffuse_1',),
    ('diffuse_3', 'overlay_multi'),
    ('diffuse_2',),
    ('environment_1', 'environment_2'),
    ('lightmap', 'lightmap_engine'),
]
PTERO_OPAQUE = 0x202D


# --- addon -----------------------------------------------------------------
def load_addon():
    if ADDON not in bpy.context.preferences.addons:
        addon_utils.enable(ADDON, default_set=False)
    imp = importlib.import_module(ADDON + ".importers.bes_importer")
    rd = importlib.import_module(ADDON + ".core.bes_reader")
    return imp, rd


# --- textury ---------------------------------------------------------------
def find_game_root(model_path):
    d = os.path.dirname(os.path.abspath(model_path))
    while True:
        try:
            names = {n.upper() for n in os.listdir(d)}
        except OSError:
            names = set()
        if 'LEVELS' in names or 'G' in names:
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.dirname(os.path.abspath(model_path))
        d = parent


def index_images(root):
    """jmeno bez pripony (lower) -> [cesty]"""
    idx = {}
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            base, ext = os.path.splitext(f)
            if ext.lower() in IMAGE_EXTS:
                idx.setdefault(base.lower(), []).append(os.path.join(dirpath, f))
    return idx


def texture_names(bes_file):
    names = set()
    for m in bes_file.materials:
        for t in getattr(m, 'textures', {}).values():
            if t.filename:
                names.add(os.path.splitext(os.path.basename(t.filename))[0].lower())
        for layer in getattr(m, 'layers', None) or []:
            if layer.filename:
                names.add(os.path.splitext(os.path.basename(layer.filename))[0].lower())
    return names


def resolve_textures(bes_file, model_path, root):
    """Pro kazde jmeno textury vybere jeden soubor. Vraci (mapa, nenalezene, nejednoznacne)."""
    idx = index_images(root)
    names = texture_names(bes_file)
    model_dir = os.path.normcase(os.path.dirname(os.path.abspath(model_path)))

    # kolik textur modelu lezi v ktere slozce
    dir_score = {}
    for n in names:
        for p in idx.get(n, []):
            d = os.path.normcase(os.path.dirname(p))
            dir_score[d] = dir_score.get(d, 0) + 1

    def rank(p):
        d = os.path.normcase(os.path.dirname(p))
        inside = d == model_dir or d.startswith(model_dir + os.sep)
        for_all = '_for_all' in d          # sdilene textury az jako posledni volba
        return (inside, dir_score.get(d, 0), not for_all,
                -EXT_RANK.get(os.path.splitext(p)[1].lower(), 99), -len(d))

    chosen, missing, ambiguous = {}, [], {}
    for n in sorted(names):
        cands = idx.get(n, [])
        if not cands:
            missing.append(n)
            continue
        best = max(cands, key=rank)
        chosen[n] = best
        if len({os.path.normcase(os.path.dirname(c)) for c in cands}) > 1:
            ambiguous[n] = (best, cands)
    return chosen, missing, ambiguous


# --- materialy -------------------------------------------------------------
_alpha_cache = {}


def image_has_alpha(img):
    """True, kdyz alfa kanal opravdu neco orezava (ne jen DXT1 s plnou alfou)."""
    if img.name in _alpha_cache:
        return _alpha_cache[img.name]
    res = False
    if img.channels == 4 and img.size[0] > 0:
        import numpy as np
        px = np.empty(img.size[0] * img.size[1] * 4, dtype=np.float32)
        img.pixels.foreach_get(px)
        res = bool((px[3::4] < 0.98).mean() > 0.001)
    _alpha_cache[img.name] = res
    return res


def load_image(path):
    img = bpy.data.images.load(path, check_existing=True)
    return img


def tex_node(nt, img, uv_index, tex, x, y):
    uv = nt.nodes.new('ShaderNodeUVMap')
    uv.uv_map = 'UVMap' if uv_index == 0 else f'UVMap{uv_index + 1}'
    uv.location = (x - 220, y)
    n = nt.nodes.new('ShaderNodeTexImage')
    n.image = img
    n.location = (x, y)
    if getattr(tex, 'u_mirror', False) or getattr(tex, 'v_mirror', False):
        n.extension = 'MIRROR'
    elif tex.u_tile or tex.v_tile:
        n.extension = 'REPEAT'
    else:
        n.extension = 'EXTEND'
    nt.links.new(uv.outputs['UV'], n.inputs['Vector'])
    return n


def mix(nt, blend, a, b, x, y, fac=None):
    m = nt.nodes.new('ShaderNodeMix')
    m.data_type = 'RGBA'
    m.blend_type = blend
    m.clamp_result = True
    m.location = (x, y)
    m.inputs['Factor'].default_value = 1.0
    if fac is not None:
        nt.links.new(fac, m.inputs['Factor'])
    nt.links.new(a, m.inputs['A'])
    nt.links.new(b, m.inputs['B'])
    return m.outputs['Result']


def modulate(nt, base, col, x, y, two_x):
    out = mix(nt, 'MULTIPLY', base, col, x, y)
    if two_x:
        m = nt.nodes.new('ShaderNodeMix')
        m.data_type = 'RGBA'
        m.blend_type = 'MULTIPLY'
        m.clamp_result = True
        m.location = (x + 180, y)
        m.inputs['Factor'].default_value = 1.0
        m.inputs['B'].default_value = (2.0, 2.0, 2.0, 1.0)
        nt.links.new(out, m.inputs['A'])
        out = m.outputs['Result']
    return out


def build_material(mat, bes_mat, kind, tex_map):
    """Prestavi node tree podle BES materialu; vlastnosti bes_* nechava kvuli exportu."""
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    out.location = (900, 0)
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (600, 0)
    bsdf.inputs['Roughness'].default_value = 1.0
    bsdf.inputs['Specular IOR Level'].default_value = 0.0
    nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

    textures = getattr(bes_mat, 'textures', {}) or {}

    def img_for(tex):
        key = os.path.splitext(os.path.basename(tex.filename))[0].lower()
        p = tex_map.get(key)
        return load_image(p) if p else None

    layers = {}   # slot -> (tex, uv_index)
    if kind == 'standard':
        present = [f for f in STD_UV_ORDER if bes_mat.map_flags & f]
        for slot, tex in textures.items():
            f = STD_SLOT_FLAG.get(slot)
            if f in present:
                layers[slot] = (tex, present.index(f))
    elif kind == 'ptero':
        uvi = 0
        for group in PTERO_UV_ORDER:
            hit = [s for s in group if s in textures]
            if hit:
                for s in hit:
                    layers[s] = (textures[s], uvi)
                uvi += 1

    base_slot = 'diffuse' if kind == 'standard' else 'diffuse_1'
    y = 300
    color = None
    alpha = None
    used = []

    if base_slot in layers:
        tex, uvi = layers[base_slot]
        img = img_for(tex)
        if img:
            n = tex_node(nt, img, uvi, tex, -300, y)
            color = n.outputs['Color']
            used.append(f"{img.name}@UV{uvi}")
            transparent = (kind == 'ptero' and bes_mat.transparency_type != PTERO_OPAQUE) \
                or (kind == 'standard' and image_has_alpha(img))
            if transparent:
                alpha = n.outputs['Alpha']
    y -= 300

    if color is not None:
        # druha barevna mapa: Standard 'opacity' slot (TLT_BIG_PIK) / PteroMat multitexture
        for slot in ('opacity', 'diffuse_2', 'overlay_multi'):
            if slot in layers:
                tex, uvi = layers[slot]
                img = img_for(tex)
                if img:
                    n = tex_node(nt, img, uvi, tex, -300, y)
                    color = modulate(nt, color, n.outputs['Color'], 0, y, MODULATE_2X)
                    used.append(f"x{img.name}@UV{uvi}")
                    y -= 300
        if 'diffuse_3' in layers:   # overlay: pres alfu overlaye
            tex, uvi = layers['diffuse_3']
            img = img_for(tex)
            if img:
                n = tex_node(nt, img, uvi, tex, -300, y)
                color = mix(nt, 'MIX', color, n.outputs['Color'], 0, y, fac=n.outputs['Alpha'])
                used.append(f"over:{img.name}@UV{uvi}")
                y -= 300
        for slot in ('lightmap', 'lightmap_engine'):
            if slot in layers:
                tex, uvi = layers[slot]
                img = img_for(tex)
                if img:
                    n = tex_node(nt, img, uvi, tex, -300, y)
                    color = modulate(nt, color, n.outputs['Color'], 0, y, False)
                    used.append(f"lm:{img.name}@UV{uvi}")
                    y -= 300
        nt.links.new(color, bsdf.inputs['Base Color'])
    elif kind != 'standard' and hasattr(bes_mat, 'mat_diffuse'):
        bsdf.inputs['Base Color'].default_value = (*bes_mat.mat_diffuse, 1.0)

    if alpha is not None:
        nt.links.new(alpha, bsdf.inputs['Alpha'])
        mat.surface_render_method = 'DITHERED'
    else:
        bsdf.inputs['Alpha'].default_value = 1.0
        mat.surface_render_method = 'DITHERED'

    if kind == 'ptero':
        mat.use_backface_culling = not bes_mat.two_sided
    mat['bes_blender_layers'] = " | ".join(used)
    return used


# --- import ----------------------------------------------------------------
def patch_parser():
    """Addon pozna skeletalni vertex podle velikosti: 40 B = 1 vaha. Jenze 40 B ma i
    obycejny vertex se 2 UV sadami (FVF 0x212 = XYZ|NORMAL|TEX2) -> normala a UV posunute.
    Rozhoduje FVF typ pozice: D3DFVF_XYZ (0x002) = bez vah, XYZB1..5 (0x006..0x00E) = skelet."""
    cp = importlib.import_module(ADDON + ".core.chunk_parser")
    bt = importlib.import_module(ADDON + ".core.bes_types")
    cls = cp.ChunkParser
    orig = cls._parse_vertices

    def _parse_vertices(self, mesh, size):
        r = self._reader
        start = r.position
        count = r.read_uint32()
        vsize = r.read_uint32()
        flags = r.read_uint32()
        if (flags & 0x0E) != 0x02:
            r.seek(start)
            return orig(self, mesh, size)
        mesh.flags = flags
        tex_count = max(0, (vsize - 24) // 8)
        for _ in range(count):
            pos = r.read_vec3()
            nor = r.read_vec3()
            uvs = [r.read_vec2() for _ in range(tex_count)]
            mesh.vertices.append(bt.BESVertex(position=pos, normal=nor, uvs=uvs, flags=flags))

    cls._parse_vertices = _parse_vertices
    return lambda: setattr(cls, '_parse_vertices', orig)


def patch_importer(imp, tex_map, log):
    cls = imp.BESImporter
    orig_find = cls._find_texture
    orig_mesh = cls._create_mesh_object
    orig_mat = cls._create_material

    def _find_texture(self, filename):
        return tex_map.get(os.path.splitext(os.path.basename(filename))[0].lower())

    def _create_mesh_object(self, bes_node):
        obj = orig_mesh(self, bes_node)
        uvsets = []
        for bm in bes_node.meshes:
            for v in bm.vertices:
                uvsets.append(getattr(v, 'uvs', None) or [])
        n_extra = max((len(u) for u in uvsets), default=0)
        me = obj.data
        if n_extra > 1 and len(uvsets) == len(me.vertices):
            for k in range(1, n_extra):
                layer = me.uv_layers.new(name=f'UVMap{k + 1}')
                if layer is None:
                    break
                for li, loop in enumerate(me.loops):
                    u = uvsets[loop.vertex_index]
                    uv = u[k] if len(u) > k else (u[0] if u else (0.0, 0.0))
                    layer.data[li].uv = imp.bes_to_blender_uv(uv)
            me.uv_layers.active_index = 0
        return obj

    def _create_material(self, bes_mat, list_index):
        mat = orig_mat(self, bes_mat, list_index)
        if isinstance(bes_mat, imp.BESStandardMaterial):
            kind = 'standard'
        elif isinstance(bes_mat, imp.BESPteroMat):
            kind = 'ptero'
        else:
            return mat      # PteroLayer nechat jak ho postavil addon
        used = build_material(mat, bes_mat, kind, tex_map)
        log.append(f"  {mat.name:14s} {kind:8s} {' | '.join(used)}")
        return mat

    cls._find_texture = _find_texture
    cls._create_mesh_object = _create_mesh_object
    cls._create_material = _create_material
    return lambda: (setattr(cls, '_find_texture', orig_find),
                    setattr(cls, '_create_mesh_object', orig_mesh),
                    setattr(cls, '_create_material', orig_mat))


def child_collection(parent, name):
    c = bpy.data.collections.new(name)
    parent.children.link(c)
    return c


def find_layer_collection(lc, coll):
    if lc.collection == coll:
        return lc
    for ch in lc.children:
        r = find_layer_collection(ch, coll)
        if r:
            return r
    return None


def import_bes_file(path):
    imp, rd = load_addon()
    path = os.path.abspath(path)
    base = os.path.splitext(os.path.basename(path))[0]
    root = GAME_ROOT or find_game_root(path)

    unpatch_parser = patch_parser()
    try:
        main, log = _import(imp, rd, path, base, root)
    finally:
        unpatch_parser()
    return main, log


def _import(imp, rd, path, base, root):
    bes_file = rd.read_bes_file(path)
    tex_map, missing, ambiguous = resolve_textures(bes_file, path, root)

    log = [f"BES {path}", f"  hledani textur v: {root}"]
    for n, (best, cands) in ambiguous.items():
        log.append(f"  nejednoznacne {n}: {best}  (z {len(cands)})")
    for n in missing:
        log.append(f"  CHYBI textura: {n}")

    scene = bpy.context.scene
    if NEW_SCENE:
        scene = bpy.data.scenes.new(f"BES {base}")
        bpy.context.window.scene = scene
    main = bpy.data.collections.new(f"BES {base}")
    scene.collection.children.link(main)
    vl = bpy.context.view_layer
    vl.active_layer_collection = find_layer_collection(vl.layer_collection, main)

    before = set(bpy.data.objects)
    unpatch = patch_importer(imp, tex_map, log)
    try:
        res = imp.import_bes(bpy.context, path, search_textures=True,
                             import_collision=True, hide_collision=True)
    finally:
        unpatch()
    if 'FINISHED' not in res:
        raise RuntimeError(f"Import {path} selhal")

    new = [o for o in bpy.data.objects if o not in before]
    lod = child_collection(main, f"{base} – LOD")
    helpers = child_collection(main, f"{base} – kolize a pomocné")
    n_lod = n_help = 0
    for o in new:
        helper = o.get('bes_is_collision') or o.get('bes_is_auxiliary') or o.get('bes_is_effect_sphere')
        is_lod = o.get('bes_is_lod')
        if not (helper or is_lod):
            continue
        target = helpers if helper else lod
        for c in list(o.users_collection):
            c.objects.unlink(o)
        target.objects.link(o)
        o.hide_viewport = False     # schovava se cela kolekce, objekt jde zobrazit okem
        o.hide_render = True
        if helper:
            o.display_type = 'WIRE'
            n_help += 1
        else:
            n_lod += 1
    for c in (lod, helpers):
        c.hide_render = True
        find_layer_collection(vl.layer_collection, c).hide_viewport = True

    # duplicitni obrazky po addonu
    for img in list(bpy.data.images):
        if img.users == 0:
            bpy.data.images.remove(img)

    log.append(f"  objektu {len(new)}, LOD {n_lod}, kolize/pomocne {n_help} (skryte)")
    print("\n".join(log))
    return main, log


def main_cli():
    path = BES_PATH
    if "--" in sys.argv:
        args = sys.argv[sys.argv.index("--") + 1:]
        if args:
            path = args[0]
    import_bes_file(path)


if __name__ == "__main__":
    main_cli()
