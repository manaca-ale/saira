#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — baixa os frames de DETECCOES pelas URLs publicas do S3 (as mesmas que o dashboard usa).

Uso: python fetch_public.py <lista.tsv> <pasta_de_saida>     (lista: nome<TAB>url)
Retoma de onde parou (pula arquivo que ja existe com tamanho > 0).
"""
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def main():
    lista, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    items = [l.rstrip("\n").split("\t") for l in lista.read_text(encoding="utf-8").splitlines() if l.strip()]

    def one(it):
        name, url = it
        dst = out / name
        if dst.exists() and dst.stat().st_size > 0:
            return name, 0, ""
        if not url.startswith("https://saira-images.s3."):
            return name, 0, "url inesperada"
        for att in range(4):
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    data = r.read()
                if data[:2] != b"\xff\xd8":
                    return name, 0, "nao e JPEG"
                dst.write_bytes(data)
                return name, len(data), ""
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {str(e)[:80]}"
        return name, 0, err

    ok = bad = nbytes = 0
    with ThreadPoolExecutor(12) as pool:
        for name, n, err in pool.map(one, items):
            if err:
                bad += 1
                print("ERRO", name, err)
            else:
                ok += 1
                nbytes += n
    print(f"fim: ok={ok} erros={bad} baixados={nbytes / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
