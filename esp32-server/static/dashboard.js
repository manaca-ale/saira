/* ── SAIRA Campo — Mobile-First Field Tool ── */

// ── DOM refs ──

const syncPill = document.getElementById("syncPill");
const deviceList = document.getElementById("deviceList");
const imageOverlay = document.getElementById("imageOverlay");
const overlayClose = document.getElementById("overlayClose");
const overlayImg = document.getElementById("overlayImg");
const overlayDevice = document.getElementById("overlayDevice");
const overlayTime = document.getElementById("overlayTime");
const overlayBody = document.getElementById("overlayBody");
const deviceCardTpl = document.getElementById("deviceCardTpl");

// ── State ──

const state = {
  devices: [],
  imageCache: {},
  pollMs: 15000,
  failCount: 0,
  overlayOpen: false,
};

const BRAZIL_TZ = "America/Sao_Paulo";

// ── Date utilities (kept from original) ──

function parseSairaDate(value) {
  if (!value) return null;
  const raw = String(value).trim();
  if (!raw) return null;
  const normalized = raw.includes(" ") ? raw.replace(" ", "T") : raw;
  const hasTimezone = /([zZ]|[+-]\d{2}:\d{2})$/.test(normalized);
  const withTimezone = hasTimezone ? normalized : `${normalized}-03:00`;
  const dt = new Date(withTimezone);
  if (Number.isNaN(dt.getTime())) return null;
  return dt;
}

function fmtDate(iso) {
  if (!iso) return "-";
  const dt = parseSairaDate(iso);
  if (dt) {
    return dt.toLocaleString("pt-BR", { hour12: false, timeZone: BRAZIL_TZ });
  }
  return String(iso).trim().replace("T", " ").replace("Z", "");
}

function fmtRelative(iso) {
  if (!iso) return "";
  const dt = parseSairaDate(iso);
  if (!dt) return "";
  const diffSec = Math.max(0, Math.round((Date.now() - dt.getTime()) / 1000));
  if (diffSec < 60) return `${diffSec}s`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}min`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h`;
  return `${Math.floor(diffSec / 86400)}d`;
}

// ── Sync pill ──

function setSyncStatus(kind, text) {
  if (!syncPill) return;
  syncPill.classList.remove("is-ok", "is-warn", "is-error");
  if (kind) syncPill.classList.add(`is-${kind}`);
  syncPill.textContent = text;
}

// ── Data loading ──

async function loadDevices() {
  try {
    setSyncStatus("warn", "Atualizando...");

    const resp = await fetch("/api/dashboard/state?image_limit=30&log_limit=0", {
      cache: "no-store",
    });

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    const data = await resp.json();

    // Build latest image per device
    const latestByDevice = {};
    const images = data.recent_images?.images || [];
    for (const img of images) {
      if (img.device_id && !latestByDevice[img.device_id]) {
        latestByDevice[img.device_id] = img;
      }
    }

    state.devices = (data.devices?.devices || []).filter(
      (d) => d.device_id && d.device_id !== "unknown_device"
    );
    state.imageCache = latestByDevice;
    state.failCount = 0;

    renderDeviceList();

    const interval = Math.round(state.pollMs / 1000);
    setSyncStatus("ok", `Online \u00b7 ${interval}s`);
  } catch (err) {
    state.failCount++;
    const msg = state.failCount >= 3 ? "Sem conexao" : "Erro de leitura";
    setSyncStatus("error", msg);
    console.error("[SAIRA Campo]", err);
  }
}

// ── Rendering ──

