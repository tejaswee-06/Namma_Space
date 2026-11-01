"""Assemble the synthetic NAMMA demo building -> visual GLB, collision data, semantic manifest.

Run:  python -m reconstruction.synthetic.build_building --out assets/scenes/demo-block-a
PROVENANCE: procedural_synthetic_designed_model. NOT a scan of any real building.
"""
from __future__ import annotations
import argparse, hashlib, json, math, os
import numpy as np
from .glb_builder import Group, write_glb
from .materials import make_materials
from . import textures as tex
from .spec import *

MATS = make_materials()
WT_I = 0.15      # interior wall thickness
WT_E = 0.10      # exterior glass thickness
DOOR_H = 2.2
PT = 0.05        # finished floor thickness


class Ctx:
    def __init__(self):
        self.root = Group("NAMMA_DEMO_BLOCK_A", {"kind": "building", "id": BUILDING_ID, "synthetic": True})
        self.colliders: list[dict] = []
        self.doors: list[dict] = []
        self.lights: list[dict] = []
        self.room_specs = rooms()
        self.stairs: list[dict] = []
        self.lifts: list[dict] = []
        self._cid = 0

    def collide(self, kind, floor, mn, mx, **kw):
        self._cid += 1
        d = {"id": f"c{self._cid}", "kind": kind, "floor": floor,
             "min": [round(float(v), 3) for v in mn], "max": [round(float(v), 3) for v in mx]}
        d.update(kw)
        self.colliders.append(d)


def M(n): return MATS[n]


def box_c(ctx, g, mat, mn, mx, kind=None, floor=0, skip="", **kw):
    """Box from min/max corners; optionally registers a collider."""
    mn, mx = np.array(mn, float), np.array(mx, float)
    c = (mn + mx) / 2
    s = mx - mn
    g.box(M(mat), c, s, skip=skip)
    if kind:
        ctx.collide(kind, floor, mn, mx, **kw)


# ---------------------------------------------------------------- wall runs
def wall_run(ctx, g, axis, line, a0, a1, y0, y1, t, mat, floor, openings=(), kind="wall",
             glass=False, frame=True):
    """Wall along `axis` ('x' -> varies in x at z=line, 'z' -> varies in z at x=line).
    openings: list of (center, width, top, sill)."""
    def B(lo, hi, ya, yb, m=mat, kk=kind):
        if hi - lo < 1e-3 or yb - ya < 1e-3:
            return
        if axis == "x":
            mn, mx = (lo, ya, line - t / 2), (hi, yb, line + t / 2)
        else:
            mn, mx = (line - t / 2, ya, lo), (line + t / 2, yb, hi)
        box_c(ctx, g, m, mn, mx, kk, floor)
    ops = sorted(openings, key=lambda o: o[0])
    cur = a0
    for c, w, top, sill in ops:
        lo, hi = c - w / 2, c + w / 2
        B(cur, lo, y0, y1)
        B(lo, hi, y0 + top, y1)                   # lintel
        if sill > 0:
            B(lo, hi, y0, y0 + sill)
        cur = hi
    B(cur, a1, y0, y1)
    if glass and frame:
        # slim frame: head + sill rails + posts at ends/openings
        def F(lo, hi, ya, yb):
            if axis == "x":
                mn, mx = (lo, ya, line - 0.035), (hi, yb, line + 0.035)
            else:
                mn, mx = (line - 0.035, ya, lo), (line + 0.035, yb, hi)
            box_c(ctx, g, "frame_dark", mn, mx)
        F(a0, a1, y1 - 0.06, y1); F(a0, a1, y0, y0 + 0.05)
        posts = [a0, a1] + [x for c, w, _, _ in ops for x in (c - w / 2, c + w / 2)]
        for p in posts:
            F(p - 0.03, p + 0.03, y0, y1)


def door_assembly(ctx, g, room, floor, fy):
    """Frame + leaf for a corridor-facing door."""
    cx, w, line = room.door_x, room.door_w, room.door_z
    sgn = -1 if room.side == "N" else 1       # direction into room
    if room.kind in ("corridor",) or w <= 0:
        return
    # frame (head + jambs)
    for sx in (-1, 1):
        box_c(ctx, g, "frame_dark", (cx + sx * w / 2 - 0.03, fy, line - 0.09), (cx + sx * w / 2 + 0.03, fy + DOOR_H, line + 0.09))
    box_c(ctx, g, "frame_dark", (cx - w / 2, fy + DOOR_H - 0.05, line - 0.09), (cx + w / 2, fy + DOOR_H, line + 0.09))
    if room.door == "swing":
        leaf_w = w - 0.08
        ang = math.radians(78) * (1 if room.side == "N" else -1)
        hx = cx - w / 2 + 0.04
        c, s = math.cos(ang), math.sin(ang)
        center = (hx + c * leaf_w / 2, fy + (DOOR_H - 0.05) / 2, line + (-s * leaf_w / 2))
        g.box(M("oak"), center, (leaf_w, DOOR_H - 0.05, 0.045), rot_y=ang)
        g.box(M("metal"), (hx + c * (leaf_w - 0.1), fy + 1.0, line - s * (leaf_w - 0.1)), (0.14, 0.03, 0.05), rot_y=ang)
    elif room.door == "double":
        lw = (w - 0.08) / 2
        for sx, a in ((-1, 70), (1, -70)):
            ang = math.radians(a) * (1 if room.side == "N" else -1) * (1 if sx == -1 else 1)
            hx = cx + sx * (w / 2 - 0.04)
            c, s = math.cos(ang), math.sin(ang)
            ang_eff = ang if sx == -1 else -ang
            c, s = math.cos(ang_eff), math.sin(ang_eff)
            off = lw / 2 * (1 if sx == -1 else -1)
            center = (hx + c * off, fy + (DOOR_H - 0.05) / 2, line - s * off)
            g.box(M("oak"), center, (lw, DOOR_H - 0.05, 0.045), rot_y=ang_eff)
    elif room.door == "slide":
        for sx in (-1, 1):
            g.box(M("metal"), (cx + sx * (w / 4 + 0.22), fy + (DOOR_H - 0.05) / 2, line + 0.02 * -sgn), (w / 2 - 0.1, DOOR_H - 0.05, 0.04))
    ctx.doors.append({"room_id": room.id, "floor": floor, "x": cx, "z": line, "width": w,
                      "type": room.door, "side": room.side})


