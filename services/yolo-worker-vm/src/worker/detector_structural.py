"""Structural-delta post-detail false-positive filter (rejection-only).

Validado offline (Camp 41) em esp32_002 Mangabeira — a 1ª alavanca de VISÃO que
separa descarte real (TP) de transeunte (B3) na pile-zone E **sobrevive ao holdout
temporal** (train AUC 0,832 → test 0,826, gap 0,006), ao contrário do DINOv2
(0,89→0,51 = overfitting, Camp 40) e do BGSUB cru (AUC 0,41). Sinal:
census_ntiles_t32 = nº de tiles 32×32 da pile-zone com ≥50% de pixels
estruturalmente mudados entre o 1º e o último frame da janela.

POR QUE funciona onde tudo falhou:
- **Census Transform** (ordering local de intensidade) ⇒ invariante a iluminação
  monotônica — sombra/sol/IR não disparam (o que matava o MOG2).
- **Micro-tiles** ⇒ saco pequeno = ~100% de mudança em 2-3 tiles, independente do
  tamanho da pilha permanente (o "permanence" global da Camp 40 diluía).
- **before(1º frame) vs after(último frame)**: o depósito PERSISTE até o fim da
  janela; o transeunte PASSA e a estrutura REVERTE. É uma MEDIDA determinística,
  não um classificador treinado ⇒ nada pra overfittar (≠ DINOv2).

Posição no pipeline: roda DEPOIS do Agent-2 (detail), só quando `disposal=True`.
Ortogonal ao BGSUB (supressão pré-Agent-1) e ao gate barra-alta (prompt do detail).
Nunca transforma negativo em positivo — só pode REJEITAR um CON do pipeline.

should_reject = n_tiles_changed < threshold (poucos tiles mudados = sem depósito).
Todo caminho de falha retorna should_reject=False (FAIL-OPEN): polígono ausente,
frame ilegível ou cv2 quebrado NUNCA descartam um descarte real.

Artefato: NENHUM (medida pura cv2+numpy, sem modelo treinado — por isso não sofre
o drift que obriga o DINOv2 a retreino semanal).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

from . import config

logger = logging.getLogger(__name__)

# Persistent shadow-decision ledger (mesma lógica do DINOv2 — sobrevive a recreate).
SHADOW_LEDGER_NAME = "structural_decisions.jsonl"
# Ledger durável das decisões de RECUPERAÇÃO (gate-rejeitado → structural → Agent-2).
RECOVERY_LEDGER_NAME = "structural_recovery_decisions.jsonl"


@dataclass
class StructFilterResult:
    """Outcome of the structural-delta post-detail filter."""

    should_reject: bool          # True = (enforce) override disposal / (shadow) would-reject
    reason: str                  # rejected | passed | skipped_disabled | skipped_not_targeted
                                 # | skipped_no_polygon | skipped_no_frames | error
    n_tiles_changed: int = -1    # sinal principal (census_ntiles_t32); -1 = não computado
    threshold: int = -1
    n_frames_used: int = 0
    latency_ms: float = 0.0


# --- Census Transform + Hamming (numpy puro, invariante a iluminação) -----------

def _census_transform(img: np.ndarray) -> np.ndarray:
    """3x3 census transform de uma imagem grayscale. Retorna uint8 (h-2, w-2)."""
    h, w = img.shape
    census = np.zeros((h - 2, w - 2), dtype=np.uint8)
    center = img[1:h - 1, 1:w - 1]
    offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    for i, (dy, dx) in enumerate(offsets):
        neighbor = img[1 + dy:h - 1 + dy, 1 + dx:w - 1 + dx]
        census |= ((neighbor > center).astype(np.uint8) << i)
    return census


def _census_hamming(gray_pre: np.ndarray, gray_post: np.ndarray) -> np.ndarray:
    """Hamming por-pixel (0..8) entre os census, re-padded ao tamanho original."""
    cp = _census_transform(gray_pre)
    cq = _census_transform(gray_post)
    xor = np.bitwise_xor(cp, cq)
    h = np.unpackbits(xor[..., np.newaxis], axis=-1).sum(axis=-1).astype(np.uint8)
    out = np.zeros(gray_pre.shape, dtype=np.uint8)
    out[1:-1, 1:-1] = h
    return out


def _build_mask(polygon: Any, shape: tuple[int, int]) -> Optional[np.ndarray]:
    """Máscara 0/255 da pile_zone a partir do JSONB `pile_zone_polygon`."""
    import cv2
    polys = polygon
    if isinstance(polys, str):
        try:
            polys = json.loads(polys)
        except Exception:  # noqa: BLE001
            return None
    if not polys:
        return None
    mask = np.zeros(shape, dtype=np.uint8)
    drawn = False
    for poly in polys:
        try:
            pts = np.array(poly, dtype=np.int32).reshape(-1, 1, 2)
            if len(pts) >= 3:
                cv2.fillPoly(mask, [pts], 255)
                drawn = True
        except Exception:  # noqa: BLE001
            continue
    return mask if drawn else None


def _count_changed_tiles(gray_pre, gray_post, mask) -> int:
    """nº de tiles (STRUCTURAL_TILE px) tocando o polígono cuja fração de pixels
    census-changed (hamming>=HAM_THR) excede TILE_FRAC. = census_ntiles_t32 da Camp 41."""
    import cv2
    ham = _census_hamming(gray_pre, gray_post)
    changed = (ham >= int(config.STRUCTURAL_HAM_THR)).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    changed = cv2.morphologyEx(changed, cv2.MORPH_OPEN, k)

    ys, xs = np.where(mask > 0)
    if xs.size == 0:
        return 0
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
    tile = int(config.STRUCTURAL_TILE)
    frac_thr = float(config.STRUCTURAL_TILE_FRAC)
    min_cover = int(config.STRUCTURAL_MIN_TILE_COVER)
    n_changed = 0
    for ty in range(y0, y1, tile):
        for tx in range(x0, x1, tile):
            tm = mask[ty:ty + tile, tx:tx + tile] > 0
            if int(tm.sum()) < min_cover:
                continue
            cc = changed[ty:ty + tile, tx:tx + tile][tm]
            if cc.size and float(cc.mean()) > frac_thr:
                n_changed += 1
    return n_changed


def record_shadow_decision(
    *,
    request_id: str,
    device_id: str,
    result: "StructFilterResult",
    gemini_disposal: bool,
    mode: Optional[str] = None,
    models_dir: Optional[str] = None,
) -> None:
    """Append uma decisão shadow/enforce ao ledger durável (fail-safe, nunca levanta).

    Grava TODOS os reasons (inclusive skips/errors) — sem isso, fail-opens ficam
    invisíveis e o shadow parece coletar dados quando na verdade não roda (bug
    achado 2026-06-18: só 3 de 26 janelas logavam). O analista filtra por reason.
    """
    try:
        d = models_dir or config.STRUCTURAL_LEDGER_DIR
        Path(d).mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "device_id": device_id,
            "mode": mode if mode is not None else config.STRUCTURAL_FILTER_MODE,
            "n_tiles_changed": int(result.n_tiles_changed),
            "threshold": int(result.threshold),
            "should_reject": bool(result.should_reject),
            "reason": result.reason,
            "n_frames_used": int(result.n_frames_used),
            "gemini_disposal": bool(gemini_disposal),
        }
        with open(Path(d) / SHADOW_LEDGER_NAME, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("structural: failed to record shadow decision: %s", exc)


def score_window(
    sequence_paths: list[Path],
    pile_zone_polygon: Any,
) -> StructFilterResult:
    """Núcleo determinístico do sinal (SEM gating de modo/câmera): nº de tiles
    census-changed na pile-zone entre o 1º e o último frame LEGÍVEL da janela
    (before/after, validação Camp 41).

    reason="scored" + n_tiles_changed no sucesso; senão um reason de skip/erro com
    n_tiles_changed=-1 (fail-open). Compartilhado por evaluate() (veto de FP de CONs)
    e pelo caminho de RECUPERAÇÃO de janela gate-rejeitada (main._structural_recovery),
    que usam limiares distintos sobre o mesmo n_tiles_changed.
    """
    if not sequence_paths or len(sequence_paths) < 2:
        return StructFilterResult(should_reject=False, reason="skipped_no_frames")
    if not pile_zone_polygon:
        return StructFilterResult(should_reject=False, reason="skipped_no_polygon")

    t0 = time.time()
    try:
        import cv2
        # Leitura ROBUSTA: o 1º/último frame da janela pode estar ilegível (movido
        # p/ processed ou purgado em janela coalescida). Varre do início p/ o 1º
        # frame legível (before) e do fim p/ o último legível (after), preservando
        # a semântica first-vs-last validada na Camp 41.
        before = b_path = None
        for _p in sequence_paths:
            _img = cv2.imread(str(_p))
            if _img is not None:
                before, b_path = _img, _p
                break
        after = a_path = None
        for _p in reversed(sequence_paths):
            _img = cv2.imread(str(_p))
            if _img is not None:
                after, a_path = _img, _p
                break
        if before is None or after is None:
            return StructFilterResult(should_reject=False, reason="error_unreadable",
                                      latency_ms=(time.time() - t0) * 1000.0)
        if b_path == a_path:
            return StructFilterResult(should_reject=False, reason="skipped_one_frame",
                                      latency_ms=(time.time() - t0) * 1000.0)
        if before.shape != after.shape:
            return StructFilterResult(should_reject=False, reason="error_shape",
                                      latency_ms=(time.time() - t0) * 1000.0)
        mask = _build_mask(pile_zone_polygon, before.shape[:2])
        if mask is None:
            return StructFilterResult(should_reject=False, reason="skipped_no_polygon")

        gray_pre = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
        gray_post = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
        n_changed = _count_changed_tiles(gray_pre, gray_post, mask)
        return StructFilterResult(
            should_reject=False,
            reason="scored",
            n_tiles_changed=int(n_changed),
            n_frames_used=2,
            latency_ms=(time.time() - t0) * 1000.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("structural: score_window failed: %s", exc, exc_info=True)
        return StructFilterResult(should_reject=False, reason="error",
                                  latency_ms=(time.time() - t0) * 1000.0)


def evaluate(
    sequence_paths: list[Path],
    device_id: str,
    pile_zone_polygon: Any,
    camera: Any = None,  # noqa: ARG001 — simetria de API com detector_dinov2
) -> StructFilterResult:
    """Re-julga um CON do pipeline. should_reject=True quando n_tiles_changed < threshold.

    Compara o 1º e o último frame da janela (before/after, igual à validação Camp 41)
    dentro do pile_zone_polygon. Qualquer falha → should_reject=False (fail-open).
    """
    if config.STRUCTURAL_FILTER_MODE == "off":
        return StructFilterResult(should_reject=False, reason="skipped_disabled")
    if device_id not in config.STRUCTURAL_DEVICES:
        return StructFilterResult(should_reject=False, reason="skipped_not_targeted")

    res = score_window(sequence_paths, pile_zone_polygon)
    if res.reason != "scored":
        return res  # skip/erro — fail-open, preserva o reason exato para o ledger
    thr = int(config.STRUCTURAL_NTILES_THR)
    res.should_reject = res.n_tiles_changed < thr
    res.threshold = thr
    res.reason = "rejected" if res.should_reject else "passed"
    return res


def record_recovery_decision(
    *,
    request_id: str,
    device_id: str,
    n_tiles_changed: int,
    threshold: int,
    recovered: bool,
    mode: str,
    reason: str,
    models_dir: Optional[str] = None,
) -> None:
    """Append durável de uma decisão de RECUPERAÇÃO (gate-rejeitado → structural).

    Sobrevive a recreate do container (o stdout não) — base para medir a taxa real de
    recuperação vs. custo de Agent-2 antes de sair do shadow. Fail-safe (nunca levanta).
    """
    try:
        d = models_dir or config.STRUCTURAL_LEDGER_DIR
        Path(d).mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "device_id": device_id,
            "mode": mode,
            "n_tiles_changed": int(n_tiles_changed),
            "threshold": int(threshold),
            "recovered": bool(recovered),
            "reason": reason,
        }
        with open(Path(d) / RECOVERY_LEDGER_NAME, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("structural: failed to record recovery decision: %s", exc)
