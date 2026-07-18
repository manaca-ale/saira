"""Hot-reload do baseline npz por mtime (Camp 39).

Uma recalibração externa reescreve o npz; o próximo get_models() deve detectar
o mtime novo e reconstruir o MOG2 sem restart do worker. O checkpoint do próprio
adaptive NÃO deve disparar rebuild (stamp atualizado após persist).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np

from worker import bgsub_filter, config


def _write_npz(path: Path, n: int = 12, seed: int = 0) -> None:
    rng = np.random.default_rng(seed)
    frames = rng.integers(0, 255, size=(n, 72, 128, 3), dtype=np.uint8)
    np.savez_compressed(str(path), frames=frames)


def test_hot_reload_on_external_recalibration(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BGSUB_MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "BGSUB_DUAL_RATE_ENABLED", False)
    dev = "esp32_test_hr"
    npz = tmp_path / f"{dev}.npz"
    _write_npz(npz, seed=1)
    bgsub_filter.invalidate_cache(dev)

    cfg = bgsub_filter._resolved_config(None)
    m1 = bgsub_filter._cache.get_models(dev, cfg)
    assert m1 is not None
    # cache hit sem mudança no disco → mesmo objeto
    assert bgsub_filter._cache.get_models(dev, cfg) is m1

    # "recalibração externa": reescreve o npz com mtime mais novo
    _write_npz(npz, seed=2)
    new_mtime = time.time() + 10
    os.utime(npz, (new_mtime, new_mtime))

    m2 = bgsub_filter._cache.get_models(dev, cfg)
    assert m2 is not None
    assert m2 is not m1  # reconstruído sem restart

    bgsub_filter.invalidate_cache(dev)


def test_adaptive_checkpoint_does_not_self_rebuild(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BGSUB_MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "BGSUB_DUAL_RATE_ENABLED", False)
    monkeypatch.setattr(config, "BGSUB_ADAPTIVE_ENABLED", True)
    monkeypatch.setattr(config, "BGSUB_ADAPTIVE_MIN_CONFIDENCE", 0)
    monkeypatch.setattr(config, "BGSUB_ADAPTIVE_SAVE_EVERY_N", 1)  # persiste já no 1º update
    dev = "esp32_test_ckpt"
    npz = tmp_path / f"{dev}.npz"
    _write_npz(npz, seed=3)
    bgsub_filter.invalidate_cache(dev)

    cfg = bgsub_filter._resolved_config(None)
    m1 = bgsub_filter._cache.get_models(dev, cfg)
    assert m1 is not None

    # update adaptativo que CHECKPOINTA o npz (frame via arquivo temporário)
    import cv2
    fdir = tmp_path / "frames"
    fdir.mkdir()
    fp = fdir / "f1.jpg"
    cv2.imwrite(str(fp), np.zeros((72, 128, 3), dtype=np.uint8))
    res = bgsub_filter.update_baseline_with_frames(
        device_id=dev, frame_paths=[fp], gate_confidence=50,
    )
    assert res.applied is True

    # o checkpoint mudou o npz, mas o stamp foi atualizado → cache hit (sem rebuild)
    assert bgsub_filter._cache.get_models(dev, cfg) is m1

    bgsub_filter.invalidate_cache(dev)


def test_mask_rebuilds_on_polygon_change():
    """Editar o polígono (ex.: pelo painel da câmera) muda a assinatura → get_mask
    reconstrói máscara e bbox sem invalidate()/restart. A máscara é geométrica
    (independe do modelo MOG2), então o rebuild ao vivo é seguro."""
    dev = "esp32_test_polysig"
    bgsub_filter.invalidate_cache(dev)
    cache = bgsub_filter._cache

    poly_a = [[[100, 100], [300, 100], [300, 300], [100, 300]]]
    m_a = cache.get_mask(dev, poly_a)
    assert m_a is not None
    bbox_a = cache.get_bbox(dev)
    # mesma assinatura → cache hit (mesmo objeto de máscara)
    assert cache.get_mask(dev, poly_a) is m_a

    # polígono novo → assinatura muda → reconstrói sem restart
    poly_b = [[[500, 400], [800, 400], [800, 650], [500, 650]]]
    m_b = cache.get_mask(dev, poly_b)
    assert m_b is not None
    assert m_b is not m_a
    assert cache.get_bbox(dev) != bbox_a  # bbox acompanhou o polígono novo

    bgsub_filter.invalidate_cache(dev)
