"""Tiny numpy software rasteriser used to *verify* GLB output without a GPU/browser.
Parses the GLB independently of the writer (round-trip check), supports node filtering and
per-floor vertical explode, perspective-correct textured Lambert shading and alpha-blended glass.
Usage: python tools/render_glb.py visual.glb out.png --eye x y z --target x y z [--hide FLOOR_03,ROOF] [--explode 0]
"""
from __future__ import annotations
import argparse, io, json, struct, sys
import numpy as np
from PIL import Image


def load_glb(path):
    b = open(path, "rb").read()
    magic, ver, total = struct.unpack_from("<4sII", b, 0)
    assert magic == b"glTF" and ver == 2 and total == len(b), "bad GLB header"
    jl, jt = struct.unpack_from("<I4s", b, 12)
    assert jt == b"JSON"
    js = json.loads(b[20:20 + jl])
    bl, bt = struct.unpack_from("<I4s", b, 20 + jl)
    assert bt == b"BIN\0"
    binb = b[28 + jl:28 + jl + bl]
    return js, binb


def accessor(js, binb, i):
    a = js["accessors"][i]
    v = js["bufferViews"][a["bufferView"]]
    comp = {5126: np.float32, 5125: np.uint32, 5123: np.uint16}[a["componentType"]]
    n = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[a["type"]]
    arr = np.frombuffer(binb, comp, a["count"] * n, v["byteOffset"] + a.get("byteOffset", 0))
    return arr.reshape(-1, n) if n > 1 else arr


def collect(js, binb, hide=(), explode=0.0, only=None):
    imgs = {}
    for i, im in enumerate(js.get("images", [])):
        v = js["bufferViews"][im["bufferView"]]
        imgs[i] = np.asarray(Image.open(io.BytesIO(binb[v["byteOffset"]:v["byteOffset"] + v["byteLength"]])).convert("RGB"), np.float32) / 255
    prims = []

    def walk(ni, yoff, vis):
        n = js["nodes"][ni]
        name = n.get("name", "")
        if any(name.startswith(h) for h in hide):
            return
        ex = n.get("extras", {})
        if ex.get("kind") == "floor":
            yoff = yoff + explode * ex["floor"]
        if only and ex.get("kind") == "floor" and name not in only:
            return
        if "mesh" in n:
            for p in js["meshes"][n["mesh"]]["primitives"]:
                m = js["materials"][p["material"]]
                pbr = m["pbrMetallicRoughness"]
                t = pbr.get("baseColorTexture")
                img = imgs[js["textures"][t["index"]]["source"]] if t else None
                pos = accessor(js, binb, p["attributes"]["POSITION"]).astype(np.float64).copy()
                pos[:, 1] += yoff
                prims.append(dict(pos=pos, nrm=accessor(js, binb, p["attributes"]["NORMAL"]),
                                  uv=accessor(js, binb, p["attributes"]["TEXCOORD_0"]),
                                  idx=accessor(js, binb, p["indices"]).reshape(-1, 3),
                                  color=np.array(pbr["baseColorFactor"]), img=img,
                                  emissive=np.array(m.get("emissiveFactor", [0, 0, 0])),
                                  blend=m.get("alphaMode") == "BLEND", name=name))
        for c in n.get("children", []):
            walk(c, yoff, vis)
    for r in js["scenes"][0]["nodes"]:
        walk(r, 0.0, True)
    return prims



NEAR = 0.08


def clip_near(p, R, t):
    """Clip triangles crossing the near plane (in-place on the prim dict; idempotent per camera)."""
    pos, uv, nrm, idx = p["pos"], p["uv"], p["nrm"], p["idx"]
    z = -(pos @ R.T + t)[:, 2]
    front = z > NEAR
    nf = front[idx].sum(1)
    cross = (nf > 0) & (nf < 3)
    if not cross.any():
        p["idx"] = idx[nf == 3]
        return
    P, UV, N, I = [pos], [uv], [nrm], [idx[nf == 3]]
    base = len(pos)
    newp, newuv, newn, newi = [], [], [], []
    for tri in idx[cross]:
        verts = [(pos[i], uv[i], nrm[i], z[i]) for i in tri]
        poly = []
        for k in range(3):
            a, b = verts[k], verts[(k + 1) % 3]
            ina, inb = a[3] > NEAR, b[3] > NEAR
            if ina:
                poly.append(a)
            if ina != inb:
                f = (NEAR - a[3]) / (b[3] - a[3])
                poly.append((a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]), a[2], NEAR))
        for q in range(1, len(poly) - 1):
            for v in (poly[0], poly[q], poly[q + 1]):
                newp.append(v[0]); newuv.append(v[1]); newn.append(v[2])
            newi.append((base, base + 1, base + 2)); base += 3
    p["pos"] = np.concatenate([pos, np.array(newp)]) if newp else pos
    p["uv"] = np.concatenate([uv, np.array(newuv, uv.dtype)]) if newp else uv
    p["nrm"] = np.concatenate([nrm, np.array(newn, nrm.dtype)]) if newp else nrm
    p["idx"] = np.concatenate([idx[nf == 3], np.array(newi, idx.dtype)]) if newi else idx[nf == 3]


