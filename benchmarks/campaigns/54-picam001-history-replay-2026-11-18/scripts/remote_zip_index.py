# -*- coding: utf-8 -*-
"""Camp 54 — roda DENTRO do worker de producao (so leitura): le o indice (central directory) de cada zip
diario `descartadas/pi-cam-001/<dia>/pi-cam-001_<dia>.zip` com leituras parciais e escreve em stdout um TSV
gzipado: dia, nome, metodo, crc, tamanho_comprimido, tamanho, offset_do_cabecalho, tamanho_do_nome.
Nao baixa frames, nao grava nada em disco, nao imprime credencial.

Uso (do PC): ssh saira-prod 'docker exec -i saira-yolo-worker-prod python -' < remote_zip_index.py > zip_dirs.tsv.gz
"""
import gzip
import io
import os
import sys
import zipfile

sys.path.insert(0, "/app/src")
try:
    from worker import storage_s3
    s3 = storage_s3._get_s3_client() if hasattr(storage_s3, "_get_s3_client") else None
except Exception:  # noqa: BLE001
    s3 = None
if s3 is None:
    import boto3
    s3 = boto3.client("s3", region_name=os.environ.get("S3_REGION", "sa-east-1"))
BUCKET = os.environ.get("S3_BUCKET_NAME") or "saira-images"
D0, D1 = "2026-07-14", "2026-09-09"


class Ranged(io.RawIOBase):
    def __init__(self, key, size):
        self.key, self.size, self.pos = key, size, 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else (self.pos + off if whence == 1 else self.size + off)
        return self.pos

    def readinto(self, b):
        n = min(len(b), self.size - self.pos)
        if n <= 0:
            return 0
        r = s3.get_object(Bucket=BUCKET, Key=self.key, Range=f"bytes={self.pos}-{self.pos + n - 1}")
        data = r["Body"].read()
        b[:len(data)] = data
        self.pos += len(data)
        return len(data)


keys = []
for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix="descartadas/pi-cam-001/"):
    for o in page.get("Contents", []):
        day = o["Key"].split("/")[2]
        if D0 <= day <= D1:
            keys.append((day, o["Key"], o["Size"]))
out = gzip.GzipFile(fileobj=sys.stdout.buffer, mode="wb")
tot = 0
for day, key, size in sorted(keys):
    try:
        zf = zipfile.ZipFile(io.BufferedReader(Ranged(key, size), buffer_size=4 * 1024 * 1024))
        infos = zf.infolist()
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"{day}: ERRO {type(e).__name__} {str(e)[:100]}\n")
        continue
    for i in infos:
        out.write(f"{day}\t{i.filename}\t{i.compress_type}\t{i.CRC}\t{i.compress_size}\t{i.file_size}\t"
                  f"{i.header_offset}\t{len(i.filename.encode('utf-8'))}\n".encode("utf-8"))
    tot += len(infos)
    sys.stderr.write(f"{day}: {len(infos)} arquivos, zip de {size / 1e6:.0f} MB\n")
out.close()
sys.stderr.write(f"total: {tot} arquivos em {len(keys)} zips\n")
