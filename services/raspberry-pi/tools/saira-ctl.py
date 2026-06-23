#!/usr/bin/env python3
"""saira-ctl — operação remota do agente de campo SAIRA (Raspberry Pi).

Roda da EC2 (dentro do túnel WireGuard) ou do laptop via túnel. Reusa os
endpoints do esp32-server: /device/<id>/trigger (comandos), /device/<id>/config
(config remota, exige X-Admin-Token), /device/<id>/health (telemetria) e
/device/<id>/logs (puxar log / relatório de calibração) — sem precisar de SSH.

Config por env ou flags:
  EC2_BASE      (default http://10.8.0.1:5002)   ou  --base
  ADMIN_TOKEN   (para escrever config)            ou  --token

Exemplos:
  saira-ctl pi-cam-001 health
  saira-ctl pi-cam-001 logs 800
  saira-ctl pi-cam-001 calibrate 20
  saira-ctl pi-cam-001 config motion_enabled=on pile_zone_polygon='[[100,100],...]'
  saira-ctl pi-cam-001 safe-mode on
  saira-ctl pi-cam-001 zoom 0.6
  saira-ctl pi-cam-001 cmd CMD_RECALIBRATE
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests

DEFAULT_BASE = os.environ.get("EC2_BASE", "http://10.8.0.1:5002")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")


def _base(args) -> str:
    return (args.base or DEFAULT_BASE).rstrip("/")


def _trigger(args, cmd: str) -> dict:
    url = f"{_base(args)}/device/{args.device}/trigger"
    r = requests.post(url, json={"cmd": cmd}, timeout=15)
    r.raise_for_status()
    return r.json()


def cmd_cmd(args) -> int:
    out = _trigger(args, args.command)
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_health(args) -> int:
    url = f"{_base(args)}/device/{args.device}/health"
    r = requests.get(url, timeout=15)
    if r.status_code == 404:
        print(f"(sem telemetria reportada ainda por {args.device})")
        return 1
    r.raise_for_status()
    data = r.json()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_config(args) -> int:
    payload = {}
    for kv in args.pairs:
        if "=" not in kv:
            print(f"ignorando '{kv}' (esperado k=v)", file=sys.stderr)
            continue
        k, _, v = kv.partition("=")
        payload[k.strip()] = v
    if not payload:
        print("nada para aplicar", file=sys.stderr)
        return 2
    headers = {}
    token = args.token or ADMIN_TOKEN
    if token:
        headers["X-Admin-Token"] = token
    url = f"{_base(args)}/device/{args.device}/config"
    r = requests.post(url, json=payload, headers=headers, timeout=15)
    if r.status_code == 401:
        print("401 Unauthorized — defina ADMIN_TOKEN (ou --token)", file=sys.stderr)
        return 1
    r.raise_for_status()
    print(r.text)
    return 0


def cmd_get_config(args) -> int:
    url = f"{_base(args)}/device/{args.device}/config.txt"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    print(r.text)
    return 0


def cmd_safe_mode(args) -> int:
    val = "1" if args.state.lower() in ("on", "1", "true", "yes") else "0"
    args.pairs = [f"safe_mode={val}"]
    return cmd_config(args)


def _list_logs(args) -> list[dict]:
    url = f"{_base(args)}/device/{args.device}/logs"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json().get("logs", [])


def _wait_new_log(args, since_mtime: float, prefix: str | None, timeout_s: float) -> dict | None:
    """Aguarda surgir um log mais novo que since_mtime (e com prefixo, se dado)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for item in _list_logs(args):
            if item["mtime"] > since_mtime and (prefix is None or item["name"].startswith(prefix)):
                return item
        time.sleep(3.0)
    return None


def _newest_mtime(args, prefix: str | None = None) -> float:
    best = 0.0
    for item in _list_logs(args):
        if prefix is None or item["name"].startswith(prefix):
            best = max(best, item["mtime"])
    return best


def _download(args, item: dict) -> bytes:
    url = item["url"]
    # url pode ser relativa (/uploads/...) se o servidor não tiver PUBLIC_BASE_URL.
    if url.startswith("/"):
        url = _base(args) + url
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.content


