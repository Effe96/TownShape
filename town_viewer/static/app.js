const ZONE_COLORS = {
  civic: "#c9a0dc",
  merchant: "#f4a460",
  rich_residential: "#ffd700",
  poor_residential: "#a9a9a9",
  farmland_edge: "#9acd32",
  port: "#87ceeb",
};
const DEFAULT_ZONE_COLOR = "#dddddd";
const WATER_COLOR = "#4a90d9";

const LANDMARK_COLORS = {
  temple: "#8b008b",
  town_hall: "#000080",
  school: "#008080",
  university: "#006400",
  garrison: "#8b0000",
  guard_post: "#cd5c5c",
  arcane_shop: "#9400d3",
  harbormaster_office: "#00008b",
};
const GENERIC_BUILDING_COLOR = "#555555";
const LANDMARK_SIZE = 10;
const GENERIC_SIZE = 5;

function buildingHalfSize(buildingType) {
  return (buildingType in LANDMARK_COLORS ? LANDMARK_SIZE : GENERIC_SIZE) / 2;
}

function buildingColor(buildingType) {
  return LANDMARK_COLORS[buildingType] || GENERIC_BUILDING_COLOR;
}

let mapData = { districts: [], buildings: [], water_features: [] };
const view = { scale: 1, offsetX: 0, offsetY: 0 };

const canvas = document.getElementById("map");
const ctx = canvas.getContext("2d");

function resizeCanvas() {
  canvas.width = canvas.clientWidth;
  canvas.height = canvas.clientHeight;
}

function worldToScreen(x, y) {
  return {
    sx: (x - view.offsetX) * view.scale + canvas.width / 2,
    sy: (y - view.offsetY) * view.scale + canvas.height / 2,
  };
}

function screenToWorld(sx, sy) {
  return {
    x: (sx - canvas.width / 2) / view.scale + view.offsetX,
    y: (sy - canvas.height / 2) / view.scale + view.offsetY,
  };
}

function fitViewToBounds() {
  const xs = mapData.buildings.map((b) => b.x);
  const ys = mapData.buildings.map((b) => b.y);
  if (xs.length === 0) return;
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const width = Math.max(maxX - minX, 1);
  const height = Math.max(maxY - minY, 1);
  view.offsetX = (minX + maxX) / 2;
  view.offsetY = (minY + maxY) / 2;
  view.scale = 0.9 * Math.min(canvas.width / width, canvas.height / height);
}

function drawPolygon(ringList, fillStyle, strokeStyle) {
  for (const ring of ringList) {
    ctx.beginPath();
    ring.forEach(([x, y], i) => {
      const { sx, sy } = worldToScreen(x, y);
      if (i === 0) ctx.moveTo(sx, sy); else ctx.lineTo(sx, sy);
    });
    ctx.closePath();
    ctx.fillStyle = fillStyle;
    ctx.fill();
    if (strokeStyle) { ctx.strokeStyle = strokeStyle; ctx.lineWidth = 1; ctx.stroke(); }
  }
}

function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  ctx.globalAlpha = 0.6;
  for (const water of mapData.water_features) drawPolygon(water.polygon, WATER_COLOR, null);
  for (const district of mapData.districts) {
    const color = ZONE_COLORS[district.zone_type] || DEFAULT_ZONE_COLOR;
    drawPolygon(district.polygon, color, "black");
  }
  ctx.globalAlpha = 1;

  for (const building of mapData.buildings) {
    const half = buildingHalfSize(building.building_type);
    const { sx, sy } = worldToScreen(building.x - half, building.y - half);
    const screenSize = half * 2 * view.scale;
    ctx.fillStyle = buildingColor(building.building_type);
    ctx.fillRect(sx, sy, screenSize, screenSize);
  }
}

function loadMap() {
  fetch("/api/map")
    .then((r) => r.json())
    .then((data) => {
      mapData = data;
      resizeCanvas();
      fitViewToBounds();
      draw();
    });
}

// Pan
let dragging = false, lastClientX = 0, lastClientY = 0, dragDistance = 0;
canvas.addEventListener("mousedown", (e) => {
  dragging = true; dragDistance = 0;
  lastClientX = e.clientX; lastClientY = e.clientY;
  canvas.classList.add("dragging");
});
window.addEventListener("mousemove", (e) => {
  if (!dragging) return;
  const dx = e.clientX - lastClientX, dy = e.clientY - lastClientY;
  dragDistance += Math.abs(dx) + Math.abs(dy);
  lastClientX = e.clientX; lastClientY = e.clientY;
  view.offsetX -= dx / view.scale;
  view.offsetY -= dy / view.scale;
  draw();
});
window.addEventListener("mouseup", () => { dragging = false; canvas.classList.remove("dragging"); });

// Zoom
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  const rect = canvas.getBoundingClientRect();
  const mouseX = e.clientX - rect.left, mouseY = e.clientY - rect.top;
  const before = screenToWorld(mouseX, mouseY);
  view.scale *= e.deltaY < 0 ? 1.15 : 1 / 1.15;
  const after = screenToWorld(mouseX, mouseY);
  view.offsetX += before.x - after.x;
  view.offsetY += before.y - after.y;
  draw();
}, { passive: false });

window.addEventListener("resize", () => { resizeCanvas(); draw(); });

loadMap();