# ---------------------------------------------------------------- furniture
def local_to_world(room, u, v):
    x = room.x0 + u
    z = room.door_z - v if room.side == "N" else room.door_z + v
    return x, z


class Fur:
    """Furniture helper bound to a room group/floor."""
    def __init__(self, ctx, g, room, fy):
        self.ctx, self.g, self.room, self.fy = ctx, g, room, fy
        self.floor = room.floor
        self.du = room.door_x - room.x0
        self.dw = room.door_w
        self.skipped = 0

    def keep_out(self, u, v, hu, hv):
        """True if a footprint centred (u,v) with half-extents (hu,hv) intrudes on the door apron
        (2.2 m deep, door width + 0.7 m each side). Such items are not placed at all."""
        if self.dw <= 0:
            return False
        lo, hi = self.du - self.dw / 2 - 0.7, self.du + self.dw / 2 + 0.7
        hit = (u + hu > lo) and (u - hu < hi) and (v - hv < 2.2)
        if hit:
            self.skipped += 1
        return hit

    def W(self, u, v):
        return local_to_world(self.room, u, v)

    def block(self, mat, u, v, sx, sz, sy, y0=0.0, obstacle=True, rot=0.0):
        if obstacle and self.keep_out(u, v, sx / 2, sz / 2):
            return
        x, z = self.W(u, v)
        self.g.box(M(mat), (x, self.fy + y0 + sy / 2, z), (sx, sy, sz), rot_y=rot)
        if obstacle:
            self.ctx.collide("furniture", self.floor, (x - sx / 2, self.fy + y0, z - sz / 2),
                             (x + sx / 2, self.fy + y0 + sy, z + sz / 2), room=self.room.id)

    def decor(self, mat, u, v, sx, sz, sy, y0):
        x, z = self.W(u, v)
        self.g.box(M(mat), (x, self.fy + y0 + sy / 2, z), (sx, sy, sz))

    def chair(self, u, v, face="+z", mat="fabric_grey", obstacle=True):
        if obstacle and self.keep_out(u, v, 0.25, 0.25):
            return
        x, z = self.W(u, v)
        fx, fz = {"+x": (1, 0), "-x": (-1, 0), "+z": (0, 1), "-z": (0, -1)}[face]
        y = self.fy
        self.g.box(M(mat), (x, y + 0.45, z), (0.44, 0.06, 0.44))
        self.g.box(M(mat), (x - fx * 0.2, y + 0.72, z - fz * 0.2), (0.44 if fz else 0.05, 0.5, 0.44 if fx else 0.05))
        self.g.cylinder(M("metal"), (x, y + 0.22, z), 0.025, 0.42, 8, caps=False)
        self.g.cylinder(M("metal"), (x, y + 0.02, z), 0.22, 0.03, 10)
        if obstacle:
            self.ctx.collide("furniture", self.floor, (x - 0.25, y, z - 0.25), (x + 0.25, y + 0.95, z + 0.25), room=self.room.id)

    def stool(self, u, v, h=0.62, mat="fabric_teal"):
        if self.keep_out(u, v, 0.2, 0.2):
            return
        x, z = self.W(u, v)
        self.g.cylinder(M(mat), (x, self.fy + h, z), 0.19, 0.06, 14)
        self.g.cylinder(M("metal"), (x, self.fy + h / 2, z), 0.02, h, 8, caps=False)
        self.g.cylinder(M("metal"), (x, self.fy + 0.02, z), 0.17, 0.03, 12)
        self.ctx.collide("furniture", self.floor, (x - 0.2, self.fy, z - 0.2), (x + 0.2, self.fy + h + 0.03, z + 0.2), room=self.room.id)

    def desk(self, u, v, sx=1.6, sz=0.8, mat="oak", monitor=True, face="+z"):
        if self.keep_out(u, v, sx / 2, sz / 2):
            return
        x, z = self.W(u, v)
        y = self.fy
        self.g.box(M(mat), (x, y + 0.74, z), (sx, 0.04, sz))
        for s in (-1, 1):
            self.g.box(M("laminate"), (x + s * (sx / 2 - 0.03), y + 0.36, z), (0.04, 0.72, sz - 0.05))
        self.g.box(M("laminate"), (x, y + 0.55, z - (0.35 if face == "+z" else -0.35) * 0), (sx - 0.1, 0.35, 0.02))
        self.ctx.collide("furniture", self.floor, (x - sx / 2, y, z - sz / 2), (x + sx / 2, y + 0.78, z + sz / 2), room=self.room.id)
        if monitor:
            self.g.box(M("screen"), (x, y + 1.0, z - 0.2 * (1 if face == "+z" else -1)), (0.55, 0.32, 0.025))
            self.g.box(M("screen_glow"), (x, y + 1.0, z - 0.2 * (1 if face == "+z" else -1) + 0.014 * (1 if face == "+z" else -1)), (0.5, 0.27, 0.004))
            self.g.box(M("metal"), (x, y + 0.84, z - 0.2 * (1 if face == "+z" else -1)), (0.06, 0.16, 0.05))
            self.g.box(M("screen"), (x, y + 0.765, z + 0.12 * (1 if face == "+z" else -1)), (0.42, 0.015, 0.14))

    def plant(self, u, v, h=1.1):
        if self.keep_out(u, v, 0.22, 0.22):
            return
        x, z = self.W(u, v)
        self.g.cylinder(M("ceramic"), (x, self.fy + 0.22, z), 0.2, 0.44, 14)
        self.g.cylinder(M("soil"), (x, self.fy + 0.44, z), 0.19, 0.02, 12)
        rng = np.random.default_rng(int(abs(x * 100 + z * 10)))
        for k in range(5):
            a = rng.random() * 6.28
            r = 0.12 * rng.random()
            self.g.sphere(M("plant" if k % 2 else "plant_light"), (x + r * math.cos(a), self.fy + 0.6 + h * 0.35 * rng.random() + 0.25, z + r * math.sin(a)),
                          0.18 + 0.1 * rng.random(), 8, 5, 1.3)
        self.ctx.collide("furniture", self.floor, (x - 0.22, self.fy, z - 0.22), (x + 0.22, self.fy + 1.2, z + 0.22), room=self.room.id)

    def sofa(self, u, v, sx=2.0, sz=0.9, mat="fabric_ochre", face="+z"):
        if self.keep_out(u, v, sx / 2, sz / 2):
            return
        x, z = self.W(u, v)
        y = self.fy
        fz = 1 if face == "+z" else -1
        self.g.box(M(mat), (x, y + 0.22, z), (sx, 0.44, sz))
        self.g.box(M(mat), (x, y + 0.65, z - fz * (sz / 2 - 0.1)), (sx, 0.5, 0.2))
        for s in (-1, 1):
            self.g.box(M(mat), (x + s * (sx / 2 - 0.1), y + 0.5, z), (0.2, 0.3, sz))
        self.ctx.collide("furniture", self.floor, (x - sx / 2, y, z - sz / 2), (x + sx / 2, y + 0.9, z + sz / 2), room=self.room.id)

    def table_round(self, u, v, r=0.55, mat="oak", chairs=4):
        if self.keep_out(u, v, r + 0.45, r + 0.45):
            return
        x, z = self.W(u, v)
        self.g.cylinder(M(mat), (x, self.fy + 0.74, z), r, 0.04, 20)
        self.g.cylinder(M("metal"), (x, self.fy + 0.37, z), 0.04, 0.72, 8, caps=False)
        self.g.cylinder(M("metal"), (x, self.fy + 0.02, z), 0.3, 0.03, 14)
        self.ctx.collide("furniture", self.floor, (x - r, self.fy, z - r), (x + r, self.fy + 0.78, z + r), room=self.room.id)
        for k in range(chairs):
            a = k * 2 * math.pi / chairs + 0.4
            cu, cv = u + (r + 0.38) * math.cos(a), v + (r + 0.38) * math.sin(a)
            self.chair(cu, cv, face="+x", mat=["fabric_teal", "fabric_ochre", "fabric_grey"][k % 3], obstacle=True)


