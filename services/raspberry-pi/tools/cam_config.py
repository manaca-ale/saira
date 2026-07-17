#!/usr/bin/env python3
"""Reconciliador declarativo de config da câmera IP (Intelbras VIP-3260-Z-IA).

Substitui/unifica cam_shutter.sh + cam_ir_saver.sh. Guarda a config DESEJADA em
cam_profile.json (declarativa, versionável) e GARANTE que a câmera bata com ela:

  1. GATE DE ESTABILIDADE: a porta 80/CGI dessa câmera é frágil e COLAPSA sob
     rajada (vira HTTP 000). Antes de tocar em qualquer coisa, sondamos o CGI
     com N leituras ESPAÇADAS e só seguimos se ele estiver estável. Se não
     estiver, sai limpo (sem martelar) — a próxima execução do cron tenta de novo.
  2. IDEMPOTENTE: lê a config atual (getConfig), compara com o alvo e escreve
     SÓ o que divergiu (comparação numérica tolerante — evita reescrever
     "33.33" vs "33.330000" pra sempre).
  3. ESCRITA SEGURA: um setConfig POR GRUPO, ESPAÇADO, e cada um é VERIFICADO por
     uma leitura de volta. Falha → backoff exponencial (minutos, não 20s) até um
     teto, depois desiste e loga — nunca entra em loop apertado que derruba a porta.
  4. DIA/NOITE: o obturador é escolhido pelo horário (day_start/night_start).
     IR/WhiteLight são constantes (persistem, só mudam brilho do iluminador).
  5. LOG: sucesso/falha por chave (stdout + syslog via `logger`).

Uso:
  cam_config.py                 # reconcilia (modo auto pelo horário)
  cam_config.py --mode day      # força o obturador de dia
  cam_config.py --dry-run       # mostra o diff, não escreve
  cam_config.py --profile p.json --env /opt/saira/agent/.env

Cron sugerido (substitui os dois antigos):
  */30 6-18 * * *  /opt/saira/venv/bin/python /opt/saira/tools/cam_config.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests
from requests.auth import HTTPDigestAuth

DEFAULT_ENV = "/opt/saira/agent/.env"
DEFAULT_PROFILE = str(Path(__file__).resolve().parent / "cam_profile.json")

# Gate de estabilidade do CGI (porta 80 frágil).
STABILITY_PROBES = 3          # leituras espaçadas
STABILITY_GAP_S = 3.0         # intervalo entre sondas
STABILITY_MIN_OK = 3          # quantas precisam responder 200 p/ considerar estável
# Escrita: espaçamento + backoff por chave.
WRITE_GAP_S = 4.0             # entre grupos de escrita
WRITE_MAX_RETRIES = 3         # tentativas por grupo
WRITE_BACKOFF_BASE_S = 30.0   # backoff inicial ao falhar um grupo
WRITE_BACKOFF_MAX_S = 240.0   # teto do backoff
HTTP_TIMEOUT_S = 10.0
NUM_TOL = 0.01                # tolerância na comparação numérica
# ExposureValue2 é DINÂMICO em ExposureMode=Auto: a câmera auto-expõe e a leitura
# de volta varia (não bate com o valor setado). Então NÃO serve para detectar
# drift nem para verify — é escrito junto com GainMax (que persiste e é o âncora
# de verificação do grupo). Sem isto, o reconciliador reescreveria a exposição
# a cada ciclo eternamente (achado de campo 2026-07-17).
NO_VERIFY_KEYS = {"VideoInOptions[0].ExposureValue2"}


def log(msg: str) -> None:
    print(msg, flush=True)
    try:
        subprocess.run(["logger", "-t", "cam_config", msg], timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def load_env(path: str) -> dict:
    """Lê IP_CAM_USER/PASS e deriva o IP do IP_CAM_URL (ou RTSP_URL)."""
    kv: dict[str, str] = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        kv[k.strip()] = v.strip().strip('"').strip("'")
    return kv


def camera_ip(env: dict) -> Optional[str]:
    import re

    for key in ("IP_CAM_URL", "RTSP_URL"):
        val = env.get(key, "")
        m = re.search(r"(\d+\.\d+\.\d+\.\d+)", val)
        if m:
            return m.group(1)
    return None


def _num_eq(a: str, b: str) -> bool:
    """Igualdade tolerante: numérica com folga NUM_TOL, senão string exata."""
    try:
        return abs(float(a) - float(b)) <= NUM_TOL
    except (ValueError, TypeError):
        return str(a).strip() == str(b).strip()


@dataclass
class Camera:
    base: str  # http://ip
    auth: HTTPDigestAuth
    session: requests.Session

    def _cgi(self, query: str) -> tuple[int, str]:
        """GET cru no CGI. Devolve (http_code, body). code=0 em falha de conexão
        (o equivalente ao HTTP 000 do curl)."""
        url = f"{self.base}/cgi-bin/{query}"
        try:
            r = self.session.get(url, auth=self.auth, timeout=HTTP_TIMEOUT_S)
            return r.status_code, r.text
        except requests.RequestException:
            return 0, ""

    def device_type(self) -> int:
        """Sonda leve (magicBox). Só o código HTTP importa pro gate."""
        return self._cgi("magicBox.cgi?action=getDeviceType")[0]

    def get_config(self, name: str) -> dict[str, str]:
        """getConfig -> {chave_sem_prefixo_table: valor}. {} em falha."""
        code, body = self._cgi(f"configManager.cgi?action=getConfig&name={name}")
        if code != 200:
            return {}
        out: dict[str, str] = {}
        for line in body.splitlines():
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k.startswith("table."):
                k = k[len("table."):]
            out[k] = v.strip()
        return out

    def set_config(self, params: dict[str, str]) -> tuple[bool, int]:
        """setConfig de um GRUPO de chaves. True se HTTP 200 e corpo com 'OK'."""
        q = "&".join(f"{k}={v}" for k, v in params.items())
        code, body = self._cgi(f"configManager.cgi?action=setConfig&{q}")
        return (code == 200 and "OK" in body.upper()), code


def build_camera(env: dict) -> Optional[Camera]:
    ip = camera_ip(env)
    if not ip:
        return None
    return Camera(
        base=f"http://{ip}",
        auth=HTTPDigestAuth(env.get("IP_CAM_USER", "admin"), env.get("IP_CAM_PASS", "")),
        session=requests.Session(),
    )


def current_mode(profile: dict, now_hhmm: str) -> str:
    """'day' se day_start <= agora < night_start, senão 'night'."""
    day = profile.get("day_start", "06:00")
    night = profile.get("night_start", "17:30")
    return "day" if day <= now_hhmm < night else "night"


def desired_keys(profile: dict, mode: str) -> dict[str, str]:
    """Mapa {chave_CGI: valor_desejado} para o modo atual.

    OBTURADOR (funciona): VideoInOptions[0].ExposureValue2 (write-only, ver
    NO_VERIFY_KEYS) + GainMax (persiste, é o âncora do verify).

    ILUMINADOR/IR: OPT-IN (lighting_enabled, default false). Comando CORRETO
    confirmado (rroller/dahua + dump da câmera): brilho do IR é
    Lighting_V2[0][PERFIL][0].MiddleLight[0].Light + .Mode (o índice de luz [0]=
    InfraredLight; PERFIL 1=noite; PercentOfMaxBrightness é READ-ONLY). PORÉM na
    VIP-3260 o write do MiddleLight retorna HTTP 200 mas NÃO persiste (só .Mode
    gruda) — quirk de firmware (achado de campo 2026-07-17). Por isso fica
    desligado por padrão; aplicar o brilho de fato pela UI web da câmera."""
    sh = profile.get("shutter", {}).get(mode, {})
    out: dict[str, str] = {}
    if "exposure_value2" in sh:
        out["VideoInOptions[0].ExposureValue2"] = str(sh["exposure_value2"])
    if "gain_max" in sh:
        out["VideoInOptions[0].GainMax"] = str(sh["gain_max"])
    if profile.get("lighting_enabled"):
        lig = profile.get("lighting", {})
        if "night_ir_light" in lig:
            out["Lighting_V2[0][1][0].Mode"] = "Manual"
            out["Lighting_V2[0][1][0].MiddleLight[0].Light"] = str(lig["night_ir_light"])
        if "night_whitelight_light" in lig:
            out["Lighting_V2[0][1][1].Mode"] = "Manual"
            out["Lighting_V2[0][1][1].NearLight[0].Light"] = str(lig["night_whitelight_light"])
    return out


def probe_stable(cam: Camera, sleep: Callable[[float], None]) -> bool:
    """Gate: N sondas espaçadas; estável só se >= STABILITY_MIN_OK responderem 200."""
    ok = 0
    for i in range(STABILITY_PROBES):
        if i:
            sleep(STABILITY_GAP_S)
        code = cam.device_type()
        if code == 200:
            ok += 1
        else:
            log(f"gate: sonda {i + 1}/{STABILITY_PROBES} CGI HTTP {code}")
    return ok >= STABILITY_MIN_OK


def read_current(cam: Camera) -> dict[str, str]:
    """Lê os grupos que nos interessam num único snapshot."""
    cur: dict[str, str] = {}
    cur.update(cam.get_config("VideoInOptions"))
    cur.update(cam.get_config("Lighting_V2"))
    return cur


def compute_drift(desired: dict[str, str], current: dict[str, str]) -> dict[str, str]:
    """Chaves cujo valor atual difere do desejado (comparação tolerante).
    Chaves NO_VERIFY (auto-variam na leitura) NÃO disparam drift sozinhas — são
    reescritas junto do âncora do grupo em apply_drift."""
    drift: dict[str, str] = {}
    for k, want in desired.items():
        if k in NO_VERIFY_KEYS:
            continue
        have = current.get(k)
        if have is None or not _num_eq(have, want):
            drift[k] = want
    return drift


def _group_of(key: str) -> str:
    return "Lighting_V2" if key.startswith("Lighting_V2") else "VideoInOptions"


def apply_drift(
    cam: Camera, desired: dict[str, str], drift: dict[str, str],
    sleep: Callable[[float], None],
) -> tuple[list[str], list[str]]:
    """Para cada GRUPO que tem drift, escreve o grupo INTEIRO do desejado (assim
    chaves NO_VERIFY como ExposureValue2 vão junto do âncora que persiste). Um
    grupo por vez, espaçado, com verify + backoff. Devolve (aplicadas, falhas)."""
    drifted_groups = {_group_of(k) for k in drift}
    groups: dict[str, dict[str, str]] = {}
    for k, v in desired.items():
        g = _group_of(k)
        if g in drifted_groups:
            groups.setdefault(g, {})[k] = v

    applied: list[str] = []
    failed: list[str] = []
    first = True
    for gname, params in groups.items():
        if not first:
            sleep(WRITE_GAP_S)
        first = False
        if _apply_group(cam, gname, params, sleep):
            applied.extend(params.keys())
        else:
            failed.extend(params.keys())
    return applied, failed


def _apply_group(
    cam: Camera, gname: str, params: dict[str, str], sleep: Callable[[float], None]
) -> bool:
    """Escreve um grupo com verify + backoff exponencial. Nunca em loop apertado."""
    backoff = 0.0
    for attempt in range(1, WRITE_MAX_RETRIES + 1):
        if backoff:
            sleep(backoff)
        ok, code = cam.set_config(params)
        if ok and _verify_group(cam, gname, params):
            log(f"OK {gname}: {params} (tent {attempt})")
            return True
        log(f"FALHA {gname} HTTP {code} (tent {attempt}/{WRITE_MAX_RETRIES})")
        backoff = WRITE_BACKOFF_BASE_S if backoff <= 0 else min(WRITE_BACKOFF_MAX_S, backoff * 2)
    return False


def _verify_group(cam: Camera, gname: str, params: dict[str, str]) -> bool:
    """Relê o grupo e confirma que as chaves VERIFICÁVEIS bateram (tolerante).
    Chaves NO_VERIFY (auto-variam na leitura) são escritas mas não verificadas."""
    cur = cam.get_config(gname)
    return all(
        k in cur and _num_eq(cur[k], v)
        for k, v in params.items() if k not in NO_VERIFY_KEYS
    )


def reconcile(
    cam: Camera,
    profile: dict,
    now_hhmm: str,
    *,
    dry_run: bool = False,
    force_mode: Optional[str] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Fluxo completo. Devolve exit code (0 ok/nada a fazer, 1 falha, 2 CGI instável)."""
    mode = force_mode or current_mode(profile, now_hhmm)
    desired = desired_keys(profile, mode)
    log(f"reconcile modo={mode} desejado={desired}")

    if not probe_stable(cam, sleep):
        log("gate: CGI instável — abortando sem escrever (próximo ciclo tenta)")
        return 2

    current = read_current(cam)
    if not current:
        log("erro: getConfig vazio mesmo com CGI estável — abortando")
        return 2

    drift = compute_drift(desired, current)
    if not drift:
        log("sem drift — câmera já bate com o perfil")
        return 0

    log(f"drift: {drift}")
    if dry_run:
        log("dry-run: não escreve")
        return 0

    applied, failed = apply_drift(cam, desired, drift, sleep)
    log(f"resultado: aplicadas={applied} falhas={failed}")
    return 1 if failed else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--env", default=DEFAULT_ENV)
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--mode", choices=["auto", "day", "night"], default="auto")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    try:
        env = load_env(args.env)
    except OSError as exc:
        log(f"erro lendo .env: {exc}")
        return 1
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    cam = build_camera(env)
    if cam is None:
        log("erro: não achei o IP da câmera no .env")
        return 1

    now_hhmm = time.strftime("%H:%M")
    force = None if args.mode == "auto" else args.mode
    return reconcile(cam, profile, now_hhmm, dry_run=args.dry_run, force_mode=force)


if __name__ == "__main__":
    raise SystemExit(main())
