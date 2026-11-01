/* NAMMA TWIN viewer: walkability, A* routing (fail-closed), independent route validation, search. */
const AVATAR_R = 0.25;
class Heap {
  constructor() { this.k = []; this.v = []; this.g = []; }
  get size() { return this.k.length; }
  push(key, val, g) { const k = this.k, v = this.v, gg = this.g; let i = k.length; k.push(key); v.push(val); gg.push(g); while (i > 0) { const p = (i - 1) >> 1; if (k[p] <= key) break; k[i] = k[p]; v[i] = v[p]; gg[i] = gg[p]; i = p; } k[i] = key; v[i] = val; gg[i] = g; }
  pop() { const k = this.k, v = this.v, gg = this.g, top = v[0], tg = gg[0], lk = k.pop(), lv = v.pop(), lg = gg.pop(); const n = k.length; if (n) { let i = 0; for (;;) { let c = 2 * i + 1; if (c >= n) break; if (c + 1 < n && k[c + 1] < k[c]) c++; if (k[c] >= lk) break; k[i] = k[c]; v[i] = v[c]; gg[i] = gg[c]; i = c; } k[i] = lk; v[i] = lv; gg[i] = lg; } this.lastG = tg; return top; }
}

class Nav {
  constructor(D) {
    const N = D.nav; this.D = D; this.res = N.resolution_m; this.x0 = N.origin[0]; this.z0 = N.origin[1]; this.nx = N.size[0]; this.nz = N.size[1];
    this.nf = N.floors.length; this.NN = this.nx * this.nz; this.portals = N.portals; this.stairs = N.stairs; this.rooms = D.semantic.rooms;
    this.clear = N.floors.map(fl => { const bits = b64ToU8(fl.mask), a = new Uint8Array(this.NN); for (let i = 0; i < this.NN; i++) a[i] = (bits[i >> 3] >> (7 - (i & 7))) & 1; return a; });
    this.obst = []; for (let f = 0; f < this.nf; f++) { const fy = f * H_FLOOR; this.obst.push(D.colliders.filter(c => c.floor === f && (c.kind === 'wall' || c.kind === 'glass' || c.kind === 'column' || c.kind === 'furniture') && c.max[1] > fy + 0.35 && c.min[1] < fy + 1.8)); }
    this.floorNames = D.semantic.building.floors.map(f => f.name);
  }
  cell(x, z) { return [Math.floor((x - this.x0) / this.res), Math.floor((z - this.z0) / this.res)]; }
  world(i, j) { return [this.x0 + (i + 0.5) * this.res, this.z0 + (j + 0.5) * this.res]; }
  walkable(f, x, z) { const [i, j] = this.cell(x, z); return i >= 0 && j >= 0 && i < this.nx && j < this.nz && this.clear[f][j * this.nx + i] === 1; }
  nearest(f, x, z, maxR = 1.2) {
    const [i, j] = this.cell(x, z), R = Math.ceil(maxR / this.res); let best = null, bd = 1e9;
    for (let dj = -R; dj <= R; dj++) for (let di = -R; di <= R; di++) { const ii = i + di, jj = j + dj; if (ii < 0 || jj < 0 || ii >= this.nx || jj >= this.nz || !this.clear[f][jj * this.nx + ii]) continue; const d = di * di + dj * dj; if (d < bd) { bd = d; best = [ii, jj]; } }
    return best;
  }
  roomAt(f, x, z) { return this.rooms.find(r => r.floor === f && x >= r.bounds.x0 && x <= r.bounds.x1 && z >= r.bounds.z0 && z <= r.bounds.z1 && r.kind !== 'corridor') || this.rooms.find(r => r.floor === f && r.kind === 'corridor' && x >= r.bounds.x0 && x <= r.bounds.x1 && z >= r.bounds.z0 && z <= r.bounds.z1) || null; }
  los(f, a, b) { const n = Math.max(2, Math.floor(Math.hypot(b[0] - a[0], b[1] - a[1]) / (this.res * 0.5))); for (let k = 0; k <= n; k++) { const t = k / n; if (!this.walkable(f, a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)) return false; } return true; }

