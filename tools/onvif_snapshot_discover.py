"""Discover snapshot URIs via ONVIF GetSnapshotUri.

Queries the camera's ONVIF Media service for all available profiles and
retrieves the snapshot URI for each one.  This is useful when the camera
does not document its HTTP snapshot endpoints.

Usage:
    pip install onvif-zeep
    python tools/onvif_snapshot_discover.py --host 192.168.0.142 --user admin --password admin

Requirements: onvif-zeep (pip install onvif-zeep)
"""

import argparse
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass
class ProfileSnapshot:
    name: str
    token: str
    snapshot_uri: str
    resolution: Optional[str]


def discover(host: str, port: int, user: str, password: str) -> list[ProfileSnapshot]:
    try:
        from onvif import ONVIFCamera
    except ImportError:
        print("ERRO: instale a biblioteca onvif-zeep:")
        print("  pip install onvif-zeep")
        sys.exit(2)

    print(f"Conectando via ONVIF a {host}:{port} (user={user}) ...")
    cam = ONVIFCamera(host, port, user, password)
    media = cam.create_media_service()

    profiles = media.GetProfiles()
    print(f"Encontrados {len(profiles)} profiles ONVIF:\n")

    results: list[ProfileSnapshot] = []
    for p in profiles:
        token = p.token
        name = getattr(p, "Name", token)

        # Resolve resolution from VideoEncoderConfiguration if available
        res_str = None
        vec = getattr(p, "VideoEncoderConfiguration", None)
        if vec:
            r = getattr(vec, "Resolution", None)
            if r:
                res_str = f"{r.Width}x{r.Height}"

        try:
            resp = media.GetSnapshotUri({"ProfileToken": token})
            uri = resp.Uri if hasattr(resp, "Uri") else str(resp)
        except Exception as e:
            uri = f"(erro: {e})"

        snap = ProfileSnapshot(name=name, token=token, snapshot_uri=uri, resolution=res_str)
        results.append(snap)

        print(f"  Profile: {name}")
        print(f"    Token:      {token}")
        print(f"    Resolution: {res_str or '?'}")
        print(f"    Snapshot:   {uri}")
        print()

    return results


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Discover snapshot URIs from an IP camera via ONVIF.",
    )
    ap.add_argument("--host", required=True, help="Camera IP address")
    ap.add_argument("--port", type=int, default=80, help="ONVIF port (default 80)")
    ap.add_argument("--user", default="admin", help="Username")
    ap.add_argument("--password", default="admin", help="Password")
    args = ap.parse_args()

    results = discover(args.host, args.port, args.user, args.password)

    if not results:
        print("Nenhum profile ONVIF encontrado.")
        return 1

    # Find the profile with smallest resolution (substream candidate)
    with_res = [r for r in results if r.resolution and "erro" not in r.snapshot_uri]
    if with_res:
        def _pixels(r: ProfileSnapshot) -> int:
            try:
                w, h = r.resolution.split("x")  # type: ignore[union-attr]
                return int(w) * int(h)
            except Exception:
                return 999_999_999
        with_res.sort(key=_pixels)
        best = with_res[0]
        print("=" * 60)
        print(f"Menor resolucao disponivel: {best.name} ({best.resolution})")
        print(f"  Snapshot URI: {best.snapshot_uri}")
        print()
        print("Sugestao para firmware (.env):")
        print(f"  IP_CAM_URL={best.snapshot_uri}")
        if len(with_res) > 1:
            print()
            print("Todas as opcoes (menor -> maior):")
            for r in with_res:
                print(f"  {r.resolution:>12}  {r.name:>20}  {r.snapshot_uri}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
