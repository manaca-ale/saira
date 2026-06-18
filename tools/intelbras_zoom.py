#!/usr/bin/env python3
"""Control / test the motorized zoom + focus of an Intelbras VIP "Z" camera.

These cameras run Dahua-OEM firmware and expose the lens via the CGI API:

    GET /cgi-bin/devVideoInput.cgi?action=getFocusStatus
    GET /cgi-bin/devVideoInput.cgi?action=adjustFocus&zoom=<0-1>&focus=<0-1>
    GET /cgi-bin/devVideoInput.cgi?action=autoFocus
    GET /cgi-bin/snapshot.cgi?channel=1

`zoom`/`focus` are absolute floats in [0.0, 1.0] (0 = wide, 1 = tele).
Auth is HTTP Digest. Some older firmwares only move the lens via
ptz.cgi?code=ZoomTele/ZoomWide; this tool falls back to that automatically
when adjustFocus does not change the reported zoom.

Examples (run from inside the camera LAN — e.g. on the Raspberry Pi):

    python intelbras_zoom.py --host 192.168.0.142 --user admin --password 'xxx' status
    python intelbras_zoom.py --host ... --user ... --password ... snap --out /tmp/z0.jpg
    python intelbras_zoom.py --host ... --user ... --password ... set --zoom 0.8
    python intelbras_zoom.py --host ... --user ... --password ... in --step 0.15
    python intelbras_zoom.py --host ... --user ... --password ... autofocus

Requires: requests (already in the Pi venv).
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Optional

import requests
from requests.auth import HTTPDigestAuth


class CameraError(RuntimeError):
    pass


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


class IntelbrasLens:
    def __init__(self, host: str, user: str, password: str, channel: int = 0, timeout: int = 8):
        self.host = host.rstrip("/")
        if not self.host.startswith(("http://", "https://")):
            self.host = "http://" + self.host
        self.channel = channel
        self.timeout = timeout
        self._s = requests.Session()
        self._s.auth = HTTPDigestAuth(user, password)

    # ---- low level ----
    def _get(self, path: str, **params) -> requests.Response:
        url = f"{self.host}{path}"
        try:
            resp = self._s.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise CameraError(f"request falhou: {exc}") from exc
        if resp.status_code != 200:
            raise CameraError(f"HTTP {resp.status_code} em {resp.url}\n{resp.text[:200]}")
        return resp

    def _devvideo(self, action: str, **params) -> str:
        return self._get(
            "/cgi-bin/devVideoInput.cgi", action=action, channel=self.channel, **params
        ).text

    # ---- public API ----
    def get_focus_status(self) -> dict[str, float]:
        """Parse the key=value body of getFocusStatus into {zoom, focus}."""
        body = self._devvideo("getFocusStatus")
        vals: dict[str, float] = {}
        for line in body.splitlines():
            line = line.strip()
            if "=" not in line:
                continue
            key, _, raw = line.partition("=")
            key = key.strip().lower()
            try:
                num = float(raw.strip())
            except ValueError:
                continue
            # keys look like: status.Status.Zoom / status.Status.Focus
            if key.endswith(".zoom") or key == "zoom":
                vals["zoom"] = num
            elif key.endswith(".focus") or key == "focus":
                vals["focus"] = num
        if not vals:
            raise CameraError(f"getFocusStatus sem zoom/focus no corpo:\n{body[:300]}")
        return vals

    def adjust_focus(self, zoom: float, focus: Optional[float] = None) -> str:
        params = {"zoom": f"{_clamp(zoom):.6f}"}
        if focus is not None:
            params["focus"] = f"{_clamp(focus):.6f}"
        return self._devvideo("adjustFocus", **params)

    def auto_focus(self) -> str:
        return self._devvideo("autoFocus")

    def ptz_zoom(self, direction: str, speed: int = 4, duration: float = 0.8) -> None:
        """Fallback: continuous zoom via ptz.cgi (ZoomTele=in, ZoomWide=out)."""
        code = "ZoomTele" if direction == "in" else "ZoomWide"
        self._get("/cgi-bin/ptz.cgi", action="start", channel=self.channel,
                  code=code, arg1=0, arg2=speed, arg3=0)
        time.sleep(duration)
        self._get("/cgi-bin/ptz.cgi", action="stop", channel=self.channel,
                  code=code, arg1=0, arg2=speed, arg3=0)

    def snapshot(self, out_path: str) -> int:
        resp = self._get("/cgi-bin/snapshot.cgi", channel=self.channel + 1)
        data = resp.content
        if len(data) < 500 or data[:2] != b"\xff\xd8":
            raise CameraError(f"snapshot inválido ({len(data)} bytes, magic={data[:2]!r})")
        with open(out_path, "wb") as fh:
            fh.write(data)
        return len(data)

    def set_zoom_verified(self, target: float, focus: Optional[float] = None,
                          max_wait: float = 14.0, poll: float = 1.5,
                          tol: float = 0.03) -> dict[str, float]:
        """Set absolute zoom and poll until the lens reaches the target.

        The motorized lens traverses slowly (a full sweep takes several
        seconds) and ignores a zoom command while an autofocus from the
        previous call is still running. So we re-issue adjustFocus on every
        poll iteration until getFocusStatus converges, instead of sending it
        once. We send the focus value alongside the zoom (keeping the current
        focus when none is given) to avoid the autofocus race. Only if it
        never moves do we try the ptz.cgi fallback (older firmwares); newer
        ones reject it with 400, which we swallow.
        """
        status = self.get_focus_status()
        before = status.get("zoom", -1.0)
        # send focus alongside zoom to avoid the AF race; keep current if unset
        focus_arg = focus if focus is not None else status.get("focus")
        self.adjust_focus(target, focus_arg)
        after = status
        waited = 0.0
        while waited < max_wait:
            time.sleep(poll)
            waited += poll
            after = self.get_focus_status()
            if abs(after.get("zoom", before) - target) <= tol:
                return after
            self.adjust_focus(target, focus_arg)  # re-issue: ignored while AF runs
        # never converged — lens may not honor adjustFocus; try ptz nudges
        if abs(after.get("zoom", before) - before) <= tol:
            print("  adjustFocus não moveu o zoom — tentando ptz.cgi (fallback)…",
                  file=sys.stderr)
            try:
                for _ in range(3):
                    cur = self.get_focus_status().get("zoom", before)
                    if abs(cur - target) <= 0.05:
                        break
                    self.ptz_zoom("in" if target > cur else "out")
                    time.sleep(poll)
                after = self.get_focus_status()
            except CameraError as exc:
                print(f"  fallback ptz.cgi indisponível ({exc.args[0].splitlines()[0]})",
                      file=sys.stderr)
        return after


def _fmt(status: dict[str, float]) -> str:
    return "  ".join(f"{k}={v:.4f}" for k, v in sorted(status.items()))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True, help="IP ou http://IP da câmera")
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--channel", type=int, default=0, help="canal (0-based no CGI)")
    ap.add_argument("--timeout", type=int, default=8)

    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="lê zoom/focus atuais")
    p_set = sub.add_parser("set", help="zoom/focus absoluto (0-1)")
    p_set.add_argument("--zoom", type=float, required=True)
    p_set.add_argument("--focus", type=float, default=None, help="omitido => autofoco depois")
    p_in = sub.add_parser("in", help="aproxima (zoom+step)")
    p_in.add_argument("--step", type=float, default=0.1)
    p_out = sub.add_parser("out", help="afasta (zoom-step)")
    p_out.add_argument("--step", type=float, default=0.1)
    sub.add_parser("autofocus", help="dispara autofoco")
    p_snap = sub.add_parser("snap", help="baixa um snapshot JPEG")
    p_snap.add_argument("--out", required=True)

    args = ap.parse_args()
    lens = IntelbrasLens(args.host, args.user, args.password, args.channel, args.timeout)

    try:
        if args.cmd == "status":
            print(_fmt(lens.get_focus_status()))
        elif args.cmd == "snap":
            n = lens.snapshot(args.out)
            print(f"snapshot OK: {n} bytes -> {args.out}")
        elif args.cmd == "set":
            print(f"antes:  {_fmt(lens.get_focus_status())}")
            after = lens.set_zoom_verified(args.zoom, args.focus)
            if args.focus is None:
                lens.auto_focus()
                time.sleep(1.5)
                after = lens.get_focus_status()
            print(f"depois: {_fmt(after)}")
        elif args.cmd in ("in", "out"):
            cur = lens.get_focus_status().get("zoom", 0.0)
            target = cur + (args.step if args.cmd == "in" else -args.step)
            print(f"antes:  zoom={cur:.4f} -> alvo={_clamp(target):.4f}")
            after = lens.set_zoom_verified(target)
            print(f"depois: {_fmt(after)}")
        elif args.cmd == "autofocus":
            lens.auto_focus()
            time.sleep(1.5)
            print(f"autofoco OK: {_fmt(lens.get_focus_status())}")
    except CameraError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
