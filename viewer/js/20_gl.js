/* NAMMA TWIN viewer: renderer (WebGL2). Shadow map, glass, point cloud, lines, route ribbon, walkability overlay. */
const S = {
  floors: [true, true, true], showRoof: true, showSite: true, showFins: true, explode: 0, cut: 1, glass: 1,
  rep: 'mesh', layers: { visual: true, points: false, collision: false, walk: false, rooms: false, pois: true, cams: false, axes: false, bounds: false },
  meshAlpha: 1, pointAlpha: 1, pointSize: 3.2, pointMode: 0, light: 'dusk', mode: 'orbit', sel: null, route: null, tab: null, selCam: -1,
};
const LIGHTS = {
  day: { sunDir: [-0.35, 0.78, 0.52], sunCol: [2.5, 2.3, 2.0], sky: [0.50, 0.62, 0.80], ground: [0.32, 0.30, 0.27], amb: 0.78, lamp: 0.25, emis: 1.4,
    fog: [0.75, 0.82, 0.90], fogK: 0.0035, horizon: [0.80, 0.87, 0.94], zenith: [0.30, 0.52, 0.84], sunGlow: 1.0, shadowR: 46 },
  dusk: { sunDir: [0.62, 0.30, 0.74], sunCol: [2.0, 1.05, 0.55], sky: [0.20, 0.26, 0.46], ground: [0.12, 0.10, 0.10], amb: 0.85, lamp: 1.05, emis: 2.6,
    fog: [0.10, 0.12, 0.19], fogK: 0.0045, horizon: [0.90, 0.52, 0.36], zenith: [0.04, 0.06, 0.15], sunGlow: 0.9, shadowR: 62 },
};
const CENTER = [18, 5, 10];
let gl, PR = {}, SH = { tex: null, fbo: null, size: 2048 }, WHITE = null;

const VS_MAIN = `#version 300 es
layout(location=0) in vec3 aPos; layout(location=1) in vec3 aNrm; layout(location=2) in vec2 aUV;
uniform mat4 uVP; uniform mat4 uSunVP; uniform float uOffY;
out vec3 vW; out vec3 vN; out vec2 vUV; out vec4 vSh;
void main(){ vec3 p=aPos+vec3(0.,uOffY,0.); vW=p; vN=aNrm; vUV=aUV;
  vSh=uSunVP*vec4(p+aNrm*0.06,1.); gl_Position=uVP*vec4(p,1.); }`;
