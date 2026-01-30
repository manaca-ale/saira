const summaryCards = document.getElementById("summary-cards");
const indicatorCards = document.getElementById("indicator-cards");
const cameraShots = document.getElementById("camera-shots");
const statusChip = document.getElementById("status-chip");
const statusText = document.getElementById("status-text");
const errorsList = document.getElementById("errors-list");
const cyclesList = document.getElementById("cycles-list");
const healthList = document.getElementById("health-list");
const controlStateBadge = document.getElementById("control-state");
const archiveStatus = document.getElementById("archive-status");
const controlStatus = document.getElementById("control-status");
const lastActionLine = document.getElementById("last-action");

const btnRunOnce = document.getElementById("btn-run-once");
const btnPause = document.getElementById("btn-pause");
const btnResume = document.getElementById("btn-resume");
const btnStop = document.getElementById("btn-stop");
const btnArchive = document.getElementById("btn-archive");

let cyclesData = [];
let errorsData = [];

const fmtDate = (iso) => {
  if (!iso) return "-";
  const d = new Date(iso + "Z");
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("pt-BR");
};

const fmtDuration = (ms) => {
  if (ms == null) return "-";
  const s = Math.round(ms / 100) / 10;
  return `${s}s`;
};

const buildCard = (label, value, sub) => {
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `
    <h4>${label}</h4>
    <div class="value">${value}</div>
    <div class="sub">${sub || ""}</div>
  `;
  return card;
};

const updateControlBadge = (control) => {
  if (!control) return;
  if (control.stop) {
    controlStateBadge.textContent = "stop";
    controlStateBadge.className = "badge error";
    if (btnArchive) btnArchive.disabled = false;
    return;
  }
  if (control.pause) {
    controlStateBadge.textContent = "pausado";
    controlStateBadge.className = "badge warn";
    if (btnArchive) btnArchive.disabled = true;
    return;
  }
  controlStateBadge.textContent = "ativo";
  controlStateBadge.className = "badge";
  if (btnArchive) btnArchive.disabled = true;
};

const setControlStatus = (message, isError = false) => {
  if (!controlStatus) return;
  controlStatus.textContent = message || "";
  controlStatus.className = isError ? "status-line error" : "status-line";
};

const renderSummary = (data) => {
  summaryCards.innerHTML = "";
  summaryCards.append(
    buildCard(
      "Câmeras ativas",
      data.cameras_active ?? "-",
      data.cameras_active_list?.join(", ") || "último ciclo"
    ),
    buildCard("Câmeras configuradas", data.cameras_configured ?? "-", "mapa do config"),
    buildCard("Ciclos totais", data.cycles_total ?? "-", "desde o início"),
    buildCard("Erros", data.cycles_error ?? "-", "ciclos com falha"),
    buildCard(
      "Último ciclo",
      data.last_cycle?.cycle_id ?? "-",
      data.last_cycle ? fmtDate(data.last_cycle.ts_end) : "sem dados"
    )
  );

  if (data.last_cycle?.ok === false) {
    statusChip.classList.add("error");
    statusText.textContent = "Último ciclo com erro";
  } else {
    statusChip.classList.remove("error");
    statusText.textContent = "Rodando";
  }

  updateControlBadge(data.control);

  if (lastActionLine) {
    const action = data.last_action;
    if (action && action.name) {
      const status = action.ok === false ? "erro" : "ok";
      const details = action.details ? `• ${action.details}` : "";
      lastActionLine.textContent = `Última ação: ${action.name} (${status})${details}`;
    } else {
      lastActionLine.textContent = "Última ação: sem dados";
    }
  }

  if (controlStatus && data.control) {
    const control = data.control;
    const age = data.last_cycle_age_s != null ? `${data.last_cycle_age_s}s` : "-";
    controlStatus.textContent = `Controle: pause=${control.pause} stop=${control.stop} run_once=${control.run_once} • Último ciclo há ${age}`;
  }

  if (cameraShots) {
    const shots = data.last_screenshots || [];
    cameraShots.innerHTML = "";
    if (!shots.length) {
      cameraShots.innerHTML = '<span class="muted">Sem capturas recentes.</span>';
    } else {
      shots.forEach((shot) => {
        const card = document.createElement("div");
        card.className = "shot-card";
        const imgSrc = `/media?path=${encodeURIComponent(shot.path)}`;
        card.innerHTML = `
          <img src="${imgSrc}" alt="${shot.camera}" />
          <div class="meta">Último screenshot - ${shot.camera} • ${fmtDate(shot.ts_end)}</div>
        `;
        cameraShots.appendChild(card);
      });
    }
  }
};

