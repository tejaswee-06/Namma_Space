"""SIMULATED smartphone-walkthrough capture of the synthetic demo building.

This is NOT COLMAP output and NOT a scan of a real place. It is a photogrammetry-*like* simulation:
  1. a virtual handheld camera walks routes produced by the validated nav grid (2 fps, 72 deg HFOV),
  2. true depth maps are rasterised from the model, so occlusion is real,
  3. surface points become 'reconstructed' only if (a) they carry enough visual texture to match,
     (b) they are seen from >=2 registered frames with enough triangulation angle, and
     (c) the viewing angle is not grazing,
  4. noise grows with depth^2, frames with too few features fail to register,
  5. the model is emitted in an ARBITRARY scale/orientation COLMAP-text frame; the metric frame
     must be recovered by reconstruction/registration/register.py (the truth is kept separately,
     only for validation).
Run: python -m reconstruction.synthetic.simulate_scan --scene assets/scenes/demo-block-a
"""
from __future__ import annotations
import argparse, json, math, os, struct, sys, time
from multiprocessing import Pool
import numpy as np
from PIL import Image
from tools.render_glb import load_glb, collect
from reconstruction.navigation_geometry.navgrid import NavMap, poi_point
from .depth import look_at, rasterize_depth

W_D, H_D = 256, 144
HFOV = 72.0
FOCAL_D = (W_D / 2) / math.tan(math.radians(HFOV / 2))
H_FLOOR = 3.6
CAM_H = 1.45
SPACING = 0.75
SEED = 20261101
SIM_LABEL = "SIMULATED_FROM_SYNTHETIC_MODEL"


# ------------------------------------------------------------------ scene sampling
def load_surfaces(glb):
    js, b = load_glb(glb)
    prims = [p for p in collect(js, b, hide=("ROOF", "SITE")) if not p["blend"]]
    tri_all, samples = [], []
    for p in prims:
        P = p["pos"][p["idx"]].astype(np.float64)
        tri_all.append(P.astype(np.float32))
    return prims, np.concatenate(tri_all)


def sample_points(prims, n_total, rng):
    areas = []
    for p in prims:
        P = p["pos"][p["idx"]].astype(np.float64)
        areas.append(0.5 * np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1))
    tot = sum(a.sum() for a in areas)
    pos, col, nrm, feat = [], [], [], []
    for p, a in zip(prims, areas):
        n = int(round(n_total * a.sum() / tot))
        if n <= 0:
            continue
        idx = p["idx"]
        P = p["pos"][idx].astype(np.float64)
        ti = rng.choice(len(a), n, p=a / a.sum())
        r1, r2 = rng.random(n), rng.random(n)
        s = np.sqrt(r1)
        b0, b1, b2 = 1 - s, s * (1 - r2), s * r2
        T = P[ti]
        pp = T[:, 0] * b0[:, None] + T[:, 1] * b1[:, None] + T[:, 2] * b2[:, None]
        nn = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
        nn /= np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-12)
        base = np.broadcast_to(p["color"][:3], (n, 3)).astype(np.float64)
        if p["img"] is not None:
            uvt = p["uv"][idx[ti]].astype(np.float64)
            uv = uvt[:, 0] * b0[:, None] + uvt[:, 1] * b1[:, None] + uvt[:, 2] * b2[:, None]
            Hh, Ww = p["img"].shape[:2]
            tex = p["img"][(uv[:, 1] % 1.0 * Hh).astype(int) % Hh, (uv[:, 0] % 1.0 * Ww).astype(int) % Ww]
            c = base * tex
            lum = p["img"] @ np.array([0.299, 0.587, 0.114])
            richness = 0.25 + 6.0 * float(lum.std())
        else:
            c = base
            richness = 0.25
        if p["emissive"].any():
            c = np.clip(c + p["emissive"][None], 0, 1)
            richness = max(richness, 0.6)
        small = (a[ti] < 0.05)
        f = np.clip(richness + 0.2 * small, 0.2, 0.97)
        pos.append(pp); col.append(c); nrm.append(nn); feat.append(f)
    return (np.concatenate(pos).astype(np.float32), np.concatenate(col).astype(np.float32),
            np.concatenate(nrm).astype(np.float32), np.concatenate(feat).astype(np.float32))


