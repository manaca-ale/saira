function byId(...ids) {
  for (const id of ids) {
    const el = document.getElementById(id);
    if (el) return el;
  }
  return null;
}

function safeSetText(el, text) {
  if (!el) return;
  el.textContent = String(text);
}

const totalImagesEl = byId("totalImages");
const activeDevicesEl = byId("activeDevices", "totalDevices");
const knownDevicesEl = byId("knownDevices");
const latestCaptureEl = byId("latestCapture");
const updatedAtEl = byId("updatedAt");
const activeRuleEl = byId("activeRule");
const imagesLabelEl = byId("imagesLabel");
const usageLabelEl = byId("usageLabel");
const overall4gEl = byId("overall4g");
const overall4gHintEl = byId("overall4gHint");
const refreshStatusEl = byId("refreshStatus");
const refreshBtn = byId("refreshBtn");
const deviceFilterEl = byId("deviceFilter");
const deviceChipsEl = byId("deviceChips");
const devicesListEl = byId("devicesList");
const galleryEl = byId("gallery");
const logsEl = byId("logs");
const imageCardTpl = byId("imageCardTpl");
const logRowTpl = byId("logRowTpl");
const deviceCardTpl = byId("deviceCardTpl");
const DASHBOARD_TIMEZONE = "America/Sao_Paulo";

const state = {
  selectedDevice: "",
  pollMs: 15000,
  lastImagesSignature: "",
  lastLogsSignature: "",
};

function toQuery(params) {
  const usp = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === null || value === undefined || value === "") return;
    usp.set(key, String(value));
  });
  const txt = usp.toString();
  return txt ? `?${txt}` : "";
}

function fmtDate(iso) {
  if (!iso) return "-";
  const dt = new Date(iso);
  if (!Number.isNaN(dt.getTime())) {
    return dt.toLocaleString("pt-BR", {
      hour12: false,
      timeZone: DASHBOARD_TIMEZONE,
    });
  }
  const raw = String(iso).trim();
  const normalized = raw.replace("T", " ").replace("Z", "");
  return normalized;
}

