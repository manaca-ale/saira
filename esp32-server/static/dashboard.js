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

const openCameraModalBtn = byId("openCameraModalBtn");
const openCameraModalBtnInline = byId("openCameraModalBtnInline");
const cameraRegistrationStatusEl = byId("cameraRegistrationStatus");
const cameraModalBackdropEl = byId("cameraModalBackdrop");
const closeCameraModalBtn = byId("closeCameraModalBtn");
const cancelCameraModalBtn = byId("cancelCameraModalBtn");
const cameraRegistrationForm = byId("cameraRegistrationForm");
const cameraDeviceIdEl = byId("cameraDeviceId");
const cameraNameEl = byId("cameraName");
const cameraLatitudeEl = byId("cameraLatitude");
const cameraLongitudeEl = byId("cameraLongitude");
const cameraLogradouroEl = byId("cameraLogradouro");
const cameraBairroEl = byId("cameraBairro");
const cameraRpaEl = byId("cameraRpa");
const cameraRtspUrlEl = byId("cameraRtspUrl");
const cameraCaptureIntervalEl = byId("cameraCaptureInterval");
const cameraIsActiveEl = byId("cameraIsActive");
const cameraFormFeedbackEl = byId("cameraFormFeedback");
const cameraFormSubmitBtn = byId("cameraFormSubmitBtn");

const state = {
  selectedDevice: "",
  pollMs: 15000,
  lastImagesSignature: "",
  lastLogsSignature: "",
  registrationOptions: [],
  registrationBackend: { ok: false, error: "Carregando..." },
  registrationLoading: false,
  registrationLoadedAt: 0,
};
const BRAZIL_TZ = "America/Sao_Paulo";

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
  const dt = parseSairaDate(iso);
  if (dt) {
    return dt.toLocaleString("pt-BR", { hour12: false, timeZone: BRAZIL_TZ });
  }
  const raw = String(iso).trim();
  return raw.replace("T", " ").replace("Z", "");
}