# ------------------------------------------------------------------ trajectory
def stair_polyline(f):
    y = f * H_FLOOR
    return [(15.1, y, 7.9), (15.1, y + 1.8, 3.9), (16.0, y + 1.8, 4.3), (16.9, y + 1.8, 4.9), (16.9, y + H_FLOOR, 7.6), (16.9, y + H_FLOOR, 8.1)]


ORDER = [
    (0, ["f0-lobby", "f0-seminar-a", "f0-admin-office", "f0-help-desk", "f0-commons"]),
    (1, ["f1-electronics-lab", "f1-computer-lab", "f1-faculty-offices", "f1-project-lab", "f1-telecom-lab"]),
    (2, ["f2-conference", "f2-iot-lab", "f2-library", "f2-lounge", "f2-dept-office"]),
]


def build_trajectory(nav, rng):
    sem = nav.semantic
    rooms = {r["id"]: r for r in sem["rooms"]}
    nav.portals = [p for p in nav.portals if p.kind == "stair"]
    frames = []     # dict(eye=(x,y,z), yaw, pitch, tag)
    cur = poi_point(sem, "poi-main-entrance")

    def walk(points_xz, f, base_yaw=None):
        pts = np.array(points_xz, float)
        seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        L = np.concatenate([[0], np.cumsum(seg)])
        if L[-1] < 1e-6:
            return
        for k, s in enumerate(np.arange(0, L[-1], SPACING)):
            x = np.interp(s, L, pts[:, 0]); z = np.interp(s, L, pts[:, 1])
            xa = np.interp(min(s + 1.2, L[-1]), L, pts[:, 0]); za = np.interp(min(s + 1.2, L[-1]), L, pts[:, 1])
            yaw = math.atan2(xa - x, za - z) if (abs(xa - x) + abs(za - z)) > 1e-6 else (base_yaw or 0)
            yaw += math.radians(14 * math.sin(0.55 * k + rng.random()) + (rng.choice([-35, 35]) if k % 6 == 5 else 0))
            frames.append(dict(eye=(x, f * H_FLOOR + CAM_H + rng.normal(0, 0.03), z), yaw=yaw,
                               pitch=math.radians(-4 + rng.normal(0, 3)), floor=f, tag="walk"))

    def sweep(x, z, f, n=12):
        y0 = rng.random() * 2 * math.pi
        for k in range(n):
            frames.append(dict(eye=(x + rng.normal(0, .05), f * H_FLOOR + CAM_H + rng.normal(0, 0.03), z + rng.normal(0, .05)),
                               yaw=y0 + 2 * math.pi * k / n, pitch=math.radians(-2 + (6 if k % 3 == 0 else 0) + rng.normal(0, 2)),
                               floor=f, tag="sweep"))

    for f, ids in ORDER:
        for rid in ids:
            r = rooms[rid]
            tgt = (f, r["anchor"]["x"], r["anchor"]["z"])
            res = None
            for cand in (tgt, (f, r["nav_anchor"]["x"], r["nav_anchor"]["z"])):
                cell = nav.nearest_walkable(f, cand[1], cand[2], 2.5)
                if cell is None:
                    continue
                tx, tz = nav.to_world(*cell)
                res = nav.route(cur, (f, tx, tz))
                if res["status"] == "ok":
                    break
            if res is None or res["status"] != "ok":
                print("  trajectory: skip", rid, None if res is None else res.get("reason")); continue
            for seg in res["segments"]:
                walk(seg["points"], seg["floor"])
            sweep(tx, tz, f)
            cur = (f, tx, tz)
        if f < 2:
            st = poi_point(sem, f"poi-f{f}-stair-a")
            res = nav.route(cur, st)
            for seg in res["segments"]:
                walk(seg["points"], seg["floor"])
            poly = stair_polyline(f)
            P = np.array(poly)
            L = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
            for s in np.arange(0, L[-1], 0.6):
                x, y, z = [np.interp(s, L, P[:, i]) for i in range(3)]
                xa, ya, za = [np.interp(min(s + 1.0, L[-1]), L, P[:, i]) for i in range(3)]
                frames.append(dict(eye=(x, y + CAM_H, z), yaw=math.atan2(xa - x, za - z) if abs(xa - x) + abs(za - z) > 1e-6 else math.pi,
                                   pitch=math.radians(-10), floor=f, tag="stairs"))
            cur = (f + 1, 16.9, 8.1)
            cur = (f + 1, *nav.to_world(*nav.nearest_walkable(f + 1, 16.9, 8.1, 0.8)))
    return frames


