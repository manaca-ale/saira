#!/usr/bin/env python3
"""Watchdog de WAN da Pi: reinicia o roteador 4G pela LAN quando a internet some.

Motivação (incidentes 16→18/08 e 20→22/08/2026 na pi-cam-001): o Tenda 4G03 Pro
trava/reinicia sozinho e o LTE não re-registra; a Pi fica VIVA na LAN o blecaute
inteiro, enxergando o roteador, mas ninguém a manda reiniciá-lo — 52h e 45h sem
câmera até alguém ir a campo. Este daemon fecha esse buraco:

  * sonda a WAN a cada CHECK_INTERVAL_S (VPN WireGuard + HTTP 204 público);
  * após WAN_DOWN_REBOOT_S contínuos sem WAN, loga na UI do roteador pela LAN e
    dispara o reboot (API interna do firmware Tenda: /login/Auth com senha MD5 +
    goform/setModules {"reboot":{"action":"reboot"}});
  * se não voltar, INSISTE a cada REBOOT_RETRY_S (em 16/08 um reboot só não
    bastou; o segundo, 52h depois, trouxe o LTE) — com teto diário
    MAX_REBOOTS_PER_DAY para nunca virar loop destrutivo.

Sem dependências além da stdlib (a Pi não tem folga de RAM para browser/Playwright;
a UI do Tenda é uma SPA que fala JSON simples). Segredo do roteador fica em
/etc/saira/wan-watchdog.env (root-only), NUNCA no repo.

A decisão (decide()) é uma função pura testável; I/O fica nas bordas.
"""
from __future__ import annotations

import hashlib
import http.cookiejar
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("wan-watchdog")


# ----------------------------------------------------------------- config
def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Config:
    router_url: str
    router_user: str
    router_password: str
    check_interval_s: float
    wan_down_reboot_s: float
    reboot_retry_s: float
    max_reboots_per_day: int
    vpn_peer: str
    http_probe_urls: tuple
    state_file: Path
    ec2_base: str
    device_id: str

    @staticmethod
    def from_env() -> "Config":
        probes = os.environ.get(
            "WAN_HTTP_PROBES",
            "http://connectivitycheck.gstatic.com/generate_204,"
            "http://www.msftconnecttest.com/connecttest.txt",
        )
        return Config(
            router_url=os.environ.get("ROUTER_URL", "http://192.168.0.1").rstrip("/"),
            router_user=os.environ.get("ROUTER_USER", "admin"),
            router_password=os.environ.get("ROUTER_PASSWORD", ""),
            check_interval_s=float(os.environ.get("CHECK_INTERVAL_S", "60")),
            wan_down_reboot_s=float(os.environ.get("WAN_DOWN_REBOOT_S", "900")),
            reboot_retry_s=float(os.environ.get("REBOOT_RETRY_S", "1800")),
            max_reboots_per_day=int(os.environ.get("MAX_REBOOTS_PER_DAY", "8")),
            vpn_peer=os.environ.get("VPN_PEER", "10.8.0.1"),
            http_probe_urls=tuple(u.strip() for u in probes.split(",") if u.strip()),
            state_file=Path(os.environ.get("STATE_FILE", "/var/lib/saira/wan-watchdog.json")),
            ec2_base=os.environ.get("EC2_BASE", "").rstrip("/"),
            device_id=os.environ.get("DEVICE_ID", "pi-cam-001"),
        )


# ------------------------------------------------------------------ state
@dataclass
class State:
    down_since: Optional[float] = None      # epoch em que a WAN morreu (None = up)
    last_reboot_at: Optional[float] = None  # epoch do último reboot disparado
    reboots_this_outage: int = 0
    reboots_today: int = 0
    reboots_day: str = ""                   # YYYY-MM-DD do contador diário
    total_reboots: int = 0
    history: list = field(default_factory=list)  # últimos eventos (auditoria)

    def to_json(self) -> dict:
        return dict(self.__dict__)

    @staticmethod
    def from_json(d: dict) -> "State":
        s = State()
        for k, v in d.items():
            if hasattr(s, k):
                setattr(s, k, v)
        return s


