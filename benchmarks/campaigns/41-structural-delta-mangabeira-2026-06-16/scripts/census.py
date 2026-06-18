#!/usr/bin/env python3
"""Census Transform + Hamming distance — illumination-invariant structural delta.

Numpy-only implementation taken from the research snippet
(pesquisas/aod-persistent-pile-outdoor.md, lines 117-137). The Census transform
maps each pixel's 3x3 neighbourhood to an 8-bit string based ONLY on the relative
ordering of intensities, so it is invariant to monotonic brightness shifts
(shadows, sun, IR cut-filter). The per-pixel Hamming distance between the
before/after census maps measures structural change regardless of absolute
luminance — exactly the property our MOG2 pile-zone filter lacked (Camp 40).
"""
from __future__ import annotations

import numpy as np


def census_transform(img: np.ndarray) -> np.ndarray:
    """3x3 census transform of a grayscale image. Returns uint8 map (h-2, w-2)."""
    h, w = img.shape
    census = np.zeros((h - 2, w - 2), dtype=np.uint8)
    center = img[1:h - 1, 1:w - 1]
    offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    for i, (dy, dx) in enumerate(offsets):
        neighbor = img[1 + dy:h - 1 + dy, 1 + dx:w - 1 + dx]
        bit = (neighbor > center).astype(np.uint8)
        census |= (bit << i)
    return census


def hamming_map(pre: np.ndarray, post: np.ndarray) -> np.ndarray:
    """Per-pixel Hamming distance (0..8) between two census maps of equal shape."""
    xor = np.bitwise_xor(pre, post)
    return np.unpackbits(xor[..., np.newaxis], axis=-1).sum(axis=-1).astype(np.uint8)


def census_hamming(gray_pre: np.ndarray, gray_post: np.ndarray) -> np.ndarray:
    """Convenience: census both frames, return Hamming map padded back to input size.

    The census transform shrinks the image by a 1px border on each side; we pad the
    Hamming map back to the original (h, w) with zeros so it aligns with full-frame
    masks. gray_pre / gray_post must be uint8 grayscale, identical shape.
    """
    cp = census_transform(gray_pre)
    cq = census_transform(gray_post)
    h = hamming_map(cp, cq)
    out = np.zeros(gray_pre.shape, dtype=np.uint8)
    out[1:-1, 1:-1] = h
    return out