def look_at(eye, target, up=(0, 1, 0)):
    f = np.array(target, float) - eye; f /= np.linalg.norm(f)
    s = np.cross(f, up); s /= np.linalg.norm(s)
    u = np.cross(s, f)
    R = np.stack([s, u, -f])
    return R, -R @ eye


def render(prims, eye, target, W=1280, H=800, fov=45, ss=2, light=(0.4, 0.8, 0.5), bg=(0.80, 0.86, 0.92), ortho=None):
    eye = np.array(eye, float)
    R, t = look_at(eye, target)
    w, h = W * ss, H * ss
    focal = 0.5 * h / np.tan(np.radians(fov) / 2)
    zbuf = np.full((h, w), np.inf)
    img = np.zeros((h, w, 3), np.float32)
    # sky gradient
    g = np.linspace(0, 1, h)[:, None, None]
    img[:] = (np.array(bg)[None, None] * (1 - g * 0.35) + np.array([1, 1, 1])[None, None] * g * 0.0)
    L = np.array(light, float); L /= np.linalg.norm(L)
    blends = []
    for pass_blend in (False, True):
        for p in prims:
            if p["blend"] != pass_blend:
                continue
            clip_near(p, R, t)
            cam = p["pos"] @ R.T + t
            zc = -cam[:, 2]
            ok = zc > 0.05
            sx = cam[:, 0] / np.maximum(zc, 1e-6) * focal + w / 2
            sy = -cam[:, 1] / np.maximum(zc, 1e-6) * focal + h / 2
            idx = p["idx"]
            valid = ok[idx].all(1)
            idx = idx[valid]
            if not len(idx):
                continue
            order = np.argsort(-zc[idx].mean(1)) if pass_blend else np.arange(len(idx))
            for tri in idx[order]:
                x = sx[tri]; y = sy[tri]; z = zc[tri]
                x0, x1 = int(max(np.floor(x.min()), 0)), int(min(np.ceil(x.max()), w - 1))
                y0, y1 = int(max(np.floor(y.min()), 0)), int(min(np.ceil(y.max()), h - 1))
                if x1 < x0 or y1 < y0:
                    continue
                den = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
                if abs(den) < 1e-9:
                    continue
                # glTF convention: CCW = front. Cull on the 3D geometric normal (opaque only).
                if not pass_blend:
                    pw = p["pos"][tri]
                    gn = np.cross(pw[1] - pw[0], pw[2] - pw[0])
                    if gn @ (eye - pw[0]) <= 0:
                        continue
                gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
                l0 = ((y[1] - y[2]) * (gx - x[2]) + (x[2] - x[1]) * (gy - y[2])) / den
                l1 = ((y[2] - y[0]) * (gx - x[2]) + (x[0] - x[2]) * (gy - y[2])) / den
                l2 = 1 - l0 - l1
                m = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
                if not m.any():
                    continue
                iw = l0 / z[0] + l1 / z[1] + l2 / z[2]
                zz = 1 / np.maximum(iw, 1e-12)
                sub = zbuf[y0:y1 + 1, x0:x1 + 1]
                m &= zz < sub
                if not m.any():
                    continue
                b0, b1, b2 = l0 / z[0] * zz, l1 / z[1] * zz, l2 / z[2] * zz
                n = p["nrm"][tri[0]]
                lam = max(0.0, float(n @ L)) * 0.75 + 0.30 + 0.12 * max(0.0, float(-n[1]))  # key + ambient
                col = np.broadcast_to(p["color"][:3], (*m.shape, 3)).astype(np.float32)
                if p["img"] is not None:
                    uv = p["uv"][tri]
                    u = (b0 * uv[0, 0] + b1 * uv[1, 0] + b2 * uv[2, 0]) % 1.0
                    v = (b0 * uv[0, 1] + b1 * uv[1, 1] + b2 * uv[2, 1]) % 1.0
                    H_, W_ = p["img"].shape[:2]
                    col = col * p["img"][(v * H_).astype(int) % H_, (u * W_).astype(int) % W_]
                shade = col * lam + p["emissive"][None, None]
                dst = img[y0:y1 + 1, x0:x1 + 1]
                if pass_blend:
                    a = p["color"][3]
                    dst[m] = dst[m] * (1 - a) + shade[m] * a
                else:
                    dst[m] = shade[m]
                    sub[m] = zz[m]
    out = np.clip(img, 0, 1) ** (1 / 1.0)
    out = (out.reshape(H, ss, W, ss, 3).mean((1, 3)) * 255).astype(np.uint8)
    return Image.fromarray(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("glb"); ap.add_argument("out")
    ap.add_argument("--eye", nargs=3, type=float, required=True)
    ap.add_argument("--target", nargs=3, type=float, required=True)
    ap.add_argument("--hide", default="")
    ap.add_argument("--explode", type=float, default=0.0)
    ap.add_argument("--size", nargs=2, type=int, default=[1280, 800])
    ap.add_argument("--fov", type=float, default=45)
    ap.add_argument("--ss", type=int, default=2)
    a = ap.parse_args()
    js, binb = load_glb(a.glb)
    prims = collect(js, binb, tuple(h for h in a.hide.split(",") if h), a.explode)
    render(prims, a.eye, a.target, *a.size, fov=a.fov, ss=a.ss).save(a.out)
    print("rendered", a.out, "prims", len(prims))
