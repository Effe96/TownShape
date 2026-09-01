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

  for (const buildingId of highlightedBuildingIds) {
    const building = mapData.buildings.find((b) => b.id === buildingId);
    if (!building) continue;
    const half = buildingHalfSize(building.building_type);
    const { sx, sy } = worldToScreen(building.x - half, building.y - half);
    ctx.strokeStyle = "#ff2222";
    ctx.lineWidth = 3;
    ctx.strokeRect(sx, sy, half * 2 * view.scale, half * 2 * view.scale);
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
      renderLegend();
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

let highlightedBuildingIds = [];

function findBuildingAt(worldX, worldY) {
  for (const building of mapData.buildings) {
    const half = buildingHalfSize(building.building_type);
    if (
      worldX >= building.x - half && worldX <= building.x + half &&
      worldY >= building.y - half && worldY <= building.y + half
    ) {
      return building;
    }
  }
  return null;
}

function renderBuildingDetail(building) {
  const panel = document.getElementById("detail-panel");
  const rows = building.residents
    .map((r) => {
      const role = r.lives_here && r.works_here ? "lives & works here"
        : r.lives_here ? "lives here" : "works here";
      return `<div class="detail-row"><span class="linked-name" data-resident-id="${r.id}">${r.first_name} ${r.last_name}</span> — ${role}</div>`;
    })
    .join("");
  panel.innerHTML = `
    <h3>${building.building_type} (#${building.id})</h3>
    <div class="detail-row"><span class="label">Zone:</span> ${building.zone_type}</div>
    <div class="detail-row"><span class="label">Capacity:</span> ${building.capacity}</div>
    <h4>Residents (${building.residents.length})</h4>
    ${rows || "<p class=\"hint\">Nobody lives or works here.</p>"}
  `;
  panel.querySelectorAll(".linked-name[data-resident-id]").forEach((el) => {
    el.addEventListener("click", () => selectResident(parseInt(el.dataset.residentId, 10)));
  });
}

function selectBuilding(buildingId) {
  fetch(`/api/buildings/${buildingId}`)
    .then((r) => r.json())
    .then((building) => {
      highlightedBuildingIds = [buildingId];
      renderBuildingDetail(building);
      draw();
    });
}

canvas.addEventListener("mouseup", (e) => {
  if (dragDistance > 3) return; // was a drag, not a click
  const rect = canvas.getBoundingClientRect();
  const world = screenToWorld(e.clientX - rect.left, e.clientY - rect.top);
  const building = findBuildingAt(world.x, world.y);
  if (building) selectBuilding(building.id);
});

let currentPage = 1;

function renderResidentList(data) {
  const list = document.getElementById("resident-list");
  list.innerHTML = data.residents
    .map((r) => `<div class="resident-row" data-resident-id="${r.id}">${r.first_name} ${r.last_name}${r.occupation ? " — " + r.occupation : ""}</div>`)
    .join("");
  list.querySelectorAll(".resident-row").forEach((el) => {
    el.addEventListener("click", () => selectResident(parseInt(el.dataset.residentId, 10)));
  });

  const totalPages = Math.max(1, Math.ceil(data.total / data.page_size));
  document.getElementById("page-info").textContent = `Page ${data.page} of ${totalPages} (${data.total} residents)`;
  document.getElementById("prev-page").disabled = data.page <= 1;
  document.getElementById("next-page").disabled = data.page >= totalPages;
}

function loadResidents() {
  const query = document.getElementById("search-input").value;
  fetch(`/api/residents?q=${encodeURIComponent(query)}&page=${currentPage}`)
    .then((r) => r.json())
    .then(renderResidentList);
}

document.getElementById("search-input").addEventListener("input", () => {
  currentPage = 1;
  loadResidents();
});
document.getElementById("prev-page").addEventListener("click", () => {
  if (currentPage > 1) { currentPage -= 1; loadResidents(); }
});
document.getElementById("next-page").addEventListener("click", () => {
  currentPage += 1; loadResidents();
});

loadResidents();

function relationshipLabel(rel) {
  if (rel.relationship_type === "parent") return rel.role === "a" ? "parent of" : "child of";
  return rel.relationship_type.replace(/_/g, " ");
}

function renderResidentDetail(resident) {
  const panel = document.getElementById("detail-panel");
  const relRows = resident.relationships
    .map((r) => `<div class="detail-row">${relationshipLabel(r)} <span class="linked-name" data-resident-id="${r.resident_id}">${r.first_name} ${r.last_name}</span></div>`)
    .join("") || "<p class=\"hint\">No recorded relationships.</p>";
  const shopRows = resident.shopping
    .map((s) => `<div class="detail-row"><span class="linked-name" data-building-id="${s.shop_building_id}">Shop #${s.shop_building_id}</span> — ${s.purchase_count} purchases, ${s.total_spent.toFixed(2)} spent${s.is_primary ? " (primary)" : ""}</div>`)
    .join("") || "<p class=\"hint\">No recorded purchases.</p>";

  panel.innerHTML = `
    <h3>${resident.first_name} ${resident.last_name}</h3>
    <div class="detail-row"><span class="label">Household:</span> ${resident.household.family_name} (wealth ${resident.household.wealth})</div>
    <div class="detail-row"><span class="label">SES:</span> ${resident.ses}</div>
    <div class="detail-row"><span class="label">Occupation:</span> ${resident.occupation || "none"}</div>
    <div class="detail-row"><span class="label">Home:</span> ${resident.home_building_id != null ? `<span class="linked-name" data-building-id="${resident.home_building_id}">Building #${resident.home_building_id}</span>` : "none"}</div>
    <div class="detail-row"><span class="label">Workplace:</span> ${resident.workplace_building_id != null ? `<span class="linked-name" data-building-id="${resident.workplace_building_id}">Building #${resident.workplace_building_id}</span>` : "none"}</div>
    <h4>Family & relationships</h4>
    ${relRows}
    <h4>Shopping</h4>
    ${shopRows}
  `;
  panel.querySelectorAll(".linked-name[data-resident-id]").forEach((el) => {
    el.addEventListener("click", () => selectResident(parseInt(el.dataset.residentId, 10)));
  });
  panel.querySelectorAll(".linked-name[data-building-id]").forEach((el) => {
    el.addEventListener("click", () => selectBuilding(parseInt(el.dataset.buildingId, 10)));
  });
}

function selectResident(residentId) {
  fetch(`/api/residents/${residentId}`)
    .then((r) => r.json())
    .then((resident) => {
      highlightedBuildingIds = [resident.home_building_id, resident.workplace_building_id]
        .filter((id) => id != null);
      renderResidentDetail(resident);
      const home = mapData.buildings.find((b) => b.id === resident.home_building_id);
      if (home) { view.offsetX = home.x; view.offsetY = home.y; }
      draw();
    });
}

function renderLegend() {
  const zoneTypes = [...new Set(mapData.districts.map((d) => d.zone_type))].sort();
  const landmarkTypesPresent = [...new Set(mapData.buildings.map((b) => b.building_type))]
    .filter((t) => t in LANDMARK_COLORS)
    .sort();

  const zoneRows = zoneTypes
    .map((zt) => `<div class="row"><span class="swatch" style="background:${ZONE_COLORS[zt] || DEFAULT_ZONE_COLOR}"></span>${zt}</div>`)
    .join("");
  const landmarkRows = landmarkTypesPresent
    .map((bt) => `<div class="row"><span class="swatch" style="background:${LANDMARK_COLORS[bt]}"></span>${bt}</div>`)
    .join("");

  document.getElementById("legend").innerHTML = `
    <div><strong>Zones</strong></div>${zoneRows}
    <div><strong>Landmarks</strong></div>${landmarkRows || "<div class=\"row hint\">none</div>"}
  `;
}
