"""Armazenamento de clipes de evento na Raspberry Pi (RAM → SD → upload).

Ciclo de vida de um clipe:

  1. archive_event(event_id, start, end)
       Copia os segmentos .ts do ring RTSP (tmpfs) cuja mtime cai em
       [start − pre_roll, end + tail] para ARCHIVE_DIR/<event_id>/ (também
       tmpfs — zero desgaste de SD). Orçamento ARCHIVE_MAX_BYTES com eviction
       LRU dos eventos mais antigos não em uso.

  2. persist_clip(event_id)   [CMD_PERSIST_CLIP:<id>, worker confirmou]
       Concatena os segmentos arquivados em um mp4 (ffmpeg -c copy, sem
       reencode) direto no SD (CLIPS_DIR) e libera o diretório em RAM.
       Pouquíssimas gravações por dia → desgaste de SD desprezível.

  3. export_clip(event_id)    [CMD_VIDEO_CLIP:<id>, plataforma requisitou]
       Retorna o mp4 do SD se existir; senão constrói um mp4 temporário em
       RAM a partir do arquivo do evento. O caller faz o upload e chama
       cleanup_export() para apagar o temporário.

  4. prune()
       Retenção: apaga mp4 do SD com mais de CLIP_RETENTION_DAYS.

Thread-safety: archive é chamado pela thread de captura; persist/export pela
thread de comandos — um lock simples protege o diretório de arquivo.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("saira-agent.clips")


class ClipStore:
    def __init__(
        self,
        *,
        seg_dir: Path,
        archive_dir: Path,
        clips_dir: Path,
        archive_max_bytes: int,
        clip_seconds: int,
        seg_seconds: int,
        pre_roll_seconds: int,
        tail_seconds: int,
        retention_days: int,
    ) -> None:
        self.seg_dir = seg_dir
        self.archive_dir = archive_dir
        self.clips_dir = clips_dir
        self.archive_max_bytes = archive_max_bytes
        self.clip_seconds = clip_seconds
        self.seg_seconds = seg_seconds
        self.pre_roll_seconds = pre_roll_seconds
        self.tail_seconds = tail_seconds
        self.retention_days = retention_days

        self._lock = threading.Lock()
        self._in_use: set[str] = set()

        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.clips_dir.mkdir(parents=True, exist_ok=True)

    # ----- 1. arquivar em RAM ---------------------------------------------
    def archive_event(self, event_id: str, start_ts: float, end_ts: float) -> bool:
        """Copia os segmentos do ring que cobrem o evento para a RAM.

        Deve ser chamado ≥ tail_seconds após end_ts (o caller agenda) para o
        ffmpeg já ter fechado os segmentos do final do evento.
        """
        lo = start_ts - self.pre_roll_seconds
        hi = end_ts + self.tail_seconds
        # O segmento mais novo pode estar sendo escrito pelo ffmpeg agora —
        # nunca copiar nada mais novo que (agora − seg_seconds − 1).
        newest_safe = time.time() - (self.seg_seconds + 1)

        candidates: list[tuple[float, Path]] = []
        try:
            for seg in self.seg_dir.glob("seg_*.ts"):
                mt = seg.stat().st_mtime
                if lo <= mt <= hi and mt <= newest_safe:
                    candidates.append((mt, seg))
        except OSError as exc:
            log.error("Falha ao listar segmentos do ring: %s", exc)
            return False
        if not candidates:
            log.warning("Nenhum segmento do ring cobre o evento %s", event_id)
            return False

        candidates.sort()
        # Cap de duração: mantém os ÚLTIMOS clip_seconds (o final do evento —
        # o ato — importa mais que o excesso de pre-roll).
        max_segs = max(1, self.clip_seconds // self.seg_seconds)
        candidates = candidates[-max_segs:]

        dest = self.archive_dir / event_id
        with self._lock:
            self._in_use.add(event_id)
        try:
            dest.mkdir(parents=True, exist_ok=True)
            total = 0
            for idx, (mt, seg) in enumerate(candidates):
                # Prefixo sequencial preserva a ordem cronológica após a cópia
                # (segment_wrap recicla nomes; a ordem real vem do mtime).
                target = dest / f"{idx:04d}_{seg.name}"
                shutil.copy2(seg, target)
                total += target.stat().st_size
            log.info(
                "Evento %s arquivado: %d segmentos, %.1f MB",
                event_id, len(candidates), total / 1e6,
            )
        except OSError as exc:
            log.error("Falha ao arquivar evento %s: %s", event_id, exc)
            shutil.rmtree(dest, ignore_errors=True)
            return False
        finally:
            with self._lock:
                self._in_use.discard(event_id)
        self._evict_lru()
        return True

    def _evict_lru(self) -> None:
        """Mantém o arquivo em RAM dentro do orçamento (LRU por mtime)."""
        try:
            dirs = [d for d in self.archive_dir.iterdir() if d.is_dir()]
        except OSError:
            return
        sized = []
        total = 0
        for d in dirs:
            size = sum(f.stat().st_size for f in d.glob("*") if f.is_file())
            sized.append((d.stat().st_mtime, size, d))
            total += size
        sized.sort()  # mais antigo primeiro
        for _, size, d in sized:
            if total <= self.archive_max_bytes:
                break
            with self._lock:
                if d.name in self._in_use:
                    continue
            shutil.rmtree(d, ignore_errors=True)
            total -= size
            log.info("Eviction LRU: arquivo do evento %s liberado (%.1f MB)", d.name, size / 1e6)

    # ----- 2. persistir no SD ----------------------------------------------
    def persist_clip(self, event_id: str) -> Optional[Path]:
        """Concatena o arquivo RAM do evento em mp4 no SD e libera a RAM."""
        out = self.clips_dir / f"{event_id}.mp4"
        if out.is_file():
            return out  # já persistido (comando duplicado)
        src = self.archive_dir / event_id
        if not src.is_dir():
            log.warning("Persist: evento %s não está no arquivo RAM", event_id)
            return None
        with self._lock:
            self._in_use.add(event_id)
        try:
            # O temporário PRECISA terminar em .mp4: o ffmpeg infere o muxer
            # pela extensão (".part" puro falha com "unable to choose format").
            tmp = self.clips_dir / f"{event_id}.part.mp4"
            if not self._concat(sorted(src.glob("*.ts")), tmp):
                tmp.unlink(missing_ok=True)
                return None
            tmp.replace(out)
            shutil.rmtree(src, ignore_errors=True)
            log.info("Clipe %s persistido no SD (%.1f MB)", event_id, out.stat().st_size / 1e6)
            return out
        finally:
            with self._lock:
                self._in_use.discard(event_id)

    # ----- 3. exportar para upload ------------------------------------------
    def export_clip(self, event_id: str) -> tuple[Optional[Path], bool]:
        """Retorna (caminho_mp4, is_temp). SD primeiro, RAM como fallback."""
        persisted = self.clips_dir / f"{event_id}.mp4"
        if persisted.is_file():
            return persisted, False
        src = self.archive_dir / event_id
        if not src.is_dir():
            return None, False
        with self._lock:
            self._in_use.add(event_id)
        try:
            tmp = self.archive_dir / f"{event_id}.export.mp4"
            if not self._concat(sorted(src.glob("*.ts")), tmp):
                tmp.unlink(missing_ok=True)
                return None, False
            return tmp, True
        finally:
            with self._lock:
                self._in_use.discard(event_id)

    @staticmethod
    def cleanup_export(path: Path, is_temp: bool) -> None:
        if is_temp:
            path.unlink(missing_ok=True)

    def _concat(self, segments: list[Path], out: Path) -> bool:
        if not segments:
            log.warning("Concat sem segmentos para %s", out.name)
            return False
        list_file = out.with_suffix(".txt")
        list_file.write_text(
            "".join(f"file '{s.as_posix()}'\n" for s in segments), encoding="utf-8"
        )
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(list_file),
                    "-c", "copy", "-movflags", "+faststart", str(out),
                ],
                check=True, capture_output=True, timeout=120,
            )
            return True
        except subprocess.CalledProcessError as exc:
            log.error("ffmpeg concat falhou: %s", exc.stderr.decode(errors="ignore")[:400])
            return False
        except subprocess.TimeoutExpired:
            log.error("ffmpeg concat excedeu timeout")
            return False
        finally:
            list_file.unlink(missing_ok=True)

    # ----- 4. retenção -------------------------------------------------------
    def prune(self) -> None:
        cutoff = time.time() - self.retention_days * 86400
        try:
            for clip in self.clips_dir.glob("*.mp4"):
                if clip.stat().st_mtime < cutoff:
                    clip.unlink(missing_ok=True)
                    log.info("Retenção: clipe %s removido do SD", clip.name)
        except OSError as exc:
            log.warning("Prune falhou: %s", exc)