function renderDeviceList() {
  if (!deviceList || !deviceCardTpl) return;

  const sorted = [...state.devices].sort((a, b) => {
    // Active first
    if (a.is_active && !b.is_active) return -1;
    if (!a.is_active && b.is_active) return 1;
    // Then by most recent activity
    const aTime = parseSairaDate(a.last_seen_at)?.getTime() || 0;
    const bTime = parseSairaDate(b.last_seen_at)?.getTime() || 0;
    return bTime - aTime;
  });

  // Check if we can update in-place (same device set, same order)
  const existingCards = deviceList.querySelectorAll(".device-card[data-device-id]");
  const existingIds = Array.from(existingCards).map((c) => c.dataset.deviceId);
  const newIds = sorted.map((d) => d.device_id);
  const canPatch = existingIds.length === newIds.length &&
    existingIds.every((id, i) => id === newIds[i]);

  if (canPatch) {
    // Update in-place to avoid image flicker
    for (let i = 0; i < sorted.length; i++) {
      patchCard(existingCards[i], sorted[i]);
    }
    return;
  }

  // Full rebuild
  deviceList.innerHTML = "";

  if (!sorted.length) {
    deviceList.innerHTML = '<p class="empty-state">Nenhum dispositivo encontrado.</p>';
    return;
  }

  const frag = document.createDocumentFragment();
  for (const device of sorted) {
    const node = deviceCardTpl.content.cloneNode(true);
    const card = node.querySelector(".device-card");
    applyCardData(card, device);
    card.addEventListener("click", () => onCardTap(device.device_id));
    frag.appendChild(node);
  }
  deviceList.appendChild(frag);
}

function applyCardData(card, device) {
  const active = Boolean(device.is_active);
  const deviceId = device.device_id;
  const latestImg = state.imageCache[deviceId];

  card.dataset.deviceId = deviceId;
  card.className = `device-card ${active ? "is-active" : "is-inactive"}`;

  const led = card.querySelector(".status-led");
  if (led) led.className = `status-led ${active ? "is-on" : "is-off"}`;

  const idEl = card.querySelector(".device-id");
  if (idEl) idEl.textContent = deviceId;

  const badge = card.querySelector(".device-badge");
  if (badge) {
    badge.textContent = active ? "ATIVO" : "INATIVO";
    badge.className = `device-badge ${active ? "badge-active" : "badge-inactive"}`;
  }

  const ago = card.querySelector(".device-ago");
  if (ago) ago.textContent = fmtRelative(device.last_seen_at);

  const img = card.querySelector(".card-thumb img");
  const emptyLabel = card.querySelector(".thumb-empty");

  if (latestImg && latestImg.image_url) {
    if (img) {
      // Only update src if it changed (avoid flicker)
      const newSrc = latestImg.image_url;
      if (img.getAttribute("src") !== newSrc) {
        img.src = newSrc;
      }
      img.style.display = "block";
    }
    if (emptyLabel) emptyLabel.style.display = "none";
  } else {
    if (img) {
      img.removeAttribute("src");
      img.style.display = "none";
    }
    if (emptyLabel) emptyLabel.style.display = "flex";
  }
}

function patchCard(card, device) {
  applyCardData(card, device);
}

// ── Overlay ──

function onCardTap(deviceId) {
  const latestImg = state.imageCache[deviceId];
  if (latestImg && latestImg.image_url) {
    openOverlay(deviceId, latestImg);
  }
}

function openOverlay(deviceId, imageData) {
  if (!imageOverlay || !overlayImg) return;

  overlayImg.src = imageData.image_url;
  if (overlayDevice) overlayDevice.textContent = deviceId;
  if (overlayTime) overlayTime.textContent = fmtDate(imageData.captured_at);

  imageOverlay.hidden = false;
  document.body.style.overflow = "hidden";
  state.overlayOpen = true;
}

function closeOverlay() {
  if (!imageOverlay) return;
  imageOverlay.hidden = true;
  document.body.style.overflow = "";
  state.overlayOpen = false;
}

// ── Event listeners ──

// Sync pill → manual refresh
if (syncPill) {
  syncPill.addEventListener("click", () => loadDevices());
}

// Overlay close
if (overlayClose) {
  overlayClose.addEventListener("click", closeOverlay);
}

// Tap backdrop to close overlay
if (overlayBody) {
  overlayBody.addEventListener("click", (e) => {
    if (e.target === overlayBody) closeOverlay();
  });
}

// Escape key
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && state.overlayOpen) closeOverlay();
});

// ── Polling with Visibility API ──

let pollTimer = null;

function schedulePoll() {
  clearTimeout(pollTimer);
  const interval = state.failCount >= 3 ? 30000 : state.pollMs;
  pollTimer = setTimeout(async () => {
    if (!document.hidden) {
      await loadDevices();
    }
    schedulePoll();
  }, interval);
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    loadDevices();
  }
});

// ── Init ──

loadDevices();
schedulePoll();
