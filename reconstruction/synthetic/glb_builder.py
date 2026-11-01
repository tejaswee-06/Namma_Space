"""Minimal glTF 2.0 / GLB writer + geometry primitives (no external deps beyond numpy).

Design:
  * `Group` = a scene-graph node (name, extras, children, per-material geometry).
  * Primitives (box, cylinder, sphere) append flat/smooth-shaded triangles with
    world-space box-projected UVs so textures tile consistently across parts.
  * `write_glb` serialises the tree with PBR materials + embedded PNG textures.
"""
from __future__ import annotations
import json
import math
import struct
from dataclasses import dataclass, field
import numpy as np


@dataclass
class Material:
    name: str
    color: tuple = (0.8, 0.8, 0.8, 1.0)
    metallic: float = 0.0
    roughness: float = 0.8
    emissive: tuple = (0.0, 0.0, 0.0)
    texture: str | None = None
    tex_m: float = 2.0            # metres covered by one texture tile
    blend: bool = False
    double_sided: bool = False


class Group:
    def __init__(self, name: str, extras: dict | None = None):
        self.name = name
        self.extras = extras or {}
        self.children: list[Group] = []
        self.geo: dict[str, dict[str, list]] = {}
        self.translation = None

    def child(self, name: str, extras: dict | None = None) -> "Group":
        g = Group(name, extras)
        self.children.append(g)
        return g

    def _acc(self, mat: str):
        return self.geo.setdefault(mat, {"p": [], "n": [], "uv": [], "i": [], "count": 0})

    def add_tris(self, mat: Material, pos, nrm, uv, idx):
        a = self._acc(mat.name)
        base = a["count"]
        pos = np.asarray(pos, np.float32)
        nrm = np.asarray(nrm, np.float32)
        tri = np.asarray(idx, np.uint32).reshape(-1, 3)
        # glTF front faces are counter-clockwise: flip any triangle whose winding
        # disagrees with its declared vertex normals (makes every primitive robust).
        e1 = pos[tri[:, 1]] - pos[tri[:, 0]]
        e2 = pos[tri[:, 2]] - pos[tri[:, 0]]
        geo = np.cross(e1, e2)
        decl = nrm[tri[:, 0]] + nrm[tri[:, 1]] + nrm[tri[:, 2]]
        flip = (geo * decl).sum(1) < 0
        tri[flip] = tri[flip][:, [0, 2, 1]]
        a["p"].append(pos)
        a["n"].append(nrm)
        a["uv"].append(np.asarray(uv, np.float32))
        a["i"].append(tri.reshape(-1) + base)
        a["count"] += len(pos)

    # ---------------- primitives ----------------
    def box(self, mat: Material, center, size, rot_y: float = 0.0, skip: str = ""):
        """Axis-aligned (optionally Y-rotated) box. skip: any of '+x -x +y -y +z -z' tokens."""
        cx, cy, cz = center
        sx, sy, sz = size
        hx, hy, hz = sx / 2, sy / 2, sz / 2
        s = max(mat.tex_m, 1e-6)
        faces = [
            ("+x", (1, 0, 0), [(hx, -hy, -hz), (hx, -hy, hz), (hx, hy, hz), (hx, hy, -hz)], "zy"),
            ("-x", (-1, 0, 0), [(-hx, -hy, hz), (-hx, -hy, -hz), (-hx, hy, -hz), (-hx, hy, hz)], "zy"),
            ("+y", (0, 1, 0), [(-hx, hy, -hz), (hx, hy, -hz), (hx, hy, hz), (-hx, hy, hz)], "xz"),
            ("-y", (0, -1, 0), [(-hx, -hy, hz), (hx, -hy, hz), (hx, -hy, -hz), (-hx, -hy, -hz)], "xz"),
            ("+z", (0, 0, 1), [(hx, -hy, hz), (-hx, -hy, hz), (-hx, hy, hz), (hx, hy, hz)], "xy"),
            ("-z", (0, 0, -1), [(-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz)], "xy"),
        ]
        c, sn = math.cos(rot_y), math.sin(rot_y)
        skips = set(skip.split())
        P, Nn, UV, I = [], [], [], []
        for name, n, verts, proj in faces:
            if name in skips:
                continue
            base = len(P)
            for v in verts:
                x, y, z = v
                # UV from unrotated world-ish coords (continuity across adjacent boxes)
                wx, wy, wz = cx + x, cy + y, cz + z
                u, vv = {"zy": (wz, wy), "xz": (wx, wz), "xy": (wx, wy)}[proj]
                UV.append((u / s, vv / s))
                rx = c * x + sn * z
                rz = -sn * x + c * z
                P.append((cx + rx, cy + y, cz + rz))
            nx = c * n[0] + sn * n[2]
            nz = -sn * n[0] + c * n[2]
            Nn += [(nx, n[1], nz)] * 4
            I += [base, base + 1, base + 2, base, base + 2, base + 3]
        if P:
            self.add_tris(mat, P, Nn, UV, I)

    def cylinder(self, mat: Material, center, radius, height, seg=20, caps=True):
        cx, cy, cz = center
        P, Nn, UV, I = [], [], [], []
        s = max(mat.tex_m, 1e-6)
        for k in range(seg + 1):
            a = 2 * math.pi * k / seg
            x, z = math.cos(a), math.sin(a)
            for y, vv in ((cy - height / 2, 0), (cy + height / 2, 1)):
                P.append((cx + radius * x, y, cz + radius * z))
                Nn.append((x, 0, z))
                UV.append((k / seg * 2 * math.pi * radius / s, y / s))
        for k in range(seg):
            a, b = 2 * k, 2 * k + 2
            I += [a, b, a + 1, a + 1, b, b + 1]
        if caps:
            for top in (True, False):
                y = cy + (height / 2 if top else -height / 2)
                base = len(P)
                P.append((cx, y, cz)); Nn.append((0, 1 if top else -1, 0)); UV.append((0.5, 0.5))
                for k in range(seg + 1):
                    a = 2 * math.pi * k / seg
                    P.append((cx + radius * math.cos(a), y, cz + radius * math.sin(a)))
                    Nn.append((0, 1 if top else -1, 0)); UV.append((0.5 + 0.5 * math.cos(a), 0.5 + 0.5 * math.sin(a)))
                for k in range(seg):
                    I += [base, base + 1 + k, base + 2 + k] if top else [base, base + 2 + k, base + 1 + k]
        self.add_tris(mat, P, Nn, UV, I)

    def sphere(self, mat: Material, center, radius, seg=14, rings=8, squash=1.0):
        cx, cy, cz = center
        P, Nn, UV, I = [], [], [], []
        for r in range(rings + 1):
            th = math.pi * r / rings
            for k in range(seg + 1):
                ph = 2 * math.pi * k / seg
                x, y, z = math.sin(th) * math.cos(ph), math.cos(th), math.sin(th) * math.sin(ph)
                P.append((cx + radius * x, cy + radius * y * squash, cz + radius * z))
                Nn.append((x, y, z)); UV.append((k / seg, r / rings))
        for r in range(rings):
            for k in range(seg):
                a = r * (seg + 1) + k
                b = a + seg + 1
                I += [a, a + 1, b, a + 1, b + 1, b]
        self.add_tris(mat, P, Nn, UV, I)

    def count_tris(self) -> int:
        n = sum(sum(len(i) for i in g["i"]) // 3 for g in self.geo.values())
        return n + sum(c.count_tris() for c in self.children)


# ------------------------------------------------------------------ GLB writer
def write_glb(path: str, root: Group, materials: dict[str, Material],
              textures: dict[str, bytes], asset_extras: dict | None = None) -> dict:
    buf = bytearray()
    views, accessors, images, tex_defs, mats, meshes, nodes = [], [], [], [], [], [], []

    def add_view(data: bytes, target=None):
        while len(buf) % 4:
            buf.append(0)
        off = len(buf)
        buf.extend(data)
        v = {"buffer": 0, "byteOffset": off, "byteLength": len(data)}
        if target:
            v["target"] = target
        views.append(v)
        return len(views) - 1

    def add_acc(arr: np.ndarray, ctype: str, comp: int, target: int, with_minmax=False):
        vi = add_view(arr.tobytes(), target)
        a = {"bufferView": vi, "componentType": comp, "count": int(arr.shape[0]), "type": ctype}
        if with_minmax:
            a["min"] = [float(x) for x in arr.min(0)]
            a["max"] = [float(x) for x in arr.max(0)]
        accessors.append(a)
        return len(accessors) - 1

    # textures
    tex_index = {}
    samplers = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]
    for tname, data in textures.items():
        vi = add_view(data)
        images.append({"bufferView": vi, "mimeType": "image/png", "name": tname})
        tex_defs.append({"source": len(images) - 1, "sampler": 0, "name": tname})
        tex_index[tname] = len(tex_defs) - 1

    mat_index = {}
    for m in materials.values():
        d = {"name": m.name, "pbrMetallicRoughness": {
            "baseColorFactor": list(m.color), "metallicFactor": m.metallic, "roughnessFactor": m.roughness}}
        if m.texture:
            d["pbrMetallicRoughness"]["baseColorTexture"] = {"index": tex_index[m.texture]}
        if any(m.emissive):
            d["emissiveFactor"] = list(m.emissive)
        if m.blend:
            d["alphaMode"] = "BLEND"
        if m.double_sided or m.blend:
            d["doubleSided"] = True
        mat_index[m.name] = len(mats)
        mats.append(d)

    def emit(g: Group) -> int:
        node = {"name": g.name}
        if g.extras:
            node["extras"] = g.extras
        prims = []
        for mname, a in g.geo.items():
            if not a["p"]:
                continue
            pos = np.concatenate(a["p"]).astype("<f4")
            nrm = np.concatenate(a["n"]).astype("<f4")
            nl = np.linalg.norm(nrm, axis=1, keepdims=True)
            nrm = (nrm / np.maximum(nl, 1e-9)).astype("<f4")
            uv = np.concatenate(a["uv"]).astype("<f4")
            idx = np.concatenate(a["i"]).astype("<u4")
            prims.append({
                "attributes": {
                    "POSITION": add_acc(pos, "VEC3", 5126, 34962, True),
                    "NORMAL": add_acc(nrm, "VEC3", 5126, 34962),
                    "TEXCOORD_0": add_acc(uv, "VEC2", 5126, 34962),
                },
                "indices": add_acc(idx.reshape(-1, 1), "SCALAR", 5125, 34963),
                "material": mat_index[mname],
            })
        if prims:
            meshes.append({"name": g.name, "primitives": prims})
            node["mesh"] = len(meshes) - 1
        idx_self = len(nodes)
        nodes.append(node)
        kids = [emit(c) for c in g.children]
        if kids:
            node["children"] = kids
        return idx_self

    root_idx = emit(root)
    while len(buf) % 4:
        buf.append(0)
    gltf = {
        "asset": {"version": "2.0", "generator": "NAMMA TWIN synthetic builder", "extras": asset_extras or {}},
        "scene": 0, "scenes": [{"nodes": [root_idx], "name": root.name}],
        "nodes": nodes, "meshes": meshes, "materials": mats, "samplers": samplers,
        "textures": tex_defs, "images": images, "accessors": accessors,
        "bufferViews": views, "buffers": [{"byteLength": len(buf)}],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(buf)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total))
        f.write(struct.pack("<I4s", len(js), b"JSON")); f.write(js)
        f.write(struct.pack("<I4s", len(buf), b"BIN\0")); f.write(bytes(buf))
    return {"bytes": total, "nodes": len(nodes), "meshes": len(meshes),
            "triangles": root.count_tris(), "materials": len(mats), "textures": len(tex_defs)}