const FS_MAIN = `#version 300 es
precision highp float; precision highp sampler2DShadow;
in vec3 vW; in vec3 vN; in vec2 vUV; in vec4 vSh;
uniform sampler2D uTex; uniform sampler2DShadow uShadow;
uniform vec4 uColor; uniform vec3 uEmis; uniform float uHasTex; uniform float uMode; uniform float uAlphaMul;
uniform vec3 uCam, uSunDir, uSunCol, uSkyCol, uGroundCol, uFogCol; uniform float uFog, uClipY, uEmisGain, uAmb, uLamp, uDoShadow;
out vec4 o;
float shadow(){ vec3 p=vSh.xyz/vSh.w*0.5+0.5; if(p.z>1.||p.x<0.||p.x>1.||p.y<0.||p.y>1.) return 1.;
  float s=0.; float t=1./2048.; for(int i=-1;i<=1;i++) for(int j=-1;j<=1;j++) s+=texture(uShadow,vec3(p.xy+vec2(float(i),float(j))*t*1.4,p.z-0.0009)); return s/9.; }
vec3 aces(vec3 x){ return clamp((x*(2.51*x+0.03))/(x*(2.43*x+0.59)+0.14),0.,1.); }
void main(){
  if(vW.y>uClipY) discard;
  vec3 n=normalize(vN); if(!gl_FrontFacing) n=-n;
  vec3 V=normalize(uCam-vW);
  vec4 tex=vec4(1.); if(uHasTex>0.5){ tex=texture(uTex,vUV); tex.rgb=pow(tex.rgb,vec3(2.2)); }
  vec3 base=uColor.rgb*tex.rgb;
  float sh=uDoShadow>0.5?shadow():1.;
  vec3 hemi=mix(uGroundCol,uSkyCol,n.y*0.5+0.5);
  float ndl=max(dot(n,uSunDir),0.);
  vec3 lit=base*(hemi*uAmb+uSunCol*ndl*sh);
  lit+=base*vec3(1.0,0.84,0.62)*uLamp*(1.-sh)*(0.42+0.5*max(n.y,0.)+0.25*max(-n.y,0.));
  lit+=uEmis*uEmisGain;
  float a=1.;
  if(uMode>0.5 && uMode<1.5){ float f=pow(1.-max(dot(n,V),0.),3.); lit=mix(lit,uSkyCol*1.4+uSunCol*0.05,f*0.55); a=clamp(uColor.a*uAlphaMul+f*0.38*uAlphaMul,0.,0.9); }
  else if(uMode>1.5){ a=uAlphaMul*(0.55+0.45*pow(1.-max(dot(n,V),0.),2.)); }
  float d=length(vW-uCam); lit=mix(lit,uFogCol,1.-exp(-d*uFog));
  lit=pow(aces(lit),vec3(1./2.2));
  o=vec4(lit,a);
}`;
const VS_DEPTH = `#version 300 es
layout(location=0) in vec3 aPos; uniform mat4 uSunVP; uniform float uOffY; uniform float uClipY;
out float vY; void main(){ vec3 p=aPos+vec3(0.,uOffY,0.); vY=p.y; gl_Position=uSunVP*vec4(p,1.); }`;
const FS_DEPTH = `#version 300 es
precision mediump float; in float vY; uniform float uClipY; void main(){ if(vY>uClipY) discard; }`;
const VS_SKY = `#version 300 es
out vec2 vP; void main(){ vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2); vP=p*2.-1.; gl_Position=vec4(vP,1.,1.); }`;
const FS_SKY = `#version 300 es
precision highp float; in vec2 vP; uniform mat4 uInvVP; uniform vec3 uCam,uHorizon,uZenith,uSunDir,uSunCol,uGround; uniform float uGlow;
out vec4 o; vec3 aces(vec3 x){ return clamp((x*(2.51*x+0.03))/(x*(2.43*x+0.59)+0.14),0.,1.); }
void main(){ vec4 f=uInvVP*vec4(vP,1.,1.); vec3 d=normalize(f.xyz/f.w-uCam);
  float t=clamp(d.y,0.,1.); vec3 c=mix(uHorizon,uZenith,pow(t,0.45));
  if(d.y<0.) c=mix(uHorizon,uGround*1.2,clamp(-d.y*3.,0.,1.));
  c+=uSunCol*uGlow*0.12*pow(max(dot(d,uSunDir),0.),48.)+uSunCol*uGlow*0.6*pow(max(dot(d,uSunDir),0.),600.);
  o=vec4(pow(aces(c),vec3(1./2.2)),1.); }`;
const VS_PTS = `#version 300 es
layout(location=0) in vec3 aPos; layout(location=1) in vec4 aAttr; layout(location=2) in float aFloor;
uniform mat4 uVP; uniform float uExplode,uClipY,uSize,uPx; uniform int uMask,uMode;
out vec3 vC;
vec3 pal(float t){ return 0.5+0.5*cos(6.28318*(vec3(1.,1.,1.)*t+vec3(0.0,0.33,0.67))); }
void main(){ int fl=int(aFloor+0.5);
  if(((uMask>>fl)&1)==0){ gl_Position=vec4(2.,2.,2.,1.); return; }
  vec3 p=aPos; p.y+=uExplode*float(fl);
  if(p.y>uClipY){ gl_Position=vec4(2.,2.,2.,1.); return; }
  vec4 c=uVP*vec4(p,1.); gl_Position=c; gl_PointSize=clamp(uSize*uPx/max(c.w,0.5),1.6,16.);
  if(uMode==0) vC=aAttr.rgb;
  else if(uMode==1) vC=pal(clamp(aPos.y/11.,0.,1.)*0.8+0.05);
  else { float cf=clamp((aAttr.a*255.-2.)/10.,0.,1.); vC=mix(vec3(0.95,0.25,0.2),mix(vec3(0.98,0.8,0.2),vec3(0.25,0.85,0.5),smoothstep(0.5,1.,cf)),smoothstep(0.,0.5,cf)); } }`;
