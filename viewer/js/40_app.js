/* NAMMA TWIN viewer: camera, input, picking, labels, walk mode, route following. */
let DATA, NAV, SCENE, RS, canvas, W = { w: 1, h: 1 };
const HOME = { target: [18, 3.2, 10], dist: 74, yaw: 0.62, pitch: 0.46 };
const C = { ...HOME, target: HOME.target.slice() }, G = { ...HOME, target: HOME.target.slice() };
const FOV = 50 * Math.PI / 180;
const WK = { floor: 0, pos: [7, 18.2], yaw: Math.PI, pitch: -0.04, y: 1.6, path: null, pd: 0, auto: false, vy: 0 };
const KEYS = new Set();
let CAMS = { vp: M4.ident(), invVP: M4.ident(), eye: [0, 0, 0], view: M4.ident(), pxScale: 1 };
let ISO = -1, renderScale = 1, perf = { ms: 16.7, fps: 60, slow: 0, fast: 0, prims: 0, tris: 0 };

function flyTo(o) { Object.assign(G, o); if (o.target) G.target = o.target.slice(); }
function resetCamera() { if (S.mode === 'walk') setMode('orbit'); flyTo(HOME); }

/* ---------- camera matrices ---------- */
function updateCamera(dt) {
  const aspect = W.w / W.h;
  if (S.mode === 'orbit') {
    const a = 1 - Math.exp(-dt * 9);
    C.dist = lerp(C.dist, G.dist, a); C.yaw = lerp(C.yaw, G.yaw, a); C.pitch = lerp(C.pitch, G.pitch, a);
    for (let i = 0; i < 3; i++) C.target[i] = lerp(C.target[i], G.target[i], a);
    const cp = Math.cos(C.pitch);
    CAMS.eye = [C.target[0] + C.dist * Math.sin(C.yaw) * cp, C.target[1] + C.dist * Math.sin(C.pitch), C.target[2] + C.dist * Math.cos(C.yaw) * cp];
    CAMS.view = M4.look(CAMS.eye, C.target);
    CAMS.proj = M4.persp(FOV, aspect, Math.max(0.3, C.dist * 0.02), 600);
  } else {
    const cp = Math.cos(WK.pitch), f = [Math.sin(WK.yaw) * cp, Math.sin(WK.pitch), Math.cos(WK.yaw) * cp];
    CAMS.eye = [WK.pos[0], WK.y, WK.pos[1]];
    CAMS.view = M4.look(CAMS.eye, [CAMS.eye[0] + f[0], CAMS.eye[1] + f[1], CAMS.eye[2] + f[2]]);
    CAMS.proj = M4.persp(FOV * 1.15, aspect, 0.06, 400);
  }
  CAMS.vp = M4.mul(CAMS.proj, CAMS.view); CAMS.invVP = M4.inv(CAMS.vp);
  CAMS.pxScale = W.h / (2 * Math.tan((S.mode === 'orbit' ? FOV : FOV * 1.15) / 2)) * 0.0125;
}

/* ---------- modes ---------- */
function setMode(m) {
  if (m === S.mode) return;
  S.mode = m;
  $('#modeOrbit').setAttribute('aria-pressed', m === 'orbit'); $('#modeWalk').setAttribute('aria-pressed', m === 'walk');
  if (m === 'walk') {
    if (!WK._placed) placeWalker(poiStart(), Math.PI);
    S.floors = [true, true, true]; ISO = -1; S.cut = 1; renderElev();
    showHud('Walk mode. WASD or arrow keys move you, drag to look, click the floor to walk there, E uses stairs and lifts.', 6000);
  } else {
    WK.auto = false; WK.path = null;
    G.target = [WK.pos[0], WK.floor * H_FLOOR + 1.2, WK.pos[1]]; Object.assign(C, { target: G.target.slice() }); G.dist = 14; C.dist = 6; G.pitch = 0.6; G.yaw = WK.yaw + Math.PI;
    $('#prompt').classList.remove('show');
  }
  renderPanel();
}
function poiStart() { const p = poiById('poi-main-entrance'); return [p.floor, p.nav_anchor.x, p.nav_anchor.z]; }
function placeWalker([f, x, z], yaw) { WK.floor = f; WK.pos = [x, z]; WK.yaw = yaw; WK.pitch = -0.04; WK.y = f * H_FLOOR + 1.6; WK._placed = true; }

