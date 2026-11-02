// 3D map of the southern Murray–Darling Basin. Data from game/build_map.py (docs/game/data/).
// World units are kilometres: x east, z south (north is -z), y up; elevation is scaled by the height exaggeration.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const $ = (id) => document.getElementById(id);
const SKIRT_Y = -4; // bottom of the block's side walls (km)
const LABEL_RANGE = { town: 600, river: 750, storage: 500, peak: 600 }; // km beyond which a label fades out
const HELP = {
  orbit: "<b>Drag</b> rotate · <b>Right-drag</b> pan · <b>Scroll</b> zoom · <b>Double-click</b> centre on a spot",
  fly: "<b>W A S D</b> move · <b>E / Space</b> up · <b>Q</b> down · <b>Shift</b> faster · <b>Drag</b> look",
};

let loaded = 0;
const progress = () => { $("progress").textContent = `${++loaded}/3`; };
const [meta, heightsBuf] = await Promise.all([
  fetch("data/meta.json").then((r) => r.json()).then((m) => (progress(), m)),
  fetch("data/heights.bin").then((r) => r.arrayBuffer()).then((b) => (progress(), b)),
]);
const heights = new Int16Array(heightsBuf); // metres, row 0 north
const W = meta.grid_w, H = meta.grid_h, WIDTH = meta.width_km, DEPTH = meta.height_km;
if (heights.length !== W * H) throw new Error(`heights.bin has ${heights.length} cells, expected ${W * H}`);
let exag = Number($("exag").value);

function toXZ(lon, lat) {
  return [(lon - meta.west) / (meta.east - meta.west) * WIDTH - WIDTH / 2,
          (meta.north - lat) / (meta.north - meta.south) * DEPTH - DEPTH / 2];
}
function toLonLat(x, z) {
  return [meta.west + (x + WIDTH / 2) / WIDTH * (meta.east - meta.west),
          meta.north - (z + DEPTH / 2) / DEPTH * (meta.north - meta.south)];
}
// Elevation in metres, bilinear between grid cells; NaN off the map.
function elevationAt(x, z) {
  const c = (x + WIDTH / 2) / WIDTH * (W - 1), r = (z + DEPTH / 2) / DEPTH * (H - 1);
  if (!(c >= 0 && r >= 0 && c <= W - 1 && r <= H - 1)) return NaN;
  const c0 = Math.min(Math.floor(c), W - 2), r0 = Math.min(Math.floor(r), H - 2);
  const fc = c - c0, fr = r - r0, i = r0 * W + c0;
  return (heights[i] * (1 - fc) + heights[i + 1] * fc) * (1 - fr) + (heights[i + W] * (1 - fc) + heights[i + W + 1] * fc) * fr;
}
// Height of the walkable surface (land or sea surface) in world units; NaN off the map.
const surfaceY = (x, z) => Math.max(elevationAt(x, z), 0) / 1000 * exag;

// --- scene -----------------------------------------------------------------------------------------------------------
const canvas = $("view");
// Log depth: views span ~50 m to ~2000 km, and low plains sit only tens of metres above the sea plane.
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, logarithmicDepthBuffer: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
const scene = new THREE.Scene();
const horizon = new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue("--sky-horizon").trim());
scene.fog = new THREE.Fog(horizon, 500, 2200);
const camera = new THREE.PerspectiveCamera(50, 1, 0.05, 6000);

scene.add(new THREE.HemisphereLight(0xe4edf5, 0x5c4a33, 1.1));
const sun = new THREE.DirectionalLight(0xfff1dc, 2.4);
sun.position.set(-250, 420, -320); // afternoon sun in the northern sky
scene.add(sun);

const terrainGeom = new THREE.PlaneGeometry(WIDTH, DEPTH, W - 1, H - 1);
terrainGeom.rotateX(-Math.PI / 2); // vertex i = row * W + col, row 0 at z = -DEPTH/2 (north), as in heights.bin
const terrainMat = new THREE.MeshStandardMaterial({ roughness: 1, metalness: 0, color: 0xffffff });
const terrain = new THREE.Mesh(terrainGeom, terrainMat);
scene.add(terrain);

new THREE.TextureLoader().load("data/texture.jpg", (tex) => {
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
  terrainMat.map = tex;
  terrainMat.needsUpdate = true;
  progress();
  $("loading").classList.add("done");
});