const FS_PTS = `#version 300 es
precision mediump float; in vec3 vC; uniform float uOpacity; out vec4 o;
void main(){ vec2 q=gl_PointCoord-0.5; float r=dot(q,q); if(r>0.25) discard; o=vec4(vC,uOpacity*(1.-smoothstep(0.16,0.25,r))); }`;
const VS_LINE = `#version 300 es
layout(location=0) in vec3 aPos; layout(location=1) in vec4 aCol; uniform mat4 uVP; uniform float uOffY;
out vec4 vC; out float vY; void main(){ vec3 p=aPos+vec3(0.,uOffY,0.); vY=p.y; vC=aCol; gl_Position=uVP*vec4(p,1.); }`;
const FS_LINE = `#version 300 es
precision mediump float; in vec4 vC; in float vY; uniform float uClipY,uAlpha; out vec4 o; void main(){ if(vY>uClipY) discard; o=vec4(vC.rgb,vC.a*uAlpha); }`;
const VS_RIB = `#version 300 es
layout(location=0) in vec3 aPos; layout(location=1) in float aV; layout(location=2) in float aSide; layout(location=3) in float aFloor;
uniform mat4 uVP; uniform float uExplode; out float vV; out float vS;
void main(){ vV=aV; vS=aSide; vec3 p=aPos; p.y+=uExplode*aFloor; gl_Position=uVP*vec4(p,1.); gl_Position.z-=0.0004*gl_Position.w; }`;
const FS_RIB = `#version 300 es
precision mediump float; in float vV; in float vS; uniform float uTime; uniform vec3 uColor; out vec4 o;
void main(){ float e=1.-smoothstep(0.6,1.,abs(vS)); float st=smoothstep(0.25,0.5,abs(fract(vV*1.7-uTime*0.8)-0.5));
  vec3 c=mix(uColor,vec3(1.),st*0.55); o=vec4(c,e*0.95); }`;
const VS_NAV = `#version 300 es
layout(location=0) in vec3 aPos; layout(location=1) in vec2 aUV; uniform mat4 uVP; uniform float uOffY; out vec2 vUV; out float vY;
void main(){ vUV=aUV; vec3 p=aPos+vec3(0.,uOffY,0.); vY=p.y; gl_Position=uVP*vec4(p,1.); }`;
const FS_NAV = `#version 300 es
precision mediump float; in vec2 vUV; in float vY; uniform sampler2D uMask; uniform vec3 uColor; uniform float uClipY,uAlpha; out vec4 o;
void main(){ if(vY>uClipY) discard; float m=texture(uMask,vUV).r; if(m<0.5) discard; o=vec4(uColor,0.36*uAlpha); }`;

function compile(type, src) {
  const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error('Shader error: ' + gl.getShaderInfoLog(s));
  return s;
}
function program(vs, fs, names) {
  const p = gl.createProgram(); gl.attachShader(p, compile(gl.VERTEX_SHADER, vs)); gl.attachShader(p, compile(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error('Link error: ' + gl.getProgramInfoLog(p));
  const u = {}; for (const n of names) u[n] = gl.getUniformLocation(p, n);
  return { p, u };
}
function buf(target, data, usage = gl.STATIC_DRAW) { const b = gl.createBuffer(); gl.bindBuffer(target, b); gl.bufferData(target, data, usage); return b; }

function initGL(canvas) {
  gl = canvas.getContext('webgl2', { antialias: true, alpha: false, powerPreference: 'high-performance', preserveDrawingBuffer: false });
  if (!gl) throw new Error('WebGL2 is not available in this browser. Try a current version of Chrome, Edge, Firefox or Safari.');
  PR.main = program(VS_MAIN, FS_MAIN, ['uVP', 'uSunVP', 'uOffY', 'uTex', 'uShadow', 'uColor', 'uEmis', 'uHasTex', 'uMode', 'uAlphaMul', 'uCam', 'uSunDir', 'uSunCol', 'uSkyCol', 'uGroundCol', 'uFogCol', 'uFog', 'uClipY', 'uEmisGain', 'uAmb', 'uLamp', 'uDoShadow']);
  PR.depth = program(VS_DEPTH, FS_DEPTH, ['uSunVP', 'uOffY', 'uClipY']);
  PR.sky = program(VS_SKY, FS_SKY, ['uInvVP', 'uCam', 'uHorizon', 'uZenith', 'uSunDir', 'uSunCol', 'uGround', 'uGlow']);
  PR.pts = program(VS_PTS, FS_PTS, ['uVP', 'uExplode', 'uClipY', 'uSize', 'uPx', 'uMask', 'uMode', 'uOpacity']);
  PR.line = program(VS_LINE, FS_LINE, ['uVP', 'uOffY', 'uClipY', 'uAlpha']);
  PR.rib = program(VS_RIB, FS_RIB, ['uVP', 'uExplode', 'uTime', 'uColor']);
  PR.nav = program(VS_NAV, FS_NAV, ['uVP', 'uOffY', 'uMask', 'uColor', 'uClipY', 'uAlpha']);
  // shadow map
  SH.tex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, SH.tex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.DEPTH_COMPONENT24, SH.size, SH.size, 0, gl.DEPTH_COMPONENT, gl.UNSIGNED_INT, null);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_COMPARE_MODE, gl.COMPARE_REF_TO_TEXTURE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_COMPARE_FUNC, gl.LEQUAL);
  SH.fbo = gl.createFramebuffer(); gl.bindFramebuffer(gl.FRAMEBUFFER, SH.fbo);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.TEXTURE_2D, SH.tex, 0);
  gl.drawBuffers([gl.NONE]); gl.readBuffer(gl.NONE);
  if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) console.warn('Shadow framebuffer incomplete; shadows disabled');
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  WHITE = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, WHITE);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([255, 255, 255, 255]));
  gl.bindVertexArray(null);
  return gl;
}

