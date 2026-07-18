"""Armazenamento de clipes de evento na Raspberry Pi (RAM → SD → upload).

Uma ocorrência LONGA é fatiada pelo gate em eventos consecutivos
(close:max_duration → reopen com event_id NOVO) — uma "cadeia". Sem tratar a
cadeia, só o evento confirmado pelo worker persistia no SD e os demais
pedaços (ex.: a saída dos infratores) morriam na eviction da RAM — o vídeo
da ocorrência ficava incompleto (incidente de 2026-07-17).

Ciclo de vida de um clipe:

  1. archive_event(event_id, start, end)
       Copia os segmentos .ts do ring RTSP (tmpfs) cuja mtime cai em
       [start − pre_roll, end + tail] para ARCHIVE_DIR/<event_id>/ (também
       tmpfs — zero desgaste de SD). Orçamento ARCHIVE_MAX_BYTES com eviction
       LRU dos eventos mais antigos não em uso.

  1b. persist_if_chained(event_id)   [logo após o archive]
       Se o evento recém-arquivado é vizinho de cadeia de um clipe JÁ
       confirmado no SD, persiste na hora — o worker nunca confirma
       individualmente os membros POSTERIORES à detecção. Sem vizinho no
       SD: fica só na RAM, como sempre (pedestre não desgasta o cartão).

  2. promote_chain(event_id)   [CMD_PERSIST_CLIP:<id>, worker confirmou]
       Concatena em mp4 (ffmpeg -c copy, sem reencode) direto no SD
       (CLIPS_DIR) o clipe confirmado E os membros da cadeia ainda na RAM,
       liberando os diretórios em RAM. Só cadeias com descarte confirmado
       tocam o SD → desgaste desprezível.

  3. export_clip(event_id)    [CMD_VIDEO_CLIP:<id>, plataforma requisitou]
       Cadeia de 1 membro já no SD → retorna o próprio mp4. Cadeia com 2+
       membros → costura num único mp4 (concat demuxer) em CLIPS_DIR/exports
       — no SD, porque o stitch de N×~90 MB não cabe no tmpfs do Pi 3. O
       caller faz o upload e chama cleanup_export() para apagar o temporário.

  4. prune()
       Retenção (CLIP_RETENTION_DAYS) + teto de bytes CLIPS_MAX_BYTES (LRU,
       backstop: FP não enche o cartão) + janitor de temporários órfãos
       (.part/exports — power-cut no meio do concat).

Thread-safety: archive/persist_if_chained rodam na thread de Timer pós-
evento; promote/export na thread de comandos; prune na manutenção.
_persist_lock serializa TODA mutação no SD; _lock protege o set _in_use
(RAM). Ordem: _persist_lock (externo) → _lock (interno), nunca o inverso.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("saira-agent.clips")

# Nome de evento carrega o início: evt-YYYYmmdd_HHMMSS (relógio local, ver
# MotionGate._new_event_id). evt-test-* (SIGUSR1) segue o mesmo formato;
# evt-warmup-* fica de fora de propósito (fail-open de boot, sem cadeia).
_EVENT_TS_RE = re.compile(r"^evt-(?:test-)?(\d{8})_(\d{6})$")


def parse_event_start(event_id: str) -> Optional[float]:
    """Epoch de início extraído do nome do evento, ou None se o nome não
    segue o padrão (evt-warmup-*, temporários .part/.export, lixo)."""
    m = _EVENT_TS_RE.match(event_id or "")
    if not m:
        return None
    try:
        st = time.strptime(f"{m.group(1)}_{m.group(2)}", "%Y%m%d_%H%M%S")
    except ValueError:
        return None
    return time.mktime(st)


def chain_members(
    anchor_id: str,
    inventory: dict[str, float],
    *,
    gap_s: float,
    est_len_s: float,
) -> list[str]:
    """Membros da cadeia do anchor (ordenados por início), dado um
    inventário {event_id: start_ts}.

    Regra: eventos consecutivos (por início) pertencem à mesma cadeia se
    next_start − (prev_start + est_len_s) ≤ gap_s, onde est_len_s é a
    duração MÁXIMA estimada de um evento (event_max_s + tail) — superestima
    eventos curtos, o que só torna a cadeia um pouco generosa (inócuo: a
    promoção apenas retém por mais tempo; a costura tem teto próprio).
    Transitiva por construção (A~B e B~C ⇒ A,B,C). Anchor com nome fora do
    padrão → [anchor] (sem cadeia, comportamento legado)."""
    anchor_ts = inventory.get(anchor_id)
    if anchor_ts is None:
        anchor_ts = parse_event_start(anchor_id)
    if anchor_ts is None:
        return [anchor_id]
    entries = dict(inventory)
    entries[anchor_id] = anchor_ts  # anchor pode não ter clipe e ainda ligar vizinhos
    ordered = sorted(entries.items(), key=lambda kv: (kv[1], kv[0]))
    idx = next(i for i, (eid, _) in enumerate(ordered) if eid == anchor_id)
    lo = idx
    while lo > 0 and ordered[lo][1] - (ordered[lo - 1][1] + est_len_s) <= gap_s:
        lo -= 1
    hi = idx
    while hi < len(ordered) - 1 and ordered[hi + 1][1] - (ordered[hi][1] + est_len_s) <= gap_s:
        hi += 1
    return [eid for eid, _ in ordered[lo:hi + 1]]


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
        chain_enabled: bool = True,
        chain_gap_s: int = 180,
        chain_span_s: int = 600,
        chain_max_s: int = 600,
        clips_max_bytes: int = 8 * 1024 * 1024 * 1024,
        event_max_s: int = 120,
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
        # Cadeia (atributos mutáveis: o config remoto escreve direto neles,
        # mesmo padrão dos knobs do MotionGate).
        self.chain_enabled = chain_enabled
        self.chain_gap_s = chain_gap_s
        self.chain_span_s = chain_span_s
        self.chain_max_s = chain_max_s
        self.clips_max_bytes = clips_max_bytes
        self.event_max_s = event_max_s

        self._lock = threading.Lock()
        self._in_use: set[str] = set()
        # Serializa TODA mutação no SD (Timer persiste por adjacência,
        # comandos promovem/exportam, manutenção poda). Ordem com _lock:
        # _persist_lock (externo) → _lock (interno); nunca o inverso.
        self._persist_lock = threading.Lock()

        # exports/ é SUBdiretório de clips_dir de propósito: rename atômico
        # no mesmo filesystem e os glob("*.mp4") não-recursivos existentes
        # continuam enxergando só os clipes confirmados.
        self.exports_dir = clips_dir / "exports"
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)

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
    def _concat_from_ram(self, event_id: str) -> Optional[Path]:
        """Concatena o arquivo RAM do evento em mp4 no SD e libera a RAM.
        Idempotente (mp4 já existe → retorna). Caller segura _persist_lock."""
        out = self.clips_dir / f"{event_id}.mp4"
        if out.is_file():
            return out  # já persistido (comando duplicado / membro repetido)
        src = self.archive_dir / event_id
        if not src.is_dir():
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

    def persist_clip(self, event_id: str) -> Optional[Path]:
        """Persiste UM evento (sem cadeia) — caso-base/legado."""
        with self._persist_lock:
            out = self._concat_from_ram(event_id)
        if out is None:
            log.warning("Persist: evento %s não está no arquivo RAM", event_id)
        return out

    def _confirmed_marker(self, event_id: str) -> Path:
        """Marker de clipe CONFIRMADO pelo worker (âncora de CMD_PERSIST_CLIP).
        Distingue evidência confirmada de clipes persistidos por adjacência —
        a adjacência só ancora em confirmados e a eviction preserva-os por
        último."""
        return self.clips_dir / f"{event_id}.mp4.confirmed"

    def confirmed_starts(self) -> dict[str, float]:
        """{event_id: start_ts} dos clipes confirmados presentes no SD."""
        out: dict[str, float] = {}
        try:
            for marker in self.clips_dir.glob("*.mp4.confirmed"):
                stem = marker.name[: -len(".mp4.confirmed")]
                ts = parse_event_start(stem)
                if ts is not None and (self.clips_dir / f"{stem}.mp4").is_file():
                    out[stem] = ts
        except OSError:
            pass
        return out

    def promote_chain(self, event_id: str) -> list[str]:
        """CMD_PERSIST_CLIP:<id> — persiste o clipe confirmado E os membros
        da mesma cadeia ainda na RAM (ocorrência longa fatiada pelo
        max_duration do gate). Marca a ÂNCORA como confirmada (base da
        persistência por adjacência). Devolve os ids com mp4 no SD ao final."""
        if not self.chain_enabled:
            return [event_id] if self.persist_clip(event_id) is not None else []
        done: list[str] = []
        with self._persist_lock:
            for member in self.chain_for(event_id):
                out = self._concat_from_ram(member)
                if out is not None:
                    done.append(member)
                elif member == event_id:
                    log.warning("Persist: evento %s sem clipe (RAM evicted?)", member)
                else:
                    log.debug("Cadeia de %s: membro %s sem clipe disponível",
                              event_id, member)
            if (self.clips_dir / f"{event_id}.mp4").is_file():
                try:
                    self._confirmed_marker(event_id).touch()
                except OSError:
                    pass
            if done:
                self._evict_clips_budget()
        return done

    def persist_if_chained(self, event_id: str) -> Optional[Path]:
        """Persistência por ADJACÊNCIA (thread do Timer, logo após o archive):
        persiste na hora o evento recém-arquivado que fecha a até
        chain_span_s de um clipe CONFIRMADO pelo worker. Cobre os membros
        POSTERIORES à confirmação (ex.: a saída dos infratores em
        2026-07-17), que o worker nunca confirma individualmente.

        Exigir âncora CONFIRMADA (e não qualquer vizinho no SD) é o freio da
        cadeia: em zona de tráfego contínuo, adjacência transitiva rolaria
        para sempre e viraria persist-everything (observado em campo na
        manhã de 18/07). O span default (600s) espelha a janela de
        coalescing de ocorrências da plataforma. Sem âncora no span: fica
        na RAM, como sempre (pedestre não desgasta o cartão)."""
        if not self.chain_enabled:
            return None
        ts = parse_event_start(event_id)
        if ts is None:
            return None
        with self._persist_lock:
            anchors = [
                cid for cid, cts in self.confirmed_starts().items()
                if cid != event_id and abs(ts - cts) <= self.chain_span_s
            ]
            if not anchors:
                return None
            out = self._concat_from_ram(event_id)
            if out is not None:
                log.info(
                    "Evento %s persistido por adjacência de cadeia (confirmado no span: %s)",
                    event_id, anchors[0],
                )
                self._evict_clips_budget()
            return out

    def known_events(self) -> dict[str, tuple[float, str]]:
        """Inventário {event_id: (start_ts, tier)} dos clipes conhecidos:
        "sd" (mp4 em clips_dir) e "ram" (diretório em archive_dir). Só ids
        com timestamp parseável — a regex exclui .part/.export/warmup."""
        inv: dict[str, tuple[float, str]] = {}
        try:
            for d in self.archive_dir.iterdir():
                if d.is_dir():
                    ts = parse_event_start(d.name)
                    if ts is not None:
                        inv[d.name] = (ts, "ram")
        except OSError:
            pass
        try:
            for f in self.clips_dir.glob("*.mp4"):
                stem = f.name[:-4]
                ts = parse_event_start(stem)
                if ts is not None:
                    inv[stem] = (ts, "sd")  # SD vence colisão com RAM
        except OSError:
            pass
        return inv

    def chain_for(self, event_id: str) -> list[str]:
        """Membros da cadeia do evento (SD + RAM), ordenados por início."""
        inv = self.known_events()
        return chain_members(
            event_id, {k: v[0] for k, v in inv.items()},
            gap_s=self.chain_gap_s,
            est_len_s=self.event_max_s + self.tail_seconds,
        )

    # ----- 3. exportar para upload ------------------------------------------
    def _export_from_ram(self, event_id: str) -> Optional[Path]:
        """Constrói um mp4 temporário em RAM a partir do arquivo do evento
        (membro ainda não persistido). O caller apaga após o uso."""
        src = self.archive_dir / event_id
        if not src.is_dir():
            return None
        with self._lock:
            self._in_use.add(event_id)
        try:
            tmp = self.archive_dir / f"{event_id}.export.mp4"
            if not self._concat(sorted(src.glob("*.ts")), tmp):
                tmp.unlink(missing_ok=True)
                return None
            return tmp
        finally:
            with self._lock:
                self._in_use.discard(event_id)

    def _export_single(self, event_id: str) -> tuple[Optional[Path], bool]:
        """Comportamento legado (sem cadeia): SD primeiro, RAM como fallback."""
        persisted = self.clips_dir / f"{event_id}.mp4"
        if persisted.is_file():
            return persisted, False
        tmp = self._export_from_ram(event_id)
        return (tmp, True) if tmp is not None else (None, False)

    def export_clip(self, event_id: str) -> tuple[Optional[Path], bool]:
        """Retorna (caminho_mp4, is_temp) para upload.

        Cadeia de 1 membro já no SD → o próprio mp4 (zero custo, is_temp
        False). 2+ membros → costura num único mp4 (concat demuxer, -c copy;
        mesmo stream ⇒ mesmos codec params; o reset_timestamps do ring faz o
        demuxer re-offsetar cada parte) em exports/ NO SD — o stitch de
        N×~90 MB não cabe no tmpfs do Pi 3. Buracos de conteúdo entre
        membros = períodos sem movimento por definição (aceito). O teto
        chain_max_s prioriza o anchor e os membros POSTERIORES (a saída é a
        evidência que motivou a costura)."""
        if not self.chain_enabled or parse_event_start(event_id) is None:
            return self._export_single(event_id)
        with self._persist_lock:
            inv = self.known_events()
            chain = [m for m in self.chain_for(event_id) if m in inv]
            if not chain:
                return None, False
            max_members = max(1, int(self.chain_max_s) // max(1, self.clip_seconds))
            if len(chain) > max_members:
                ai = chain.index(event_id) if event_id in chain else 0
                take = chain[ai:ai + max_members]
                room = max_members - len(take)
                if room > 0:
                    take = chain[max(0, ai - room):ai] + take
                log.info(
                    "Cadeia de %d membros excede o teto de %d — exportando %s",
                    len(chain), max_members, ",".join(take),
                )
                chain = take
            parts: list[Path] = []
            ram_temps: list[Path] = []
            for m in chain:
                if inv[m][1] == "sd":
                    parts.append(self.clips_dir / f"{m}.mp4")
                else:
                    tmp = self._export_from_ram(m)
                    if tmp is not None:
                        parts.append(tmp)
                        ram_temps.append(tmp)
                    else:
                        log.warning("Costura de %s: membro %s indisponível — pulado",
                                    event_id, m)
            if not parts:
                return None, False
            if len(parts) == 1:
                # Um membro só: sem costura. Se veio da RAM, o próprio
                # temporário é o export (o caller o apaga via cleanup_export).
                return (parts[0], True) if ram_temps else (parts[0], False)
            out = self.exports_dir / f"{event_id}.export.mp4"
            ok = self._concat(parts, out)
            for t in ram_temps:
                t.unlink(missing_ok=True)
            if not ok:
                out.unlink(missing_ok=True)
                return None, False
            log.info("Cadeia %s costurada: %d clipes, %.1f MB",
                     event_id, len(parts), out.stat().st_size / 1e6)
            return out, True

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
    def _evict_clips_budget(self) -> None:
        """Teto de bytes do SD (LRU por mtime), despejando NÃO-confirmados
        antes de confirmados — ruído de cauda nunca expulsa a evidência.
        Backstop: tempestade de FP não pode encher o cartão — que também é
        o root fs da Pi. Caller segura _persist_lock."""
        try:
            confirmed = {
                self.clips_dir / f"{eid}.mp4" for eid in self.confirmed_starts()
            }
            clips = sorted(
                self.clips_dir.glob("*.mp4"),
                key=lambda p: (p in confirmed, p.stat().st_mtime),
            )
        except OSError:
            return
        sizes: dict[Path, int] = {}
        total = 0
        for c in clips:
            try:
                sizes[c] = c.stat().st_size
            except OSError:
                sizes[c] = 0
            total += sizes[c]
        for c in clips:
            if total <= self.clips_max_bytes:
                break
            c.unlink(missing_ok=True)
            self._confirmed_marker(c.name[:-4]).unlink(missing_ok=True)
            total -= sizes[c]
            log.warning("Orçamento do SD estourado: clipe %s removido (%.1f MB)",
                        c.name, sizes[c] / 1e6)

    def prune(self) -> None:
        """Retenção (dias) + orçamento (bytes) + janitor de temporários."""
        now = time.time()
        cutoff = now - self.retention_days * 86400
        with self._persist_lock:
            try:
                for clip in self.clips_dir.glob("*.mp4"):
                    if clip.stat().st_mtime < cutoff:
                        clip.unlink(missing_ok=True)
                        self._confirmed_marker(clip.name[:-4]).unlink(missing_ok=True)
                        log.info("Retenção: clipe %s removido do SD", clip.name)
                # Marker órfão (mp4 sumiu por poda de emergência/manual).
                for marker in self.clips_dir.glob("*.mp4.confirmed"):
                    if not marker.with_name(marker.name[: -len(".confirmed")]).is_file():
                        marker.unlink(missing_ok=True)
            except OSError as exc:
                log.warning("Prune falhou: %s", exc)
            self._evict_clips_budget()
            # Janitor: .part órfão (power-cut no meio do concat) e exports que
            # o upload não limpou. 1h de margem cobre qualquer upload 4G.
            stale = now - 3600
            for pattern_dir, pattern in (
                (self.clips_dir, "*.part.mp4"),
                (self.exports_dir, "*.mp4"),
                (self.archive_dir, "*.export.mp4"),
            ):
                try:
                    for orphan in pattern_dir.glob(pattern):
                        if orphan.stat().st_mtime < stale:
                            orphan.unlink(missing_ok=True)
                            log.info("Janitor: temporário órfão %s removido", orphan.name)
                except OSError:
                    pass