const renderIndicators = () => {
  if (!indicatorCards) return;
  indicatorCards.innerHTML = "";
  if (!cyclesData.length) {
    indicatorCards.append(buildCard("Média de duração", "-", "sem ciclos"));
    return;
  }

  const durations = cyclesData.map((c) => c.duration_ms || 0);
  const total = durations.reduce((a, b) => a + b, 0);
  const avg = total / durations.length;
  const sorted = durations.slice().sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)] || 0;
  const p95 = sorted[Math.floor(sorted.length * 0.95)] || 0;

  const errors = cyclesData.filter((c) => c.ok === false);
  const errorRate = (errors.length / cyclesData.length) * 100;

  const lastWindowSize = 5;
  const lastWindow = cyclesData.slice(-lastWindowSize);
  const windowErrors = lastWindow.filter((c) => c.ok === false).length;

  const lastError = errors.length ? errors[errors.length - 1] : null;

  indicatorCards.append(
    buildCard("Média duração", fmtDuration(avg), `mediana ${fmtDuration(median)}`),
    buildCard("P95 duração", fmtDuration(p95), "ciclos mais lentos"),
    buildCard("Taxa de erro", `${errorRate.toFixed(1)}%`, `${errors.length} falhas`),
    buildCard("Erros na última janela", `${windowErrors}/${lastWindowSize}`, "janela de 5 ciclos"),
    buildCard(
      "Último erro",
      lastError ? `#${lastError.cycle_id}` : "-",
      lastError ? (lastError.error?.message || "erro") : "sem falhas"
    )
  );
};

const renderErrors = (items) => {
  errorsList.innerHTML = "";
  if (!items.length) {
    errorsList.innerHTML = '<div class="item"><p class="muted">Sem erros recentes.</p></div>';
    return;
  }
  items.forEach((item) => {
    const wrapper = document.createElement("div");
    wrapper.className = "item";
    const artifactDir = item.artifact_dir;
    const links = [];
    if (artifactDir) {
      ["window.txt", "logcat.txt", "health.json", "screenshot.png"].forEach((file) => {
        const path = `${artifactDir}\\${file}`;
        links.push(`<a class="code" target="_blank" href="/media?path=${encodeURIComponent(path)}">${file}</a>`);
      });
    }
    wrapper.innerHTML = `
      <h4>Cycle ${item.cycle_id} <span class="badge error">erro</span></h4>
      <p>${item.type || "Erro"}: ${item.message || "-"}</p>
      <p>Etapa: <span class="code">${item.step || "-"}</span> • ${fmtDate(item.ts_end)}</p>
      ${links.length ? `<p>Artifacts: ${links.join(" ")}</p>` : ""}
    `;
    errorsList.appendChild(wrapper);
  });
};

const renderCycles = (items) => {
  cyclesList.innerHTML = "";
  if (!items.length) {
    cyclesList.innerHTML = '<div class="item"><p class="muted">Sem ciclos ainda.</p></div>';
    return;
  }

  items
    .slice()
    .reverse()
    .forEach((item) => {
      const wrapper = document.createElement("div");
      wrapper.className = "item";
      const status = item.ok ? "ok" : "erro";
      const badgeClass = item.ok ? "badge" : "badge error";
      const errorMsg = item.error?.message ? `• ${item.error.message}` : "";
      const steps = item.steps || [];
      const stepList = steps
        .map(
          (step) =>
            `<div class="code">${step.ok ? "?" : "?"} ${step.name} (${fmtDuration(
              step.duration_ms
            )}) ${step.details || ""}</div>`
        )
        .join("");

      wrapper.innerHTML = `
        <h4>Cycle ${item.cycle_id} <span class="${badgeClass}">${status}</span></h4>
        <p>Duração: ${fmtDuration(item.duration_ms)} • ${fmtDate(item.ts_end)} ${errorMsg}</p>
        <details>
          <summary class="muted">Detalhes do ciclo</summary>
          <div class="stack">${stepList || '<span class="muted">Sem steps</span>'}</div>
        </details>
      `;
      cyclesList.appendChild(wrapper);
    });
};