function fmtRelative(iso) {
  if (!iso) return "-";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return fmtDate(iso);
  const diffSec = Math.max(0, Math.round((Date.now() - dt.getTime()) / 1000));
  if (diffSec < 60) return `${diffSec}s atras`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}min atras`;
  return `${Math.floor(diffSec / 3600)}h atras`;
}

function fmtNum(num, digits = 1) {
  const n = Number(num);
  if (!Number.isFinite(n)) return "0";
  return n.toLocaleString("pt-BR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function setRefreshStatus(kind, text) {
  if (!refreshStatusEl) return;
  refreshStatusEl.classList.remove("is-ok", "is-error", "is-warn");
  if (kind === "ok") refreshStatusEl.classList.add("is-ok");
  if (kind === "warn") refreshStatusEl.classList.add("is-warn");
  if (kind === "error") refreshStatusEl.classList.add("is-error");
  refreshStatusEl.textContent = text;
}

function renderDeviceFilter(devices) {
  if (!deviceFilterEl) return;
  const current = state.selectedDevice;
  const list = devices
    .map((item) => item.device_id)
    .filter((id) => typeof id === "string" && id.length > 0)
    .sort((a, b) => a.localeCompare(b));

  deviceFilterEl.innerHTML = "";
  const all = document.createElement("option");
  all.value = "";
  all.textContent = "Todos os dispositivos";
  deviceFilterEl.appendChild(all);

  for (const deviceId of list) {
    const opt = document.createElement("option");
    opt.value = deviceId;
    opt.textContent = deviceId;
    deviceFilterEl.appendChild(opt);
  }

  if (list.includes(current)) {
    deviceFilterEl.value = current;
    state.selectedDevice = current;
  } else {
    deviceFilterEl.value = "";
    state.selectedDevice = "";
  }
}

function renderDeviceChips(activeDevices) {
  if (!deviceChipsEl) return;
  deviceChipsEl.innerHTML = "";
  if (!activeDevices.length) {
    deviceChipsEl.innerHTML = "<p class='empty'>Nenhum dispositivo ativo no momento.</p>";
    return;
  }

  const frag = document.createDocumentFragment();
  for (const deviceId of activeDevices) {
    const chip = document.createElement("span");
    chip.className = "chip is-active";
    chip.textContent = deviceId;
    frag.appendChild(chip);
  }
  deviceChipsEl.appendChild(frag);
}

function renderDevices(devices) {
  if (!devicesListEl) return;
  devicesListEl.innerHTML = "";
  if (!devices.length) {
    devicesListEl.innerHTML = "<p class='empty'>Nenhum dispositivo encontrado.</p>";
    return;
  }

  const frag = document.createDocumentFragment();
  for (const item of devices) {
    if (deviceCardTpl && deviceCardTpl.content) {
      const node = deviceCardTpl.content.cloneNode(true);
      const active = Boolean(item.is_active);
      safeSetText(node.querySelector(".device-name"), item.device_id || "unknown_device");
      const stateEl = node.querySelector(".device-state");
      if (stateEl) {
        stateEl.textContent = active ? "ATIVO" : "INATIVO";
        stateEl.className = `device-state ${active ? "is-active" : "is-inactive"}`;
      }
      safeSetText(node.querySelector(".images-count"), `Imagens na janela: ${item.recent_images_count ?? 0}`);
      safeSetText(node.querySelector(".last-seen"), `Ultimo sinal: ${fmtDate(item.last_seen_at)} (${fmtRelative(item.last_seen_at)})`);
      safeSetText(node.querySelector(".last-image"), `Ultima imagem: ${fmtDate(item.last_image_at)} (${fmtRelative(item.last_image_at)})`);
      const mbDay = Number(item.estimated_4g_mb_per_day || 0);
      const gbMonth = Number(item.estimated_4g_gb_per_month || 0);
      safeSetText(
        node.querySelector(".data-usage"),
        `4G estimado: ${fmtNum(mbDay, 1)} MB/dia | ${fmtNum(gbMonth, 2)} GB/mes`
      );
      frag.appendChild(node);
    } else {
      const fallback = document.createElement("article");
      fallback.className = "device-card";
      fallback.textContent = `${item.device_id || "unknown_device"} | ${Boolean(item.is_active) ? "ATIVO" : "INATIVO"}`;
      frag.appendChild(fallback);
    }
  }
  devicesListEl.appendChild(frag);
}

function renderGallery(images) {
  if (!galleryEl) return;
  const signature = images.map((item) => item.filename || "").join("|");
  if (signature === state.lastImagesSignature) return;
  state.lastImagesSignature = signature;

  galleryEl.innerHTML = "";
  if (!images.length) {
    galleryEl.innerHTML = "<p class='empty'>Nenhuma foto encontrada para o filtro selecionado.</p>";
    return;
  }

  const frag = document.createDocumentFragment();
  for (const item of images) {
    if (!imageCardTpl || !imageCardTpl.content) continue;
    const node = imageCardTpl.content.cloneNode(true);
    const img = node.querySelector("img");
    if (img) {
      img.src = item.image_url;
      img.alt = `Captura ${item.device_id || "unknown_device"}`;
    }
    safeSetText(node.querySelector(".device"), item.device_id || "unknown_device");
    safeSetText(node.querySelector(".time"), fmtDate(item.captured_at));
    frag.appendChild(node);
  }
  galleryEl.appendChild(frag);
}

function renderLogs(logs) {
  if (!logsEl) return;
  const signature = logs
    .map((item) => `${item.timestamp || ""}|${item.device_id || ""}|${item.event || ""}|${item.message || ""}`)
    .join("|");
  if (signature === state.lastLogsSignature) return;
  state.lastLogsSignature = signature;

  logsEl.innerHTML = "";
  if (!logs.length) {
    logsEl.innerHTML = "<p class='empty'>Nenhum log recente para o filtro selecionado.</p>";
    return;
  }

  const frag = document.createDocumentFragment();
  for (const item of logs) {
    if (!logRowTpl || !logRowTpl.content) continue;
    const node = logRowTpl.content.cloneNode(true);
    safeSetText(node.querySelector(".line-top"), `${item.device_id || "unknown_device"} | ${item.event || "evento"}`);
    safeSetText(node.querySelector(".line-bottom"), `${fmtDate(item.timestamp)} | ${item.message || ""}`);
    frag.appendChild(node);
  }
  logsEl.appendChild(frag);
}

async function loadDashboard(options = {}) {
  const manual = Boolean(options.manual);
  try {
    setRefreshStatus("warn", manual ? "Atualizando..." : "Sincronizando...");

    const selected = state.selectedDevice;
    const summaryQ = toQuery({ device_id: selected });
    const imagesQ = toQuery({ device_id: selected, limit: 12 });
    const logsQ = toQuery({ device_id: selected, limit: 25 });

    const [summaryResp, devicesResp, imagesResp, logsResp] = await Promise.all([
      fetch(`/api/dashboard/summary${summaryQ}`, { cache: "no-store" }),
      fetch("/api/dashboard/devices", { cache: "no-store" }),
      fetch(`/api/dashboard/recent-images${imagesQ}`, { cache: "no-store" }),
      fetch(`/api/dashboard/recent-logs${logsQ}`, { cache: "no-store" }),
    ]);

    if (!summaryResp.ok || !devicesResp.ok || !imagesResp.ok || !logsResp.ok) {
      throw new Error(`Falha na API (${summaryResp.status}/${devicesResp.status}/${imagesResp.status}/${logsResp.status})`);
    }

    const summary = await summaryResp.json();
    const devicesData = await devicesResp.json();
    const imagesData = await imagesResp.json();
    const logsData = await logsResp.json();

    const allDevices = Array.isArray(devicesData.devices) ? devicesData.devices : [];
    renderDeviceFilter(allDevices);

    const selectedNow = state.selectedDevice;
    const visibleDevices = selectedNow
      ? allDevices.filter((item) => item.device_id === selectedNow)
      : allDevices;

    const activeDevices = visibleDevices.filter((item) => Boolean(item.is_active)).map((item) => item.device_id);

    renderDeviceChips(activeDevices);
    renderDevices(visibleDevices);
    renderGallery(Array.isArray(imagesData.images) ? imagesData.images : []);
    renderLogs(Array.isArray(logsData.logs) ? logsData.logs : []);

    const daysScope = Number(summary.total_images_scope_days || 1);
    safeSetText(imagesLabelEl, `Imagens recentes (${daysScope}d)`);
    safeSetText(totalImagesEl, String(summary.total_images ?? "-"));
    safeSetText(activeDevicesEl, String(activeDevices.length));
    safeSetText(knownDevicesEl, String(visibleDevices.length));
    const mbDay = Number(summary.estimated_4g_mb_per_day || 0);
    const gbMonth = Number(summary.estimated_4g_gb_per_month || 0);
    safeSetText(usageLabelEl, `Estimativa 4G (${selectedNow ? "filtro" : "geral"})`);
    safeSetText(overall4gEl, `${fmtNum(mbDay, 1)} MB/dia`);
    safeSetText(overall4gHintEl, `${fmtNum(gbMonth, 2)} GB/mes (estimado)`);

    const windowSeconds = Number(summary.active_window_seconds || 60);
    safeSetText(activeRuleEl, `Ativo se ultimo evento/imagem em ate ${windowSeconds}s`);

    if (summary.latest_image) {
      safeSetText(latestCaptureEl, `${summary.latest_image.device_id} | ${fmtDate(summary.latest_image.captured_at)}`);
    } else {
      safeSetText(latestCaptureEl, "Sem dados");
    }

    safeSetText(updatedAtEl, `Atualizado em ${fmtDate(summary.updated_at)}${selectedNow ? ` | Filtro: ${selectedNow}` : ""}`);
    setRefreshStatus("ok", `Online | auto refresh ${Math.round(state.pollMs / 1000)}s`);
  } catch (err) {
    setRefreshStatus("error", "Erro de leitura");
    safeSetText(updatedAtEl, `Erro: ${err.message}`);
    console.error(err);
  }
}

if (deviceFilterEl) {
  deviceFilterEl.addEventListener("change", () => {
    state.selectedDevice = deviceFilterEl.value || "";
    state.lastImagesSignature = "";
    state.lastLogsSignature = "";
    loadDashboard({ manual: true });
  });
}

if (refreshBtn) {
  refreshBtn.addEventListener("click", () => {
    loadDashboard({ manual: true });
  });
}

loadDashboard();
setInterval(() => loadDashboard(), state.pollMs);