  route(start, goal, accessible = false) {
    const [sf, sx, sz] = start, [gf, gx, gz] = goal, nx = this.nx, NN = this.NN;
    const s = this.nearest(sf, sx, sz, 0.8), g = this.nearest(gf, gx, gz, 0.8);
    if (!s) return { status: 'invalid', reason: 'The start point is not on a mapped, obstacle-free walkway.' };
    if (!g) return { status: 'invalid', reason: 'The destination is not on a mapped, obstacle-free walkway, so no route is offered.' };
    const pc = new Map();
    for (const p of this.portals) {
      if (accessible && !p.accessible) continue;
      for (const [a, b] of [[p.a, p.b], [p.b, p.a]]) {
        const ci = this.nearest(a[0], a[1], a[2], 0.4), cj = this.nearest(b[0], b[1], b[2], 0.4); if (!ci || !cj) continue;
        const k = a[0] * NN + ci[1] * nx + ci[0]; if (!pc.has(k)) pc.set(k, []); pc.get(k).push([b[0] * NN + cj[1] * nx + cj[0], p.cost_m, p.kind === 'lift' ? 2 : 1]);
      }
    }
    const S0 = sf * NN + s[1] * nx + s[0], G0 = gf * NN + g[1] * nx + g[0], gi = g[0], gj = g[1];
    const gc = new Float64Array(this.nf * NN).fill(Infinity), prev = new Int32Array(this.nf * NN).fill(-1), via = new Uint8Array(this.nf * NN);
    const hq = new Heap(), res = this.res, SQ = Math.SQRT2;
    const h = (f, i, j) => f === gf ? Math.hypot(i - gi, j - gj) * res : 0;
    gc[S0] = 0; hq.push(h(sf, s[0], s[1]), S0, 0);
    const N8 = [[1, 0, 1], [-1, 0, 1], [0, 1, 1], [0, -1, 1], [1, 1, SQ], [1, -1, SQ], [-1, 1, SQ], [-1, -1, SQ]];
    let expanded = 0;
    while (hq.size) {
      const cur = hq.pop(); if (hq.lastG > gc[cur] + 1e-6) continue; if (cur === G0) break; expanded++;
      const f = Math.floor(cur / NN), r = cur - f * NN, j = Math.floor(r / nx), i = r - j * nx, cg = gc[cur], cl = this.clear[f];
      for (let q = 0; q < 8; q++) {
        const di = N8[q][0], dj = N8[q][1], w = N8[q][2], ni = i + di, nj = j + dj; if (ni < 0 || nj < 0 || ni >= nx || nj >= this.nz || !cl[nj * nx + ni]) continue;
        if (di && dj && !(cl[j * nx + ni] && cl[nj * nx + i])) continue;
        const k = f * NN + nj * nx + ni, ng = cg + w * res;
        if (ng < gc[k]) { gc[k] = ng; prev[k] = cur; via[k] = 0; hq.push(ng + h(f, ni, nj), k, ng); }
      }
      const pl = pc.get(cur); if (pl) for (const [dst, cost, kind] of pl) { const ng = cg + cost; if (ng < gc[dst]) { gc[dst] = ng; prev[dst] = cur; via[dst] = kind; hq.push(ng, dst, ng); } }
    }
    if (!isFinite(gc[G0])) return { status: 'no_path', reason: 'This destination is not connected to the start through validated walkable space' + (accessible ? ' on a step-free route' : '') + '.', expanded };
    const chain = [G0]; while (chain[chain.length - 1] !== S0) chain.push(prev[chain[chain.length - 1]]); chain.reverse();
    const segs = [], trans = []; let curF = sf, pts = [];
    for (const st of chain) {
      const f = Math.floor(st / NN), r = st - f * NN, j = Math.floor(r / nx), i = r - j * nx;
      if (f !== curF) { segs.push({ floor: curF, raw: pts }); trans.push({ kind: via[st] === 2 ? 'lift' : 'stairs', from: curF, to: f }); pts = []; curF = f; }
      pts.push(this.world(i, j));
    }
    segs.push({ floor: curF, raw: pts });
    let total = 0;
    for (const sg of segs) {
      const p = sg.raw, out = [p[0]]; let k = 0;
      while (k < p.length - 1) { let m = p.length - 1; while (m > k + 1 && !this.los(sg.floor, p[k], p[m])) m--; out.push(p[m]); k = m; }
      sg.pts = out; delete sg.raw; for (let q = 0; q < out.length - 1; q++) total += Math.hypot(out[q + 1][0] - out[q][0], out[q + 1][1] - out[q][1]);
    }
    const r = { status: 'ok', segments: segs, transitions: trans, length: total, cost: gc[G0], expanded, accessible };
    r.validation = this.validate(r); return r;
  }