def pose_matrices(fr):
    eye = np.array(fr["eye"], float)
    fwd = np.array([math.sin(fr["yaw"]) * math.cos(fr["pitch"]), math.sin(fr["pitch"]), math.cos(fr["yaw"]) * math.cos(fr["pitch"])])
    R, t = look_at(eye, eye + fwd)
    return eye, R, t


def _depth_job(args):
    k, R, t, P = args
    return k, rasterize_depth(P, R, t, W_D, H_D, FOCAL_D)


_P = None
def _init(P):
    global _P
    _P = P
def _job(a):
    k, R, t = a
    return k, rasterize_depth(_P, R, t, W_D, H_D, FOCAL_D)


# ------------------------------------------------------------------ main simulation
def simulate(scene_dir, n_cand=3_000_000, out_sub="scan", n_preview_frames=16):
    t_start = time.time()
    rng = np.random.default_rng(SEED)
    out = os.path.join(scene_dir, out_sub); os.makedirs(os.path.join(out, "colmap"), exist_ok=True)
    nav = NavMap(scene_dir)
    sem = nav.semantic
    prims, TRI = load_surfaces(os.path.join(scene_dir, "visual.glb"))
    print(f"scene tris={len(TRI)} prims={len(prims)}")
    frames = build_trajectory(nav, rng)
    print("frames", len(frames))
    pos, col, nrm, feat = sample_points(prims, n_cand, rng)
    has_feat = rng.random(len(pos)) < feat           # does this surface point carry a matchable feature?
    pos, col, nrm, feat = pos[has_feat], col[has_feat], nrm[has_feat], feat[has_feat]
    N = len(pos)
    print("candidate feature points", N, f"({has_feat.mean():.2f} of {n_cand})")

    poses = [pose_matrices(f) for f in frames]
    with Pool(2, initializer=_init, initargs=(TRI,)) as pool:
        depths = dict(pool.imap_unordered(_job, [(k, poses[k][1], poses[k][2]) for k in range(len(frames))], chunksize=4))
    print(f"depth maps done in {time.time() - t_start:.0f}s")

    cnt = np.zeros(N, np.uint16)
    vsum = np.zeros((N, 3), np.float32)
    bestz = np.full(N, np.inf, np.float32)
    bestcam = np.full(N, -1, np.int32)
    registered, richness = [], []
    for k, fr in enumerate(frames):
        eye, R, t = poses[k]
        d = depths[k]
        cam = pos @ R.T.astype(np.float32) + t.astype(np.float32)
        z = -cam[:, 2]
        inz = (z > 0.4) & (z < 14.0)
        sx = np.where(inz, cam[:, 0] / np.maximum(z, 1e-3) * FOCAL_D + W_D / 2, -1)
        sy = np.where(inz, -cam[:, 1] / np.maximum(z, 1e-3) * FOCAL_D + H_D / 2, -1)
        ins = inz & (sx >= 0) & (sx < W_D) & (sy >= 0) & (sy < H_D)
        idx = np.nonzero(ins)[0]
        if len(idx) == 0:
            registered.append(False); richness.append(0.0); continue
        dd = d[sy[idx].astype(int), sx[idx].astype(int)]
        vis = z[idx] <= dd + 0.05 + 0.04 * z[idx]
        view = pos[idx] - eye.astype(np.float32)
        vn = view / np.maximum(np.linalg.norm(view, axis=1, keepdims=True), 1e-6)
        cosang = np.abs((vn * nrm[idx]).sum(1))
        ok = vis & (cosang > 0.25)
        idx, vn = idx[ok], vn[ok]
        rich = float(feat[idx].mean()) if len(idx) else 0.0
        n_vis = len(idx)
        reg = (n_vis >= 400) and (rich >= 0.42) and (rng.random() > 0.04)      # motion-blur / low-texture failure
        registered.append(bool(reg)); richness.append(rich)
        if not reg:
            continue
        cnt[idx] += 1
        vsum[idx] += vn
        upd = z[idx] < bestz[idx]
        bestz[idx[upd]] = z[idx][upd]; bestcam[idx[upd]] = k
    print(f"visibility pass done in {time.time() - t_start:.0f}s; registered {sum(registered)}/{len(frames)}")

    resultant = np.linalg.norm(vsum, axis=1) / np.maximum(cnt, 1)
    keep = (cnt >= 2) & (resultant < 0.9994)                         # >=2 views and >=~2 deg of triangulation angle
    kp = np.nonzero(keep)[0]
    sig = (0.003 + 0.0015 * bestz[kp] ** 2) / np.sqrt(np.minimum(cnt[kp], 6))
    eyes = np.array([p[0] for p in poses], np.float32)
    ray = pos[kp] - eyes[bestcam[kp]]
    ray /= np.maximum(np.linalg.norm(ray, axis=1, keepdims=True), 1e-6)
    P_noisy = pos[kp] + ray * (rng.normal(0, 1, len(kp)) * sig)[:, None].astype(np.float32) + (rng.normal(0, 1, (len(kp), 3)) * (sig / 4)[:, None]).astype(np.float32)
    C = np.clip(col[kp] * (0.92 + 0.14 * rng.random((len(kp), 1))) + rng.normal(0, 0.02, (len(kp), 3)), 0, 1)
    out_ids = rng.random(len(kp)) < 0.004                           # gross outliers
    P_noisy[out_ids] += (rng.normal(0, 0.6, (int(out_ids.sum()), 3))).astype(np.float32)
    trk = np.minimum(cnt[kp], 255).astype(np.uint8)
    print("reconstructed points (raw)", len(kp), "outliers injected", int(out_ids.sum()))

    # voxel-thin to 6 cm for the dense cloud, keep highest-track point per voxel
    P_d, C_d, T_d = voxel_thin(P_noisy, C, trk, 0.06)
    P_s, C_s, T_s = voxel_thin(P_noisy[trk >= 5], C[trk >= 5], trk[trk >= 5], 0.35)     # 'sparse' = long tracks, coarse
    P_v, C_v, T_v = voxel_thin(P_noisy, C, trk, 0.12)
    print(f"dense {len(P_d)}  sparse {len(P_s)}  viewer {len(P_v)}")

    # ------- arbitrary COLMAP frame
    s_arb = float(rng.uniform(0.2, 0.6))
    ang = rng.uniform(0, 2 * np.pi); tilt = np.radians(rng.uniform(8, 22)); roll = np.radians(rng.uniform(-10, 10))
    Rz = np.array([[math.cos(ang), -math.sin(ang), 0], [math.sin(ang), math.cos(ang), 0], [0, 0, 1]])
    Rx = np.array([[1, 0, 0], [0, math.cos(tilt), -math.sin(tilt)], [0, math.sin(tilt), math.cos(tilt)]])
    Ry = np.array([[math.cos(roll), 0, math.sin(roll)], [0, 1, 0], [-math.sin(roll), 0, math.cos(roll)]])
    R0 = Rz @ Rx @ Ry
    t0 = rng.uniform(-8, 8, 3)
    to_arb = lambda X: (s_arb * (np.asarray(X, float) @ R0.T)) + t0
    json.dump({"label": "VALIDATION ONLY - not available to the registration step in a real capture",
               "scale": s_arb, "R": R0.tolist(), "t": t0.tolist(), "maps": "p_colmap = scale * R @ p_metric + t"},
              open(os.path.join(out, "ground_truth_transform.json"), "w"), indent=1)

    write_colmap(out, frames, poses, registered, to_arb, R0, s_arb, t0, P_s, C_s, T_s, rng)
    write_ply(os.path.join(out, "dense_cloud_metric_gt_frame.ply"), P_d, C_d, T_d, "SIMULATED dense cloud in the building frame (ground-truth registered, metres)")
    write_ply(os.path.join(out, "dense_cloud_colmap_frame.ply"), to_arb(P_d).astype(np.float32), C_d, T_d, "SIMULATED dense cloud in an ARBITRARY COLMAP-like frame (unregistered)")
    write_ply(os.path.join(out, "sparse_cloud_metric_gt_frame.ply"), P_s, C_s, T_s, "SIMULATED sparse cloud (building frame)")
    write_viewer_cloud(os.path.join(out, "viewer_cloud.bin"), P_v, C_v, T_v)

    report = coverage_report(sem, P_d, frames, registered, richness, poses, N, len(kp), len(P_d), len(P_s), n_cand, time.time() - t_start, s_arb)
    json.dump(report, open(os.path.join(out, "scan_report.json"), "w"), indent=1)
    export_trajectory(out, frames, registered, poses)
    render_preview_frames(out, scene_dir, frames, registered, poses, n_preview_frames, rng)
    print(json.dumps({k: report[k] for k in ("frames", "registered_frames", "registration_rate", "dense_points", "sparse_points", "mean_room_floor_coverage")}, indent=1))
    return report


