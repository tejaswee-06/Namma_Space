/* NAMMA TWIN viewer: core (math, data decoding, GLB parsing). Dependency-free WebGL2. */
'use strict';
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, t) => a + (b - a) * t;
const H_FLOOR = 3.6;

/* ---------- 4x4 matrices (column-major, Float32Array) ---------- */
const M4 = {
  ident() { const o = new Float32Array(16); o[0] = o[5] = o[10] = o[15] = 1; return o; },
  mul(a, b) {
    const o = new Float32Array(16);
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
      let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k]; o[c * 4 + r] = s;
    }
    return o;
  },
  persp(fovy, asp, n, f) {
    const t = 1 / Math.tan(fovy / 2), o = new Float32Array(16);
    o[0] = t / asp; o[5] = t; o[10] = (f + n) / (n - f); o[11] = -1; o[14] = 2 * f * n / (n - f); return o;
  },
  ortho(l, r, b, t, n, f) {
    const o = new Float32Array(16);
    o[0] = 2 / (r - l); o[5] = 2 / (t - b); o[10] = -2 / (f - n);
    o[12] = -(r + l) / (r - l); o[13] = -(t + b) / (t - b); o[14] = -(f + n) / (f - n); o[15] = 1; return o;
  },
  look(e, t, u = [0, 1, 0]) {
    let f = [t[0] - e[0], t[1] - e[1], t[2] - e[2]]; const fl = Math.hypot(...f); f = f.map(v => v / fl);
    let s = [f[1] * u[2] - f[2] * u[1], f[2] * u[0] - f[0] * u[2], f[0] * u[1] - f[1] * u[0]]; const sl = Math.hypot(...s); s = s.map(v => v / sl);
    const w = [s[1] * f[2] - s[2] * f[1], s[2] * f[0] - s[0] * f[2], s[0] * f[1] - s[1] * f[0]];
    const d = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    return new Float32Array([s[0], w[0], -f[0], 0, s[1], w[1], -f[1], 0, s[2], w[2], -f[2], 0, -d(s, e), -d(w, e), d(f, e), 1]);
  },
  inv(m) {
    const o = new Float32Array(16), a = m;
    const b00 = a[0] * a[5] - a[1] * a[4], b01 = a[0] * a[6] - a[2] * a[4], b02 = a[0] * a[7] - a[3] * a[4], b03 = a[1] * a[6] - a[2] * a[5], b04 = a[1] * a[7] - a[3] * a[5], b05 = a[2] * a[7] - a[3] * a[6];
    const b06 = a[8] * a[13] - a[9] * a[12], b07 = a[8] * a[14] - a[10] * a[12], b08 = a[8] * a[15] - a[11] * a[12], b09 = a[9] * a[14] - a[10] * a[13], b10 = a[9] * a[15] - a[11] * a[13], b11 = a[10] * a[15] - a[11] * a[14];
    let d = b00 * b11 - b01 * b10 + b02 * b09 + b03 * b08 - b04 * b07 + b05 * b06; if (!d) return M4.ident(); d = 1 / d;
    o[0] = (a[5] * b11 - a[6] * b10 + a[7] * b09) * d; o[1] = (a[2] * b10 - a[1] * b11 - a[3] * b09) * d; o[2] = (a[13] * b05 - a[14] * b04 + a[15] * b03) * d; o[3] = (a[10] * b04 - a[9] * b05 - a[11] * b03) * d;
    o[4] = (a[6] * b08 - a[4] * b11 - a[7] * b07) * d; o[5] = (a[0] * b11 - a[2] * b08 + a[3] * b07) * d; o[6] = (a[14] * b02 - a[12] * b05 - a[15] * b01) * d; o[7] = (a[8] * b05 - a[10] * b02 + a[11] * b01) * d;
    o[8] = (a[4] * b10 - a[5] * b08 + a[7] * b06) * d; o[9] = (a[1] * b08 - a[0] * b10 - a[3] * b06) * d; o[10] = (a[12] * b04 - a[13] * b02 + a[15] * b00) * d; o[11] = (a[9] * b02 - a[8] * b04 - a[11] * b00) * d;
    o[12] = (a[5] * b07 - a[4] * b09 - a[6] * b06) * d; o[13] = (a[0] * b09 - a[1] * b07 + a[2] * b06) * d; o[14] = (a[13] * b01 - a[12] * b03 - a[14] * b00) * d; o[15] = (a[8] * b03 - a[9] * b01 + a[10] * b00) * d;
    return o;
  },
  xform(m, x, y, z, w = 1) {
    return [m[0] * x + m[4] * y + m[8] * z + m[12] * w, m[1] * x + m[5] * y + m[9] * z + m[13] * w, m[2] * x + m[6] * y + m[10] * z + m[14] * w, m[3] * x + m[7] * y + m[11] * z + m[15] * w];
  },
};

/* ---------- data ---------- */
function b64ToU8(b64) {
  const bin = atob(b64), u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  return u;
}
const embedded = id => { const el = document.getElementById(id); return el ? el.textContent.trim() : null; };
const embeddedJSON = id => { const t = embedded(id); return t ? JSON.parse(t) : null; };

function parseGLB(u8) {
  const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
  if (dv.getUint32(0, true) !== 0x46546C67) throw new Error('Not a GLB file');
  const jl = dv.getUint32(12, true);
  const json = JSON.parse(new TextDecoder().decode(u8.subarray(20, 20 + jl)));
  const bl = dv.getUint32(20 + jl, true);
  return { json, bin: u8.subarray(28 + jl, 28 + jl + bl) };
}

function decodeCloud(u8) {
  const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
  const hl = dv.getUint32(0, true);
  const hdr = JSON.parse(new TextDecoder().decode(u8.subarray(4, 4 + hl)));
  const n = hdr.n, off = 4 + hl, st = hdr.stride;
  const pos = new Float32Array(n * 3), attr = new Uint8Array(n * 4), fl = new Uint8Array(n);
  const [mn, mx] = [hdr.min, hdr.max];
  for (let i = 0; i < n; i++) {
    const o = off + i * st;
    const x = mn[0] + dv.getUint16(o, true) / 65535 * (mx[0] - mn[0]);
    const y = mn[1] + dv.getUint16(o + 2, true) / 65535 * (mx[1] - mn[1]);
    const z = mn[2] + dv.getUint16(o + 4, true) / 65535 * (mx[2] - mn[2]);
    pos[i * 3] = x; pos[i * 3 + 1] = y; pos[i * 3 + 2] = z;
    attr[i * 4] = u8[o + 6]; attr[i * 4 + 1] = u8[o + 7]; attr[i * 4 + 2] = u8[o + 8]; attr[i * 4 + 3] = u8[o + 9];
    fl[i] = clamp(Math.floor((y + 0.2) / H_FLOOR), 0, 2);
  }
  return { n, pos, attr, fl, hdr };
}

async function loadData(progress) {
  const D = {};
  progress(0.02, 'Decoding building model');
  D.glb = parseGLB(b64ToU8(embedded('d-visual')));
  D.semantic = embeddedJSON('d-semantic');
  D.nav = embeddedJSON('d-nav');
  D.colliders = embeddedJSON('d-colliders').colliders;
  progress(0.18, 'Decoding simulated scan');
  D.cloud = decodeCloud(b64ToU8(embedded('d-cloud')));
  D.cameras = embeddedJSON('d-cameras');
  D.report = embeddedJSON('d-report');
  D.reg = embeddedJSON('d-reg');
  D.frames = embeddedJSON('d-frames') || {};
  return D;
}