  /* independent re-check of the final polyline against raw collider boxes (not the raster) */
  validate(route) {
    let worst = 1e9; const viol = new Set();
    for (const sg of route.segments) {
      const obs = this.obst[sg.floor];
      for (let q = 0; q < sg.pts.length - 1; q++) {
        const a = sg.pts[q], b = sg.pts[q + 1], len = Math.hypot(b[0] - a[0], b[1] - a[1]), n = Math.max(2, Math.ceil(len / 0.05));
        for (let k = 0; k <= n; k++) {
          const t = k / n, x = a[0] + (b[0] - a[0]) * t, z = a[1] + (b[1] - a[1]) * t;
          for (let o = 0; o < obs.length; o++) {
            const c = obs[o], dx = Math.max(c.min[0] - x, x - c.max[0], 0), dz = Math.max(c.min[2] - z, z - c.max[2], 0), d = Math.hypot(dx, dz);
            if (d < worst) worst = d; if (d < AVATAR_R) viol.add(c.id);
          }
        }
      }
    }
    return { collisionFree: viol.size === 0, minClearance: worst, violations: [...viol], checkedRadius: AVATAR_R };
  }

  /* 3D path for the ribbon / walker: [{p:[x,y,z], floor}] */
  path3d(route) {
    const out = [];
    route.segments.forEach((sg, si) => {
      sg.pts.forEach(([x, z]) => out.push({ p: [x, sg.floor * H_FLOOR, z], floor: sg.floor }));
      const t = route.transitions[si]; if (!t) return;
      if (t.kind === 'stairs') {
        const lower = Math.min(t.from, t.to), st = this.stairs.find(s => s.floor_from === lower), pl = st.polyline.map(q => ({ p: q.slice(), floor: q[1] > (lower * H_FLOOR + 1.8) ? lower + 1 : lower }));
        (t.to > t.from ? pl : pl.slice().reverse()).forEach(q => out.push(q));
      } else {
        const lp = this.portals.find(p => p.kind === 'lift' && p.a[0] === Math.min(t.from, t.to)), x = lp.a[1], z = lp.a[2];
        out.push({ p: [x, t.from * H_FLOOR, z], floor: t.from }, { p: [x, t.to * H_FLOOR, z], floor: t.to });
      }
    });
    return out;
  }

  describe(route, startName, destName) {
    const steps = [{ t: 'Start at ' + startName, d: this.floorNames[route.segments[0].floor] }]; let last = null, acc = 0;
    const flush = () => { if (last && acc > 1.5) steps.push({ t: 'Walk through ' + last, d: Math.round(acc) + ' m' }); acc = 0; };
    route.segments.forEach((sg, si) => {
      for (let q = 0; q < sg.pts.length - 1; q++) {
        const a = sg.pts[q], b = sg.pts[q + 1], len = Math.hypot(b[0] - a[0], b[1] - a[1]), n = Math.max(1, Math.ceil(len / 0.5));
        for (let k = 0; k < n; k++) { const t = (k + 0.5) / n, r = this.roomAt(sg.floor, a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t); const nm = r ? r.name : last; if (nm !== last) { flush(); last = nm; } acc += len / n; }
      }
      flush(); last = null;
      const t = route.transitions[si]; if (t) steps.push({ t: (t.kind === 'lift' ? 'Take the lift ' : 'Take the stairs ') + (t.to > t.from ? 'up' : 'down') + ' to ' + this.floorNames[t.to], d: t.kind === 'lift' ? 'step-free' : 'stairs' });
    });
    steps.push({ t: 'Arrive at ' + destName, d: '' }); return steps;
  }
  seconds(route) { return route.length / 1.3 + route.transitions.reduce((s, t) => s + (t.kind === 'lift' ? 22 : 24), 0); }
}

/* ---------- search ---------- */
function searchPOIs(D, q) {
  q = q.trim().toLowerCase(); if (!q) return [];
  const toks = q.split(/\s+/), fl = D.semantic.building.floors, out = [];
  for (const p of D.semantic.pois) {
    const name = p.name.toLowerCase(), al = (p.aliases || []).map(a => a.toLowerCase()), cat = p.category.toLowerCase(), fn = fl[p.floor].name.toLowerCase();
    let sc = 0;
    if (name === q) sc = 100; else if (name.startsWith(q)) sc = 85; else if (name.split(/\W+/).some(w => w.startsWith(q))) sc = 65; else if (al.some(a => a === q)) sc = 75; else if (al.some(a => a.startsWith(q))) sc = 58; else if (name.includes(q)) sc = 40; else if (al.some(a => a.includes(q))) sc = 32; else if (cat.startsWith(q)) sc = 28;
    if (!sc && toks.length > 1) { const hay = [name, ...al, cat, fn].join(' '); if (toks.every(t => hay.includes(t))) sc = 30; }
    if (!sc && toks.length === 1 && fn.includes(q)) sc = 12;
    if (sc) out.push([sc, p]);
  }
  return out.sort((a, b) => b[0] - a[0] || a[1].floor - b[1].floor).slice(0, 8).map(x => x[1]);
}