/* ---------- building scene from GLB ---------- */
async function buildScene(glb, progress) {
  const { json, bin } = glb;
  const acc = i => {
    const a = json.accessors[i], v = json.bufferViews[a.bufferView];
    const n = { SCALAR: 1, VEC2: 2, VEC3: 3 }[a.type], C = a.componentType === 5126 ? Float32Array : Uint32Array;
    return { arr: new C(bin.buffer, bin.byteOffset + (v.byteOffset || 0) + (a.byteOffset || 0), a.count * n), a };
  };
  const texs = [];
  const aniso = gl.getExtension('EXT_texture_filter_anisotropic');
  for (let i = 0; i < json.textures.length; i++) {
    const im = json.images[json.textures[i].source], v = json.bufferViews[im.bufferView];
    const blob = new Blob([bin.subarray(v.byteOffset, v.byteOffset + v.byteLength)], { type: im.mimeType });
    const bmp = await createImageBitmap(blob);
    const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, bmp);
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.REPEAT);
    if (aniso) gl.texParameterf(gl.TEXTURE_2D, aniso.TEXTURE_MAX_ANISOTROPY_EXT, Math.min(8, gl.getParameter(aniso.MAX_TEXTURE_MAX_ANISOTROPY_EXT)));
    texs.push(t); bmp.close && bmp.close();
    progress && progress((i + 1) / json.textures.length);
  }
  const prims = [];
  const walk = (ni, ctx) => {
    const n = json.nodes[ni], ex = n.extras || {};
    const c = { floor: ex.floor !== undefined ? ex.floor : ctx.floor, kind: ex.kind || ctx.kind, room: ex.room || (ex.kind === 'room' ? ex.id : ctx.room), name: n.name };
    if (n.mesh !== undefined) {
      for (const p of json.meshes[n.mesh].primitives) {
        const P = acc(p.attributes.POSITION), N = acc(p.attributes.NORMAL), U = acc(p.attributes.TEXCOORD_0), I = acc(p.indices);
        const vao = gl.createVertexArray(); gl.bindVertexArray(vao);
        buf(gl.ARRAY_BUFFER, P.arr); gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
        buf(gl.ARRAY_BUFFER, N.arr); gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 3, gl.FLOAT, false, 0, 0);
        buf(gl.ARRAY_BUFFER, U.arr); gl.enableVertexAttribArray(2); gl.vertexAttribPointer(2, 2, gl.FLOAT, false, 0, 0);
        buf(gl.ELEMENT_ARRAY_BUFFER, I.arr);
        gl.bindVertexArray(null);
        const m = json.materials[p.material], pb = m.pbrMetallicRoughness;
        const ti = pb.baseColorTexture ? pb.baseColorTexture.index : -1;
        prims.push({ vao, count: I.arr.length, floor: c.floor === undefined ? -1 : c.floor, kind: c.kind || '', room: c.room || '', name: c.name,
          color: pb.baseColorFactor, emissive: m.emissiveFactor || [0, 0, 0], tex: ti >= 0 ? texs[ti] : null, glass: m.alphaMode === 'BLEND',
          bmin: P.a.min, bmax: P.a.max, tris: I.arr.length / 3 });
      }
    }
    for (const ch of (n.children || [])) walk(ch, c);
  };
  for (const r of json.scenes[0].nodes) walk(r, { floor: -1, kind: '', room: '' });
  return prims;
}

/* ---------- static overlays ---------- */
function lineBatch(floor, verts) {
  const vao = gl.createVertexArray(); gl.bindVertexArray(vao);
  buf(gl.ARRAY_BUFFER, new Float32Array(verts));
  gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 28, 0);
  gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 4, gl.FLOAT, false, 28, 12);
  gl.bindVertexArray(null);
  return { floor, vao, count: verts.length / 7 };
}
const BOX_EDGES = [[0, 1], [1, 3], [3, 2], [2, 0], [4, 5], [5, 7], [7, 6], [6, 4], [0, 4], [1, 5], [2, 6], [3, 7]];
function boxLines(out, mn, mx, c) {
  const P = []; for (let i = 0; i < 8; i++) P.push([i & 1 ? mx[0] : mn[0], i & 2 ? mx[1] : mn[1], i & 4 ? mx[2] : mn[2]]);
  for (const [a, b] of BOX_EDGES) out.push(...P[a], ...c, ...P[b], ...c);
}
const CAT_COL = { Laboratory: [0.35, 0.75, 1.0], Office: [0.9, 0.75, 0.45], Lecture: [0.8, 0.5, 0.95], Entrance: [0.4, 0.95, 0.6], Dining: [1.0, 0.6, 0.4], Library: [0.55, 0.85, 0.5], Meeting: [0.95, 0.55, 0.7],
  Washroom: [0.5, 0.8, 0.9], Stairs: [0.7, 0.7, 0.75], Lift: [0.7, 0.7, 0.75], Service: [0.9, 0.9, 0.5], Circulation: [0.75, 0.75, 0.75], Exit: [1.0, 0.4, 0.4] };