def voxel_thin(P, C, T, v):
    key = np.floor(P / v).astype(np.int64)
    key = (key[:, 0] + 100000) * 4_000_000_000 + (key[:, 1] + 100000) * 20000 + (key[:, 2] + 100000)
    order = np.lexsort((-T.astype(np.int32), key))
    ks = key[order]
    first = np.ones(len(ks), bool); first[1:] = ks[1:] != ks[:-1]
    sel = order[first]
    return P[sel].astype(np.float32), C[sel].astype(np.float32), T[sel]


def write_ply(path, P, C, T, comment):
    n = len(P)
    hdr = ("ply\nformat binary_little_endian 1.0\n" f"comment {comment}\ncomment label {SIM_LABEL}\n"
           f"element vertex {n}\nproperty float x\nproperty float y\nproperty float z\n"
           "property uchar red\nproperty uchar green\nproperty uchar blue\nproperty uchar track_length\nend_header\n").encode()
    rec = np.zeros(n, dtype=[("p", "<f4", 3), ("c", "u1", 3), ("t", "u1")])
    rec["p"] = P; rec["c"] = (np.clip(C, 0, 1) * 255).astype(np.uint8); rec["t"] = T
    with open(path, "wb") as f:
        f.write(hdr); f.write(rec.tobytes())


