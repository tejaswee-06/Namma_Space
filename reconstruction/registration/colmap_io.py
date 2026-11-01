"""Readers for COLMAP text models and the simple binary PLYs written by this repo."""
from __future__ import annotations
import numpy as np


def qvec2rot(q):
    w, x, y, z = q
    return np.array([
        [1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * w * z, 2 * x * z + 2 * w * y],
        [2 * x * y + 2 * w * z, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * w * x],
        [2 * x * z - 2 * w * y, 2 * y * z + 2 * w * x, 1 - 2 * x * x - 2 * y * y]])


def read_images_txt(path):
    """Returns list of dict(name, R (world->cam), t, center, up) in the model's own frame."""
    out = []
    with open(path) as f:
        lines = [l for l in f.read().splitlines() if not l.startswith("#")]
    for i in range(0, len(lines), 2):
        if not lines[i].strip():
            continue
        p = lines[i].split()
        q = tuple(float(v) for v in p[1:5]); t = np.array([float(v) for v in p[5:8]])
        R = qvec2rot(q)
        out.append({"name": p[9], "R": R, "t": t, "center": -R.T @ t,
                    "up": R.T @ np.array([0.0, -1.0, 0.0])})       # COLMAP camera: +Y is down
    return out


def read_points3d_txt(path):
    P, C = [], []
    for l in open(path):
        if l.startswith("#") or not l.strip():
            continue
        p = l.split()
        P.append([float(v) for v in p[1:4]]); C.append([int(v) for v in p[4:7]])
    return np.array(P), np.array(C, np.uint8)


def read_ply(path):
    with open(path, "rb") as f:
        n = None
        while True:
            line = f.readline().decode().strip()
            if line.startswith("element vertex"):
                n = int(line.split()[-1])
            if line == "end_header":
                break
        rec = np.frombuffer(f.read(), dtype=[("p", "<f4", 3), ("c", "u1", 3), ("t", "u1")], count=n)
    return rec["p"].astype(np.float64), rec["c"].copy(), rec["t"].copy()