const catCol = c => CAT_COL[c] || [0.8, 0.8, 0.8];

function buildStatic(D) {
  const R = { collision: [], rooms: [], cams: [], axes: null, bounds: null, nav: [], points: null, ribbon: null };
  const KC = { wall: [1.0, 0.62, 0.25, 0.7], glass: [0.4, 0.7, 1.0, 0.7], column: [1.0, 0.4, 0.6, 0.8], furniture: [0.3, 0.95, 0.85, 0.7], step: [0.75, 0.55, 1.0, 0.7] };
  const byF = [[], [], []];
  for (const c of D.colliders) { if (c.kind === 'slab' || c.floor > 2) continue; boxLines(byF[c.floor], c.min, c.max, KC[c.kind] || [1, 1, 1, 0.6]); }
  byF.forEach((v, f) => R.collision.push(lineBatch(f, v)));
  const rF = [[], [], []];
  for (const r of D.semantic.rooms) {
    const b = r.bounds, y0 = r.floor * H_FLOOR, c = catCol(r.category);
    boxLines(rF[r.floor], [b.x0, y0 + 0.02, b.z0], [b.x1, y0 + 3.25, b.z1], [...c, 0.85]);
  }
  rF.forEach((v, f) => R.rooms.push(lineBatch(f, v)));
  // camera frustums (simulated capture path)
  const cF = [[], [], []]; const hw = Math.tan(36 * Math.PI / 180), hh = hw * 9 / 16, L = 0.4;
  for (const c of D.cameras) {
    const e = c.eye, cp = Math.cos(c.pitch), f = [Math.sin(c.yaw) * cp, Math.sin(c.pitch), Math.cos(c.yaw) * cp];
    let r = [f[2], 0, -f[0]]; const rl = Math.hypot(r[0], r[2]) || 1; r = [r[0] / rl, 0, r[2] / rl];
    const u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]];
    const col = c.registered ? [0.42, 0.9, 0.62, 0.8] : [1.0, 0.42, 0.38, 0.8];
    const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([sx, sy]) => [e[0] + (f[0] + r[0] * sx * hw + u[0] * sy * hh) * L, e[1] + (f[1] + r[1] * sx * hw + u[1] * sy * hh) * L, e[2] + (f[2] + r[2] * sx * hw + u[2] * sy * hh) * L]);
    const out = cF[clamp(c.floor, 0, 2)];
    for (let i = 0; i < 4; i++) { out.push(...e, ...col, ...corners[i], ...col); out.push(...corners[i], ...col, ...corners[(i + 1) % 4], ...col); }
  }
  cF.forEach((v, f) => R.cams.push(lineBatch(f, v)));
  const ax = []; ax.push(0, 0.02, 0, 1, .3, .3, 1, 6, 0.02, 0, 1, .3, .3, 1, 0, 0.02, 0, .4, 1, .4, 1, 0, 6, 0, .4, 1, .4, 1, 0, 0.02, 0, .4, .6, 1, 1, 0, 0.02, 6, .4, .6, 1, 1);
  R.axes = lineBatch(-1, ax);
  const bd = []; boxLines(bd, [0, 0, 0], [36, 3 * H_FLOOR, 20], [1, 1, 1, 0.5]); R.bounds = lineBatch(-1, bd);
  // walkability textures
  const N = D.nav, nx = N.size[0], nz = N.size[1], res = N.resolution_m;
  N.floors.forEach(fl => {
    const bits = b64ToU8(fl.mask), data = new Uint8Array(nx * nz);
    for (let i = 0; i < nx * nz; i++) data[i] = (bits[i >> 3] >> (7 - (i & 7))) & 1 ? 255 : 0;
    const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, nx, nz, 0, gl.RED, gl.UNSIGNED_BYTE, data);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const x0 = N.origin[0], z0 = N.origin[1], x1 = x0 + nx * res, z1 = z0 + nz * res, y = fl.floor * H_FLOOR + 0.03;
    const vao = gl.createVertexArray(); gl.bindVertexArray(vao);
    buf(gl.ARRAY_BUFFER, new Float32Array([x0, y, z0, 0, 0, x1, y, z0, 1, 0, x1, y, z1, 1, 1, x0, y, z0, 0, 0, x1, y, z1, 1, 1, x0, y, z1, 0, 1]));
    gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 20, 0); gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 2, gl.FLOAT, false, 20, 12);
    gl.bindVertexArray(null);
    R.nav.push({ floor: fl.floor, tex: t, vao });
  });
  // point cloud
  const C = D.cloud, pv = gl.createVertexArray(); gl.bindVertexArray(pv);
  buf(gl.ARRAY_BUFFER, C.pos); gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
  buf(gl.ARRAY_BUFFER, C.attr); gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 4, gl.UNSIGNED_BYTE, true, 0, 0);
  buf(gl.ARRAY_BUFFER, C.fl); gl.enableVertexAttribArray(2); gl.vertexAttribPointer(2, 1, gl.UNSIGNED_BYTE, false, 0, 0);
  gl.bindVertexArray(null); R.points = { vao: pv, n: C.n };
  // ribbon (dynamic)
  const rv = gl.createVertexArray(); gl.bindVertexArray(rv); const rb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, rb);
  gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 24, 0); gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 1, gl.FLOAT, false, 24, 12);
  gl.enableVertexAttribArray(2); gl.vertexAttribPointer(2, 1, gl.FLOAT, false, 24, 16); gl.enableVertexAttribArray(3); gl.vertexAttribPointer(3, 1, gl.FLOAT, false, 24, 20);
  gl.bindVertexArray(null); R.ribbon = { vao: rv, buf: rb, count: 0 };
  return R;
}