def write_viewer_cloud(path, P, C, T):
    """Compact: header JSON (len-prefixed) + uint16 xyz quantised to bbox + uint8 rgb + uint8 track."""
    mn, mx = P.min(0), P.max(0)
    q = np.round((P - mn) / np.maximum(mx - mn, 1e-6) * 65535).astype("<u2")
    rec = np.zeros(len(P), dtype=[("q", "<u2", 3), ("c", "u1", 3), ("t", "u1")])
    rec["q"] = q; rec["c"] = (np.clip(C, 0, 1) * 255).astype(np.uint8); rec["t"] = T
    hdr = json.dumps({"n": len(P), "min": mn.tolist(), "max": mx.tolist(), "label": SIM_LABEL, "stride": 10}).encode()
    with open(path, "wb") as f:
        f.write(struct.pack("<I", len(hdr))); f.write(hdr); f.write(rec.tobytes())


def write_colmap(out, frames, poses, registered, to_arb, R0, s, t0, P_s, C_s, T_s, rng):
    cd = os.path.join(out, "colmap")
    fx = (1280 / 2) / math.tan(math.radians(HFOV / 2))
    with open(os.path.join(cd, "cameras.txt"), "w") as f:
        f.write(f"# {SIM_LABEL}: NOT produced by COLMAP. Format follows COLMAP text model.\n# Camera list with one line of data per camera:\n"
                "#   CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n# Number of cameras: 1\n")
        f.write(f"1 SIMPLE_PINHOLE 1280 720 {fx:.4f} 640 360\n")
    DCV = np.diag([1.0, -1.0, -1.0])
    lines = []
    nreg = 0
    for k, (fr, (eye, R, t)) in enumerate(zip(frames, poses)):
        if not registered[k]:
            continue
        nreg += 1
        c_arb = to_arb(eye[None])[0]
        Rc = DCV @ R @ R0.T                       # world(arb) -> camera (COLMAP convention: +Z forward, +Y down)
        # SfM estimate noise (1.5 cm * scale, 0.1 deg)
        c_arb = c_arb + rng.normal(0, 0.015 * s, 3)
        dth = np.radians(0.1) * rng.normal(0, 1, 3)
        K = np.array([[0, -dth[2], dth[1]], [dth[2], 0, -dth[0]], [-dth[1], dth[0], 0]])
        Rc = (np.eye(3) + K) @ Rc
        u, _, vt = np.linalg.svd(Rc); Rc = u @ vt
        tv = -Rc @ c_arb
        q = rot2quat(Rc)
        lines.append(f"{nreg} {q[0]:.9f} {q[1]:.9f} {q[2]:.9f} {q[3]:.9f} {tv[0]:.9f} {tv[1]:.9f} {tv[2]:.9f} 1 frame_{k:04d}.jpg\n\n")
    with open(os.path.join(cd, "images.txt"), "w") as f:
        f.write(f"# {SIM_LABEL}. Image list with two lines of data per image (second line = POINTS2D, left empty: no real features exist).\n"
                "#   IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n"
                f"# Number of images: {nreg}\n")
        f.writelines(lines)
    Pa = to_arb(P_s)
    with open(os.path.join(cd, "points3D.txt"), "w") as f:
        f.write(f"# {SIM_LABEL}. 3D point list: POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[] (track omitted)\n# Number of points: {len(Pa)}\n")
        for i, (p, c, tr) in enumerate(zip(Pa, C_s, T_s)):
            f.write(f"{i + 1} {p[0]:.5f} {p[1]:.5f} {p[2]:.5f} {int(c[0]*255)} {int(c[1]*255)} {int(c[2]*255)} {0.4 + 0.5 * rng.random():.3f}\n")


