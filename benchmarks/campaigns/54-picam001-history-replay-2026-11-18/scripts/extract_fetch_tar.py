#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — extrai o tar devolvido pelo script remoto (make_fetch_script.py) para frames/janela,
conferindo cada frame contra a lista pedida: tamanho, CRC-32 do zip e cabecalho JPEG. Nao sobrescreve.

Uso: python extract_fetch_tar.py <lista.json> <frames.tar> [pasta_destino]
"""
from __future__ import annotations

import json
import sys
import tarfile
import zlib
from pathlib import Path

ROOT = Path(r"C:\Saira\data\historico-picam")


def main():
    items = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    want = {it[1].rsplit("/", 1)[-1]: it for it in items}   # [dia, nome, offset, csize, size, metodo, crc, nlen]
    dst = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / "frames" / "janela"
    dst.mkdir(parents=True, exist_ok=True)
    ok, bad, extra, seen = 0, [], 0, set()
    with tarfile.open(sys.argv[2]) as tf:
        for m in tf:
            if not m.isfile():
                continue
            name = m.name.rsplit("/", 1)[-1]
            it = want.get(name)
            if it is None:
                extra += 1
                continue
            data = tf.extractfile(m).read()
            if len(data) != it[4] or (zlib.crc32(data) & 0xFFFFFFFF) != it[6] or data[:2] != b"\xff\xd8":
                bad.append(name)
                continue
            out = dst / name
            if not out.exists():
                out.write_bytes(data)
            seen.add(name)
            ok += 1
    missing = sorted(set(want) - seen)
    print(f"pedidos {len(want)} | conferidos e gravados {ok} | ruins {len(bad)} | fora da lista {extra} | "
          f"faltando {len(missing)}")
    for n in bad[:10] + missing[:10]:
        print("  ", n)
    sys.exit(0 if not bad and not missing else 1)


if __name__ == "__main__":
    main()
