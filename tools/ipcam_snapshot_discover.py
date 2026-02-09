import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin


@dataclass
class Result:
    url: str
    auth: str
    http_code: int
    size: int
    content_type: str
    saved_path: Optional[str]
    elapsed_ms: int


def _which_curl() -> str:
    # On Windows, "curl" might be an alias for Invoke-WebRequest in PowerShell.
    # Prefer curl.exe when available.
    for cand in ("curl.exe", "curl"):
        p = shutil.which(cand)
        if p:
            return p
    raise FileNotFoundError("curl/curl.exe not found in PATH")


def _run_curl(curl_path: str, url: str, auth_mode: str, user: str, password: str, timeout_s: int, out_path: str) -> Result:
    # Capture metrics via -w to avoid parsing headers. Keep output stable for parsing.
    # Note: --anyauth is convenient but can add latency; we try explicit modes.
    wfmt = "%{http_code} %{size_download} %{content_type}"
    cmd = [
        curl_path,
        "-sS",
        "--max-time",
        str(timeout_s),
        "--connect-timeout",
        str(min(5, timeout_s)),
        "-o",
        out_path,
        "-w",
        wfmt,
    ]

    if auth_mode == "basic":
        cmd += ["--basic", "-u", f"{user}:{password}"]
    elif auth_mode == "digest":
        cmd += ["--digest", "-u", f"{user}:{password}"]
    elif auth_mode == "none":
        pass
    else:
        raise ValueError(f"unknown auth_mode={auth_mode}")

    cmd.append(url)

    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    dt_ms = int((time.time() - t0) * 1000)

    # curl writes metrics to stdout (because of -w). stderr used for errors.
    metrics = (proc.stdout or "").strip()
    if proc.returncode != 0:
        # If curl failed, try to preserve some context.
        # Treat as "no response" with code 0.
        err = (proc.stderr or "").strip().splitlines()[-1] if proc.stderr else ""
        return Result(url=url, auth=auth_mode, http_code=0, size=0, content_type=f"curl_error:{err}", saved_path=None, elapsed_ms=dt_ms)

    parts = metrics.split(" ", 2)
    if len(parts) < 3:
        return Result(url=url, auth=auth_mode, http_code=0, size=0, content_type=f"bad_metrics:{metrics}", saved_path=None, elapsed_ms=dt_ms)

    try:
        code = int(parts[0])
    except ValueError:
        code = 0
    try:
        size = int(float(parts[1]))
    except ValueError:
        size = 0
    ctype = parts[2].strip() if parts[2] else ""

    saved = out_path if (code == 200 and size > 0) else None
    if not saved:
        try:
            os.remove(out_path)
        except OSError:
            pass

    return Result(url=url, auth=auth_mode, http_code=code, size=size, content_type=ctype, saved_path=saved, elapsed_ms=dt_ms)