def cmd_logs(args) -> int:
    n = args.lines or 500
    before = _newest_mtime(args, prefix=args.device)
    print(f"disparando CMD_GET_LOGS:{n} ...")
    _trigger(args, f"CMD_GET_LOGS:{n}")
    item = _wait_new_log(args, before, prefix=args.device, timeout_s=args.wait)
    if not item:
        print("timeout: o log não chegou ao servidor a tempo "
              "(a Pi está online? tente aumentar --wait)", file=sys.stderr)
        return 1
    content = _download(args, item)
    if args.out:
        with open(args.out, "wb") as f:
            f.write(content)
        print(f"salvo em {args.out} ({len(content)} bytes) — {item['url']}")
    else:
        sys.stdout.write(content.decode("utf-8", "replace"))
    return 0


def cmd_calibrate(args) -> int:
    secs = args.seconds or 20
    before = _newest_mtime(args, prefix="calib_")
    print(f"disparando CMD_CALIBRATE:{secs} (aguarde ~{secs}s + upload) ...")
    _trigger(args, f"CMD_CALIBRATE:{secs}")
    item = _wait_new_log(args, before, prefix="calib_", timeout_s=secs + args.wait)
    if not item:
        print("timeout: relatório de calibração não chegou "
              "(a Pi está online? câmera ok?)", file=sys.stderr)
        return 1
    report = json.loads(_download(args, item))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    base = _base(args)
    print(f"\nsnapshot anotado (zona + heatmap): {base}/uploads/{args.device}/ "
          "(última imagem do painel)")
    return 0


# Atalhos -> comandos
def _shortcut(cmd_str):
    def handler(args):
        out = _trigger(args, cmd_str)
        print(json.dumps(out, ensure_ascii=False))
        return 0
    return handler


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="saira-ctl", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("device", help="device_id (ex.: pi-cam-001)")
    p.add_argument("--base", help=f"EC2 base (default {DEFAULT_BASE})")
    p.add_argument("--token", help="X-Admin-Token (ou env ADMIN_TOKEN)")
    sub = p.add_subparsers(dest="sub", required=True)

    sp = sub.add_parser("cmd", help="dispara um comando bruto (CMD_*[:arg])")
    sp.add_argument("command")
    sp.set_defaults(func=cmd_cmd)

    sub.add_parser("health", help="telemetria de saúde").set_defaults(func=cmd_health)

    sp = sub.add_parser("config", help="aplica chaves de config (k=v ...)")
    sp.add_argument("pairs", nargs="+")
    sp.set_defaults(func=cmd_config)

    sub.add_parser("get-config", help="mostra o config.txt atual").set_defaults(func=cmd_get_config)

    sp = sub.add_parser("safe-mode", help="liga/desliga o kill-switch")
    sp.add_argument("state", choices=["on", "off"])
    sp.set_defaults(func=cmd_safe_mode)

    sp = sub.add_parser("logs", help="puxa as últimas N linhas de log")
    sp.add_argument("lines", nargs="?", type=int, default=500)
    sp.add_argument("--out", help="salva em arquivo (senão imprime)")
    sp.add_argument("--wait", type=float, default=60.0, help="timeout de espera (s)")
    sp.set_defaults(func=cmd_logs)

    sp = sub.add_parser("calibrate", help="modo calibração (fg/delta + snapshot anotado)")
    sp.add_argument("seconds", nargs="?", type=int, default=20)
    sp.add_argument("--wait", type=float, default=30.0, help="margem de espera além de seconds (s)")
    sp.set_defaults(func=cmd_calibrate)

    sp = sub.add_parser("zoom", help="zoom óptico absoluto 0..1")
    sp.add_argument("value")
    sp.set_defaults(func=lambda a: _shortcut(f"CMD_ZOOM:{a.value}")(a))

    sub.add_parser("snapshot", help="sobe um frame agora").set_defaults(func=_shortcut("CMD_SNAPSHOT"))
    sub.add_parser("autofocus", help="autofoco").set_defaults(func=_shortcut("CMD_AUTOFOCUS"))
    sub.add_parser("recalibrate", help="re-anchor do baseline do gate").set_defaults(func=_shortcut("CMD_RECALIBRATE"))
    sub.add_parser("restart", help="reinicia o agente (systemd sobe de novo)").set_defaults(func=_shortcut("CMD_RESTART_AGENT"))
    sub.add_parser("restart-buffer", help="reinicia o cam-rtsp-buffer").set_defaults(func=_shortcut("CMD_RESTART_BUFFER"))
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except requests.RequestException as exc:
        print(f"erro de rede: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