function fmtRelative(iso) {
  if (!iso) return "-";
  const dt = parseSairaDate(iso);
  if (!dt) return fmtDate(iso);
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

function setCameraFeedback(kind, text) {
  if (!cameraFormFeedbackEl) return;
  cameraFormFeedbackEl.classList.remove("is-error", "is-success");
  if (kind === "error") cameraFormFeedbackEl.classList.add("is-error");
  if (kind === "success") cameraFormFeedbackEl.classList.add("is-success");
  cameraFormFeedbackEl.textContent = text;
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

function setRegistrationStatus(message, kind = "ok") {
  if (!cameraRegistrationStatusEl) return;
  cameraRegistrationStatusEl.textContent = message;
  cameraRegistrationStatusEl.className = "camera-register-status";
  if (kind === "error") {
    cameraRegistrationStatusEl.style.color = "#8f261b";
  } else if (kind === "warn") {
    cameraRegistrationStatusEl.style.color = "#845109";
  } else {
    cameraRegistrationStatusEl.style.color = "#24573b";
  }
}

function renderCameraDeviceOptions() {
  if (!cameraDeviceIdEl) return;
  const current = cameraDeviceIdEl.value;
  cameraDeviceIdEl.innerHTML = "";

  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Selecione um dispositivo";
  cameraDeviceIdEl.appendChild(placeholder);

  const rows = Array.isArray(state.registrationOptions) ? state.registrationOptions.slice() : [];
  rows.sort((a, b) => String(a.device_id || "").localeCompare(String(b.device_id || "")));

  let unregisteredCount = 0;
  for (const row of rows) {
    const deviceId = String(row.device_id || "").trim();
    if (!deviceId) continue;
    const isRegistered = Boolean(row.is_registered);
    if (!isRegistered) unregisteredCount += 1;
    const opt = document.createElement("option");
    opt.value = deviceId;
    opt.disabled = isRegistered;
    opt.textContent = isRegistered
      ? `${deviceId} (ja cadastrado)`
      : `${deviceId}${row.is_active ? " (ativo)" : " (inativo)"}`;
    cameraDeviceIdEl.appendChild(opt);
  }

  if (current) {
    cameraDeviceIdEl.value = current;
  }

  const backend = state.registrationBackend || {};
  if (!backend.ok) {
    setRegistrationStatus(`Cadastro indisponivel: ${backend.error || "backend offline"}`, "error");
    return;
  }
  setRegistrationStatus(
    `${unregisteredCount} dispositivo(s) disponivel(is) para cadastro | ${rows.length - unregisteredCount} ja cadastrado(s).`,
    unregisteredCount > 0 ? "ok" : "warn"
  );
}

function openCameraModal() {
  if (!cameraModalBackdropEl) return;
  cameraModalBackdropEl.hidden = false;
  document.body.style.overflow = "hidden";
  if (cameraNameEl) {
    const active = document.activeElement;
    const shouldFocus = !active || active === document.body;
    if (shouldFocus) cameraNameEl.focus();
  }
}

function closeCameraModal() {
  if (!cameraModalBackdropEl) return;
  cameraModalBackdropEl.hidden = true;
  document.body.style.overflow = "";
}

function onDeviceOptionChange() {
  if (!cameraDeviceIdEl || !cameraNameEl) return;
  const deviceId = String(cameraDeviceIdEl.value || "").trim();
  if (!deviceId) return;
  const current = String(cameraNameEl.value || "").trim();
  if (!current || current.startsWith("Camera ")) {
    cameraNameEl.value = `Camera ${deviceId}`;
  }
}

function parseNumberField(el) {
  const raw = String(el?.value || "").trim();
  if (!raw) return null;
  const n = Number(raw);
  if (!Number.isFinite(n)) return null;
  return n;
}

function payloadOrNull(raw) {
  const txt = String(raw || "").trim();
  return txt ? txt : null;
}

async function loadCameraRegistrationOptions({ silent = false } = {}) {
  if (state.registrationLoading) return;
  state.registrationLoading = true;
  if (!silent) setRegistrationStatus("Atualizando opcoes de cadastro...", "warn");
  try {
    const resp = await fetch("/api/dashboard/camera-registration/options", { cache: "no-store" });
    if (!resp.ok) {
      throw new Error(`Falha ao buscar opcoes (${resp.status})`);
    }
    const data = await resp.json();
    state.registrationOptions = Array.isArray(data.devices) ? data.devices : [];
    state.registrationBackend = data.backend || {};
    state.registrationLoadedAt = Date.now();
    renderCameraDeviceOptions();
  } catch (err) {
    state.registrationOptions = [];
    state.registrationBackend = { ok: false, error: err.message || "Erro" };
    renderCameraDeviceOptions();
  } finally {
    state.registrationLoading = false;
  }
}

async function fetchLatestCameraImageByDevice(deviceId) {
  const did = String(deviceId || "").trim();
  if (!did) return null;
  const resp = await fetch(`/api/dashboard/camera-latest-image${toQuery({ device_id: did })}`, {
    cache: "no-store",
  });
  if (!resp.ok) return null;
  const payload = await resp.json().catch(() => null);
  if (!payload || typeof payload !== "object") return null;
  return payload;
}

async function submitCameraRegistration(event) {
  event.preventDefault();
  if (!cameraRegistrationForm) return;

  const deviceId = String(cameraDeviceIdEl?.value || "").trim();
  const name = String(cameraNameEl?.value || "").trim();
  const latitude = parseNumberField(cameraLatitudeEl);
  const longitude = parseNumberField(cameraLongitudeEl);
  const captureInterval = parseInt(String(cameraCaptureIntervalEl?.value || "30").trim(), 10);

  if (!deviceId) {
    setCameraFeedback("error", "Selecione um dispositivo.");
    return;
  }
  if (!name) {
    setCameraFeedback("error", "Informe o nome da camera.");
    return;
  }
  if (latitude === null || longitude === null) {
    setCameraFeedback("error", "Latitude e longitude devem ser numericas.");
    return;
  }
  if (!Number.isInteger(captureInterval) || captureInterval < 1) {
    setCameraFeedback("error", "Intervalo de captura deve ser inteiro >= 1.");
    return;
  }

  const payload = {
    device_id: deviceId,
    name,
    latitude,
    longitude,
    capture_interval_seconds: captureInterval,
    is_active: Boolean(cameraIsActiveEl?.checked),
    logradouro: payloadOrNull(cameraLogradouroEl?.value),
    bairro: payloadOrNull(cameraBairroEl?.value),
    rpa: payloadOrNull(cameraRpaEl?.value),
    rtsp_url: payloadOrNull(cameraRtspUrlEl?.value),
  };

  if (cameraFormSubmitBtn) cameraFormSubmitBtn.disabled = true;
  setCameraFeedback("warn", "Enviando cadastro para o backend...");

  try {
    const resp = await fetch("/api/dashboard/camera-registration", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const errorMsg = body.error || `Falha no cadastro (${resp.status})`;
      throw new Error(errorMsg);
    }

    const camera = body.camera || {};
    setCameraFeedback("success", `Camera cadastrada com sucesso (id=${camera.id || "n/a"}).`);
    state.registrationLoadedAt = 0;
    await Promise.all([
      loadCameraRegistrationOptions({ silent: true }),
      loadDashboard({ manual: true }),
    ]);
    setTimeout(() => closeCameraModal(), 600);
  } catch (err) {
    setCameraFeedback("error", err.message || "Falha ao cadastrar camera.");
  } finally {
    if (cameraFormSubmitBtn) cameraFormSubmitBtn.disabled = false;
  }
}

async function loadDashboard(options = {}) {
  const manual = Boolean(options.manual);
  try {
    setRefreshStatus("warn", manual ? "Atualizando..." : "Sincronizando...");

    const selected = state.selectedDevice;
    const stateQ = toQuery({ device_id: selected, image_limit: 12, log_limit: 25 });
    const dashboardResp = await fetch(`/api/dashboard/state${stateQ}`, { cache: "no-store" });
    if (!dashboardResp.ok) {
      throw new Error(`Falha na API (${dashboardResp.status})`);
    }
    const dashboardData = await dashboardResp.json();
    const summary = dashboardData.summary || {};
    const devicesData = dashboardData.devices || {};
    const imagesData = dashboardData.recent_images || {};
    const logsData = dashboardData.recent_logs || {};

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

    let latestCapture = null;
    if (selectedNow) {
      latestCapture = await fetchLatestCameraImageByDevice(selectedNow);
    }
    if (latestCapture && latestCapture.captured_at) {
      safeSetText(latestCaptureEl, `${selectedNow} | ${fmtDate(latestCapture.captured_at)}`);
    } else if (summary.latest_image) {
      safeSetText(latestCaptureEl, `${summary.latest_image.device_id} | ${fmtDate(summary.latest_image.captured_at)}`);
    } else {
      safeSetText(latestCaptureEl, "Sem dados");
    }

    safeSetText(updatedAtEl, `Atualizado em ${fmtDate(summary.updated_at)}${selectedNow ? ` | Filtro: ${selectedNow}` : ""}`);
    setRefreshStatus("ok", `Online | auto refresh ${Math.round(state.pollMs / 1000)}s`);

    if (!state.registrationLoading && Date.now() - state.registrationLoadedAt > 30000) {
      loadCameraRegistrationOptions({ silent: true });
    }
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
    loadCameraRegistrationOptions({ silent: true });
  });
}

if (openCameraModalBtn) {
  openCameraModalBtn.addEventListener("click", () => openCameraModal());
}
if (openCameraModalBtnInline) {
  openCameraModalBtnInline.addEventListener("click", () => openCameraModal());
}
if (closeCameraModalBtn) {
  closeCameraModalBtn.addEventListener("click", () => closeCameraModal());
}
if (cancelCameraModalBtn) {
  cancelCameraModalBtn.addEventListener("click", () => closeCameraModal());
}
if (cameraModalBackdropEl) {
  cameraModalBackdropEl.addEventListener("click", (event) => {
    if (event.target === cameraModalBackdropEl) {
      closeCameraModal();
    }
  });
}
if (cameraDeviceIdEl) {
  cameraDeviceIdEl.addEventListener("change", onDeviceOptionChange);
}
if (cameraRegistrationForm) {
  cameraRegistrationForm.addEventListener("submit", submitCameraRegistration);
}
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && cameraModalBackdropEl && !cameraModalBackdropEl.hidden) {
    closeCameraModal();
  }
});

loadDashboard();
loadCameraRegistrationOptions();
setInterval(() => loadDashboard(), state.pollMs);
