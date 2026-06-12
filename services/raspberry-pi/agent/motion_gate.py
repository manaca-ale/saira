"""Motion gate BGSUB (MOG2 streaming) para o agente SAIRA na Raspberry Pi.

Simplificação em streaming do filtro batch do worker
(services/yolo-worker-vm/src/worker/bgsub_filter.py), reaproveitando os
parâmetros validados (history=80, varThreshold=40, sombras binarizadas em
>100, zona via pile_zone_polygon com referência 1280×720).

Diferenças deliberadas em relação ao worker:
  - Não há baseline .npz: a baseline é refeita A CADA BOOT via warm-up
    (WARMUP_SECONDS alimentando o MOG2 com learningRate automático).
  - Decisão por frame (máquina de estados), não por janela com votação.
  - Dois sinais distintos:
      fg_px    — foreground MOG2 dentro da zona (objeto novo vs baseline);
                 dispara o INÍCIO do evento.
      delta_px — absdiff frame-a-frame dentro da zona (movimento em curso);
                 decide o FIM do evento (uma pilha recém-depositada continua
                 como foreground, mas para de "se mexer").
  - Estado RECOVER pós-evento: absorve o depósito com LR alto e só rearma o
    gate quando a zona volta a bater com a baseline (histerese), evitando
    reabrir evento em cima de pilha estática.

Processa o frame decodificado em resolução reduzida (IMREAD_REDUCED_COLOR_2:
720p → 360p) — ~¼ do custo de CPU, essencial no Pi 3. Os thresholds de pixel
do Config já são expressos nessa escala reduzida.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger("saira-agent.motion")

# Referência em que os polígonos foram desenhados (mesma do worker).
POLYGON_REF_W = 1280
POLYGON_REF_H = 720

# Limiar de intensidade do absdiff para contar um pixel como "mudou".
_DELTA_INTENSITY_THRESHOLD = 25


@dataclass
class GateDecision:
    """Resultado da análise de um frame."""

    state: str  # warmup | idle | event | recover
    fg_px: int
    delta_px: int
    event_id: Optional[str]  # evento corrente (se houver)
    action: Optional[str]  # start | active | end | None
    is_warmup: bool = False


class MotionGate:
    """Máquina de estados de movimento alimentada frame a frame.

    Não é thread-safe: deve ser usada apenas pela thread de captura.
    """

    def __init__(
        self,
        *,
        history: int = 80,
        var_threshold: float = 40.0,
        shadow_threshold: int = 100,
        min_px_active: int = 200,
        delta_min_px: int = 100,
        consec_start: int = 2,
        lr_idle: float = 0.005,
        lr_recover: float = 0.05,
        warmup_seconds: int = 90,
        event_end_quiet_s: int = 10,
        event_max_s: int = 120,
        recover_max_s: int = 180,
        polygon_json: str = "",
        device_id: str = "pi-cam",
    ) -> None:
        self._history = history
        self._var_threshold = var_threshold
        self._shadow_threshold = shadow_threshold
        self.min_px_active = min_px_active
        self.delta_min_px = delta_min_px
        self.consec_start = consec_start
        self.lr_idle = lr_idle
        self.lr_recover = lr_recover
        self.warmup_seconds = warmup_seconds
        self.event_end_quiet_s = event_end_quiet_s
        self.event_max_s = event_max_s
        self.recover_max_s = recover_max_s
        self._device_id = device_id

        self._polygon_json = polygon_json
        self._mask: Optional[np.ndarray] = None  # cache por shape
        self._mask_shape: Optional[tuple[int, int]] = None

        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        self._prev_gray: Optional[np.ndarray] = None

        # Estado da máquina
        self.state = "warmup"
        self._warmup_until = 0.0
        self._warmup_event_id: Optional[str] = None
        self._consec_active = 0
        self._event_id: Optional[str] = None
        self._event_started_at = 0.0
        self._quiet_since: Optional[float] = None
        self._recover_since = 0.0
        self._recover_clear_frames = 0

        self._reset_mog2()

    # ----- setup / config -------------------------------------------------
    def _reset_mog2(self) -> None:
        self._mog2 = cv2.createBackgroundSubtractorMOG2(
            history=self._history,
            varThreshold=self._var_threshold,
            detectShadows=True,
        )
        self._prev_gray = None

    def begin_warmup(self, *, silent: bool = False, now: Optional[float] = None) -> None:
        """(Re)inicia o warm-up — chamado no boot e em re-anchor.

        silent=True não gera evento sintético (re-anchor não deve custar
        uma janela Gemini; o warm-up de boot sim, por fail-open).
        """
        now = now if now is not None else time.time()
        self._reset_mog2()
        self.state = "warmup"
        self._warmup_until = now + self.warmup_seconds
        self._consec_active = 0
        self._event_id = None
        self._quiet_since = None
        if silent:
            self._warmup_event_id = None
        else:
            boot_ts = time.strftime("%Y%m%d_%H%M%S", time.localtime(now))
            self._warmup_event_id = f"evt-warmup-{boot_ts}"
        log.info(
            "Warm-up BGSUB iniciado (%ds, evento sintético=%s)",
            self.warmup_seconds,
            self._warmup_event_id or "nenhum",
        )

    def set_polygon(self, polygon_json: str) -> None:
        """Troca a zona em runtime (vinda do config remoto)."""
        polygon_json = (polygon_json or "").strip()
        if polygon_json == self._polygon_json:
            return
        self._polygon_json = polygon_json
        self._mask = None
        self._mask_shape = None
        log.info("Polígono da zona atualizado (%d chars)", len(polygon_json))

    def _zone_mask(self, shape: tuple[int, int]) -> np.ndarray:
        """Máscara binária da zona no shape analisado (cache por shape)."""
        if self._mask is not None and self._mask_shape == shape:
            return self._mask
        h, w = shape
        mask = np.zeros((h, w), dtype=np.uint8)
        polygons = []
        if self._polygon_json:
            try:
                raw = json.loads(self._polygon_json)
                # Aceita [[x,y],...] (um polígono) ou [[[x,y],...],...] (vários)
                if raw and isinstance(raw[0][0], (int, float)):
                    raw = [raw]
                sx = w / float(POLYGON_REF_W)
                sy = h / float(POLYGON_REF_H)
                for poly in raw:
                    pts = np.array(
                        [[int(round(x * sx)), int(round(y * sy))] for x, y in poly],
                        dtype=np.int32,
                    )
                    if len(pts) >= 3:
                        polygons.append(pts)
            except (ValueError, TypeError, IndexError) as exc:
                log.warning("pile_zone_polygon inválido (%s) — usando frame inteiro", exc)
        if polygons:
            cv2.fillPoly(mask, polygons, 255)
        else:
            mask[:] = 255
        self._mask = mask
        self._mask_shape = shape
        return mask

    # ----- análise por frame ----------------------------------------------
    def _learning_rate(self) -> float:
        if self.state == "warmup":
            return -1.0  # automático: converge rápido na baseline do boot
        if self.state == "event":
            return 0.0  # nunca absorver um depósito enquanto é julgado
        if self.state == "recover":
            return self.lr_recover
        return self.lr_idle

    def _measure(self, img: np.ndarray) -> tuple[int, int]:
        """Aplica MOG2 + absdiff e retorna (fg_px, delta_px) dentro da zona."""
        mask = self._zone_mask(img.shape[:2])

        fg = self._mog2.apply(img, learningRate=self._learning_rate())
        # Sombras vêm como 127; binariza acima do shadow_threshold (=100 mantém
        # o comportamento detectShadows do worker: sombra não conta).
        _, fg_bin = cv2.threshold(fg, self._shadow_threshold, 255, cv2.THRESH_BINARY)
        fg_bin = cv2.morphologyEx(fg_bin, cv2.MORPH_OPEN, self._kernel)
        fg_bin = cv2.morphologyEx(fg_bin, cv2.MORPH_CLOSE, self._kernel)
        fg_px = int(np.count_nonzero(cv2.bitwise_and(fg_bin, mask)))

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        delta_px = 0
        if self._prev_gray is not None and self._prev_gray.shape == gray.shape:
            diff = cv2.absdiff(gray, self._prev_gray)
            _, diff_bin = cv2.threshold(
                diff, _DELTA_INTENSITY_THRESHOLD, 255, cv2.THRESH_BINARY
            )
            diff_bin = cv2.morphologyEx(diff_bin, cv2.MORPH_OPEN, self._kernel)
            delta_px = int(np.count_nonzero(cv2.bitwise_and(diff_bin, mask)))
        self._prev_gray = gray
        return fg_px, delta_px

    def _new_event_id(self, now: float) -> str:
        return "evt-" + time.strftime("%Y%m%d_%H%M%S", time.localtime(now))

    def process(self, jpeg_bytes: bytes) -> GateDecision:
        """Analisa um frame JPEG e avança a máquina de estados."""
        now = time.time()
        if self._warmup_until == 0.0:
            self.begin_warmup(now=now)

        buf = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_REDUCED_COLOR_2)
        if img is None:
            log.warning("Frame JPEG inválido — ignorado pelo gate")
            return GateDecision(
                state=self.state, fg_px=0, delta_px=0,
                event_id=self._event_id or self._warmup_event_id,
                action=None, is_warmup=self.state == "warmup",
            )

        fg_px, delta_px = self._measure(img)
        fg_active = fg_px >= self.min_px_active
        moving = delta_px >= self.delta_min_px

        # ---- warm-up -----------------------------------------------------
        if self.state == "warmup":
            if now < self._warmup_until:
                action = None
                if self._warmup_event_id is not None:
                    action = "start" if self._consec_active == 0 else "active"
                    self._consec_active += 1  # reutilizado como "frames no warm-up"
                return GateDecision(
                    state="warmup", fg_px=fg_px, delta_px=delta_px,
                    event_id=self._warmup_event_id, action=action, is_warmup=True,
                )
            # warm-up terminou
            ended_id = self._warmup_event_id
            self._warmup_event_id = None
            self._consec_active = 0
            self.state = "idle"
            log.info("Warm-up concluído — gate armado (fg_px=%d)", fg_px)
            if ended_id is not None:
                return GateDecision(
                    state="idle", fg_px=fg_px, delta_px=delta_px,
                    event_id=ended_id, action="end", is_warmup=True,
                )
            return GateDecision(
                state="idle", fg_px=fg_px, delta_px=delta_px,
                event_id=None, action=None,
            )

        # ---- idle: aguardando início de evento ----------------------------
        if self.state == "idle":
            if fg_active:
                self._consec_active += 1
                if self._consec_active >= self.consec_start:
                    self.state = "event"
                    self._event_id = self._new_event_id(now)
                    self._event_started_at = now
                    self._quiet_since = None
                    log.info(
                        "Evento %s iniciado (fg_px=%d, delta_px=%d)",
                        self._event_id, fg_px, delta_px,
                    )
                    return GateDecision(
                        state="event", fg_px=fg_px, delta_px=delta_px,
                        event_id=self._event_id, action="start",
                    )
            else:
                self._consec_active = 0
            return GateDecision(
                state="idle", fg_px=fg_px, delta_px=delta_px,
                event_id=None, action=None,
            )

        # ---- event: em andamento ------------------------------------------
        if self.state == "event":
            assert self._event_id is not None
            elapsed = now - self._event_started_at

            # Fim de evento é decidido por MOVIMENTO (delta), não por foreground:
            # uma pilha recém-depositada continua FG mas para de se mexer.
            if moving:
                self._quiet_since = None
            elif self._quiet_since is None:
                self._quiet_since = now

            quiet_for = (now - self._quiet_since) if self._quiet_since else 0.0
            should_end = quiet_for >= self.event_end_quiet_s or elapsed >= self.event_max_s

            if not should_end:
                return GateDecision(
                    state="event", fg_px=fg_px, delta_px=delta_px,
                    event_id=self._event_id, action="active",
                )

            ended_id = self._event_id
            reason = "max_duration" if elapsed >= self.event_max_s else "quiet"
            self._event_id = None
            self._consec_active = 0
            self.state = "recover"
            self._recover_since = now
            self._recover_clear_frames = 0
            log.info(
                "Evento %s encerrado (%s, %.0fs, fg_px=%d)",
                ended_id, reason, elapsed, fg_px,
            )
            return GateDecision(
                state="recover", fg_px=fg_px, delta_px=delta_px,
                event_id=ended_id, action="end",
            )

        # ---- recover: absorvendo o depósito / rearmando --------------------
        if not fg_active:
            self._recover_clear_frames += 1
            if self._recover_clear_frames >= 3:
                self.state = "idle"
                self._consec_active = 0
                log.info("Zona limpa/absorvida — gate rearmado")
        else:
            self._recover_clear_frames = 0
            if now - self._recover_since >= self.recover_max_s:
                # Não convergiu (mudança de iluminação, câmera mexida):
                # re-anchor silencioso — refaz a baseline sem custo Gemini.
                log.warning(
                    "Recover não convergiu em %ds — re-anchor (warm-up silencioso)",
                    self.recover_max_s,
                )
                self.begin_warmup(silent=True, now=now)
        return GateDecision(
            state=self.state, fg_px=fg_px, delta_px=delta_px,
            event_id=None, action=None,
        )