/* ---------- picking ---------- */
function unproject(nx, ny, z) { const p = M4.xform(CAMS.invVP, nx, ny, z); return [p[0] / p[3], p[1] / p[3], p[2] / p[3]]; }
function rayFrom(clientX, clientY) {
  const r = canvas.getBoundingClientRect(), nx = (clientX - r.left) / r.width * 2 - 1, ny = 1 - (clientY - r.top) / r.height * 2;
  const a = unproject(nx, ny, -1), b = unproject(nx, ny, 1), d = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], l = Math.hypot(...d);
  return { o: CAMS.eye.slice(), d: d.map(v => v / l) };
}
function rayBox(o, d, mn, mx) {
  let t0 = 0, t1 = 1e9;
  for (let i = 0; i < 3; i++) { if (Math.abs(d[i]) < 1e-9) { if (o[i] < mn[i] || o[i] > mx[i]) return -1; } else { let a = (mn[i] - o[i]) / d[i], b = (mx[i] - o[i]) / d[i]; if (a > b) [a, b] = [b, a]; t0 = Math.max(t0, a); t1 = Math.min(t1, b); if (t0 > t1) return -1; } }
  return t0;
}
function pickScene(cx, cy) {
  const { o, d } = rayFrom(cx, cy); let best = null, bt = 1e9;
  const clipY = S.cut >= 0.999 ? 1e4 : S.cut * 3 * H_FLOOR + 0.2;
  for (const p of SCENE) {
    if (p.glass || !floorVisible(p) || !S.layers.visual || S.meshAlpha < 0.3 || p.kind === 'site') continue;
    const oy = offY(p.floor), mn = [p.bmin[0], p.bmin[1] + oy, p.bmin[2]], mx = [p.bmax[0], p.bmax[1] + oy, p.bmax[2]];
    if (mn[1] > clipY) continue;
    const t = rayBox(o, d, mn, mx); if (t > 0 && t < bt) { bt = t; best = p; }
  }
  if (!best) return null;
  const pt = [o[0] + d[0] * bt, o[1] + d[1] * bt, o[2] + d[2] * bt];
  let f = best.floor; if (f < 0 || f > 2) f = clamp(Math.floor((pt[1] + 0.2) / H_FLOOR), 0, 2);
  const room = best.room ? DATA.semantic.rooms.find(r => r.id === best.room) : null;
  return { prim: best, t: bt, point: pt, floor: f, room: room || NAV.roomAt(f, pt[0], pt[2] - 0) };
}