def floor_finish_mat(room): return room.floor_mat


def furnish(ctx, g, room, fy):
    F = Fur(ctx, g, room, fy)
    w = room.x1 - room.x0
    D = 8.2
    k = room.kind
    if k == "lab":
        rows = [(3.1, 1.0), (5.6, 1.0)]
        cols = max(2, int((w - 1.6) // 3.0))
        for r_i, (v, _) in enumerate(rows):
            for c in range(cols):
                u = 1.8 + c * ((w - 3.0) / max(cols - 1, 1)) if cols > 1 else w / 2
                F.block("bench_top", u, v, 2.2, 0.95, 0.06, 0.84)
                for s in (-1, 1):
                    F.decor("metal", u + s * 1.05, v, 0.06, 0.85, 0.84, 0.0)
                F.decor("metal", u, v, 2.1, 0.03, 0.2, 0.62)
                F.decor("bench_top", u, v + 0.3, 0.8, 0.4, 0.28, 0.9)           # scope body
                F.decor("screen_glow", u, v + 0.3 - 0.2, 0.55, 0.01, 0.2, 0.94)
                F.decor("laminate", u + 0.8, v - 0.1, 0.35, 0.3, 0.12, 0.9)
                F.stool(u - 0.55, v - 0.8)
                F.stool(u + 0.55, v - 0.8)
                # collider for whole bench footprint
        F.block("laminate", w / 2, D, w - 3, 0.55, 2.0, 0.0)
        F.decor("whiteboard", 0.1, 3.5, 0.03, 3.0, 1.2, 1.0)
    elif k == "computerlab":
        for r_i, v in enumerate((2.8, 4.9, 7.0)):
            for c in range(3):
                u = 1.8 + c * 3.4
                F.desk(u, v, 2.4, 0.8, "laminate", monitor=False)
                for m in (-0.6, 0.6):
                    F.decor("screen", u + m, v + 0.2, 0.55, 0.03, 0.32, 0.95)
                    F.decor("screen_glow", u + m, v + 0.18, 0.5, 0.004, 0.27, 0.97)
                    F.decor("metal", u + m, v + 0.2, 0.06, 0.05, 0.16, 0.78)
                F.chair(u - 0.6, v - 0.75, "+z", "fabric_blue"); F.chair(u + 0.6, v - 0.75, "+z", "fabric_blue")
        F.decor("projection", w / 2, D + 0.05, 3.0, 0.03, 1.6, 1.2)
    elif k == "office":
        n = max(2, int(w // 3.0))
        for c in range(n):
            u = 1.6 + c * ((w - 3.2) / max(n - 1, 1))
            F.desk(u, 6.4, 1.6, 0.8, "oak", True, face="-z" if False else "+z")
            F.chair(u, 5.4, "+z", "leather")
        F.block("oak", w - 0.5, 3.0, 0.45, 1.4, 1.9, 0.0)
        F.block("oak", w - 0.5, 4.7, 0.45, 0.9, 1.9, 0.0)
        F.table_round(2.0, 2.6, 0.5, "oak", 3)
        F.plant(0.5, 7.7)
        F.plant(w - 0.5, 7.7)
    elif k == "conference":
        F.block("oak", w / 2, 4.2, 6.4, 1.5, 0.05, 0.72, obstacle=False)
        F.block("metal", w / 2, 4.2, 0.4, 1.0, 0.7, 0.0, obstacle=False)
        xa, za = local_to_world(room, w / 2 - 3.2, 4.2 - 0.75)
        xb, zb = local_to_world(room, w / 2 + 3.2, 4.2 + 0.75)
        ctx.collide("furniture", room.floor, (min(xa, xb), fy, min(za, zb)), (max(xa, xb), fy + 0.78, max(za, zb)), room=room.id)
        for i in range(6):
            u = w / 2 - 2.5 + i * 1.0
            F.chair(u, 5.25 if True else 0, "-z" if room.side == "S" else "+z", "leather", True)
            F.chair(u, 3.15, "+z" if room.side == "S" else "-z", "leather", True)
        F.decor("screen", w / 2, D + 0.05, 2.4, 0.04, 1.35, 0.9)
        F.decor("screen_glow", w / 2, D + 0.02, 2.3, 0.006, 1.25, 0.95)
        F.block("oak", w / 2, D - 0.2, 3.0, 0.45, 0.8, 0.0)
        F.plant(0.5, 7.6)
    elif k == "seminar":
        for r, v in enumerate((1.9, 2.9, 3.9, 4.9, 5.9)):
            for c in range(10):
                u = 1.2 + c * 1.1 + (0.9 if c >= 5 else 0)
                F.chair(u, v, "+z", "fabric_teal" if (r + c) % 3 else "fabric_ochre")
            F.decor("oak", w / 2, v + 0.18, w - 1.4, 0.22, 0.04, 0.74)
        F.block("oak", w / 2, 7.4, 1.4, 0.7, 1.05, 0.0)
        F.decor("projection", w / 2, 8.05, 5.5, 0.03, 2.6, 0.7)
        for i in range(8):
            F.decor("oak_dark", i * 1.7 + 0.9, 8.1, 0.12, 0.04, 2.9, 0.4)
    elif k == "lobby":
        F.block("oak", 7.0, 6.2, 4.2, 0.9, 1.1, 0.0)
        F.decor("terrazzo", 7.0, 6.2, 4.3, 1.0, 0.05, 1.1)
        F.decor("sign_blue", 7.0, 6.7, 2.4, 0.03, 0.18, 1.45)
        F.chair(6.2, 7.3, "-z", "leather"); F.chair(7.8, 7.3, "-z", "leather")
        F.sofa(2.2, 3.0, 2.0, 0.9, "fabric_ochre", "-z"); F.sofa(11.2, 3.0, 2.0, 0.9, "fabric_teal", "-z")
        F.block("oak", 2.2, 4.4, 1.0, 0.6, 0.38, 0.0)
        F.decor("rug", 7.0, 3.2, 3.6, 2.2, 0.01, 0.0)
        F.plant(0.5, 7.6); F.plant(13.4, 7.6); F.plant(0.5, 1.0, 1.4); F.plant(13.4, 1.0, 1.4)
        F.block("metal", 11.5, 6.4, 0.5, 0.35, 1.3, 0.0)           # info kiosk
        F.decor("screen_glow", 11.5, 6.22, 0.42, 0.01, 0.55, 0.6)
    elif k == "commons":
        for i, (u, v) in enumerate([(2.2, 2.2), (5.2, 2.2), (8.2, 2.2), (2.2, 5.0), (5.2, 5.0), (8.2, 5.0), (11.2, 3.2), (13.4, 5.6)]):
            F.table_round(u, v, 0.55, "oak", 4)
        F.block("oak", 13.2, 7.4, 4.2, 0.8, 1.05, 0.0)
        F.decor("terrazzo", 13.2, 7.4, 4.3, 0.9, 0.05, 1.05)
        for i in range(4):
            F.stool(11.8 + i * 0.85, 6.7, 0.72, "fabric_ochre")
        F.decor("sign_amber", 13.2, 7.9, 2.0, 0.03, 0.2, 2.0)
        F.block("metal", 15.2, 3.2, 0.9, 0.8, 1.9, 0.0)             # vending
        F.decor("screen_glow", 15.2 - 0.0, 3.2 - 0.41, 0.6, 0.01, 1.1, 0.5)
        F.plant(0.5, 7.7); F.plant(15.6, 7.7, 1.5)
    elif k == "helpdesk":
        F.desk(w / 2, 6.0, 2.4, 0.9, "oak", True)
        F.chair(w / 2, 5.0, "+z", "leather")
        F.block("oak", w - 0.4, 3.0, 0.45, 1.6, 1.9, 0.0)
        F.sofa(1.4, 2.4, 1.6, 0.8, "fabric_grey", "-z")
        F.plant(0.5, 7.5)
    elif k == "library":
        for c, u in enumerate((2.0, 4.4, 6.8, 9.2)):
            F.block("oak_dark", u, 6.2, 0.45, 4.4, 2.2, 0.0)
            for s in range(5):
                F.decor(["book_a", "book_b", "book_c"][s % 3], u, 6.2, 0.43, 4.2, 0.05, 0.4 + s * 0.4)
        for u, v in ((12.0, 2.6), (12.0, 5.6)):
            F.desk(u, v, 2.0, 1.0, "oak", False)
            F.chair(u - 0.5, v - 0.9, "+z", "fabric_blue"); F.chair(u + 0.5, v - 0.9, "+z", "fabric_blue")
        F.sofa(12.4, 7.4, 1.8, 0.8, "fabric_ochre", "-z")
        F.plant(0.5, 7.7); F.plant(13.4, 0.8)
    elif k == "lounge":
        F.sofa(2.0, 6.5, 2.2, 0.95, "fabric_teal", "-z"); F.sofa(5.3, 4.6, 2.0, 0.95, "fabric_ochre", "+z")
        F.block("oak", 3.5, 5.6, 1.2, 0.7, 0.4, 0.0)
        F.decor("rug", 3.6, 5.6, 4.0, 2.6, 0.01, 0.0)
        F.plant(0.5, 7.6, 1.6); F.plant(7.4, 7.6, 1.4); F.plant(7.4, 1.0, 1.4)
    elif k == "wc":
        for s in range(2):
            u = 0.5 + s * 0.9
            F.block("laminate", u + 0.0, 7.6, 0.9, 0.04, 1.9, 0.0, obstacle=True)
        F.block("laminate", 0.04, 6.6, 0.04, 2.0, 1.9, 0.0)
        F.block("laminate", 1.96, 6.6, 0.04, 2.0, 1.9, 0.0)
        for s in range(2):
            F.decor("ceramic", 0.5 + s * 1.0, 7.7, 0.4, 0.55, 0.4, 0.0)
        F.block("ceramic", 0.3, 3.5, 0.5, 1.6, 0.2, 0.8)
        F.decor("metal", 0.3, 3.5, 0.04, 0.04, 0.28, 1.0)
        F.decor("metal", 0.05, 3.5, 0.02, 1.4, 0.9, 1.2)
    elif k == "stair":
        pass


# ---------------------------------------------------------------- stairs
STAIR = {"ax0": 14.3, "ax1": 15.9, "bx0": 16.1, "bx1": 17.7, "z_start": 7.6, "z_land0": 3.8, "z_land1": 4.8, "riser": 0.18, "tread": 0.28, "n": 10}


def build_stairs(ctx, fg, f):
    fy = f * H
    S = STAIR
    g = fg.child(f"STAIRS_F{f}", {"kind": "stairs", "floor": f, "synthetic": True})
    if f >= FLOORS - 1:
        return
    for k in range(1, S["n"] + 1):
        z_hi = S["z_start"] - S["tread"] * (k - 1)
        z_lo = z_hi - S["tread"]
        top = fy + S["riser"] * k
        box_c(ctx, g, "concrete", (S["ax0"], fy, z_lo), (S["ax1"], top, z_hi), "step", f)
    box_c(ctx, g, "concrete", (S["ax0"], fy, S["z_land0"]), (S["bx1"], fy + 1.8, S["z_land1"]), "step", f)
    for k in range(1, S["n"] + 1):
        z_lo = S["z_land1"] + S["tread"] * (k - 1)
        z_hi = z_lo + S["tread"]
        top = fy + 1.8 + S["riser"] * k
        box_c(ctx, g, "concrete", (S["bx0"], fy, z_lo), (S["bx1"], top, z_hi), "step", f)
    # handrails (visual)
    g.box(M("frame_dark"), (S["ax0"] - 0.03, fy + 0.9 + 0.9, 6.2), (0.04, 0.04, 2.9))
    g.box(M("frame_dark"), (S["bx1"] + 0.03, fy + 2.7 + 0.9, 6.2), (0.04, 0.04, 2.9))
    for k in range(0, 10, 3):
        z = S["z_start"] - S["tread"] * k
        g.box(M("frame_dark"), (S["ax0"] - 0.03, fy + S["riser"] * k + 0.45, z), (0.03, 0.9, 0.03))
        z2 = S["z_land1"] + S["tread"] * k
        g.box(M("frame_dark"), (S["bx1"] + 0.03, fy + 1.8 + S["riser"] * k + 0.45, z2), (0.03, 0.9, 0.03))
    ctx.stairs.append({"floor_from": f, "floor_to": f + 1,
                       "bottom_node": [15.1, fy, 8.1], "top_node": [16.9, fy + H, 8.1],
                       "path_length_m_approx": 9.5, "accessible": False,
                       "polyline": [[15.1, fy, 7.9], [15.1, fy + 1.8, 3.9], [16.0, fy + 1.8, 4.3], [16.9, fy + 1.8, 4.9], [16.9, fy + H, 7.6], [16.9, fy + H, 8.1]],
                       "note": "Two-flight half-landing stair; path_length is an approximation of the walked length."})


# ---------------------------------------------------------------- floors
def build_floor(ctx, f):
    fy = f * H
    fg = ctx.root.child(f"FLOOR_{f+1:02d}", {"kind": "floor", "floor": f, "id": f"floor-{f}", "elevation": fy,
                                                "name": ["Ground Floor", "First Floor", "Second Floor"][f]})
    struct = fg.child(f"STRUCTURE_F{f}", {"kind": "structure", "floor": f})
    rooms_g = fg.child(f"ROOMS_F{f}", {"kind": "rooms", "floor": f})
    walls_g = fg.child(f"WALLS_F{f}", {"kind": "walls", "floor": f})
    doors_g = fg.child(f"DOORS_F{f}", {"kind": "doors", "floor": f})
    glaz_g = fg.child(f"WINDOWS_F{f}", {"kind": "windows", "floor": f})
    fur_g = fg.child(f"FURNITURE_F{f}", {"kind": "furniture", "floor": f})
    light_g = fg.child(f"LIGHTING_F{f}", {"kind": "lighting", "floor": f})
    sign_g = fg.child(f"SIGNAGE_F{f}", {"kind": "signage", "floor": f})
    rs = [r for r in ctx.room_specs if r.floor == f]
    wall_h0, wall_h1 = fy, fy + H - SLAB                 # clear height between finished floor and slab soffit

    # ---- slabs (per-room finish + structural body) ----
    for r in rs:
        rg = rooms_g.child(f"ROOM_{r.id}", {"kind": "room", "id": r.id, "floor": f, "name": r.name, "category": r.category})
        x0, x1, z0, z1 = r.x0, r.x1, r.z0, r.z1
        if r.kind == "lift":
            pass
        pieces = [(x0, x1, z0, z1)]
        if r.kind == "stair" and f > 0:
            # hole for stairs arriving from below
            hx0, hx1, hz0, hz1 = 14.2, 17.8, 3.6, 7.6
            pieces = [(x0, x1, z0, hz0), (x0, x1, hz1, z1), (x0, hx0, hz0, hz1), (hx1, x1, hz0, hz1)]
        for (a, b, c, d) in pieces:
            if b - a < 1e-3 or d - c < 1e-3:
                continue
            box_c(ctx, rg, r.floor_mat, (a, fy - PT, c), (b, fy, d), "slab", f, room=r.id, skip="-y")
            box_c(ctx, struct, "concrete", (a, fy - SLAB, c), (b, fy - PT, d), None, f)
            ctx.collide("slab", f, (a, fy - SLAB, c), (b, fy, d), room=r.id)
    # remove duplicate colliders registered by box_c for finish layers (keep one slab collider per piece)
    ctx.colliders = [c for c in ctx.colliders if not (c["kind"] == "slab" and c["floor"] == f and c["max"][1] - c["min"][1] < 0.06)]

    # ---- exterior walls: spandrel + glazing + mullions ----
    ex = glaz_g
    spandrel_y0, spandrel_y1 = fy - SLAB, fy + 0.2
    gy0, gy1 = spandrel_y1, fy + H - SLAB
    ent_open = (7.0, 2.6, 2.4, 0.0) if f == 0 else None
    exit_open = (10.0, 1.6, 2.2, 0.0) if f == 0 else None
    # south (z=LEN_Z)
    for (axis, line, a0, a1, openings, nm) in (
        ("x", LEN_Z, 0, LEN_X, [ent_open] if ent_open else [], "S"),
        ("x", 0.0, 0, LEN_X, [], "N"),
        ("z", 0.0, 0, LEN_Z, [], "W"),
        ("z", LEN_X, 0, LEN_Z, [exit_open] if exit_open else [], "E"),
    ):
        # spandrel (concrete) band
        wall_run(ctx, struct, axis, line, a0, a1, spandrel_y0, spandrel_y1, 0.32, "concrete", f, (), "wall")
        # glazing
        wall_run(ctx, ex, axis, line, a0, a1, gy0, gy1, WT_E, "glass", f, openings, "glass", glass=True)
        # mullions every 3 m
        n = int((a1 - a0) / 3.0) + 1
        for i in range(n + 1):
            p = a0 + i * 3.0
            if p > a1 + 1e-6:
                continue
            if any(abs(p - o[0]) < o[1] / 2 + 0.05 for o in openings):
                continue
            if axis == "x":
                mn, mx = (p - 0.045, gy0, line - 0.07), (p + 0.045, gy1, line + 0.07)
            else:
                mn, mx = (line - 0.07, gy0, p - 0.045), (line + 0.07, gy1, p + 0.045)
            box_c(ctx, ex, "frame_dark", mn, mx, "column" if (p % 6 == 0) else None, f)
        # horizontal transom at 2.4m
        wall_run(ctx, ex, axis, line, a0, a1, fy + 2.4 - 0.025, fy + 2.4 + 0.025, 0.12, "frame_dark", f, [(o[0], o[1], 99, 0) for o in openings] if False else (), "wall", False)
    # corner columns & structural columns every 6m on N and S lines
    for x in np.arange(0, LEN_X + 0.1, 6.0):
        for z in (0.0, LEN_Z):
            box_c(ctx, struct, "concrete", (x - 0.22, fy, z - 0.22), (x + 0.22, fy + H - SLAB, z + 0.22), "column", f)

    # ---- interior walls ----
    for rside, zc0, zc1 in (("N", 0.0, COR_Z0), ("S", COR_Z1, LEN_Z)):
        # partitions come ONLY from this band's own room boundaries (a boundary on the other side of
        # the corridor must never cut through a room here)
        band = [r for r in rs if r.kind != "corridor" and r.side == rside]
        x_cuts = sorted({0.0, LEN_X} | {r.x0 for r in band} | {r.x1 for r in band})
        for x in x_cuts:
            if x <= 0.0 or x >= LEN_X:
                continue
            wg = walls_g.child(f"WALL_F{f}_{rside}_X{x:g}", {"kind": "wall", "floor": f})
            wall_run(ctx, wg, "z", x, zc0 + 0.0, zc1, wall_h0, wall_h1, WT_I, "plaster_warm", f)
    # lift riser separation + lift car walls
    wg = walls_g.child(f"WALL_F{f}_LIFT_RISER", {"kind": "wall", "floor": f})
    wall_run(ctx, wg, "x", 6.4, 18.0, 20.0, wall_h0, wall_h1, WT_I, "concrete", f)

    # corridor facing walls with doors
    for r in rs:
        if r.kind == "corridor":
            continue
        line = r.door_z
        wg = walls_g.child(f"WALL_{r.id}_FRONT", {"kind": "wall", "floor": f, "room": r.id})
        ops = [(r.door_x, r.door_w, DOOR_H, 0.0)]
        if r.front == "glass":
            wall_run(ctx, wg, "x", line, r.x0, r.x1, wall_h0, wall_h1, 0.08, "glass", f, ops, "glass", glass=True)
        else:
            wall_run(ctx, wg, "x", line, r.x0, r.x1, wall_h0, wall_h1, WT_I, "plaster_warm", f, ops)
        dg = doors_g.child(f"DOOR_{r.id}", {"kind": "door", "id": f"door-{r.id}", "room": r.id, "floor": f})
        door_assembly(ctx, dg, r, f, fy)
        # accent signage plate above door in corridor
        sx = r.door_x
        sz = line + (0.12 if r.side == "S" else -0.12) * -1 if False else line + (-0.1 if r.side == "N" else 0.1) * -1
        # plate on corridor side of the wall
        zc = line + (0.09 if r.side == "N" else -0.09)
        sign_g.box(M("sign_blue" if r.category != "Washroom" else "sign_amber"), (sx, fy + 2.45, zc), (0.9, 0.2, 0.03))

    # ---- furniture & fixtures ----
    for r in rs:
        fg_r = fur_g.child(f"FURN_{r.id}", {"kind": "furniture_group", "room": r.id, "floor": f})
        furnish(ctx, fg_r, r, fy)
        if r.kind == "lift":
            lg = fg_r
            # lift car: back wall, panels, control
            lg.box(M("metal"), (19.0, fy + 1.1, 6.52), (1.8, 2.2, 0.05))
            for sx in (-1, 1):
                lg.box(M("metal"), (19.0 + sx * 0.88, fy + 1.1, 7.45), (0.05, 2.2, 1.9))
            lg.box(M("led"), (19.0, fy + 2.17, 7.45), (1.6, 0.03, 1.5))
            lg.box(M("sign_blue"), (19.7, fy + 1.1, 7.5), (0.03, 0.3, 0.12))
            ctx.lifts.append({"floor": f, "x": 19.0, "z": 7.5, "y": fy})
    # corridor: planters & wall lights & signage
    cor = [r for r in rs if r.kind == "corridor"][0]
    Fc = Fur(ctx, fur_g.child(f"FURN_{cor.id}", {"kind": "furniture_group", "room": cor.id, "floor": f}), cor, fy)
    Fc.plant(0.6, 1.4 - 0.2, 1.4) if False else None
    for (px, pz) in ((0.7, 10.0), (35.3, 10.0)):
        x, z = px, pz
        Fc.g.cylinder(M("ceramic"), (x, fy + 0.25, z), 0.25, 0.5, 14)
        Fc.g.sphere(M("plant"), (x, fy + 0.95, z), 0.4, 8, 5, 1.4)
        ctx.collide("furniture", f, (x - 0.27, fy, z - 0.27), (x + 0.27, fy + 1.6, z + 0.27), room=cor.id)
    # benches in corridor niche
    for bx in (2.5, 26.5):
        Fc.g.box(M("oak"), (bx, fy + 0.42, 11.08), (1.8, 0.06, 0.4))
        Fc.g.box(M("metal"), (bx - 0.8, fy + 0.2, 11.08), (0.05, 0.4, 0.36)); Fc.g.box(M("metal"), (bx + 0.8, fy + 0.2, 11.08), (0.05, 0.4, 0.36))
        ctx.collide("furniture", f, (bx - 0.9, fy, 10.88), (bx + 0.9, fy + 0.45, 11.28), room=cor.id)

    # ---- ceiling lighting panels (emissive) + light list ----
    for r in rs:
        if r.kind in ("lift",):
            continue
        cx = (r.x0 + r.x1) / 2
        cz = (r.z0 + r.z1) / 2
        nx = max(1, int((r.x1 - r.x0) // 3.2))
        nz = 1 if r.kind == "corridor" else max(1, int((r.z1 - r.z0) // 3.5))
        for i in range(nx):
            for j in range(nz):
                px = r.x0 + (i + 0.5) * (r.x1 - r.x0) / nx
                pz = r.z0 + (j + 0.5) * (r.z1 - r.z0) / nz
                sx, sz = (1.4, 0.35) if r.kind == "corridor" else (1.0, 0.6)
                light_g.box(M("led"), (px, fy + H - SLAB - 0.015, pz), (sx, 0.03, sz))
        area = (r.x1 - r.x0) * (r.z1 - r.z0)
        if r.kind == "corridor":
            for lx in (5, 12, 18, 24, 31):
                ctx.lights.append({"floor": f, "room": r.id, "position": [lx, fy + 2.9, 10.0], "intensity": 3.0, "range": 8.0})
        else:
            ctx.lights.append({"floor": f, "room": r.id, "position": [round(cx, 2), round(fy + 2.9, 2), round(cz, 2)],
                               "intensity": round(min(6.0, 1.5 + area / 25), 2), "range": round(max(r.x1 - r.x0, r.z1 - r.z0) * 0.9, 1)})

    # ---- stairs ----
    build_stairs(ctx, fg, f)
    # stair room: floor-level landing platform strip so door arrival is flush
    # (covered by slab pieces above)

    # entrance canopy & steps on ground floor
    if f == 0:
        cg = fg.child("ENTRANCE_CANOPY", {"kind": "canopy", "floor": 0})
        box_c(ctx, cg, "concrete", (4.6, 3.05, LEN_Z - 0.2), (9.4, 3.3, LEN_Z + 2.6), "wall", 0)
        cg.box(M("led"), (7.0, 3.03, LEN_Z + 1.4), (3.6, 0.02, 1.6))
        for sx in (4.7, 9.3):
            cg.box(M("metal"), (sx, 1.5, LEN_Z + 2.45), (0.1, 3.0, 0.1))
        cg.box(M("sign_blue"), (7.0, 3.55, LEN_Z + 2.6), (3.8, 0.4, 0.05))
        sign_g.box(M("sign_blue"), (7.0, 3.55, LEN_Z + 2.6), (3.0, 0.26, 0.06))


def build_site_and_roof(ctx):
    site = ctx.root.child("SITE", {"kind": "site"})
    box_c(ctx, site, "paving", (-5, -0.35, -4), (41, -0.05, 27), None, 0, skip="")
    ctx.collide("slab", 0, (-5, -0.35, -4), (41, -0.05, 27), room="site")
    # lawns
    for (a, b) in (((-5, -4), (41, -1.2)), ((-5, -1.2), (-1.5, 27))):
        site.box(M("grass"), ((a[0] + b[0]) / 2, -0.04, (a[1] + b[1]) / 2), (b[0] - a[0], 0.02, b[1] - a[1]))
    # trees
    rng = np.random.default_rng(7)
    for tx, tz in ((-3, 6), (-3, 15), (39, 3), (39, 17), (12, 24), (26, 24), (-3, 24)):
        site.cylinder(M("trunk"), (tx, 1.4, tz), 0.16, 2.8, 8)
        for k in range(4):
            site.sphere(M("plant" if k % 2 else "plant_light"), (tx + rng.normal(0, .5), 3.6 + k * 0.45, tz + rng.normal(0, .5)), 1.5 - k * 0.2, 10, 7)
    # outdoor benches
    for bx in (16.0, 24.0):
        site.box(M("oak"), (bx, 0.42, 22.5), (2.0, 0.06, 0.45))
    # roof
    roof = ctx.root.child("ROOF", {"kind": "roof", "floor": FLOORS})
    ry = FLOORS * H
    box_c(ctx, roof, "concrete", (-0.6, ry - SLAB, -0.6), (LEN_X + 0.6, ry, LEN_Z + 0.6), "slab", FLOORS - 1, room="roof")
    roof.box(M("roof"), ((LEN_X) / 2, ry + 0.02, LEN_Z / 2), (LEN_X + 1.0, 0.04, LEN_Z + 1.0))
    for (a, b) in (((-0.6, -0.6), (LEN_X + 0.6, -0.3)), ((-0.6, LEN_Z + 0.3), (LEN_X + 0.6, LEN_Z + 0.6)),
                   ((-0.6, -0.3), (-0.3, LEN_Z + 0.3)), ((LEN_X + 0.3, -0.3), (LEN_X + 0.6, LEN_Z + 0.3))):
        box_c(ctx, roof, "concrete", (a[0], ry, a[1]), (b[0], ry + 0.9, b[1]), "wall", FLOORS - 1)
    box_c(ctx, roof, "concrete", (14.0, ry, 0.0), (20.0, ry + 2.7, 8.6), "wall", FLOORS - 1)    # stair/lift overrun
    roof.box(M("frame_dark"), (17.0, ry + 2.75, 4.3), (6.2, 0.1, 8.8))
    for i in range(6):
        for j in range(3):
            roof.box(M("solar"), (24.5 + i * 1.8, ry + 0.55, 3.0 + j * 2.4), (1.6, 0.05, 2.0))
            for s in (-0.7, 0.7):
                roof.box(M("metal"), (24.5 + i * 1.8, ry + 0.27, 3.0 + j * 2.4 + s), (0.05, 0.5, 0.05))
    for i in range(3):
        roof.box(M("metal"), (4 + i * 3.0, ry + 0.7, 14.0), (2.0, 1.4, 1.4))
        roof.cylinder(M("frame_dark"), (4 + i * 3.0, ry + 1.45, 14.0), 0.5, 0.1, 16)


def build_facade_fins(ctx):
    for f in range(FLOORS):
        fy = f * H
        fg = ctx.root.child(f"FACADE_FINS_F{f}", {"kind": "facade_fins", "floor": f})
        for i in range(0, 24):
            x = 0.75 + i * 1.5
            if f == 0 and 4.4 < x < 9.6:
                continue
            fg.box(M("oak"), (x, fy + (H - SLAB) / 2 + 0.2, LEN_Z + 0.35), (0.06, H - SLAB - 0.4, 0.38))


def nav_anchor(r):
    """Where a person stands to 'arrive' at a room: just inside its door, on the kept-clear apron."""
    y = r.floor * H
    if r.kind == "corridor":
        return {"x": 18.0, "y": y, "z": 10.0}
    inward = -1 if r.side == "N" else 1
    d = 0.5 if r.kind == "stair" else 1.3
    return {"x": round(r.door_x, 2), "y": y, "z": round(r.door_z + inward * d, 2)}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    ctx = Ctx()
    for f in range(FLOORS):
        build_floor(ctx, f)
    build_site_and_roof(ctx)
    build_facade_fins(ctx)
    textures = tex.build_all()
    visual = os.path.join(out_dir, "visual.glb")
    info = write_glb(visual, ctx.root, MATS, textures, {
        "provenance": "procedural_synthetic_designed_model", "is_real_site_capture": False,
        "scene_version": SCENE_VERSION, "coordinate_system": "building-local-y-up-v1", "units": "metres"})

    # collision GLB (box-only)
    cg = Group("COLLISION", {"kind": "collision", "synthetic": True})
    for c in ctx.colliders:
        if c["kind"] in ("slab", "step"):
            continue
        g = cg.child(f"{c['kind']}_{c['id']}", {"kind": c["kind"], "floor": c["floor"]})
        mn, mx = np.array(c["min"]), np.array(c["max"])
        g.box(MATS["frame_dark"], (mn + mx) / 2, mx - mn)
    collision = os.path.join(out_dir, "collision.glb")
    cinfo = write_glb(collision, cg, {"frame_dark": MATS["frame_dark"]}, {}, {"provenance": "derived_from_visual_model"})
    json.dump({"units": "metres", "up": "Y", "colliders": ctx.colliders, "step_up_max_m": 0.35,
               "note": "kind slab/step = walkable top surfaces; others block horizontal motion between y+0.35 and y+1.7"},
              open(os.path.join(out_dir, "colliders.json"), "w"), separators=(",", ":"))

    # semantic layer
    sem_rooms = []
    for r in ctx.room_specs:
        sem_rooms.append({
            "id": r.id, "name": r.name, "floor": r.floor, "category": r.category, "kind": r.kind, "aliases": r.aliases,
            "description": r.desc or f"{r.name} on the {['ground','first','second'][r.floor]} floor.",
            "bounds": {"x0": r.x0, "x1": r.x1, "z0": r.z0, "z1": r.z1},
            "area_m2": round((r.x1 - r.x0) * (r.z1 - r.z0), 1),
            "door": {"x": r.door_x, "z": r.door_z, "width": r.door_w, "type": r.door} if r.door_w > 0 else None,
            "anchor": {"x": round((r.x0 + r.x1) / 2, 2), "y": r.floor * H, "z": round((r.z0 + r.z1) / 2, 2)},
            "entry_anchor": {"x": r.door_x, "y": r.floor * H, "z": r.door_z + (-0.9 if r.side == "N" else 0.9) * (0 if r.kind == "corridor" else -1)},
            "accessible": r.kind not in ("stair",),
            "nav_anchor": nav_anchor(r),
            "source": "designed_synthetic",
        })
    pois = []
    for r in ctx.room_specs:
        if r.kind in ("corridor",):
            continue
        pois.append({"poi_id": f"poi-{r.id}", "room_id": r.id, "name": r.name, "aliases": r.aliases, "category": r.category,
                     "floor": r.floor, "anchor": next(s for s in sem_rooms if s["id"] == r.id)["anchor"],
                     "nav_anchor": nav_anchor(r),
                     "description": r.desc or "", "source": "designed_synthetic", "verified": False})
    pois.append({"poi_id": "poi-main-entrance", "room_id": "f0-lobby", "name": "Main Entrance", "aliases": ["entry", "front door", "gate", "entrance"],
                 "category": "Entrance", "floor": 0, "anchor": {"x": 7.0, "y": 0.0, "z": 19.2}, "nav_anchor": {"x": 7.0, "y": 0.0, "z": 19.2}, "description": "Glazed main entrance on the south facade.",
                 "source": "designed_synthetic", "verified": False})
    pois.append({"poi_id": "poi-emergency-exit", "room_id": "f0-corridor", "name": "Emergency Exit (East)", "aliases": ["fire exit", "exit", "emergency exit"],
                 "category": "Exit", "floor": 0, "anchor": {"x": 35.2, "y": 0.0, "z": 10.0}, "nav_anchor": {"x": 35.2, "y": 0.0, "z": 10.0}, "description": "East-end corridor exit.",
                 "source": "designed_synthetic", "verified": False})
    floors = [{"id": f"floor-{f}", "level": f, "name": ["Ground Floor", "First Floor", "Second Floor"][f],
               "elevation_m": f * H, "ceiling_height_m": H - SLAB} for f in range(FLOORS)]
    semantic = {"building": {"id": BUILDING_ID, "name": "NAMMA Demo Block A (synthetic)", "floors": floors,
                              "footprint": {"x": [0, LEN_X], "z": [0, LEN_Z]}},
                "rooms": sem_rooms, "pois": pois, "doors": ctx.doors, "stairs": ctx.stairs, "lifts": ctx.lifts, "lights": ctx.lights}
    json.dump(semantic, open(os.path.join(out_dir, "semantic.json"), "w"), indent=1)

    from reconstruction.navigation_geometry.navgrid import NavMap
    NavMap(out_dir).export(os.path.join(out_dir, "navgrid.json"))
    stats = {"visual": info, "collision": cinfo, "colliders": len(ctx.colliders), "rooms": len(sem_rooms), "pois": len(pois),
             "lights": len(ctx.lights)}
    json.dump(stats, open(os.path.join(out_dir, "build_stats.json"), "w"), indent=1)
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assets/scenes/demo-block-a")
    a = ap.parse_args()
    print(json.dumps(build(a.out), indent=1))
