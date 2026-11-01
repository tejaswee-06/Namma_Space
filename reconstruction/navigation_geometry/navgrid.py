"""Geometry-derived walkability + A* routing.

Walkability is rasterised from the *collision geometry* (colliders.json: slabs = floor extents,
walls/columns/furniture/steps = obstacles), NOT from the visual mesh, a point cloud or a splat.
Policy is fail-closed: a cell is walkable only if it lies on a floor slab AND is at least
`radius` metres from every obstacle / slab edge / stair hole. Unknown space is blocked.

Routing is 8-connected A* over (floor, ix, iz) with explicit stair/lift portal edges,
followed by line-of-sight smoothing on the same clearance mask. `validate_route` re-checks the
final polyline against the raw collider AABBs (independent of the grid) so a rasterisation
bug cannot silently produce a route through a wall.
"""
from __future__ import annotations
import base64, heapq, json, math, os
from dataclasses import dataclass
import numpy as np
from scipy import ndimage

SQRT2 = math.sqrt(2)
H = 3.6


@dataclass
class Portal:
    kind: str                 # stair | lift
    a: tuple                  # (floor, x, z)
    b: tuple
    cost: float
    accessible: bool


class NavMap:
    def __init__(self, scene_dir: str, res: float = 0.1, radius: float = 0.35, extra_blocks=(), avatar_radius: float = 0.25):
        self.res, self.radius, self.avatar_radius = res, radius, avatar_radius
        sem = json.load(open(os.path.join(scene_dir, "semantic.json")))
        col = json.load(open(os.path.join(scene_dir, "colliders.json")))
        self.semantic = sem
        self.colliders = col["colliders"]
        self.n_floors = len(sem["building"]["floors"])
        fp = sem["building"]["footprint"]
        self.x0, self.z0 = fp["x"][0] - 1.0, fp["z"][0] - 1.0
        self.nx = int(round((fp["x"][1] - fp["x"][0] + 2.0) / res))
        self.nz = int(round((fp["z"][1] - fp["z"][0] + 2.0) / res))
        self.extra_blocks = list(extra_blocks)
        self.floor_slab = np.zeros((self.n_floors, self.nz, self.nx), bool)
        self.obst = np.zeros_like(self.floor_slab)
        self._rasterise()
        self.clear = np.zeros_like(self.floor_slab)
        self.dist = np.zeros(self.floor_slab.shape, np.float32)
        for f in range(self.n_floors):
            free_src = self.floor_slab[f] & ~self.obst[f]
            self.dist[f] = ndimage.distance_transform_edt(free_src) * res
            self.clear[f] = self.dist[f] >= radius
        self.portals: list[Portal] = []
        for s in sem["stairs"]:
            self.portals.append(Portal("stair", (s["floor_from"], s["bottom_node"][0], s["bottom_node"][2]),
                                       (s["floor_to"], s["top_node"][0], s["top_node"][2]), s["path_length_m_approx"], False))
        by_floor = {l["floor"]: l for l in sem["lifts"]}
        for f in range(self.n_floors - 1):
            a, b = by_floor[f], by_floor[f + 1]
            self.portals.append(Portal("lift", (f, a["x"], a["z"]), (f + 1, b["x"], b["z"]), 8.0, True))

    # ---------------------------------------------------------------- grid helpers
    def to_cell(self, x, z):
        return int(math.floor((x - self.x0) / self.res)), int(math.floor((z - self.z0) / self.res))

    def to_world(self, ix, iz):
        return self.x0 + (ix + 0.5) * self.res, self.z0 + (iz + 0.5) * self.res

    def _fill(self, arr, mn, mx):
        i0, j0 = self.to_cell(mn[0], mn[2]); i1, j1 = self.to_cell(mx[0], mx[2])
        i0, i1 = max(i0, 0), min(i1, self.nx - 1); j0, j1 = max(j0, 0), min(j1, self.nz - 1)
        if i1 >= i0 and j1 >= j0:
            arr[j0:j1 + 1, i0:i1 + 1] = True

    def _rasterise(self):
        for c in self.colliders:
            f = c["floor"]; mn, mx = c["min"], c["max"]
            fy = f * H
            if f >= self.n_floors:
                continue
            k = c["kind"]
            if k == "slab":
                if c.get("room") in ("site", "roof"):
                    continue
                if abs(mx[1] - fy) < 0.02:
                    self._fill(self.floor_slab[f], mn, mx)
            elif k == "step":
                self._fill(self.obst[f], mn, mx)               # stairs are portals, not planar floor
            elif k in ("wall", "glass", "column"):
                if mx[1] > fy + 0.35 and mn[1] < fy + 1.8:
                    self._fill(self.obst[f], mn, mx)
            elif k == "furniture":
                if mx[1] > fy + 0.35 and mn[1] < fy + 1.8:
                    self._fill(self.obst[f], mn, mx)
        for (f, x0, z0, x1, z1) in self.extra_blocks:
            self._fill(self.obst[f], (x0, 0, z0), (x1, 0, z1))

    # ---------------------------------------------------------------- queries
    def walkable(self, f, x, z):
        i, j = self.to_cell(x, z)
        return 0 <= i < self.nx and 0 <= j < self.nz and bool(self.clear[f, j, i])

    def nearest_walkable(self, f, x, z, max_r=1.2):
        i, j = self.to_cell(x, z)
        best = None
        R = int(max_r / self.res)
        for dj in range(-R, R + 1):
            for di in range(-R, R + 1):
                ii, jj = i + di, j + dj
                if 0 <= ii < self.nx and 0 <= jj < self.nz and self.clear[f, jj, ii]:
                    d = di * di + dj * dj
                    if best is None or d < best[0]:
                        best = (d, ii, jj)
        return None if best is None else (best[1], best[2])

    def _los(self, f, a, b):
        (x0, z0), (x1, z1) = a, b
        n = max(2, int(math.hypot(x1 - x0, z1 - z0) / (self.res * 0.5)))
        for t in np.linspace(0, 1, n):
            if not self.walkable(f, x0 + (x1 - x0) * t, z0 + (z1 - z0) * t):
                return False
        return True

    def route(self, start, goal, accessible=False):
        """start/goal = (floor, x, z). Returns dict(status, ...)."""
        sf, sx, sz = start; gf, gx, gz = goal
        for name, (f, x, z) in (("start", start), ("destination", goal)):
            if not (0 <= f < self.n_floors):
                return {"status": "invalid", "reason": f"{name}: unknown floor {f}"}
            i, j = self.to_cell(x, z)
            if not (0 <= i < self.nx and 0 <= j < self.nz) or not self.floor_slab[f, j, i]:
                return {"status": "unmapped", "reason": f"{name} is outside mapped floor area (fail-closed)"}
        s = self.nearest_walkable(sf, sx, sz, 0.6); g = self.nearest_walkable(gf, gx, gz, 0.6)
        if s is None:
            return {"status": "invalid", "reason": "start is inside an obstacle or lacks clearance"}
        if g is None:
            return {"status": "invalid", "reason": "destination is inside an obstacle or lacks clearance"}
        portal_cells = {}
        for p in self.portals:
            if accessible and not p.accessible:
                continue
            for (a, b) in ((p.a, p.b), (p.b, p.a)):
                ci = self.nearest_walkable(a[0], a[1], a[2], 0.4)
                cj = self.nearest_walkable(b[0], b[1], b[2], 0.4)
                if ci and cj:
                    portal_cells.setdefault((a[0], ci[0], ci[1]), []).append(((b[0], cj[0], cj[1]), p.cost, p.kind))
        start_s, goal_s = (sf, s[0], s[1]), (gf, g[0], g[1])

        def h(st):
            f, i, j = st
            return math.hypot(i - goal_s[1], j - goal_s[2]) * self.res if f == goal_s[0] else math.hypot(i - goal_s[1], j - goal_s[2]) * self.res * 0.0
        openq = [(h(start_s), 0.0, start_s)]
        gbest = {start_s: 0.0}; prev = {}; via = {}
        N8 = [(1, 0, 1), (-1, 0, 1), (0, 1, 1), (0, -1, 1), (1, 1, SQRT2), (1, -1, SQRT2), (-1, 1, SQRT2), (-1, -1, SQRT2)]
        expanded = 0
        while openq:
            _, gc, cur = heapq.heappop(openq)
            if gc > gbest.get(cur, 1e18) + 1e-9:
                continue
            if cur == goal_s:
                break
            expanded += 1
            f, i, j = cur
            for di, dj, w in N8:
                ni, nj = i + di, j + dj
                if not (0 <= ni < self.nx and 0 <= nj < self.nz) or not self.clear[f, nj, ni]:
                    continue
                if di and dj and not (self.clear[f, j, ni] and self.clear[f, nj, i]):
                    continue                                   # no diagonal corner-cutting
                st = (f, ni, nj); ng = gc + w * self.res
                if ng < gbest.get(st, 1e18):
                    gbest[st] = ng; prev[st] = cur; via[st] = None
                    heapq.heappush(openq, (ng + h(st), ng, st))
            for (dst, cost, kind) in portal_cells.get(cur, ()):
                ng = gc + cost
                if ng < gbest.get(dst, 1e18):
                    gbest[dst] = ng; prev[dst] = cur; via[dst] = kind
                    heapq.heappush(openq, (ng, ng, dst))
        if goal_s not in gbest:
            return {"status": "no_path", "reason": "destination is not connected to the start through validated walkable space",
                    "expanded": expanded}
        chain = [goal_s]
        while chain[-1] != start_s:
            chain.append(prev[chain[-1]])
        chain.reverse()
        # split into per-floor segments, smooth each
        segments, cur_seg, cur_f = [], [], chain[0][0]
        transitions = []
        for k, st in enumerate(chain):
            if st[0] != cur_f or (via.get(st) and k > 0):
                if cur_seg:
                    segments.append((cur_f, cur_seg))
                transitions.append({"kind": via.get(st) or "stair", "from_floor": cur_f, "to_floor": st[0]})
                cur_seg, cur_f = [], st[0]
            cur_seg.append(self.to_world(st[1], st[2]))
        segments.append((cur_f, cur_seg))
        out_segments, total = [], 0.0
        for f, pts in segments:
            sm = [pts[0]]; k = 0
            while k < len(pts) - 1:
                j2 = len(pts) - 1
                while j2 > k + 1 and not self._los(f, pts[k], pts[j2]):
                    j2 -= 1
                sm.append(pts[j2]); k = j2
            sm[0] = (sx, sz) if f == sf and k == len(pts) - 1 and False else sm[0]
            out_segments.append({"floor": f, "y": f * H, "points": [[round(x, 3), round(z, 3)] for x, z in sm]})
            total += sum(math.hypot(sm[q + 1][0] - sm[q][0], sm[q + 1][1] - sm[q][1]) for q in range(len(sm) - 1))
        portal_cost = sum(p.cost for p in self.portals if False)
        total_cost = gbest[goal_s]
        return {"status": "ok", "segments": out_segments, "transitions": transitions,
                "planar_length_m": round(total, 2), "cost_m": round(total_cost, 2), "expanded": expanded,
                "accessible_only": accessible, "model": "synthetic_geometry_derived_grid",
                "validated": None}

    # ---------------------------------------------------------------- independent validation
    def validate_route(self, route, radius=None, step=0.05):
        """Re-check the polyline against raw collider AABBs (not the raster). Returns dict."""
        r = self.avatar_radius if radius is None else radius      # physical avatar radius; planner uses a larger margin
        worst = 1e9; viol = []
        for seg in route["segments"]:
            f = seg["floor"]; fy = f * H
            obs = [c for c in self.colliders if c["floor"] == f and c["kind"] in ("wall", "glass", "column", "furniture")
                   and c["max"][1] > fy + 0.35 and c["min"][1] < fy + 1.8]
            slabs = [c for c in self.colliders if c["floor"] == f and c["kind"] == "slab" and c.get("room") not in ("site", "roof")
                     and abs(c["max"][1] - fy) < 0.02]
            pts = np.array(seg["points"])
            for a, b in zip(pts[:-1], pts[1:]):
                n = max(2, int(np.linalg.norm(b - a) / step))
                P = a[None] + (b - a)[None] * np.linspace(0, 1, n)[:, None]
                for c in obs:
                    dx = np.maximum(np.maximum(c["min"][0] - P[:, 0], P[:, 0] - c["max"][0]), 0)
                    dz = np.maximum(np.maximum(c["min"][2] - P[:, 1], P[:, 1] - c["max"][2]), 0)
                    d = np.hypot(dx, dz)
                    worst = min(worst, float(d.min()))
                    if (d < r).any():
                        viol.append(c["id"])
                on = np.zeros(len(P), bool)
                for c in slabs:
                    on |= (P[:, 0] >= c["min"][0] - 1e-6) & (P[:, 0] <= c["max"][0] + 1e-6) & (P[:, 1] >= c["min"][2] - 1e-6) & (P[:, 1] <= c["max"][2] + 1e-6)
                if not on.all():
                    viol.append("off-slab")
        return {"collision_free": not viol, "min_clearance_m": round(worst, 3), "violations": sorted(set(viol)),
                "checked_radius_m": round(r, 3), "method": "independent AABB re-check of polyline, 5 cm sampling"}

    # ---------------------------------------------------------------- export for the viewer
    def export(self, path):
        out = {"resolution_m": self.res, "origin": [self.x0, self.z0], "size": [self.nx, self.nz], "avatar_radius_m": self.radius,
               "floors": [], "portals": [{"kind": p.kind, "a": list(p.a), "b": list(p.b), "cost_m": p.cost, "accessible": p.accessible} for p in self.portals],
               "stairs": [{"floor_from": st["floor_from"], "polyline": st.get("polyline")} for st in self.semantic["stairs"]],
               "provenance": "geometry-derived from collision layer of a SYNTHETIC model; not validated against a real building",
               "encoding": "base64(packbits(row-major z,x)); 1=walkable with clearance"}
        for f in range(self.n_floors):
            out["floors"].append({"floor": f, "elevation_m": f * H, "walkable_cells": int(self.clear[f].sum()),
                                  "mask": base64.b64encode(np.packbits(self.clear[f].reshape(-1)).tobytes()).decode()})
        json.dump(out, open(path, "w"), separators=(",", ":"))
        return out["floors"][0]["walkable_cells"]


def poi_point(sem, poi_id):
    """Navigation arrival point (floor, x, z) for a POI: its nav_anchor, never a room centroid."""
    p = next(p for p in sem["pois"] if p["poi_id"] == poi_id)
    a = p["nav_anchor"]
    return (p["floor"], a["x"], a["z"])
