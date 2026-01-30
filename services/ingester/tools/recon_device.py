#!/usr/bin/env python3
"""
Reconnaissance script — coleta informações do dispositivo Android para calibração.

Uso:
  1. Conecte o dispositivo via ADB
  2. Abra o app ICSee manualmente em cada tela desejada
  3. Rode: python tools/recon_device.py <estado>

Estados disponíveis:
  home            — tela inicial do Android (home screen)
  camera_list     — lista de câmeras no ICSee
  camera_normal   — visualização normal de uma câmera
  camera_fullscreen — câmera em tela cheia

O script coleta:
  - Screenshot da tela atual
  - UI hierarchy via uiautomator dump (XML com todos os elementos clicáveis)
  - Activity/package em foreground via dumpsys
  - Resolução da tela

Resultados salvos em: tools/recon_output/<estado>/
"""
import json
import os
import subprocess
import sys
import time

RECON_DIR = os.path.join(os.path.dirname(__file__), "recon_output")
ADB_TIMEOUT = 30


def run_adb(*args: str, timeout: int = ADB_TIMEOUT) -> subprocess.CompletedProcess:
    cmd = ["adb"] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def run_shell(cmd: str, timeout: int = ADB_TIMEOUT) -> str:
    result = run_adb("shell", cmd, timeout=timeout)
    return (result.stdout or "").strip()


def get_device_id() -> str | None:
    result = run_adb("devices")
    import re
    devices = re.findall(r"^(.+?)\s+device$", result.stdout or "", re.MULTILINE)
    return devices[0] if devices else None


def collect(state_name: str) -> None:
    device = get_device_id()
    if not device:
        print("ERRO: Nenhum dispositivo ADB conectado.")
        sys.exit(1)

    out_dir = os.path.join(RECON_DIR, state_name)
    os.makedirs(out_dir, exist_ok=True)

    print(f"Dispositivo: {device}")
    print(f"Estado alvo: {state_name}")
    print(f"Output: {out_dir}")
    print()

    # 1. Resolução da tela
    print("[1/5] Coletando resolução da tela...")
    resolution = run_shell("wm size")
    density = run_shell("wm density")
    print(f"  {resolution}")
    print(f"  {density}")

    # 2. Activity em foreground
    print("[2/5] Coletando activity em foreground...")
    dumpsys = run_shell("dumpsys activity activities | grep -E 'mResumedActivity|mFocusedApp|mCurrentFocus'")
    # Also get the full focused window info
    window_focus = run_shell("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'")
    print(f"  Activities: {dumpsys}")
    print(f"  Window: {window_focus}")

    # 3. Screenshot
    print("[3/5] Capturando screenshot...")
    remote_path = "/sdcard/recon_screenshot.png"
    local_path = os.path.join(out_dir, "screenshot.png")
    run_adb("shell", "screencap", remote_path, timeout=120)
    run_adb("pull", remote_path, local_path, timeout=60)
    run_adb("shell", "rm", remote_path)
    print(f"  Salvo: {local_path}")

    # 4. UI hierarchy (uiautomator)
    print("[4/5] Coletando UI hierarchy (uiautomator dump)...")
    remote_xml = "/sdcard/recon_ui.xml"
    local_xml = os.path.join(out_dir, "ui_hierarchy.xml")
    ui_result = run_adb("shell", "uiautomator", "dump", remote_xml, timeout=60)
    if ui_result.returncode == 0:
        run_adb("pull", remote_xml, local_xml)
        run_adb("shell", "rm", remote_xml)
        print(f"  Salvo: {local_xml}")
    else:
        print(f"  AVISO: uiautomator dump falhou: {ui_result.stderr}")
        local_xml = None

    # 5. Resumo
    print("[5/5] Gerando resumo...")
    summary = {
        "state": state_name,
        "device": device,
        "resolution": resolution,
        "density": density,
        "foreground_activity": dumpsys,
        "window_focus": window_focus,
        "screenshot": "screenshot.png",
        "ui_hierarchy": "ui_hierarchy.xml" if local_xml else None,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    # Parse clickable elements from XML if available
    if local_xml and os.path.exists(local_xml):
        clickables = parse_clickable_elements(local_xml)
        summary["clickable_elements"] = clickables
        print(f"  Elementos clicáveis encontrados: {len(clickables)}")

    summary_path = os.path.join(out_dir, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"  Resumo salvo: {summary_path}")

    print()
    print("=== Coleta concluída ===")
    print(f"Arquivos em: {out_dir}")
    if local_xml:
        print(f"Analise o ui_hierarchy.xml para identificar resource-ids e seletores.")


def parse_clickable_elements(xml_path: str) -> list[dict]:
    """Extract clickable elements from uiautomator XML dump."""
    import xml.etree.ElementTree as ET

    elements = []
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError:
        return elements

    for node in tree.iter("node"):
        clickable = node.get("clickable", "false") == "true"
        if not clickable:
            continue

        bounds_str = node.get("bounds", "")
        bounds = _parse_bounds(bounds_str)

        elements.append({
            "class": node.get("class"),
            "resource-id": node.get("resource-id") or None,
            "text": node.get("text") or None,
            "content-desc": node.get("content-desc") or None,
            "bounds": bounds_str,
            "center": _center(bounds) if bounds else None,
            "package": node.get("package"),
        })

    return elements


def _parse_bounds(bounds_str: str) -> tuple[int, int, int, int] | None:
    """Parse '[x1,y1][x2,y2]' into (x1, y1, x2, y2)."""
    import re
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
    if not m:
        return None
    return tuple(int(v) for v in m.groups())


def _center(bounds: tuple[int, int, int, int]) -> dict[str, int]:
    x1, y1, x2, y2 = bounds
    return {"x": (x1 + x2) // 2, "y": (y1 + y2) // 2}


VALID_STATES = ["home", "camera_list", "camera_normal", "camera_fullscreen"]

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in VALID_STATES:
        print(f"Uso: python {sys.argv[0]} <estado>")
        print(f"Estados: {', '.join(VALID_STATES)}")
        sys.exit(1)

    collect(sys.argv[1])