function setRibbon(R, path3d) {
  // path3d: [{p:[x,y,z], floor}] -> triangle ribbon of width 0.3 m
  const v = []; let dist = 0;
  for (let i = 0; i < path3d.length - 1; i++) {
    const a = path3d[i], b = path3d[i + 1], dx = b.p[0] - a.p[0], dz = b.p[2] - a.p[2], len = Math.hypot(dx, dz, b.p[1] - a.p[1]) || 1e-6;
    const hl = Math.hypot(dx, dz) || 1e-6, nx = -dz / hl * 0.15, nz = dx / hl * 0.15, d0 = dist, d1 = dist + len;
    const q = (pt, s, d, f) => [pt[0] + nx * s, pt[1] + 0.06, pt[2] + nz * s, d, s, f];
    const A = q(a.p, 1, d0, a.floor), B = q(a.p, -1, d0, a.floor), C = q(b.p, 1, d1, b.floor), E = q(b.p, -1, d1, b.floor);
    v.push(...A, ...B, ...C, ...B, ...E, ...C); dist = d1;
  }
  gl.bindBuffer(gl.ARRAY_BUFFER, R.ribbon.buf); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(v), gl.DYNAMIC_DRAW); R.ribbon.count = v.length / 6;
}

/* ---------- frame ---------- */
const offY = f => (f < 0 ? 0 : f * S.explode);
function floorVisible(p) {
  if (p.kind === 'roof') return S.showRoof && S.floors.every(Boolean) || (S.showRoof && S.floors[2]);
  if (p.floor < 0) return S.showSite;
  if (p.kind === 'facade_fins' && !S.showFins) return false;
  return S.floors[p.floor];
}
function sunMatrix(L) {
  const d = L.sunDir, n = Math.hypot(...d), s = d.map(v => v / n), r = L.shadowR;
  const eye = [CENTER[0] + s[0] * 90, CENTER[1] + 8 + s[1] * 90, CENTER[2] + s[2] * 90];
  return M4.mul(M4.ortho(-r, r, -r, r, 1, 200), M4.look(eye, [CENTER[0], CENTER[1] + 2, CENTER[2]]));
}
function setupMain(cam, L, sunVP, clipY) {
  const u = PR.main.u;
  gl.uniformMatrix4fv(u.uVP, false, cam.vp); gl.uniformMatrix4fv(u.uSunVP, false, sunVP);
  gl.uniform3fv(u.uCam, cam.eye); const sd = L.sunDir, sl = Math.hypot(...sd); gl.uniform3f(u.uSunDir, sd[0] / sl, sd[1] / sl, sd[2] / sl);
  gl.uniform3fv(u.uSunCol, L.sunCol); gl.uniform3fv(u.uSkyCol, L.sky); gl.uniform3fv(u.uGroundCol, L.ground); gl.uniform3fv(u.uFogCol, L.fog);
  gl.uniform1f(u.uFog, L.fogK); gl.uniform1f(u.uClipY, clipY); gl.uniform1f(u.uEmisGain, L.emis); gl.uniform1f(u.uAmb, L.amb); gl.uniform1f(u.uLamp, L.lamp);
  gl.uniform1i(u.uTex, 0); gl.uniform1i(u.uShadow, 1);
  gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, SH.tex); gl.activeTexture(gl.TEXTURE0);
}
function drawPrim(p, mode, alphaMul) {
  const u = PR.main.u;
  gl.uniform4fv(u.uColor, p.color); gl.uniform3fv(u.uEmis, p.emissive); gl.uniform1f(u.uHasTex, p.tex ? 1 : 0);
  gl.uniform1f(u.uMode, mode); gl.uniform1f(u.uAlphaMul, alphaMul); gl.uniform1f(u.uOffY, offY(p.floor));
  gl.bindTexture(gl.TEXTURE_2D, p.tex || WHITE);
  gl.bindVertexArray(p.vao); gl.drawElements(gl.TRIANGLES, p.count, gl.UNSIGNED_INT, 0);
}