def _is_image(result: Result) -> bool:
    if result.http_code != 200:
        return False
    ct = (result.content_type or "").lower()
    return ct.startswith("image/")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Discover HTTP snapshot URL for an IP camera (tries common endpoints and picks the smallest).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--base", required=True, help="Base URL, e.g. http://192.168.0.142/ (can include :port)")
    ap.add_argument("--user", default="", help="Camera username (for basic/digest auth)")
    ap.add_argument("--password", default="", help="Camera password (for basic/digest auth)")
    ap.add_argument("--timeout", type=int, default=8, help="Timeout per request (seconds)")
    ap.add_argument("--out-dir", default=os.path.join(".cache", "ipcam_discover"), help="Directory to store successful snapshots")
    ap.add_argument("--no-digest", action="store_true", help="Skip digest auth attempts")
    ap.add_argument("--no-basic", action="store_true", help="Skip basic auth attempts")
    ap.add_argument("--no-anon", action="store_true", help="Skip unauthenticated attempts")
    ap.add_argument("--limit", type=int, default=0, help="Max candidates to try (0 = no limit)")

    args = ap.parse_args()

    base = args.base.strip()
    if not base.startswith(("http://", "https://")):
        print("ERROR: --base must start with http:// or https://", file=sys.stderr)
        return 2
    if not base.endswith("/"):
        base += "/"

    curl_path = _which_curl()
    os.makedirs(args.out_dir, exist_ok=True)

    # Common snapshot endpoints (mix of vendors). Keep list small and practical.
    # You can extend this list as you encounter new camera models.
    candidates: list[str] = [
        "snap.jpg",
        "snapshot.jpg",
        "image.jpg",
        "img.jpg",
        "jpg/image.jpg",
        "cgi-bin/snapshot.cgi",
        "cgi-bin/snapshot.cgi?channel=1",
        "cgi-bin/snapshot.cgi?channel=1&subtype=0",
        "cgi-bin/snapshot.cgi?channel=1&subtype=1",  # often lower-res
        "cgi-bin/snapshot.cgi?subtype=1",
        "cgi-bin/CGIProxy.fcgi?cmd=snapPicture2",
        "ISAPI/Streaming/channels/101/picture",
        "ISAPI/Streaming/channels/102/picture",
        "Streaming/channels/1/picture",
        "Streaming/channels/2/picture",
        "onvif-http/snapshot?Profile_1",
        "onvif-http/snapshot?Profile_2",
        # Herospeed / XEPLON / generic Chinese cameras
        "webcapture.jpg?command=snap&channel=1",
        "webcapture.jpg?command=snap&channel=0",
        "snap.jpg?chn=1",
        "snap.jpg?chn=0",
        "snap.jpg?quality=60",
        "snap.jpg?w=640&h=480",
        "snap.jpg?size=3",               # QVGA on some models
        "snap.jpg?size=2",               # VGA on some models
        "tmpfs/auto.jpg",
        "tmpfs/snap.jpg",
        "web/cgi-bin/hi3510/param.cgi?cmd=snap",
        "cgi-bin/snapshot.cgi?channel=0&subtype=1",
        "capture.jpg",
        "images/snapshot.jpg",
        "onvifsnapshot/media_service/snapshot?channel=1&subtype=0",
        "onvifsnapshot/media_service/snapshot?channel=1&subtype=1",
    ]

    auth_modes: list[str] = []
    if not args.no_anon:
        auth_modes.append("none")
    if args.user or args.password:
        if not args.no_basic:
            auth_modes.append("basic")
        if not args.no_digest:
            auth_modes.append("digest")

    if not auth_modes:
        print("ERROR: no auth modes enabled. Provide --user/--password or remove --no-anon.", file=sys.stderr)
        return 2

    print(f"curl: {curl_path}")
    print(f"base: {base}")
    print(f"auth: {', '.join(auth_modes)}")
    print()

    results: list[Result] = []
    tried = 0
    for rel in candidates:
        if args.limit and tried >= args.limit:
            break
        tried += 1

        url = urljoin(base, rel)
        safe_name = rel.replace("/", "_").replace("?", "_").replace("&", "_").replace("=", "_")
        out_path = os.path.join(args.out_dir, f"{safe_name}.bin")

        best_for_url: Optional[Result] = None
        for auth in auth_modes:
            r = _run_curl(
                curl_path=curl_path,
                url=url,
                auth_mode=auth,
                user=args.user,
                password=args.password,
                timeout_s=args.timeout,
                out_path=out_path,
            )
            results.append(r)
            ok = _is_image(r)
            status = "OK" if ok else "NO"
            print(f"[{status}] {r.http_code:>3} {r.size:>8}B {r.elapsed_ms:>5}ms auth={auth:<6} ct={r.content_type} url={url}")

            if ok and (best_for_url is None or r.size < best_for_url.size):
                best_for_url = r
            if ok:
                # If it works with some auth mode, stop trying other modes for the same URL.
                break

        if best_for_url and best_for_url.saved_path:
            # Keep separate files per auth/URL without overwriting next attempts.
            final_path = os.path.join(args.out_dir, f"{safe_name}__{best_for_url.auth}.jpg")
            try:
                os.replace(best_for_url.saved_path, final_path)
                best_for_url.saved_path = final_path
            except OSError:
                pass

    ok_results = [r for r in results if _is_image(r)]
    print()
    if not ok_results:
        print("Nenhum snapshot valido encontrado. Dicas:")
        print("- Confirme o IP/porta e se a camera responde HTTP.")
        print("- Tente passar --user/--password (basic/digest).")
        print("- Se a camera for RTSP-only, use RTSP (nao HTTP snapshot).")
        return 1

    best = sorted(ok_results, key=lambda r: (r.size, r.elapsed_ms))[0]
    print("Melhor candidato (menor tamanho):")
    print(f"- url:  {best.url}")
    print(f"- auth: {best.auth}")
    print(f"- size: {best.size} bytes")
    print(f"- ct:   {best.content_type}")
    if best.saved_path:
        print(f"- saved:{best.saved_path}")
    print()
    print("Sugestao para firmware (.env):")
    print(f"IP_CAM_URL={best.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
