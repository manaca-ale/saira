#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — gera o script que roda DENTRO do worker de producao (so leitura) para ler, por faixa de bytes,
apenas os frames pedidos dos zips diarios do S3 e devolver um tar em stdout. Nada e gravado no servidor e
nenhuma credencial sai de la.

Uso:
  python make_fetch_script.py <lista.json> <saida.py>
  ssh saira-prod 'docker exec -i saira-yolo-worker-prod python -' < saida.py > frames.tar 2> fetch.log
A lista e a de draw_sample.py: [dia, nome, offset, tam_comprimido, tamanho, metodo, crc, tam_nome].
"""
import base64
import gzip
import json
import sys
from pathlib import Path

REMOTE = r'''
import base64, gzip, io, json, os, sys, tarfile, time, zlib
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, "/app/src")
try:
    from worker import storage_s3
    s3 = storage_s3._get_s3_client() if hasattr(storage_s3, "_get_s3_client") else None
except Exception:
    s3 = None
if s3 is None:
    import boto3
    s3 = boto3.client("s3", region_name=os.environ.get("S3_REGION", "sa-east-1"))
BUCKET = os.environ.get("S3_BUCKET_NAME") or "saira-images"
ITEMS = json.loads(gzip.decompress(base64.b64decode("__PAYLOAD__")))


def get(key, a, b):
    last = None
    for att in range(5):
        try:
            return s3.get_object(Bucket=BUCKET, Key=key, Range="bytes=%d-%d" % (a, b))["Body"].read()
        except Exception as e:
            last = e
            time.sleep(1.5 * (att + 1))
    raise last


def fetch(it):
    day, name, off, csize, size, method, crc, nlen = it
    key = "descartadas/pi-cam-001/%s/pi-cam-001_%s.zip" % (day, day)
    try:
        data = get(key, off, off + 30 + nlen + 128 + csize - 1)
        if data[:4] != b"PK\x03\x04":
            return name, None, "cabecalho invalido"
        start = 30 + int.from_bytes(data[26:28], "little") + int.from_bytes(data[28:30], "little")
        if start + csize > len(data):
            data = get(key, off, off + start + csize - 1)
        comp = data[start:start + csize]
        raw = comp if method == 0 else zlib.decompress(comp, -15)
        if len(raw) != size or (zlib.crc32(raw) & 0xffffffff) != crc:
            return name, None, "crc ou tamanho nao conferem"
        return name, raw, ""
    except Exception as e:
        return name, None, "%s: %s" % (type(e).__name__, str(e)[:80])


t0 = time.time()
ok = bad = nbytes = 0
with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as tar:
    with ThreadPoolExecutor(16) as pool:
        for i in range(0, len(ITEMS), 320):
            for name, raw, err in pool.map(fetch, ITEMS[i:i + 320]):
                if raw is None:
                    bad += 1
                    sys.stderr.write("ERRO %s %s\n" % (name, err))
                    continue
                ti = tarfile.TarInfo(name=name.rsplit("/", 1)[-1])
                ti.size = len(raw)
                tar.addfile(ti, io.BytesIO(raw))
                ok += 1
                nbytes += len(raw)
            sys.stderr.write("%d/%d frames, %.0f MB, %.0f s\n" % (ok, len(ITEMS), nbytes / 1e6, time.time() - t0))
            sys.stderr.flush()
sys.stderr.write("fim: ok=%d erros=%d bytes=%d em %.0f s\n" % (ok, bad, nbytes, time.time() - t0))
'''


def main():
    items = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    payload = base64.b64encode(gzip.compress(json.dumps(items, separators=(",", ":")).encode("utf-8"))).decode("ascii")
    Path(sys.argv[2]).write_text(REMOTE.replace("__PAYLOAD__", payload), encoding="utf-8", newline="\n")
    print(f"{len(items)} frames na lista; script de {len(payload) / 1e6:.2f} MB de carga")


if __name__ == "__main__":
    main()