/* ---------- pointer / keyboard ---------- */
const PTR = new Map(); let dragMoved = 0, downAt = 0, pinch0 = 0;
function bindInput() {
  canvas.addEventListener('contextmenu', e => e.preventDefault());
  canvas.addEventListener('pointerdown', e => { canvas.setPointerCapture(e.pointerId); PTR.set(e.pointerId, { x: e.clientX, y: e.clientY, b: e.button, shift: e.shiftKey || e.ctrlKey }); dragMoved = 0; downAt = performance.now(); canvas.classList.add('dragging'); if (PTR.size === 2) { const [a, b] = [...PTR.values()]; pinch0 = Math.hypot(a.x - b.x, a.y - b.y); } canvas.focus({ preventScroll: true }); });
  canvas.addEventListener('pointermove', e => {
    const p = PTR.get(e.pointerId); if (!p) return;
    const dx = e.clientX - p.x, dy = e.clientY - p.y; dragMoved += Math.abs(dx) + Math.abs(dy);
    if (S.mode === 'orbit') {
      if (PTR.size === 2) {
        const [a, b] = [...PTR.values()], dist = Math.hypot(a.x - b.x, a.y - b.y);
        if (pinch0) G.dist = clamp(G.dist * pinch0 / dist, 2.5, 170); pinch0 = dist; p.x = e.clientX; p.y = e.clientY; return;
      }
      if (p.b === 2 || p.b === 1 || p.shift) panView(dx, dy); else { G.yaw -= dx * 0.0055; G.pitch = clamp(G.pitch + dy * 0.0055, 0.02, 1.52); }
    } else { WK.yaw -= dx * 0.0046; WK.pitch = clamp(WK.pitch - dy * 0.0046, -1.3, 1.3); }
    p.x = e.clientX; p.y = e.clientY;
  });
  const up = e => {
    const had = PTR.delete(e.pointerId); canvas.classList.toggle('dragging', PTR.size > 0); if (!had) return;
    if (dragMoved < 6 && performance.now() - downAt < 450 && e.type === 'pointerup') onClick(e);
  };
  canvas.addEventListener('pointerup', up); canvas.addEventListener('pointercancel', up);
  canvas.addEventListener('wheel', e => { e.preventDefault(); if (S.mode === 'orbit') G.dist = clamp(G.dist * Math.exp(e.deltaY * 0.0012), 2.5, 170); else WK.pitch = clamp(WK.pitch, -1.3, 1.3); }, { passive: false });
  window.addEventListener('keydown', e => {
    if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
    const k = e.key.toLowerCase();
    if (['w', 'a', 's', 'd', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright', 'shift'].includes(k)) { KEYS.add(k); if (S.mode === 'walk' && k !== 'shift') { WK.auto = false; } if (k.startsWith('arrow')) e.preventDefault(); }
    else if (k === 'e') usePortal(); else if (k === 'r') resetCamera(); else if (k === 'escape') { if (WK.auto) { WK.auto = false; } else clearSelection(); }
    else if (k === '/' ) { e.preventDefault(); $('#q').focus(); }
  });
  window.addEventListener('keyup', e => KEYS.delete(e.key.toLowerCase()));
  window.addEventListener('blur', () => KEYS.clear());
}
function panView(dx, dy) {
  const v = CAMS.view, k = C.dist * 0.0017, r = [v[0], v[4], v[8]], u = [v[1], v[5], v[9]];
  for (let i = 0; i < 3; i++) G.target[i] += (-dx * r[i] + dy * u[i]) * k;
  G.target[1] = clamp(G.target[1], -1, 14);
}
function onClick(e) {
  if (S.mode === 'walk') {
    const { o, d } = rayFrom(e.clientX, e.clientY), y = WK.floor * H_FLOOR;
    if (d[1] < -0.02) { const t = (y - o[1]) / d[1], x = o[0] + d[0] * t, z = o[2] + d[2] * t; walkTo([WK.floor, x, z]); }
    return;
  }
  const hit = pickScene(e.clientX, e.clientY);
  if (!hit) { clearSelection(); return; }
  if (hit.room) selectRoom(hit.room, { fly: false }); else { S.sel = { type: 'obj', prim: hit.prim, floor: hit.floor }; rebuildSelection(); renderPanel(); openTab('explore'); }
}

/* ---------- selection ---------- */
const poiById = id => DATA.semantic.pois.find(p => p.poi_id === id);
const roomById = id => DATA.semantic.rooms.find(r => r.id === id);
function rebuildSelection() {
  RS.sel = null; if (!S.sel || S.sel.type === 'obj') return;
  const r = roomById(S.sel.id); if (!r) return; const b = r.bounds, y0 = r.floor * H_FLOOR, v = [];
  boxLines(v, [b.x0 + 0.03, y0 + 0.03, b.z0 + 0.03], [b.x1 - 0.03, y0 + 3.2, b.z1 - 0.03], cssToRGB(getComputedStyle(document.documentElement).getPropertyValue('--brass').trim()).concat([1]));
  RS.sel = [lineBatch(r.floor, v)];
}
function selectRoom(r, opt = { fly: true }) {
  S.sel = { type: 'room', id: r.id }; rebuildSelection(); if (opt.fly !== false) flyToRoom(r);
  if (!S.floors[r.floor]) { S.floors[r.floor] = true; }
  openTab(S.tab === 'nav' || S.tab === 'recon' || S.tab === 'layers' ? S.tab : 'explore'); renderPanel(); syncLabels(true);
}
function clearSelection() { S.sel = null; RS.sel = null; renderPanel(); syncLabels(true); }
function flyToRoom(r) {
  const b = r.bounds, cx = (b.x0 + b.x1) / 2, cz = (b.z0 + b.z1) / 2, size = Math.max(b.x1 - b.x0, b.z1 - b.z0);
  flyTo({ target: [cx, r.floor * H_FLOOR + 1.2 + offY(r.floor), cz], dist: clamp(size * 1.5 + 7, 10, 34), pitch: 0.62, yaw: C.yaw });
  if (S.mode === 'walk') setMode('orbit');
}
function selectPOI(p) {
  const r = roomById(p.room_id); NV.to = p.poi_id; NV.error = null;
  if (r) { S.sel = { type: 'room', id: r.id }; rebuildSelection(); }
  computeRoute(true); openTab('nav'); syncLabels(true);
}

/* ---------- floors / views ---------- */
function setIso(f) {
  ISO = f; S.floors = [0, 1, 2].map(i => f < 0 || i === f); renderElev(); renderPanel(); syncLabels(true);
}
function viewPreset(name) {
  S.glass = 1; S.explode = 0; S.cut = 1; S.showRoof = true; S.showSite = true; S.showFins = true; setIsoQuiet(-1); if (S.mode === 'walk') setMode('orbit');
  if (name === 'exterior') flyTo(HOME);
  if (name === 'cutaway') { S.showRoof = false; S.glass = 0.35; S.cut = 0.7; S.showFins = false; flyTo({ target: [18, 3.4, 10], dist: 52, yaw: 0.5, pitch: 0.78 }); }
  if (name === 'exploded') { S.explode = 5; S.showRoof = true; S.glass = 0.4; flyTo({ target: [18, 8, 10], dist: 86, yaw: 0.7, pitch: 0.3 }); }
  if (name === 'plan') { const f = Math.max(ISO, 0); setIsoQuiet(0); S.showRoof = false; S.cut = (3 * 0 + 3.2 - 0.2) / (3 * H_FLOOR) + 0.0; flyTo({ target: [18, 1.5, 10], dist: 56, yaw: 0, pitch: 1.5 }); }
  renderElev(); renderPanel(); syncLabels(true);
}
function setIsoQuiet(f) { ISO = f; S.floors = [0, 1, 2].map(i => f < 0 || i === f); }

/* ---------- walking ---------- */
function walkTo(goal) {
  const r = NAV.route([WK.floor, WK.pos[0], WK.pos[1]], goal);
  if (r.status !== 'ok') { toast(r.reason || 'No walkable route to that point.'); return; }
  followPath(NAV.path3d(r)); if (!r.validation.collisionFree) toast('Route is not collision free, so it is not offered.');
}
function followPath(path) {
  const pts = path.map(q => q.p), cum = [0]; for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1], pts[i][2] - pts[i - 1][2]));
  WK.path = { pts, cum, total: cum[cum.length - 1] }; WK.pd = 0; WK.auto = true;
}
function sampleAt(path, d) {
  const { pts, cum } = path; d = clamp(d, 0, path.total); let i = 1; while (i < cum.length - 1 && cum[i] < d) i++;
  const t = (d - cum[i - 1]) / Math.max(cum[i] - cum[i - 1], 1e-6), a = pts[i - 1], b = pts[i];
  return [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];
}
function nearPortal() {
  for (const p of NAV.portals) for (const [a, b, dir] of [[p.a, p.b, 1], [p.b, p.a, -1]]) if (a[0] === WK.floor && Math.hypot(a[1] - WK.pos[0], a[2] - WK.pos[1]) < 1.5) return { p, a, b, dir };
  return null;
}
function usePortal() {
  if (S.mode !== 'walk' || WK.auto) return; const n = nearPortal(); if (!n) return;
  const to = n.b[0], up = to > WK.floor;
  if (n.p.kind === 'lift') { followPath([{ p: [n.a[1], WK.floor * H_FLOOR, n.a[2]] }, { p: [n.a[1], to * H_FLOOR, n.a[2]] }]); }
  else { const lower = Math.min(WK.floor, to), st = NAV.stairs.find(s => s.floor_from === lower), pl = st.polyline.map(q => ({ p: q.slice() })); followPath(up ? pl : pl.slice().reverse()); }
}
function updateWalk(dt) {
  let moving = false;
  if (WK.auto && WK.path) {
    WK.pd += dt * 1.7; const q = sampleAt(WK.path, WK.pd), look = sampleAt(WK.path, WK.pd + 1.6);
    WK.pos = [q[0], q[2]]; const base = WK.floor * H_FLOOR; WK.y = q[1] + 1.6; WK.floor = clamp(Math.round((q[1] - 0.3) / H_FLOOR), 0, 2);
    const dx = look[0] - q[0], dz = look[2] - q[2];
    if (Math.hypot(dx, dz) > 0.05) { const ty = Math.atan2(dx, dz); let d = ty - WK.yaw; d = Math.atan2(Math.sin(d), Math.cos(d)); WK.yaw += d * (1 - Math.exp(-dt * 4)); }
    WK.pitch = lerp(WK.pitch, (WK.path.pts.length < 3 ? 0 : -0.04) + (look[1] - q[1]) * -0.05, 1 - Math.exp(-dt * 3));
    if (WK.pd >= WK.path.total) { WK.auto = false; WK.floor = clamp(Math.round((WK.path.pts[WK.path.pts.length - 1][1] - 0.3) / H_FLOOR), 0, 2); WK.y = WK.floor * H_FLOOR + 1.6; showHud('You have arrived.', 2500); }
    moving = true;
  } else {
    const f = [Math.sin(WK.yaw), Math.cos(WK.yaw)], r = [-Math.cos(WK.yaw), Math.sin(WK.yaw)], sp = (KEYS.has('shift') ? 3.4 : 1.9) * dt;
    let mx = 0, mz = 0;
    if (KEYS.has('w') || KEYS.has('arrowup')) { mx += f[0]; mz += f[1]; } if (KEYS.has('s') || KEYS.has('arrowdown')) { mx -= f[0]; mz -= f[1]; }
    if (KEYS.has('d')) { mx += r[0]; mz += r[1]; } if (KEYS.has('a')) { mx -= r[0]; mz -= r[1]; }
    if (KEYS.has('arrowleft')) WK.yaw += dt * 1.8; if (KEYS.has('arrowright')) WK.yaw -= dt * 1.8;
    const l = Math.hypot(mx, mz);
    if (l > 0) {
      mx = mx / l * sp; mz = mz / l * sp; const x = WK.pos[0], z = WK.pos[1];
      if (NAV.walkable(WK.floor, x + mx, z + mz)) WK.pos = [x + mx, z + mz]; else if (NAV.walkable(WK.floor, x + mx, z)) WK.pos = [x + mx, z]; else if (NAV.walkable(WK.floor, x, z + mz)) WK.pos = [x, z + mz];
      moving = true;
    }
    WK.y = lerp(WK.y, WK.floor * H_FLOOR + 1.6, 1 - Math.exp(-dt * 8));
  }
  const np = nearPortal(), pr = $('#prompt');
  if (np && !WK.auto) { const up = np.b[0] > WK.floor, lab = (np.p.kind === 'lift' ? 'Take the lift ' : 'Take the stairs ') + (up ? 'up' : 'down'); if (pr.dataset.k !== lab) { pr.innerHTML = `<button class="btn primary glass" id="btnPortal">${lab} <span class="mono dim">(E)</span></button>`; pr.dataset.k = lab; $('#btnPortal').onclick = usePortal; } pr.classList.add('show'); }
  else { pr.classList.remove('show'); pr.dataset.k = ''; }
  return moving;
}

