"""Small numpy depth rasteriser used by the capture simulator (visibility / occlusion)."""
from __future__ import annotations
import numpy as np

NEAR = 0.10


def look_at(eye, target, up=(0.0, 1.0, 0.0)):
    eye = np.asarray(eye, float)
    f = np.asarray(target, float) - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    R = np.stack([s, u, -f])           # GL convention: camera looks down -Z, +Y up
    return R, -R @ eye


def _clip_tri(v):
    """Clip one camera-space triangle (3,3) against z_cam<=-NEAR (i.e. depth>=NEAR). Returns list of tris."""
    d = -v[:, 2]
    poly = []
    for k in range(3):
        a, b = v[k], v[(k + 1) % 3]
        da, db = d[k], d[(k + 1) % 3]
        if da >= NEAR:
            poly.append(a)
        if (da >= NEAR) != (db >= NEAR):
            f = (NEAR - da) / (db - da)
            poly.append(a + f * (b - a))
    return [np.array([poly[0], poly[i], poly[i + 1]]) for i in range(1, len(poly) - 1)]


def rasterize_depth(P, R, t, w, h, focal, far=30.0):
    """P: (T,3,3) world triangles. Returns float32 depth map (h,w), inf where empty."""
    cam = P @ R.T + t
    z = -cam[..., 2]
    sel = (z.max(1) > NEAR) & (z.min(1) < far)
    cam, z = cam[sel], z[sel]
    front = (z >= NEAR).all(1)
    tris = [cam[front]]
    strad = cam[~front]
    extra = []
    for v in strad:
        extra += _clip_tri(v)
    if extra:
        tris.append(np.array(extra))
    cam = np.concatenate(tris) if len(tris) > 1 else tris[0]
    zc = np.maximum(-cam[..., 2], NEAR)
    sx = cam[..., 0] / zc * focal + w / 2
    sy = -cam[..., 1] / zc * focal + h / 2
    keep = (sx.max(1) > 0) & (sx.min(1) < w) & (sy.max(1) > 0) & (sy.min(1) < h)
    sx, sy, zc = sx[keep], sy[keep], zc[keep]
    depth = np.full((h, w), np.inf, np.float32)
    for k in range(len(sx)):
        x, y, d = sx[k], sy[k], zc[k]
        x0 = int(max(np.floor(x.min()), 0)); x1 = int(min(np.ceil(x.max()), w - 1))
        y0 = int(max(np.floor(y.min()), 0)); y1 = int(min(np.ceil(y.max()), h - 1))
        den = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
        if abs(den) < 1e-9:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        l0 = ((y[1] - y[2]) * (gx - x[2]) + (x[2] - x[1]) * (gy - y[2])) / den
        l1 = ((y[2] - y[0]) * (gx - x[2]) + (x[0] - x[2]) * (gy - y[2])) / den
        l2 = 1 - l0 - l1
        m = (l0 >= -1e-4) & (l1 >= -1e-4) & (l2 >= -1e-4)
        if not m.any():
            continue
        zz = 1.0 / np.maximum(l0 / d[0] + l1 / d[1] + l2 / d[2], 1e-9)
        sub = depth[y0:y1 + 1, x0:x1 + 1]
        m &= zz < sub
        sub[m] = zz[m]
    return depth