const water = new THREE.Mesh(
  new THREE.PlaneGeometry(WIDTH, DEPTH).rotateX(-Math.PI / 2),
  new THREE.MeshStandardMaterial({ color: 0x2c5a78, roughness: 0.35, metalness: 0.1 }),
);
water.position.y = -0.001;
scene.add(water);

// Side walls round the map, so it reads as a solid block of ground.
const border = [];
for (let c = 0; c < W; c++) border.push(c);
for (let r = 1; r < H; r++) border.push(r * W + W - 1);
for (let c = W - 2; c >= 0; c--) border.push((H - 1) * W + c);
for (let r = H - 2; r > 0; r--) border.push(r * W);
border.push(0);
const skirtPos = new Float32Array(border.length * 2 * 3);
const skirtIdx = [];
for (let k = 0; k < border.length - 1; k++) {
  const a = 2 * k, b = 2 * k + 2;
  skirtIdx.push(a, b, a + 1, b, b + 1, a + 1);
}
const skirtGeom = new THREE.BufferGeometry();
skirtGeom.setAttribute("position", new THREE.BufferAttribute(skirtPos, 3));
skirtGeom.setIndex(skirtIdx);
scene.add(new THREE.Mesh(skirtGeom, new THREE.MeshStandardMaterial({ color: 0x6b553c, roughness: 1, side: THREE.DoubleSide })));

function applyHeights() {
  const pos = terrainGeom.attributes.position;
  for (let i = 0; i < pos.count; i++) pos.setY(i, heights[i] / 1000 * exag);
  pos.needsUpdate = true;
  terrainGeom.computeVertexNormals();
  terrainGeom.computeBoundingSphere();
  border.forEach((i, k) => {
    const x = pos.getX(i), z = pos.getZ(i), top = Math.max(heights[i], 0) / 1000 * exag;
    skirtPos.set([x, top, z, x, SKIRT_Y, z], k * 6);
  });
  skirtGeom.attributes.position.needsUpdate = true;
  skirtGeom.computeVertexNormals();
  skirtGeom.computeBoundingSphere();
}
applyHeights();

// --- ground picking (ray march against the height grid, much cheaper than a mesh raycast) -----------------------------
const raycaster = new THREE.Raycaster();
function pickGround(ndcX, ndcY) {
  raycaster.setFromCamera({ x: ndcX, y: ndcY }, camera);
  const { origin: o, direction: d } = raycaster.ray;
  let t = 0, prev = 0;
  for (let n = 0; n < 600 && t < 5000; n++) {
    const x = o.x + d.x * t, y = o.y + d.y * t, z = o.z + d.z * t;
    const g = surfaceY(x, z);
    if (Number.isNaN(g)) { prev = t; t += 5; continue; }
    if (y <= g) {
      let lo = prev, hi = t;
      for (let b = 0; b < 12; b++) {
        const m = (lo + hi) / 2;
        if (o.y + d.y * m <= surfaceY(o.x + d.x * m, o.z + d.z * m)) hi = m; else lo = m;
      }
      return new THREE.Vector3(o.x + d.x * hi, o.y + d.y * hi, o.z + d.z * hi);
    }
    prev = t;
    t += Math.max(0.02, (y - g) * 0.6);
  }
  return null;
}

// --- controls ----------------------------------------------------------------------------------------------------------
const orbit = new OrbitControls(camera, canvas);
orbit.enableDamping = true;
orbit.screenSpacePanning = false;
orbit.zoomToCursor = true;
orbit.maxPolarAngle = Math.PI * 0.48;
orbit.minDistance = 0.5;
orbit.maxDistance = 2600;
orbit.listenToKeyEvents(window);

function resetView() {
  const back = Math.max(1, 1.1 * innerHeight / innerWidth); // stand further off on portrait screens to fit the width
  orbit.target.set(0, surfaceY(0, 0), 60);
  camera.position.set(-60 * back, 520 * back, 60 + 700 * back);
  orbit.update();
}
resetView();

let mode = "orbit";
const fly = { yaw: 0, pitch: 0, keys: new Set(), dragging: false, lastX: 0, lastY: 0 };

