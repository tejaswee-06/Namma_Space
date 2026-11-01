"""Procedural PBR-style textures (PNG bytes) for the synthetic demo building.

All textures are generated from seeded noise so builds are reproducible.
Each texture represents a square patch of `size_m` metres and tiles seamlessly.
"""
from __future__ import annotations
import io
import numpy as np
from PIL import Image

N = 512


def _tileable_noise(rng, octaves=5, base=4):
    out = np.zeros((N, N), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        g = base * 2 ** o
        small = rng.random((g, g)).astype(np.float32)
        # tile-safe upsample via FFT-free bicubic on wrapped array
        big = np.array(Image.fromarray((small * 255).astype(np.uint8)).resize((N, N), Image.BICUBIC), np.float32) / 255
        out += big * amp
        tot += amp
        amp *= 0.5
    return out / tot


def _png(arr: np.ndarray) -> bytes:
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    b = io.BytesIO()
    img.save(b, "PNG", optimize=True)
    return b.getvalue()


def concrete(seed=1):
    r = np.random.default_rng(seed)
    n = _tileable_noise(r, 6, 3)
    fine = r.random((N, N)).astype(np.float32) * 0.08
    v = 150 + (n - 0.5) * 70 + fine * 60
    return _png(np.stack([v, v, v * 0.98], -1))


def plaster(seed=2):
    r = np.random.default_rng(seed)
    n = _tileable_noise(r, 4, 6)
    v = 238 + (n - 0.5) * 10
    return _png(np.stack([v, v * 0.985, v * 0.955], -1))


def oak(seed=3):
    r = np.random.default_rng(seed)
    y, x = np.mgrid[0:N, 0:N].astype(np.float32)
    warp = _tileable_noise(r, 4, 2) * 14
    grain = np.sin((x * 0.11 + warp * 3.0)) * 0.5 + 0.5
    rings = np.sin((x * 0.025 + warp)) * 0.5 + 0.5
    fine = _tileable_noise(r, 5, 16)
    t = 0.45 * grain + 0.35 * rings + 0.2 * fine
    base = np.array([196, 146, 92], np.float32)
    dark = np.array([128, 84, 46], np.float32)
    img = dark[None, None] * (1 - t[..., None]) + base[None, None] * t[..., None]
    # plank seams every 128px
    seam = ((x % 128) < 2)[..., None] * 0.45
    img = img * (1 - seam)
    return _png(img)


def floor_tile(seed=4):
    r = np.random.default_rng(seed)
    n = _tileable_noise(r, 4, 8)
    y, x = np.mgrid[0:N, 0:N]
    tile = 256  # 2 tiles per patch
    seam = ((x % tile) < 3) | ((y % tile) < 3)
    v = 205 + (n - 0.5) * 26
    # subtle per-tile tone shift
    ti = ((x // tile) + 2 * (y // tile)) % 4
    v = v + (ti - 1.5) * 4
    v = np.where(seam, 120, v)
    return _png(np.stack([v, v * 0.995, v * 0.985], -1))


def carpet(seed=5):
    r = np.random.default_rng(seed)
    fine = r.random((N, N)).astype(np.float32)
    n = _tileable_noise(r, 3, 12)
    v = 80 + (fine - 0.5) * 38 + (n - 0.5) * 14
    return _png(np.stack([v * 0.78, v * 0.86, v * 1.12], -1))


def terrazzo(seed=6):
    r = np.random.default_rng(seed)
    base = np.full((N, N, 3), 214, np.float32)
    for _ in range(900):
        cx, cy = r.integers(0, N, 2)
        rad = r.integers(2, 7)
        col = r.choice([60, 110, 150, 230, 245])
        tint = r.random(3) * 20
        yy, xx = np.ogrid[:N, :N]
        m = ((xx - cx) ** 2 + (yy - cy) ** 2) < rad * rad
        base[m] = np.clip(col + tint, 0, 255)
    base += (r.random((N, N, 1)) - 0.5) * 8
    return _png(base)


def paving(seed=7):
    r = np.random.default_rng(seed)
    n = _tileable_noise(r, 5, 6)
    y, x = np.mgrid[0:N, 0:N]
    seam = ((x % 128) < 3) | (((y + 64 * ((x // 128) % 2)) % 128) < 3)
    v = 120 + (n - 0.5) * 50
    v = np.where(seam, 70, v)
    return _png(np.stack([v, v * 0.98, v * 0.95], -1))


GENERATORS = {
    "concrete": concrete, "plaster": plaster, "oak": oak, "tile": floor_tile,
    "carpet": carpet, "terrazzo": terrazzo, "paving": paving,
}


def build_all() -> dict[str, bytes]:
    return {k: f() for k, f in GENERATORS.items()}
