"""Cap da janela por ORÇAMENTO DE BYTES (fit_frames_to_payload).

Regressão de um bug de produção (14/07/2026): a pi-cam-001 ficou com ZERO
detecções porque `subsample_frames` capa por CONTAGEM (48) enquanto o Gemini
recusa por BYTES (8 MB). Frame de Pi ~240 KB × 48 = ~11,5 MB → detector_gemini
levantava RuntimeError e o evento inteiro se perdia. As ESP32 nunca sentiram
(frames ~30 KB), então o teto em contagem escondia uma dependência do
dispositivo.
"""
from pathlib import Path

from worker import event_windows


def _mkframes(tmp_path: Path, n: int, size: int) -> list[Path]:
    paths = []
    for i in range(n):
        p = tmp_path / f"f{i:03d}.jpg"
        p.write_bytes(b"\xff\xd8" + b"x" * (size - 2))
        paths.append(p)
    return paths


def test_fits_when_already_under_budget(tmp_path):
    paths = _mkframes(tmp_path, 10, 1000)  # 10 KB total
    assert event_windows.fit_frames_to_payload(paths, 8_000_000) == paths


def test_shrinks_until_it_fits(tmp_path):
    # Reproduz o caso real: 48 frames de ~240 KB = ~11,5 MB contra teto de 8 MB.
    paths = _mkframes(tmp_path, 48, 240_000)
    out = event_windows.fit_frames_to_payload(paths, 8_000_000)
    assert len(out) < 48
    assert sum(p.stat().st_size for p in out) <= 8_000_000


def test_preserves_first_and_last(tmp_path):
    """O gate compara primeiro vs último frame — encolher não pode perdê-los."""
    paths = _mkframes(tmp_path, 48, 240_000)
    out = event_windows.fit_frames_to_payload(paths, 8_000_000)
    assert out[0] == paths[0]
    assert out[-1] == paths[-1]


def test_keeps_chronological_order(tmp_path):
    paths = _mkframes(tmp_path, 48, 240_000)
    out = event_windows.fit_frames_to_payload(paths, 8_000_000)
    assert out == sorted(out, key=lambda p: p.name)


def test_single_oversized_frame_does_not_loop(tmp_path):
    """Um frame maior que o teto inteiro: devolve 1 e não trava o worker."""
    paths = _mkframes(tmp_path, 1, 9_000_000)
    out = event_windows.fit_frames_to_payload(paths, 8_000_000)
    assert out == paths  # nada a encolher; o detector decide falhar


def test_all_frames_oversized_terminates(tmp_path):
    paths = _mkframes(tmp_path, 5, 9_000_000)
    out = event_windows.fit_frames_to_payload(paths, 8_000_000)
    assert len(out) == 1  # converge para o mínimo em vez de girar para sempre


def test_disabled_budget_is_noop(tmp_path):
    paths = _mkframes(tmp_path, 5, 1000)
    assert event_windows.fit_frames_to_payload(paths, 0) == paths


def test_missing_frame_is_not_fatal(tmp_path):
    paths = _mkframes(tmp_path, 5, 240_000)
    paths.append(tmp_path / "sumiu.jpg")  # some entre a montagem e o envio
    out = event_windows.fit_frames_to_payload(paths, 8_000_000)
    assert out == paths  # devolve como está; o caller trata o arquivo ausente