def decide(cfg: Config, st: State, wan_up: bool, now: float, today: str) -> Optional[str]:
    """Função pura: muta `st` e devolve 'reboot' quando é hora de reiniciar o
    roteador, senão None. Regras:
      - WAN up -> zera o episódio (down_since/reboots_this_outage).
      - WAN down há menos que wan_down_reboot_s -> espera (blip normal do LTE).
      - reboot recente (< reboot_retry_s) -> espera o roteador subir/registrar.
      - teto diário atingido -> desiste até o dia virar (nunca loop infinito).
    """
    if st.reboots_day != today:
        st.reboots_day, st.reboots_today = today, 0
    if wan_up:
        if st.down_since is not None:
            st.history.append({"t": now, "ev": "wan_up",
                               "after_reboots": st.reboots_this_outage,
                               "outage_s": int(now - st.down_since)})
            st.history = st.history[-50:]
        st.down_since = None
        st.reboots_this_outage = 0
        return None
    if st.down_since is None:
        st.down_since = now
        return None
    if now - st.down_since < cfg.wan_down_reboot_s:
        return None
    if st.last_reboot_at is not None and now - st.last_reboot_at < cfg.reboot_retry_s:
        return None
    if st.reboots_today >= cfg.max_reboots_per_day:
        return None
    return "reboot"


def record_reboot(st: State, now: float, ok: bool, detail: str = "") -> None:
    st.last_reboot_at = now
    st.reboots_this_outage += 1
    st.reboots_today += 1
    if ok:
        st.total_reboots += 1
    st.history.append({"t": now, "ev": "reboot" if ok else "reboot_failed",
                       "n": st.reboots_this_outage, "detail": detail})
    st.history = st.history[-50:]


# ----------------------------------------------------------------- probes
def ping(host: str, timeout_s: int = 3) -> bool:
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", str(timeout_s), host],
                           capture_output=True, timeout=timeout_s + 2)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def http_ok(url: str, timeout_s: int = 8) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "saira-wan-watchdog"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return 200 <= resp.status < 400
    except (urllib.error.URLError, OSError, ValueError):
        return False


def wan_is_up(cfg: Config) -> bool:
    """UP se QUALQUER sonda responder: VPN (EC2) ou HTTP público. Só reinicia o
    roteador quando não há internet nenhuma — EC2 fora do ar não é culpa dele."""
    if cfg.vpn_peer and ping(cfg.vpn_peer):
        return True
    return any(http_ok(u) for u in cfg.http_probe_urls)