let lastShadowKey = '';
function renderFrame(scene, R, cam, time, W, Hh) {
  const L = LIGHTS[S.light], sunVP = sunMatrix(L), clipY = S.cut >= 0.999 ? 1e4 : S.cut * 3 * H_FLOOR + 0.2;
  const meshOn = S.layers.visual && S.meshAlpha > 0.01, solid = meshOn && S.meshAlpha > 0.95;
  // ---- shadow pass
  const key = [S.light, S.explode, S.floors.join(), S.showRoof, S.showSite, S.showFins, clipY, meshOn].join('|');
  if (solid) {
    gl.bindFramebuffer(gl.FRAMEBUFFER, SH.fbo); gl.viewport(0, 0, SH.size, SH.size); gl.clear(gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST); gl.depthMask(true); gl.disable(gl.BLEND); gl.enable(gl.POLYGON_OFFSET_FILL); gl.polygonOffset(2, 4);
    gl.useProgram(PR.depth.p); gl.uniformMatrix4fv(PR.depth.u.uSunVP, false, sunVP); gl.uniform1f(PR.depth.u.uClipY, clipY);
    for (const p of scene) { if (p.glass || !floorVisible(p)) continue; gl.uniform1f(PR.depth.u.uOffY, offY(p.floor)); gl.bindVertexArray(p.vao); gl.drawElements(gl.TRIANGLES, p.count, gl.UNSIGNED_INT, 0); }
    gl.disable(gl.POLYGON_OFFSET_FILL); gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  }
  gl.viewport(0, 0, W, Hh);
  gl.clearColor(0, 0, 0, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  // ---- sky
  gl.disable(gl.DEPTH_TEST); gl.disable(gl.BLEND); gl.useProgram(PR.sky.p);
  const su = PR.sky.u, sd = L.sunDir, sl = Math.hypot(...sd);
  gl.uniformMatrix4fv(su.uInvVP, false, cam.invVP); gl.uniform3fv(su.uCam, cam.eye); gl.uniform3fv(su.uHorizon, L.horizon); gl.uniform3fv(su.uZenith, L.zenith);
  gl.uniform3f(su.uSunDir, sd[0] / sl, sd[1] / sl, sd[2] / sl); gl.uniform3fv(su.uSunCol, L.sunCol); gl.uniform3fv(su.uGround, L.ground); gl.uniform1f(su.uGlow, L.sunGlow);
  gl.bindVertexArray(null); gl.drawArrays(gl.TRIANGLES, 0, 3);
  gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LEQUAL);
  // ---- opaque mesh
  const drawn = { prims: 0, tris: 0 };
  if (meshOn) {
    gl.useProgram(PR.main.p); setupMain(cam, L, sunVP, clipY); gl.uniform1f(PR.main.u.uDoShadow, solid ? 1 : 0);
    if (solid) {
      gl.disable(gl.BLEND); gl.depthMask(true);
      for (const p of scene) { if (p.glass || !floorVisible(p)) continue; drawPrim(p, 0, 1); drawn.prims++; drawn.tris += p.tris; }
    } else {
      gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); gl.depthMask(false);
      for (const p of scene) { if (!floorVisible(p)) continue; drawPrim(p, 2, S.meshAlpha * 0.5); drawn.prims++; drawn.tris += p.tris; }
    }
  }
  // ---- walkability overlay
  gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); gl.depthMask(false);
  if (S.layers.walk) {
    gl.useProgram(PR.nav.p); gl.uniformMatrix4fv(PR.nav.u.uVP, false, cam.vp); gl.uniform1f(PR.nav.u.uClipY, clipY); gl.uniform1i(PR.nav.u.uMask, 2); gl.uniform3f(PR.nav.u.uColor, 0.2, 0.9, 0.7); gl.uniform1f(PR.nav.u.uAlpha, 1);
    gl.activeTexture(gl.TEXTURE2);
    for (const n of R.nav) { if (!S.floors[n.floor]) continue; gl.bindTexture(gl.TEXTURE_2D, n.tex); gl.uniform1f(PR.nav.u.uOffY, offY(n.floor)); gl.bindVertexArray(n.vao); gl.drawArrays(gl.TRIANGLES, 0, 6); }
    gl.activeTexture(gl.TEXTURE0);
  }
  // ---- point cloud
  if (S.layers.points) {
    gl.useProgram(PR.pts.p); const u = PR.pts.u; gl.uniformMatrix4fv(u.uVP, false, cam.vp); gl.uniform1f(u.uExplode, S.explode); gl.uniform1f(u.uClipY, clipY);
    gl.uniform1f(u.uSize, S.pointSize); gl.uniform1f(u.uPx, cam.pxScale); gl.uniform1i(u.uMask, S.floors.reduce((m, v, i) => m | (v ? 1 << i : 0), 0)); gl.uniform1i(u.uMode, S.pointMode); gl.uniform1f(u.uOpacity, S.pointAlpha);
    gl.depthMask(S.pointAlpha > 0.95); gl.bindVertexArray(R.points.vao); gl.drawArrays(gl.POINTS, 0, R.points.n);
  }
  // ---- glass (back to front)
  if (meshOn && solid) {
    gl.useProgram(PR.main.p); setupMain(cam, L, sunVP, clipY); gl.uniform1f(PR.main.u.uDoShadow, 0); gl.depthMask(false); gl.enable(gl.BLEND);
    const gl_ = []; for (const p of scene) { if (!p.glass || !floorVisible(p)) continue; const cx = (p.bmin[0] + p.bmax[0]) / 2, cy = (p.bmin[1] + p.bmax[1]) / 2 + offY(p.floor), cz = (p.bmin[2] + p.bmax[2]) / 2; gl_.push([Math.hypot(cx - cam.eye[0], cy - cam.eye[1], cz - cam.eye[2]), p]); }
    gl_.sort((a, b) => b[0] - a[0]);
    for (const [, p] of gl_) drawPrim(p, 1, S.glass);
  }
  // ---- lines
  gl.useProgram(PR.line.p); gl.uniformMatrix4fv(PR.line.u.uVP, false, cam.vp); gl.uniform1f(PR.line.u.uClipY, clipY); gl.uniform1f(PR.line.u.uAlpha, 1); gl.depthMask(false);
  const drawLines = (b, a = 1) => { if (b.floor >= 0 && !S.floors[b.floor]) return; gl.uniform1f(PR.line.u.uOffY, offY(b.floor)); gl.uniform1f(PR.line.u.uAlpha, a); gl.bindVertexArray(b.vao); gl.drawArrays(gl.LINES, 0, b.count); };
  if (S.layers.collision) R.collision.forEach(b => drawLines(b, 0.85));
  if (S.layers.rooms) R.rooms.forEach(b => drawLines(b, 0.9));
  if (S.layers.cams) R.cams.forEach(b => drawLines(b, 0.9));
  if (S.layers.axes) drawLines(R.axes);
  if (S.layers.bounds) drawLines(R.bounds);
  if (R.sel) for (const b of R.sel) drawLines(b, 1);
  // ---- route ribbon
  if (R.ribbon.count) {
    gl.disable(gl.DEPTH_TEST); gl.useProgram(PR.rib.p); gl.uniformMatrix4fv(PR.rib.u.uVP, false, cam.vp); gl.uniform1f(PR.rib.u.uExplode, S.explode); gl.uniform1f(PR.rib.u.uTime, time);
    const rc = getComputedStyle(document.documentElement).getPropertyValue('--route').trim(); const rgb = cssToRGB(rc);
    gl.uniform3f(PR.rib.u.uColor, rgb[0], rgb[1], rgb[2]); gl.bindVertexArray(R.ribbon.vao); gl.drawArrays(gl.TRIANGLES, 0, R.ribbon.count); gl.enable(gl.DEPTH_TEST);
  }
  gl.depthMask(true); gl.disable(gl.BLEND); gl.bindVertexArray(null);
  return drawn;
}
function cssToRGB(s) {
  if (s[0] === '#') { const h = s.length === 4 ? s.slice(1).split('').map(c => c + c).join('') : s.slice(1); return [parseInt(h.slice(0, 2), 16) / 255, parseInt(h.slice(2, 4), 16) / 255, parseInt(h.slice(4, 6), 16) / 255]; }
  const m = s.match(/\d+(\.\d+)?/g); return m ? m.slice(0, 3).map(v => v / 255) : [0.35, 0.7, 1];
}