def rot2quat(R):
    t = np.trace(R)
    if t > 0:
        s = math.sqrt(t + 1) * 2; return (0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s)
    i = int(np.argmax(np.diag(R)))
    if i == 0:
        s = math.sqrt(1 + R[0, 0] - R[1, 1] - R[2, 2]) * 2; return ((R[2, 1] - R[1, 2]) / s, 0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s)
    if i == 1:
        s = math.sqrt(1 + R[1, 1] - R[0, 0] - R[2, 2]) * 2; return ((R[0, 2] - R[2, 0]) / s, (R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s)
    s = math.sqrt(1 + R[2, 2] - R[0, 0] - R[1, 1]) * 2; return ((R[1, 0] - R[0, 1]) / s, (R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s)


def coverage_report(sem, P, frames, registered, richness, poses, n_feat, n_raw, n_dense, n_sparse, n_cand, secs, s_arb):
    rooms_out = []
    for r in sem["rooms"]:
        b = r["bounds"]; fy = r["floor"] * H_FLOOR
        m = (P[:, 0] >= b["x0"]) & (P[:, 0] <= b["x1"]) & (P[:, 2] >= b["z0"]) & (P[:, 2] <= b["z1"]) & (P[:, 1] > fy - 0.3) & (P[:, 1] < fy + 3.4)
        Q = P[m]
        nx = max(1, int((b["x1"] - b["x0"]) / 0.25)); nz = max(1, int((b["z1"] - b["z0"]) / 0.25))
        def cov(ylo, yhi):
            mm = (Q[:, 1] >= fy + ylo) & (Q[:, 1] < fy + yhi)
            if not mm.any():
                return 0.0
            gi = np.clip(((Q[mm, 0] - b["x0"]) / 0.25).astype(int), 0, nx - 1); gj = np.clip(((Q[mm, 2] - b["z0"]) / 0.25).astype(int), 0, nz - 1)
            g = np.zeros((nz, nx), bool); g[gj, gi] = True
            return float(g.mean())
        fc, cc = cov(-0.1, 0.3), cov(3.0, 3.4)
        area = (b["x1"] - b["x0"]) * (b["z1"] - b["z0"])
        rooms_out.append({"room_id": r["id"], "name": r["name"], "floor": r["floor"], "points": int(m.sum()), "points_per_m2_floor_area": round(m.sum() / max(area, 1e-6), 1),
                          "floor_coverage": round(fc, 3), "ceiling_coverage": round(cc, 3),
                          "status": "good" if fc > 0.6 else ("partial" if fc > 0.3 else "poor")})
    reg = int(sum(registered))
    return {"label": SIM_LABEL, "is_real_site_capture": False, "is_colmap_output": False,
            "method": "numpy depth-buffer visibility + photogrammetry-like feature/triangulation/noise model; see module docstring",
            "frames": len(frames), "registered_frames": reg, "registration_rate": round(reg / len(frames), 3),
            "frame_tags": {t: sum(1 for f in frames if f["tag"] == t) for t in ("walk", "sweep", "stairs")},
            "candidate_surface_points": n_cand, "feature_points": int(n_feat), "triangulated_points": int(n_raw),
            "dense_points": int(n_dense), "sparse_points": int(n_sparse),
            "noise_model": "sigma = (0.003 + 0.0015*z^2)/sqrt(min(tracks,6)) m; 0.4% gross outliers; colour jitter",
            "dropout_model": "p(feature) from texture luminance std; glass excluded; >=2 views, >=~2deg triangulation; |cos(incidence)|>0.25",
            "pose_noise": "1.5 cm position, 0.1 deg rotation (in metric units before arbitrary scaling)",
            "arbitrary_frame_scale_hidden": True, "runtime_s": round(secs, 1),
            "mean_room_floor_coverage": round(float(np.mean([r["floor_coverage"] for r in rooms_out])), 3),
            "rooms": rooms_out,
            "limitations": ["Not a measurement of a real place", "Geometry visibility is exact; real SfM would also drop views for blur/exposure/parallax",
                            "Glass and mirrors are invisible rather than producing artefacts", "No rolling shutter, lens distortion, or illumination change"]}


def export_trajectory(out, frames, registered, poses):
    json.dump([{"i": k, "eye": [round(float(x), 3) for x in p[0]], "yaw": round(float(f["yaw"]), 4), "pitch": round(float(f["pitch"]), 4),
                "floor": f["floor"], "tag": f["tag"], "registered": bool(registered[k]), "image": f"frames/frame_{k:04d}.jpg"}
               for k, (f, p) in enumerate(zip(frames, poses))], open(os.path.join(out, "cameras.json"), "w"), separators=(",", ":"))


def render_preview_frames(out, scene_dir, frames, registered, poses, n, rng):
    from tools.render_glb import render
    os.makedirs(os.path.join(out, "frames"), exist_ok=True)
    js, b = load_glb(os.path.join(scene_dir, "visual.glb"))
    pick = np.linspace(0, len(frames) - 1, n).astype(int)
    for k in pick:
        prims = collect(js, b, hide=("ROOF", "SITE"))
        eye, R, t = poses[k]
        fwd = -R[2]
        img = render(prims, eye, eye + fwd, 480, 270, fov=HFOV * 270 / 480 * 1.0 + 0 if False else 43.5, ss=1)
        img.save(os.path.join(out, "frames", f"frame_{k:04d}.jpg"), quality=90)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="assets/scenes/demo-block-a")
    ap.add_argument("--cand", type=int, default=3_000_000)
    a = ap.parse_args()
    simulate(a.scene, a.cand)