# ----------------------------------------------------------------- router
class TendaRouter:
    """Cliente mínimo da UI web do Tenda 4G03 Pro (firmware V04.03.01.xx).
    Mapeado do JS da própria UI: login.js + chunk-common.js + sysReboot.js."""

    def __init__(self, base: str, user: str, password: str, timeout_s: int = 15):
        self.base, self.user, self.password, self.timeout = base, user, password, timeout_s
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def _json(self, path: str, body: Optional[dict] = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method="POST" if data else "GET",
            headers={"Content-Type": "application/json; charset=UTF-8",
                     "User-Agent": "saira-wan-watchdog"},
        )
        with self.opener.open(req, timeout=self.timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
        try:
            return json.loads(raw)
        except ValueError:
            return {"raw": raw[:200]}

    def reachable(self) -> bool:
        try:
            req = urllib.request.Request(self.base + "/login.html",
                                         headers={"User-Agent": "saira-wan-watchdog"})
            with self.opener.open(req, timeout=self.timeout) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def login(self) -> bool:
        """Imita o browser: GET login.html + /login/Usernum carimbam a sessão
        ANTES do Auth — sem isso o firmware responde "login time expired"
        (observado em campo 23/08/2026) e o Auth falha mesmo com senha certa."""
        try:
            self.reachable()
            self._json("/login/Usernum")
        except (urllib.error.URLError, OSError, ValueError):
            pass
        pwd_md5 = hashlib.md5(self.password.encode()).hexdigest()
        r = self._json("/login/Auth", {"username": self.user, "password": pwd_md5})
        ok = int(r.get("errCode", -1)) == 0
        if not ok:
            log.warning("login no roteador recusado: %s", r)
        return ok

    def get_modules(self, modules: str) -> dict:
        return self._json(f"/goform/getModules?modules={modules}&rand={time.time()}")

    def reboot(self) -> dict:
        return self._json("/goform/setModules", {"reboot": {"action": "reboot"}})


def reboot_router(cfg: Config) -> tuple:
    r = TendaRouter(cfg.router_url, cfg.router_user, cfg.router_password)
    if not r.reachable():
        return False, "roteador inalcançável na LAN"
    try:
        if not r.login():
            return False, "login recusado (senha errada ou UI bloqueada por tentativas)"
        resp = r.reboot()
    except (urllib.error.URLError, OSError) as exc:
        # Conexão cortada logo após o POST = o roteador já está caindo: sucesso.
        return True, f"reboot enviado (conexão encerrada: {exc.__class__.__name__})"
    return True, f"reboot aceito: {resp}"


# -------------------------------------------------------------- reporting
def post_status(cfg: Config, message: str) -> None:
    if not cfg.ec2_base:
        return
    try:
        data = urllib.parse.urlencode({"message": f"{cfg.device_id}: {message}"}).encode()
        req = urllib.request.Request(f"{cfg.ec2_base}/status", data=data, method="POST")
        urllib.request.urlopen(req, timeout=10).read()
    except (urllib.error.URLError, OSError, ValueError):
        pass


def load_state(path: Path) -> State:
    try:
        return State.from_json(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return State()


def save_state(path: Path, st: State) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st.to_json()), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        log.warning("não consegui salvar estado em %s: %s", path, exc)


# ------------------------------------------------------------------- main
def main() -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(message)s")
    _load_env_file(Path(os.environ.get("WAN_WATCHDOG_ENV", "/etc/saira/wan-watchdog.env")))
    _load_env_file(Path("/opt/saira/agent/.env"))  # EC2_BASE / DEVICE_ID do agente
    cfg = Config.from_env()
    if not cfg.router_password:
        log.error("ROUTER_PASSWORD vazio — watchdog sem poder de reboot; só monitorando")
    st = load_state(cfg.state_file)
    log.info("wan-watchdog iniciado: roteador=%s reboot após %.0fs sem WAN, retry %.0fs, teto %d/dia",
             cfg.router_url, cfg.wan_down_reboot_s, cfg.reboot_retry_s, cfg.max_reboots_per_day)
    was_up: Optional[bool] = None
    while True:
        now = time.time()
        up = wan_is_up(cfg)
        if up != was_up:
            log.warning("WAN %s", "UP" if up else "DOWN")
            if up and was_up is False and st.reboots_this_outage:
                post_status(cfg, f"wan_watchdog: WAN voltou após {st.reboots_this_outage} reboot(s) do roteador")
            was_up = up
        action = decide(cfg, st, up, now, time.strftime("%Y-%m-%d", time.localtime(now)))
        if action == "reboot":
            down_min = (now - (st.down_since or now)) / 60
            if cfg.router_password:
                ok, detail = reboot_router(cfg)
                log.critical("WAN morta há %.0f min — reboot do roteador #%d: %s (%s)",
                             down_min, st.reboots_this_outage + 1, "OK" if ok else "FALHOU", detail)
                record_reboot(st, now, ok, detail)
            else:
                log.error("WAN morta há %.0f min e sem ROUTER_PASSWORD — nada a fazer", down_min)
                st.last_reboot_at = now  # evita spam de log a cada tick
        save_state(cfg.state_file, st)
        time.sleep(cfg.check_interval_s)


if __name__ == "__main__":
    sys.exit(main())