function setMode(next) {
  if (next === mode) return;
  mode = next;
  $("mode-orbit").classList.toggle("on", mode === "orbit");
  $("mode-fly").classList.toggle("on", mode === "fly");
  $("help").innerHTML = HELP[mode];
  orbit.enabled = mode === "orbit";
  const dir = camera.getWorldDirection(new THREE.Vector3());
  if (mode === "fly") {
    fly.yaw = Math.atan2(-dir.x, -dir.z);
    fly.pitch = Math.asin(THREE.MathUtils.clamp(dir.y, -1, 1));
    return;
  }
  const hit = pickGround(0, 0) || camera.position.clone().addScaledVector(dir, 30);
  hit.y = surfaceY(hit.x, hit.z) || 0;
  orbit.target.copy(hit);
  orbit.update();
}
$("help").innerHTML = HELP.orbit;
$("mode-orbit").onclick = () => setMode("orbit");
$("mode-fly").onclick = () => setMode("fly");
$("reset").onclick = () => { setMode("orbit"); resetView(); };

addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  if (e.code === "KeyF") { setMode(mode === "fly" ? "orbit" : "fly"); return; }
  fly.keys.add(e.code);
});
addEventListener("keyup", (e) => fly.keys.delete(e.code));
addEventListener("blur", () => fly.keys.clear());