/* ---------- labels ---------- */
let LBL = [];
function syncLabels(rebuild) {
  const host = $('#labels'); if (rebuild || !LBL.length) {
    host.innerHTML = ''; LBL = [];
    for (const p of DATA.semantic.pois) { const el = document.createElement('div'); el.className = 'lbl'; el.innerHTML = `<i class="dot" style="background:rgb(${catCol(p.category).map(v => Math.round(v * 255))})"></i><span></span>`; el.lastChild.textContent = p.name; el.onclick = () => selectPOI(p); host.appendChild(el); LBL.push({ el, kind: 'poi', f: p.floor, p: [p.anchor.x, p.floor * H_FLOOR + 1.9, p.anchor.z], id: p.room_id, pri: p.category === 'Entrance' ? 2 : 1 }); }
    for (const r of DATA.semantic.rooms) { const el = document.createElement('div'); el.className = 'lbl room'; el.textContent = r.name; host.appendChild(el); LBL.push({ el, kind: 'room', f: r.floor, p: [r.anchor.x, r.floor * H_FLOOR + 2.6, r.anchor.z], id: r.id, pri: 0 }); }
  }
}
function updateLabels() {
  const cam = CAMS, W_ = W.w, H_ = W.h, placed = [], dist = S.mode === 'orbit' ? C.dist : 0;
  const show = (S.mode === 'walk') || dist < 46 || ISO >= 0;
  const cand = [];
  for (const l of LBL) {
    const isSel = S.sel && S.sel.id === l.id, vis = l.kind === 'poi' ? S.layers.pois : S.layers.rooms;
    let on = vis && S.floors[l.f] && (show || isSel); let x = 0, y = 0, d = 0;
    if (on) {
      const p = M4.xform(cam.vp, l.p[0], l.p[1] + offY(l.f), l.p[2]); if (p[3] <= 0.1) on = false; else { x = (p[0] / p[3] * 0.5 + 0.5) * canvas.clientWidth; y = (1 - (p[1] / p[3] * 0.5 + 0.5)) * canvas.clientHeight; if (x < -40 || x > canvas.clientWidth + 40 || y < 0 || y > canvas.clientHeight) on = false; d = p[3]; if (S.mode === 'walk' && d > 22) on = false; if (l.p[1] + offY(l.f) > (S.cut >= 0.999 ? 1e4 : S.cut * 3 * H_FLOOR + 0.2)) on = false; }
    }
    if (on) cand.push({ l, x, y, d, isSel }); else l.el.style.display = 'none';
    l.el.classList.toggle('sel', !!isSel);
  }
  cand.sort((a, b) => (b.isSel - a.isSel) || (b.l.pri - a.l.pri) || (a.d - b.d));
  for (const c of cand) {
    const w = c.l.kind === 'room' ? 110 : 120, h = 26; let ok = true;
    if (!c.isSel) for (const q of placed) if (Math.abs(q.x - c.x) < w && Math.abs(q.y - c.y) < h) { ok = false; break; }
    if (ok) { placed.push(c); c.l.el.style.display = ''; c.l.el.style.transform = `translate(${c.x.toFixed(1)}px,${c.y.toFixed(1)}px) translate(-50%,-100%)`; } else c.l.el.style.display = 'none';
  }
}