const renderHealth = (items) => {
  healthList.innerHTML = "";
  if (!items.length) {
    healthList.innerHTML = '<div class="item"><p class="muted">Sem registros de saúde.</p></div>';
    return;
  }
  items
    .slice()
    .reverse()
    .slice(0, 20)
    .forEach((item) => {
      const wrapper = document.createElement("div");
      wrapper.className = "item";
      wrapper.innerHTML = `
        <h4>Health ${item.health_cycle_id ?? "-"}</h4>
        <p>Serial: <span class="code">${item.serial || "-"}</span> • ${fmtDate(item.timestamp)}</p>
        <p>Bateria: ${item.snapshot?.battery_level ?? "-"}% • Temp: ${item.snapshot?.battery_temp_c ?? "-"}°C</p>
        <p>Wi-Fi: ${item.snapshot?.wlan0_ip || "-"} • Internet: ${item.snapshot?.internet_ok ? "ok" : "falha"}</p>
      `;
      healthList.appendChild(wrapper);
    });
};

const loadSummary = async () => {
  const res = await fetch("/api/summary");
  if (!res.ok) return;
  const data = await res.json();
  renderSummary(data);
};

const loadErrors = async () => {
  const res = await fetch("/api/errors?limit=120");
  if (!res.ok) return;
  const data = await res.json();
  errorsData = data.items || [];
  renderErrors(errorsData);
};

const loadCycles = async () => {
  const res = await fetch("/api/cycles?limit=240");
  if (!res.ok) return;
  const data = await res.json();
  cyclesData = data.items || [];
  renderCycles(cyclesData);
  renderIndicators();
};

const loadHealth = async () => {
  const res = await fetch("/api/health?limit=200");
  if (!res.ok) return;
  const data = await res.json();
  renderHealth(data.items || []);
};


const postControl = async (action) => {
  console.log("POST /api/control", action);
  setControlStatus("Enviando comando...", false);
  const res = await fetch("/api/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  if (!res.ok) {
    const text = await res.text();
    console.warn("API /api/control erro", res.status, text);
    setControlStatus(text || "Falha ao enviar comando.", true);
    return;
  }
  const payload = await res.json();
  console.log("API /api/control ok", payload);
  setControlStatus("Comando aplicado.", false);
  loadSummary();
};

const archiveLogs = async () => {
  console.log("POST /api/archive");
  if (archiveStatus) archiveStatus.textContent = "Arquivando logs...";
  const res = await fetch("/api/archive", { method: "POST" });
  if (!res.ok) {
    const text = await res.text();
    console.warn("API /api/archive erro", res.status, text);
    if (archiveStatus) archiveStatus.textContent = text || "Falha ao arquivar.";
    setControlStatus("Arquivo não encontrado: reinicie o servidor do dashboard.", true);
    return;
  }
  const data = await res.json();
  console.log("API /api/archive ok", data);
  if (archiveStatus) archiveStatus.textContent = `Arquivados: ${data.moved || 0} itens.`;
  setControlStatus("Arquivamento concluído.", false);
  refreshAll();
};

const refreshAll = () => {
  loadSummary();
  loadErrors();
  loadCycles();
  loadHealth();
};

refreshAll();
setInterval(refreshAll, 20000);

const loadVersion = async () => {
  const res = await fetch("/api/version");
  if (!res.ok) return;
  const data = await res.json();
  setControlStatus(`Servidor: ${data.version} • ${data.file}`, false);
};

loadVersion();

const wireButton = (id, fn) => {
  const btn = document.getElementById(id);
  if (btn) btn.addEventListener("click", fn);
};

wireButton("refresh-errors", loadErrors);
wireButton("refresh-cycles", loadCycles);
wireButton("refresh-health", loadHealth);

btnRunOnce?.addEventListener("click", () => postControl("run_once"));
btnPause?.addEventListener("click", () => postControl("pause"));
btnResume?.addEventListener("click", () => postControl("resume"));
btnStop?.addEventListener("click", () => postControl("stop"));
btnArchive?.addEventListener("click", archiveLogs);
