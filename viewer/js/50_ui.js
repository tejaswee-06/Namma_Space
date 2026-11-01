/* NAMMA TWIN viewer: UI (dock, panels, search, route UI), boot and render loop. */
const NV = { from: null, to: null, accessible: false, route: null, steps: null, error: null };
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
let toastT = 0, hudT = 0;
function toast(m) { const t = $('#toast'); t.textContent = m; t.classList.add('show'); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('show'), 3800); }
function showHud(m, ms = 4000) { const h = $('#hud'); h.textContent = m; h.classList.add('show'); clearTimeout(hudT); hudT = setTimeout(() => h.classList.remove('show'), ms); }

/* ---------- icons ---------- */
const IC = {
  explore: '<path d="M12 3 3 8l9 5 9-5-9-5Z"/><path d="m3 13 9 5 9-5"/>',
  building: '<rect x="5" y="3" width="14" height="18" rx="1.5"/><path d="M9 8h2M13 8h2M9 12h2M13 12h2M10 21v-4h4v4"/>',
  recon: '<circle cx="6" cy="7" r="1.4"/><circle cx="14" cy="5" r="1.4"/><circle cx="18" cy="12" r="1.4"/><circle cx="9" cy="14" r="1.4"/><circle cx="15" cy="19" r="1.4"/><circle cx="5" cy="19" r="1.4"/>',
  nav: '<path d="M12 21s-6-5.6-6-10.5a6 6 0 1 1 12 0C18 15.4 12 21 12 21Z"/><circle cx="12" cy="10.5" r="2.2"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5M3 16l9 5 9-5"/>',
  pois: '<path d="M4 6h16M4 12h16M4 18h10"/>',
};
const ico = k => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${IC[k]}</svg>`;
const TABS = [['explore', 'Explore'], ['building', 'Building'], ['recon', 'Reconstruction'], ['nav', 'Navigation'], ['layers', 'Layers'], ['pois', 'Places']];

/* ---------- dock with magnification (vanilla stand-in for React Bits Dock) ---------- */
function buildDock() {
  const d = $('#dock'); d.innerHTML = '';
  TABS.forEach(([k, label], i) => {
    if (i === 4) { const s = document.createElement('i'); s.className = 'dksep'; d.appendChild(s); }
    const b = document.createElement('button'); b.className = 'dk'; b.dataset.k = k; b.setAttribute('aria-label', label); b.setAttribute('aria-pressed', 'false');
    b.innerHTML = ico(k) + `<span class="tip">${label}</span>`; b.onclick = () => openTab(S.tab === k ? null : k); d.appendChild(b);
  });
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches, items = [...d.querySelectorAll('.dk')];
  const mag = x => { items.forEach(b => { const r = b.getBoundingClientRect(), c = r.left + r.width / 2, dist = Math.abs(x - c), s = x == null ? 1 : 1 + 0.55 * Math.exp(-(dist * dist) / (2 * 62 * 62)); b.style.transform = `scale(${s.toFixed(3)})`; b.style.margin = `0 ${((s - 1) * 14).toFixed(1)}px`; }); };
  if (!reduce && matchMedia('(hover:hover)').matches) { d.addEventListener('pointermove', e => mag(e.clientX)); d.addEventListener('pointerleave', () => items.forEach(b => { b.style.transform = ''; b.style.margin = ''; })); }
}
function openTab(k) {
  S.tab = k; $$('.dk').forEach(b => b.setAttribute('aria-pressed', b.dataset.k === k));
  $('#panel').classList.toggle('closed', !k); renderPanel();
  if (k === 'recon' && S.rep === 'mesh' && !S.layers.points && !S._reconSeen) { S._reconSeen = true; }
}

/* ---------- floor elevator ---------- */
function renderElev() {
  const e = $('#elev'); const names = ['G', '1', '2'];
  e.innerHTML = '<small>FLOOR</small>' + [2, 1, 0].map(f => `<button data-f="${f}" aria-pressed="${ISO === f}" aria-label="${esc(NAV.floorNames[f])} only" title="${esc(NAV.floorNames[f])}">${names[f]}</button>`).join('') + `<button data-f="-1" aria-pressed="${ISO < 0}" aria-label="All floors" title="All floors" style="font-size:12px">All</button>`;
  e.querySelectorAll('button').forEach(b => b.onclick = () => setIso(+b.dataset.f));
}

/* ---------- panel ---------- */
const tog = (id, label, on, sub = '', dis = false) => `<button class="tog" role="switch" aria-checked="${on}" data-t="${id}" ${dis ? 'disabled' : ''}><span class="lb">${label}${sub ? `<small>${sub}</small>` : ''}</span><span class="sw"></span></button>`;
const slider = (id, label, v, min, max, step, fmt) => `<div class="sec" style="gap:4px"><div class="lab"><label for="s-${id}">${label}</label><span class="mono">${fmt(v)}</span></div><input id="s-${id}" type="range" data-s="${id}" min="${min}" max="${max}" step="${step}" value="${v}"></div>`;
const chip = (act, val, label, on) => `<button class="chip" data-a="${act}" data-v="${val}" aria-pressed="${on}">${label}</button>`;
const poiPill = p => `<i class="dot" style="background:rgb(${catCol(p.category).map(v => Math.round(v * 255))})"></i>`;

function renderPanel() {
  const P = $('#panel'), k = S.tab; if (!k) return;
  const title = TABS.find(t => t[0] === k)[1];
  P.innerHTML = `<div class="ph"><h2>${title}</h2><button class="ico-btn x" aria-label="Close panel" data-a="close"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg></button></div><div class="pb">${PANELS[k]()}</div>`;
  P.onclick = panelClick; P.oninput = panelInput; P.onchange = panelInput;
}
const PANELS = {
  explore() {
    const s = S.sel, B = DATA.semantic.building;
    let h = '';
    if (s && s.type === 'room') {
      const r = roomById(s.id), pois = DATA.semantic.pois.filter(p => p.room_id === r.id), fl = NAV.floorNames[r.floor];
      h += `<div class="sec"><div class="card"><div class="row"><div class="grow"><div style="font-weight:700;font-size:16px">${esc(r.name)}</div><div class="muted" style="font-size:12.5px">${esc(r.category)} · ${esc(fl)}</div></div></div>
        <dl class="kv" style="margin-top:12px"><dt>Area</dt><dd class="mono">${r.area_m2.toFixed(1)} m²</dd><dt>Size</dt><dd class="mono">${(r.bounds.x1 - r.bounds.x0).toFixed(1)} × ${(r.bounds.z1 - r.bounds.z0).toFixed(1)} m</dd><dt>Step-free access</dt><dd>${r.accessible === false ? 'No' : 'Yes'}</dd><dt>Data source</dt><dd>${esc(r.source.replace(/_/g, ' '))}</dd><dt>Verified on site</dt><dd>${pois[0] && pois[0].verified ? 'Yes' : 'No'}</dd></dl></div>
        ${r.description ? `<p class="note">${esc(r.description)}</p>` : ''}
        <div class="row"><button class="btn route grow" data-a="navto" data-v="${esc(pois[0] ? pois[0].poi_id : '')}" ${pois[0] ? '' : 'disabled'}>Route here</button><button class="btn" data-a="clearsel">Clear</button></div></div>`;
    } else if (s && s.type === 'obj') {
      h += `<div class="sec"><div class="card"><div style="font-weight:700;font-size:16px">${esc((s.prim.name || 'Object').replace(/_/g, ' '))}</div><dl class="kv" style="margin-top:10px"><dt>Kind</dt><dd>${esc(s.prim.kind || 'object')}</dd><dt>Floor</dt><dd>${esc(NAV.floorNames[s.floor] || 'Site')}</dd></dl></div><button class="btn" data-a="clearsel">Clear</button></div>`;
    } else {
      h += `<div class="sec"><div class="card"><div style="font-weight:700;font-size:16px">${esc(B.name)}</div><dl class="kv" style="margin-top:10px"><dt>Floors</dt><dd class="mono">${B.floors.length}</dd><dt>Rooms</dt><dd class="mono">${DATA.semantic.rooms.length}</dd><dt>Places</dt><dd class="mono">${DATA.semantic.pois.length}</dd><dt>Footprint</dt><dd class="mono">36 × 20 m</dd><dt>Model version</dt><dd class="mono">0.3.0-synthetic</dd></dl></div>
        <p class="note">Click any room to inspect it, or search a destination to get a validated walking route. This is a procedural demo building, not a real site.</p></div>`;
    }
    h += `<div class="sec"><h3>Quick views</h3><div class="chips">${chip('view', 'exterior', 'Exterior')}${chip('view', 'cutaway', 'Cutaway')}${chip('view', 'exploded', 'Exploded')}${chip('view', 'plan', 'Floor plan')}</div></div>`;
    return h;
  },
  building() {
    return `<div class="sec"><h3>Views</h3><div class="chips">${chip('view', 'exterior', 'Exterior')}${chip('view', 'cutaway', 'Cutaway')}${chip('view', 'exploded', 'Exploded')}${chip('view', 'plan', 'Floor plan')}</div></div>
    <div class="sec"><h3>Floors</h3><div class="chips">${[0, 1, 2].map(f => chip('floor', f, NAV.floorNames[f], S.floors[f])).join('')}</div></div>
    <div class="sec">${slider('explode', 'Explode floors', S.explode, 0, 8, 0.1, v => (+v).toFixed(1) + ' m')}${slider('cut', 'Section cut height', S.cut, 0.1, 1, 0.01, v => v >= 0.999 ? 'off' : Math.round(v * 3 * H_FLOOR * 10) / 10 + ' m')}${slider('glass', 'Glass opacity', S.glass, 0, 1, 0.05, v => Math.round(v * 100) + '%')}</div>
    <div class="sec">${tog('roof', 'Roof', S.showRoof)}${tog('site', 'Site and ground', S.showSite)}${tog('fins', 'Facade fins', S.showFins)}</div>
    <div class="sec"><h3>Lighting</h3><div class="chips">${chip('light', 'day', 'Daylight', S.light === 'day')}${chip('light', 'dusk', 'Dusk', S.light === 'dusk')}</div></div>`;
  },
  recon() {
    const R = DATA.report, g = DATA.reg, hasF = Object.keys(DATA.frames);
    const pts = DATA.cloud.n.toLocaleString();
    return `<div class="card" style="border-color:color-mix(in srgb,var(--warn) 45%,transparent)"><div class="row"><span class="badge">Simulated scan</span></div><p class="note" style="margin:8px 0 0">This capture is simulated from the synthetic model with a photogrammetry-like noise and visibility model. It is <b>not COLMAP output</b> and not a real site.</p></div>
    <div class="sec"><h3>Representation</h3><div class="chips">${chip('rep', 'mesh', 'Mesh', S.rep === 'mesh')}${chip('rep', 'points', 'Point cloud', S.rep === 'points')}${chip('rep', 'hybrid', 'Hybrid', S.rep === 'hybrid')}<button class="chip off" disabled title="Not generated in this build">Gaussian splat · not generated</button></div></div>
    ${S.layers.points ? `<div class="sec"><h3>Point colour</h3><div class="chips">${chip('pmode', 0, 'Captured colour', S.pointMode === 0)}${chip('pmode', 1, 'Height', S.pointMode === 1)}${chip('pmode', 2, 'Observation count', S.pointMode === 2)}</div>${slider('psize', 'Point size', S.pointSize, 1, 8, 0.2, v => (+v).toFixed(1))}</div>` : ''}
    <div class="sec"><h3>Capture statistics</h3><dl class="kv"><dt>Frames</dt><dd class="mono">${R.frames}</dd><dt>Registered</dt><dd class="mono">${R.registered_frames} (${Math.round(R.registration_rate * 100)}%)</dd><dt>Dense points</dt><dd class="mono">${R.dense_points.toLocaleString()}</dd><dt>Points shown</dt><dd class="mono">${pts}</dd><dt>Mean floor coverage</dt><dd class="mono">${Math.round(R.mean_room_floor_coverage * 100)}%</dd></dl></div>
    <div class="sec"><h3>Metric registration</h3><dl class="kv"><dt>Status</dt><dd><span class="badge ${g.status === 'REGISTERED' ? 'ok' : ''}">${esc(g.status)}</span></dd><dt>Frame</dt><dd>${esc(g.coordinate_system)}</dd><dt>Baseline</dt><dd class="mono">${g.reference_measurements.baseline_m.toFixed(2)} m</dd><dt>Validation error</dt><dd class="mono">${g.reference_measurements.validation.map(v => (v.rel_error * 100).toFixed(2) + '%').join(', ')}</dd></dl>
      <p class="note">Registration was computed from two simulated picks and a measured baseline, then checked against an independent measurement. Drift from structure-from-motion is not included.</p></div>
    ${hasF.length ? `<div class="sec"><h3>Compare with the model</h3><p class="note">Pick a simulated capture frame. The view jumps to that camera pose in the 3D model so you can compare.</p><div class="chips">${DATA.cameras.filter(c => DATA.frames[c.image]).map(c => `<button class="chip" data-a="frame" data-v="${c.i}">#${c.i}</button>`).join('')}</div>${S.selCam >= 0 && DATA.frames[DATA.cameras[S.selCam].image] ? `<div class="pip"><img alt="Simulated capture frame ${S.selCam}" src="${DATA.frames[DATA.cameras[S.selCam].image]}"><span class="tag">Simulated frame #${S.selCam}</span></div>` : ''}</div>` : ''}
    <div class="sec"><h3>Known limitations</h3><ul class="note" style="margin:0;padding-left:18px">${R.limitations.map(l => `<li>${esc(l)}</li>`).join('')}</ul></div>`;
  },
  nav() {
    const pois = DATA.semantic.pois, opt = sel => pois.slice().sort((a, b) => a.floor - b.floor || a.name.localeCompare(b.name)).map(p => `<option value="${esc(p.poi_id)}" ${p.poi_id === sel ? 'selected' : ''}>${esc(p.name)} · ${esc(NAV.floorNames[p.floor])}</option>`).join('');
    const r = NV.route;
    let out = '';
    if (NV.error) out = `<div class="card" style="border-color:var(--bad)"><div class="row"><span class="badge bad">No route</span></div><p class="note" style="margin:8px 0 0">${esc(NV.error)}</p></div>`;
    else if (r) {
      const mins = NAV.seconds(r) / 60, v = r.validation;
      out = `<div class="card"><div class="row" style="gap:16px"><div><div class="mono" style="font-size:22px;font-weight:600">${r.length.toFixed(0)} m</div><div class="muted" style="font-size:12px">distance</div></div><div><div class="mono" style="font-size:22px;font-weight:600">${mins < 1 ? '<1' : Math.round(mins)} min</div><div class="muted" style="font-size:12px">estimated</div></div><span class="spacer"></span><span class="badge ${v.collisionFree ? 'ok' : 'bad'}" title="Independent re-check of every 5 cm along the path against collision geometry">${v.collisionFree ? 'Collision-checked' : 'Not collision-free'}</span></div>
        <div class="muted" style="font-size:12px;margin-top:10px">Min clearance <span class="mono">${(v.minClearance * 100).toFixed(0)} cm</span> for a ${(AVATAR_R * 200).toFixed(0)} cm wide avatar${r.accessible ? ' · step-free route' : ''}</div></div>
        <ol class="steps">${NV.steps.map((s, i) => `<li><i>${i + 1}</i><span style="flex:1">${esc(s.t)}</span><span class="muted mono" style="font-size:12px">${esc(s.d)}</span></li>`).join('')}</ol>
        <div class="row"><button class="btn primary grow" data-a="walkroute">Walk this route</button><button class="btn" data-a="fitroute">Overview</button></div>`;
    } else out = '<div class="empty">Choose a start and a destination. Routes are only shown when they pass an independent collision check.</div>';
    return `<div class="sec"><label class="lab" for="selFrom">From</label><select id="selFrom" class="btn" style="width:100%;height:40px;justify-content:flex-start" data-s="from">${opt(NV.from || 'poi-main-entrance')}</select>
      <label class="lab" for="selTo">To</label><select id="selTo" class="btn" style="width:100%;height:40px;justify-content:flex-start" data-s="to"><option value="">Choose destination</option>${opt(NV.to)}</select>
      ${tog('acc', 'Step-free route', NV.accessible, 'Lift only, no stairs')}</div>${out}`;
  },
  layers() {
    const L = S.layers;
    return `<div class="sec"><h3>Visual</h3>${tog('L:visual', 'Visual mesh', L.visual, 'Textured model')}${slider('malpha', 'Mesh opacity', S.meshAlpha, 0, 1, 0.05, v => Math.round(v * 100) + '%')}</div>
    <div class="sec"><h3>Geometry</h3>${tog('L:points', 'Point cloud', L.points, 'Simulated scan, ' + DATA.cloud.n.toLocaleString() + ' pts')}${tog('L:collision', 'Collision boxes', L.collision, 'Walls, glass, columns, furniture')}${tog('L:walk', 'Walkable area', L.walk, '0.1 m grid, avatar-inflated')}${tog('L:cams', 'Capture cameras', L.cams, 'Green registered, red failed')}</div>
    <div class="sec"><h3>Semantic</h3>${tog('L:rooms', 'Room volumes', L.rooms)}${tog('L:pois', 'Place labels', L.pois)}</div>
    <div class="sec"><h3>Reference</h3>${tog('L:axes', 'Axes (X red, Y green, Z blue)', L.axes)}${tog('L:bounds', 'Building bounds', L.bounds)}<p class="note">All layers share one frame: Y up, metres, origin at the south-west ground corner.</p></div>`;
  },
  pois() {
    const by = {}; DATA.semantic.pois.forEach(p => (by[p.floor] = by[p.floor] || []).push(p));
    return [0, 1, 2].map(f => `<div class="sec"><h3>${esc(NAV.floorNames[f])}</h3><div class="list">${(by[f] || []).sort((a, b) => a.name.localeCompare(b.name)).map(p => `<button class="item" data-a="poi" data-v="${esc(p.poi_id)}">${poiPill(p)}<span style="flex:1;min-width:0">${esc(p.name)}</span><span class="pill">${esc(p.category)}</span></button>`).join('')}</div></div>`).join('');
  },
};

function panelClick(e) {
  const t = e.target.closest('[data-a],[data-t]'); if (!t) return;
  if (t.dataset.t) return toggle(t.dataset.t);
  const a = t.dataset.a, v = t.dataset.v;
  if (a === 'close') openTab(null);
  else if (a === 'view') viewPreset(v);
  else if (a === 'floor') { S.floors[+v] = !S.floors[+v]; if (!S.floors.some(Boolean)) S.floors[+v] = true; ISO = S.floors.every(Boolean) ? -1 : (S.floors.filter(Boolean).length === 1 ? S.floors.indexOf(true) : -2); renderElev(); renderPanel(); syncLabels(true); }
  else if (a === 'light') { S.light = v; document.documentElement.dataset.theme = v === 'day' ? 'light' : 'dark'; renderPanel(); }
  else if (a === 'rep') setRep(v);
  else if (a === 'pmode') { S.pointMode = +v; renderPanel(); }
  else if (a === 'navto') { NV.to = v; computeRoute(true); openTab('nav'); }
  else if (a === 'clearsel') clearSelection();
  else if (a === 'poi') selectPOI(poiById(v));
  else if (a === 'walkroute') startWalkRoute();
  else if (a === 'fitroute') fitRoute();
  else if (a === 'frame') jumpToFrame(+v);
}
function panelInput(e) {
  const s = e.target.dataset.s; if (!s) return; const v = e.target.value, n = parseFloat(v);
  if (s === 'explode') S.explode = n; else if (s === 'cut') S.cut = n; else if (s === 'glass') S.glass = n; else if (s === 'malpha') S.meshAlpha = n; else if (s === 'psize') S.pointSize = n;
  else if (s === 'from') { NV.from = v; computeRoute(false); renderPanel(); return; } else if (s === 'to') { NV.to = v || null; computeRoute(true); renderPanel(); return; }
  const out = e.target.closest('.sec').querySelector('.lab .mono'); if (out) { const tmp = document.createElement('div'); out.textContent = ({ explode: x => x.toFixed(1) + ' m', cut: x => x >= 0.999 ? 'off' : Math.round(x * 3 * H_FLOOR * 10) / 10 + ' m', glass: x => Math.round(x * 100) + '%', malpha: x => Math.round(x * 100) + '%', psize: x => x.toFixed(1) })[s](n); }
  if (s === 'cut') syncLabels(false);
}
function toggle(id) {
  if (id.startsWith('L:')) { const k = id.slice(2); S.layers[k] = !S.layers[k]; if (k === 'points' || k === 'visual') syncRep(); }
  else if (id === 'roof') S.showRoof = !S.showRoof; else if (id === 'site') S.showSite = !S.showSite; else if (id === 'fins') S.showFins = !S.showFins;
  else if (id === 'acc') { NV.accessible = !NV.accessible; computeRoute(false); }
  renderPanel();
}
function setRep(v) { S.rep = v; S.layers.visual = v !== 'points'; S.layers.points = v !== 'mesh'; S.pointAlpha = 1; S.meshAlpha = v === 'hybrid' ? 0.35 : 1; if (v === 'points') S.meshAlpha = 1; renderPanel(); }
function syncRep() { S.rep = S.layers.points && S.layers.visual ? 'hybrid' : S.layers.points ? 'points' : 'mesh'; }
function jumpToFrame(i) {
  const c = DATA.cameras[i]; S.selCam = i; S.layers.cams = true;
  if (S.mode !== 'walk') { S.mode = 'walk'; $('#modeOrbit').setAttribute('aria-pressed', false); $('#modeWalk').setAttribute('aria-pressed', true); }
  S.floors = [true, true, true]; ISO = -1; renderElev(); S.cut = 1;
  WK.floor = c.floor; WK.pos = [c.eye[0], c.eye[2]]; WK.y = c.eye[1]; WK.yaw = c.yaw; WK.pitch = c.pitch; WK._placed = true; WK.auto = false;
  renderPanel(); showHud('Camera set to simulated capture pose #' + i, 3500);
}

/* ---------- routing UI ---------- */
function computeRoute(fit) {
  const pois = DATA.semantic.pois;
  if (!NV.from) NV.from = 'poi-main-entrance';
  NV.route = null; NV.steps = null; NV.error = null; RS.ribbon.count = 0;
  if (!NV.to) return;
  const a = poiById(NV.from), b = poiById(NV.to); if (!a || !b) return;
  if (a.poi_id === b.poi_id) { NV.error = 'Start and destination are the same place.'; return; }
  const r = NAV.route([a.floor, a.nav_anchor.x, a.nav_anchor.z], [b.floor, b.nav_anchor.x, b.nav_anchor.z], NV.accessible);
  if (r.status !== 'ok') { NV.error = r.reason; return; }
  if (!r.validation.collisionFree) { NV.error = 'A route was found but failed the independent collision check, so it is not shown.'; return; }
  NV.route = r; NV.steps = NAV.describe(r, a.name, b.name); setRibbon(RS, NAV.path3d(r)); if (fit) fitRoute();
}
function fitRoute() {
  const P = NAV.path3d(NV.route); if (!P.length) return; let mn = [1e9, 1e9, 1e9], mx = [-1e9, -1e9, -1e9];
  P.forEach(q => q.p.forEach((v, i) => { mn[i] = Math.min(mn[i], v); mx[i] = Math.max(mx[i], v); }));
  if (S.mode === 'walk') setMode('orbit');
  flyTo({ target: [(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2 + 1, (mn[2] + mx[2]) / 2], dist: clamp(Math.max(mx[0] - mn[0], mx[2] - mn[2], (mx[1] - mn[1]) * 1.5) * 1.35 + 10, 16, 90), pitch: 0.8, yaw: 0.35 });
}
function startWalkRoute() {
  if (!NV.route) return; const a = poiById(NV.from);
  if (S.mode !== 'walk') { S.mode = 'walk'; $('#modeOrbit').setAttribute('aria-pressed', false); $('#modeWalk').setAttribute('aria-pressed', true); }
  S.floors = [true, true, true]; ISO = -1; S.cut = 1; renderElev();
  const path = NAV.path3d(NV.route); placeWalker([a.floor, a.nav_anchor.x, a.nav_anchor.z], WK.yaw); followPath(path);
  showHud('Walking the route. Any movement key takes control.', 4000); renderPanel();
}

/* ---------- search ---------- */
let resSel = -1, resList = [];
function bindSearch() {
  const q = $('#q'), box = $('#results');
  const draw = () => {
    resList = searchPOIs(DATA, q.value); resSel = resList.length ? 0 : -1;
    box.innerHTML = resList.length ? resList.map((p, i) => `<button class="res" role="option" aria-selected="${i === 0}" data-i="${i}">${poiPill(p)}<span>${esc(p.name)}</span><span class="fl">${esc(NAV.floorNames[p.floor])}</span></button>`).join('') : (q.value.trim() ? '<div class="empty">No matching place</div>' : '');
    box.classList.toggle('open', !!q.value.trim()); q.setAttribute('aria-expanded', !!q.value.trim());
  };
  const pick = i => { const p = resList[i]; if (!p) return; q.value = ''; box.classList.remove('open'); q.blur(); selectPOI(p); };
  q.addEventListener('input', draw); q.addEventListener('focus', draw);
  q.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); resSel = (resSel + (e.key === 'ArrowDown' ? 1 : -1) + resList.length) % Math.max(resList.length, 1); box.querySelectorAll('.res').forEach((b, i) => b.setAttribute('aria-selected', i === resSel)); }
    else if (e.key === 'Enter') pick(Math.max(resSel, 0)); else if (e.key === 'Escape') { q.value = ''; box.classList.remove('open'); q.blur(); }
  });
  box.addEventListener('pointerdown', e => { const b = e.target.closest('.res'); if (b) { e.preventDefault(); pick(+b.dataset.i); } });
  document.addEventListener('pointerdown', e => { if (!e.target.closest('.search')) box.classList.remove('open'); });
}

/* ---------- provenance, theme, fullscreen ---------- */
function bindChrome() {
  $('#provBadge').onclick = () => { openTab('recon'); showHud('Everything here is synthetic. The scan is simulated, not COLMAP output.', 6000); };
  $('#btnTheme').onclick = () => { const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'), nx = cur === 'dark' ? 'light' : 'dark'; document.documentElement.dataset.theme = nx; S.light = nx === 'light' ? 'day' : 'dusk'; try { localStorage.setItem('nt-theme', nx); } catch (_) {} if (S.tab === 'building') renderPanel(); };
  $('#btnFull').onclick = () => { try { document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen(); } catch (_) {} };
  $('#modeOrbit').onclick = () => setMode('orbit'); $('#modeWalk').onclick = () => setMode('walk'); $('#btnReset').onclick = resetCamera;
}

/* ---------- loop ---------- */
let lastT = 0, fpsAcc = 0, fpsN = 0, scaleCool = 0;
function resize() {
  const dpr = Math.min(window.devicePixelRatio || 1, 2) * renderScale, w = Math.max(2, Math.round(canvas.clientWidth * dpr)), h = Math.max(2, Math.round(canvas.clientHeight * dpr));
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  W = { w: canvas.clientWidth || 1, h: canvas.clientHeight || 1 };
}
function frame(t) {
  const dt = Math.min(0.1, (t - lastT) / 1000 || 0.016); lastT = t;
  resize(); if (S.mode === 'walk') updateWalk(dt); updateCamera(dt);
  const t0 = performance.now(), dn = renderFrame(SCENE, RS, CAMS, t / 1000, canvas.width, canvas.height); perf.prims = dn.prims; perf.tris = dn.tris;
  updateLabels();
  fpsAcc += dt; fpsN++; if (fpsAcc > 1) { perf.fps = fpsN / fpsAcc; fpsAcc = 0; fpsN = 0; scaleCool--; if (scaleCool <= 0 && perf.fps < 28 && renderScale > 0.55) { renderScale -= 0.15; scaleCool = 3; } }
  requestAnimationFrame(frame);
}

/* ---------- boot ---------- */
function bootProgress(p, m) { $('#bootBar').style.width = Math.round(p * 100) + '%'; $('#bootMsg').textContent = m; }
const tick = () => new Promise(r => setTimeout(r, 0));
async function boot() {
  try {
    try { const th = localStorage.getItem('nt-theme'); if (th) { document.documentElement.dataset.theme = th; S.light = th === 'light' ? 'day' : 'dusk'; } else document.documentElement.dataset.theme = 'dark'; } catch (_) { document.documentElement.dataset.theme = 'dark'; }
    canvas = $('#stage'); bootProgress(0.01, 'Starting renderer'); await tick(); initGL(canvas);
    DATA = await loadData((p, m) => bootProgress(p * 0.5, m)); await tick();
    bootProgress(0.5, 'Building routing grid'); NAV = new Nav(DATA); await tick();
    bootProgress(0.58, 'Uploading geometry'); SCENE = await buildScene(DATA.glb, (p, m) => bootProgress(0.58 + p * 0.3, m || 'Uploading geometry')); await tick();
    bootProgress(0.9, 'Preparing overlays'); RS = buildStatic(DATA);
    $('#sceneName').textContent = DATA.semantic.building.name.replace(/\s*\(synthetic\)/i, '');
    buildDock(); renderElev(); bindInput(); bindSearch(); bindChrome(); syncLabels(true); resize();
    window.addEventListener('resize', resize); openTab('explore');
    bootProgress(1, 'Ready'); requestAnimationFrame(t => { lastT = t; frame(t); }); setTimeout(() => $('#boot').classList.add('gone'), 250);
    window.__namma = { S, NV, WK, C, G, perf, get DATA() { return DATA; }, NAV, SCENE, RS, selectPOI, setMode, viewPreset, setIso, openTab, computeRoute, walkTo, jumpToFrame, setRep, poiById, flyTo, get ISO() { return ISO; }, ready: true };
  } catch (err) {
    console.error(err); const f = $('#fail'); f.style.display = 'block'; f.textContent = 'The viewer could not start: ' + (err && err.message ? err.message : err); $('#bootMsg').textContent = 'Failed'; window.__nammaError = String(err && err.stack || err);
  }
}
boot();
