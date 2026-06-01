"""DINOv2 post-detail false-positive filter (rejection-only).

Validado offline (Camp 26 + Camp 27) em cam_10 Imbiribeira: a pile-zone é
linearmente separável por embedding DINOv2 (RepeatedSKF 95,6%±2,1%, AUC 0,945).
⚠️ Camp 27 expôs DRIFT temporal — modelo estático decai forward. Por isso este
filtro nasce em modo SHADOW (loga, não altera decisão) e exige retreino periódico.

Posição no pipeline: roda DEPOIS do Agent-2 (detail), só quando `disposal=True`.
É ORTOGONAL ao BGSUB (que é supressão pré-Agent-1). Nunca transforma negativo em
positivo — só pode REJEITAR um CON do pipeline.

Mecânica:
1. Recorta a pile_zone (bbox = min/max dos vértices do `pile_zone_polygon`, idêntico
   ao treino em extract_embeddings_cam10.py) dos últimos N frames.
2. DINOv2 ViT-S/14 (CLS token 384-d), média dos N frames.
3. Inferência NUMPY-pura (sem sklearn): p_con = sigmoid((feat-mean)/scale · coef + b).
4. should_reject = p_con < threshold.

Artefato por device: `{DINOV2_MODELS_DIR}/dinov2_clf_{device_id}.npz`
(scaler_mean, scaler_scale, coef, intercept, threshold, bbox, ...).

Todo caminho de falha retorna should_reject=False (FAIL-OPEN): um modelo quebrado,
torch ausente ou crop inválido NUNCA descarta um descarte real.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

from . import config

logger = logging.getLogger(__name__)

# ImageNet normalization (igual ao treino).
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


@dataclass
class DinoFilterResult:
    """Outcome of the DINOv2 post-detail filter."""

    should_reject: bool          # True = (enforce) override disposal=False / (shadow) would-reject
    reason: str                  # rejected | passed | skipped_disabled | skipped_not_targeted
                                 # | skipped_no_polygon | skipped_no_model | skipped_no_crops | error
    p_con: float = -1.0          # P(CONFIRMADO); -1 = não computado
    threshold: float = -1.0
    n_frames_used: int = 0
    latency_ms: float = 0.0


class _Classifier:
    """Numpy-only LogReg+scaler carregado do artefato .npz."""

    __slots__ = ("scaler_mean", "scaler_scale", "coef", "intercept",
                 "threshold", "bbox")

    def __init__(self, npz: Any) -> None:
        self.scaler_mean = npz["scaler_mean"].astype(np.float64)
        self.scaler_scale = npz["scaler_scale"].astype(np.float64)
        self.coef = npz["coef"].astype(np.float64)
        self.intercept = float(npz["intercept"])
        self.threshold = float(npz["threshold"])
        bbox = npz["bbox"].tolist() if "bbox" in npz.files else []
        self.bbox = tuple(int(v) for v in bbox) if len(bbox) == 4 else None

    def p_con(self, feat: np.ndarray) -> float:
        z = (feat.astype(np.float64) - self.scaler_mean) / self.scaler_scale
        logit = float(z @ self.coef + self.intercept)
        return 1.0 / (1.0 + np.exp(-logit))


class _DinoCache:
    """Lazy cache do modelo DINOv2 (1 instância global) + classificadores por device."""

    def __init__(self) -> None:
        self._model: Any = None
        self._model_failed = False
        self._clf: dict[str, Optional[_Classifier]] = {}

    def get_model(self) -> Any:
        """Carrega DINOv2 ViT-S/14 uma vez. None se falhar (fail-open)."""
        if self._model is not None:
            return self._model
        if self._model_failed:
            return None
        try:
            import torch  # lazy
            torch.set_num_threads(int(config.DINOV2_TORCH_THREADS))
            t0 = time.time()
            model = torch.hub.load("facebookresearch/dinov2",
                                   config.DINOV2_VARIANT, verbose=False)
            model.eval()
            self._model = model
            logger.info("dinov2: model loaded (%s) in %.1fs",
                        config.DINOV2_VARIANT, time.time() - t0)
            return self._model
        except Exception as exc:  # noqa: BLE001
            self._model_failed = True
            logger.warning("dinov2: failed to load model (%s): %s — filter inert",
                           config.DINOV2_VARIANT, exc)
            return None

    def get_classifier(self, device_id: str) -> Optional[_Classifier]:
        if device_id in self._clf:
            return self._clf[device_id]
        path = Path(config.DINOV2_MODELS_DIR) / f"dinov2_clf_{device_id}.npz"
        if not path.exists():
            logger.info("dinov2: no classifier artifact for %s at %s", device_id, path)
            self._clf[device_id] = None
            return None
        try:
            npz = np.load(str(path), allow_pickle=True)
            clf = _Classifier(npz)
            self._clf[device_id] = clf
            logger.info("dinov2: classifier loaded for %s (thr=%.2f, bbox=%s)",
                        device_id, clf.threshold, clf.bbox)
            return clf
        except Exception as exc:  # noqa: BLE001
            logger.warning("dinov2: failed to load classifier %s: %s", path, exc)
            self._clf[device_id] = None
            return None

    def invalidate(self, device_id: Optional[str] = None) -> None:
        if device_id is None:
            self._clf.clear()
        else:
            self._clf.pop(device_id, None)


_cache = _DinoCache()


def invalidate_cache(device_id: Optional[str] = None) -> None:
    _cache.invalidate(device_id)


def _bbox_from_polygon(polygon: Any) -> Optional[tuple[int, int, int, int]]:
    """(x0,y0,x1,y1) = min/max dos vértices — idêntico ao treino."""
    try:
        import json
        polys = polygon
        if isinstance(polys, str):
            polys = json.loads(polys)
        pts = [pt for poly in polys for pt in poly]
        xs = [int(p[0]) for p in pts]
        ys = [int(p[1]) for p in pts]
        if not xs or not ys:
            return None
        return min(xs), min(ys), max(xs), max(ys)
    except Exception:  # noqa: BLE001
        return None


def _make_crop_tensor(frame_paths: list[Path], bbox: tuple[int, int, int, int],
                      input_size: int) -> Optional[np.ndarray]:
    """Recorta+normaliza os frames -> array (N,C,H,W) float32. None se nada resolvível."""
    import cv2
    x0, y0, x1, y1 = bbox
    crops = []
    for fp in frame_paths:
        img = cv2.imread(str(fp))
        if img is None:
            continue
        h, w = img.shape[:2]
        cx0 = max(0, min(x0, w - 1)); cy0 = max(0, min(y0, h - 1))
        cx1 = max(cx0 + 1, min(x1, w)); cy1 = max(cy0 + 1, min(y1, h))
        crop = img[cy0:cy1, cx0:cx1]
        if crop.size == 0:
            continue
        crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        crop = cv2.resize(crop, (input_size, input_size), interpolation=cv2.INTER_AREA)
        arr = crop.astype(np.float32) / 255.0
        arr = (arr - _MEAN) / _STD
        crops.append(arr)
    if not crops:
        return None
    return np.stack(crops).transpose(0, 3, 1, 2)


def evaluate(
    sequence_paths: list[Path],
    device_id: str,
    pile_zone_polygon: Any,
    camera: Any = None,  # noqa: ARG001 — simetria de API com bgsub_filter
) -> DinoFilterResult:
    """Re-julga um CON do pipeline. should_reject=True quando p_con < threshold.

    Args:
        sequence_paths: frames da janela em ordem cronológica.
        device_id: e.g. "esp32_001"; localiza o artefato do classificador.
        pile_zone_polygon: JSONB de `cameras.pile_zone_polygon` (lista de polígonos).

    Returns DinoFilterResult. Qualquer falha → should_reject=False (fail-open).
    """
    if config.DINOV2_FILTER_MODE == "off":
        return DinoFilterResult(should_reject=False, reason="skipped_disabled")
    if device_id not in config.DINOV2_FILTER_DEVICES:
        return DinoFilterResult(should_reject=False, reason="skipped_not_targeted")
    if not sequence_paths:
        return DinoFilterResult(should_reject=False, reason="skipped_disabled")
    if not pile_zone_polygon:
        return DinoFilterResult(should_reject=False, reason="skipped_no_polygon")

    clf = _cache.get_classifier(device_id)
    if clf is None:
        return DinoFilterResult(should_reject=False, reason="skipped_no_model")

    t0 = time.time()
    try:
        bbox = _bbox_from_polygon(pile_zone_polygon) or clf.bbox
        if bbox is None:
            return DinoFilterResult(should_reject=False, reason="skipped_no_polygon")

        n = int(config.DINOV2_N_FRAMES)
        sel = sequence_paths[-n:] if len(sequence_paths) >= n else sequence_paths
        batch = _make_crop_tensor(sel, bbox, int(config.DINOV2_INPUT_SIZE))
        if batch is None:
            return DinoFilterResult(should_reject=False, reason="skipped_no_crops")

        model = _cache.get_model()
        if model is None:
            return DinoFilterResult(should_reject=False, reason="error")

        import torch
        with torch.no_grad():
            emb = model(torch.from_numpy(batch).float()).cpu().numpy()
        feat = emb.mean(axis=0)  # (384,)

        thr = (config.DINOV2_THRESHOLD
               if config.DINOV2_THRESHOLD is not None else clf.threshold)
        p_con = clf.p_con(feat)
        return DinoFilterResult(
            should_reject=bool(p_con < thr),
            reason="rejected" if p_con < thr else "passed",
            p_con=float(p_con),
            threshold=float(thr),
            n_frames_used=int(batch.shape[0]),
            latency_ms=(time.time() - t0) * 1000.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("dinov2: evaluate failed for %s: %s", device_id, exc, exc_info=True)
        return DinoFilterResult(should_reject=False, reason="error",
                                latency_ms=(time.time() - t0) * 1000.0)