canvas.addEventListener("pointerdown", (e) => {
  if (mode !== "fly") return;
  fly.dragging = true;
  fly.lastX = e.clientX;
  fly.lastY = e.clientY;
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener("pointerup", () => { fly.dragging = false; });

const pointer = { x: 0, y: 0, over: false };
canvas.addEventListener("pointerleave", () => { pointer.over = false; });
canvas.addEventListener("pointermove", (e) => {
  pointer.x = e.clientX / innerWidth * 2 - 1;
  pointer.y = -(e.clientY / innerHeight) * 2 + 1;
  pointer.over = true;
  if (mode !== "fly" || !fly.dragging) return;
  fly.yaw -= (e.clientX - fly.lastX) * 0.004;
  fly.pitch = THREE.MathUtils.clamp(fly.pitch - (e.clientY - fly.lastY) * 0.004, -1.45, 1.45);
  fly.lastX = e.clientX;
  fly.lastY = e.clientY;
});

// Double-click: glide the orbit centre to that spot.
let glide = null;
canvas.addEventListener("dblclick", (e) => {
  if (mode !== "orbit") return;
  const hit = pickGround(e.clientX / innerWidth * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
  if (!hit) return;
  glide = { from: orbit.target.clone(), to: hit, offset: camera.position.clone().sub(orbit.target), t: 0 };
});

function stepFly(dt) {
  camera.quaternion.setFromEuler(new THREE.Euler(fly.pitch, fly.yaw, 0, "YXZ"));
  const k = fly.keys;
  const move = new THREE.Vector3(
    (k.has("KeyD") ? 1 : 0) - (k.has("KeyA") ? 1 : 0),
    0,
    (k.has("KeyS") ? 1 : 0) - (k.has("KeyW") ? 1 : 0),
  ).applyQuaternion(camera.quaternion);
  move.y += (k.has("KeyE") || k.has("Space") ? 1 : 0) - (k.has("KeyQ") ? 1 : 0);
  if (move.lengthSq() === 0) return;
  const ground = surfaceY(camera.position.x, camera.position.z) || 0;
  const speed = THREE.MathUtils.clamp((camera.position.y - ground) * 1.2, 0.4, 80) * (k.has("ShiftLeft") || k.has("ShiftRight") ? 4 : 1);
  camera.position.addScaledVector(move.normalize(), speed * dt);
}

function keepAboveGround() {
  const p = camera.position;
  p.x = THREE.MathUtils.clamp(p.x, -WIDTH, WIDTH);
  p.z = THREE.MathUtils.clamp(p.z, -DEPTH, DEPTH);
  const g = surfaceY(p.x, p.z);
  if (!Number.isNaN(g) && p.y < g + 0.08) p.y = g + 0.08;
  if (p.y > 3000) p.y = 3000;
}

$("exag").addEventListener("input", (e) => {
  exag = Number(e.target.value);
  $("exag-out").textContent = exag;
  applyHeights();
  orbit.target.y = surfaceY(orbit.target.x, orbit.target.z) || 0;
});

// --- labels ------------------------------------------------------------------------------------------------------------
const labels = meta.labels.map((l) => {
  const el = document.createElement("div");
  el.className = `label ${l.kind}`;
  el.textContent = l.name;
  $("labels").appendChild(el);
  const [x, z] = toXZ(l.lon, l.lat);
  return { ...l, el, x, z };
});
let showLabels = true;
$("show-labels").onchange = (e) => { showLabels = e.target.checked; };

const v = new THREE.Vector3();
function visible(x, y, z) {
  // Hidden when a ridge sits between the camera and the label.
  const c = camera.position;
  for (let s = 1; s < 10; s++) {
    const f = s / 10, px = c.x + (x - c.x) * f, pz = c.z + (z - c.z) * f;
    if (c.y + (y - c.y) * f < surfaceY(px, pz)) return false;
  }
  return true;
}
function updateLabels() {
  for (const l of labels) {
    const y = (surfaceY(l.x, l.z) || 0) + 0.05;
    const dist = camera.position.distanceTo(v.set(l.x, y, l.z));
    const fade = showLabels ? THREE.MathUtils.clamp(1.6 - dist / LABEL_RANGE[l.kind], 0, 1) : 0;
    v.project(camera);
    if (fade === 0 || v.z > 1 || Math.abs(v.x) > 1.1 || Math.abs(v.y) > 1.1 || !visible(l.x, y, l.z)) {
      l.el.style.opacity = 0;
      continue;
    }
    const sx = (v.x + 1) / 2 * innerWidth, sy = (1 - v.y) / 2 * innerHeight;
    const centred = l.kind === "river" ? "translate(-50%, -50%)" : "translate(-3px, -50%)";
    l.el.style.opacity = fade;
    l.el.style.transform = `translate(${sx}px, ${sy}px) ${centred}`;
  }
}

// --- HUD ---------------------------------------------------------------------------------------------------------------
const fmt = (lon, lat) => `${Math.abs(lat).toFixed(2)}°S ${lon.toFixed(2)}°E`;
let hudTimer = 0;
function updateHud(dt) {
  const dir = camera.getWorldDirection(v);
  $("compass").style.transform = `rotate(${-Math.atan2(dir.x, -dir.z)}rad)`;
  if ((hudTimer += dt) < 0.1) return;
  hudTimer = 0;
  const g = surfaceY(camera.position.x, camera.position.z);
  const alt = Number.isNaN(g) ? "" : ` · <b>${Math.round((camera.position.y - g) / exag * 1000)} m</b> above ground`;
  let line = `Camera <b>${fmt(...toLonLat(camera.position.x, camera.position.z))}</b>${alt}`;
  const hit = pointer.over ? pickGround(pointer.x, pointer.y) : null;
  if (hit) {
    const [lon, lat] = toLonLat(hit.x, hit.z);
    line = `Cursor <b>${fmt(lon, lat)}</b> · <b>${Math.round(Math.max(elevationAt(hit.x, hit.z), 0))} m</b><br>${line}`;
  }
  $("readout").innerHTML = line;
}
$("compass").onclick = () => {
  if (mode === "fly") { fly.yaw = 0; return; }
  const off = camera.position.clone().sub(orbit.target);
  const flat = Math.hypot(off.x, off.z);
  camera.position.set(orbit.target.x, camera.position.y, orbit.target.z + flat);
  orbit.update();
};

// --- loop --------------------------------------------------------------------------------------------------------------
function resize() {
  renderer.setSize(innerWidth, innerHeight, false);
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
}
addEventListener("resize", resize);
resize();

const clock = new THREE.Clock();
renderer.setAnimationLoop(() => {
  const dt = Math.min(clock.getDelta(), 0.1);
  if (glide) {
    glide.t = Math.min(glide.t + dt / 0.7, 1);
    const e = 1 - (1 - glide.t) ** 3;
    orbit.target.lerpVectors(glide.from, glide.to, e);
    camera.position.copy(orbit.target).add(glide.offset);
    if (glide.t === 1) glide = null;
  }
  if (mode === "fly") stepFly(dt);
  else orbit.update();
  keepAboveGround();
  updateLabels();
  updateHud(dt);
  renderer.render(scene, camera);
});
