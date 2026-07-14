import React, { useEffect, useState } from "react";
import { ImageOff, RefreshCw, Radio, X } from "lucide-react";
import type { Camera as CameraEntity, CameraLatestImage } from "../services/cameraService";
import type { LiveState } from "../hooks/useLiveSession";
import {
  formatDateTimeBrazil,
  formatRelativeSeconds,
  parseSairaDate,
} from "../utils/datetime";

interface CameraImageLightboxProps {
  camera: CameraEntity;
  latestImage: CameraLatestImage | null;
  isRefreshing: boolean;
  onRefresh: () => void;
  onClose: () => void;
  /** Modo ao vivo — só câmeras tipadas como 'pi'. */
  canLive?: boolean;
  liveState?: LiveState;
  /** Segundos até o teto duro da sessão. */
  liveRemainingS?: number;
  onLiveStart?: () => void;
  onLiveStop?: () => void;
}

const formatMmSs = (totalSeconds: number): string => {
  const s = Math.max(0, totalSeconds);
  const mm = Math.floor(s / 60);
  const ss = s % 60;
  return `${mm}:${String(ss).padStart(2, "0")}`;
};

export const CameraImageLightbox: React.FC<CameraImageLightboxProps> = ({
  camera,
  latestImage,
  isRefreshing,
  onRefresh,
  onClose,
  canLive = false,
  liveState = "idle",
  liveRemainingS = 0,
  onLiveStart,
  onLiveStop,
}) => {
  // Anti-flicker: pré-carrega a URL nova fora da tela e só troca o src quando
  // ela decodificar — o frame anterior fica visível até lá (e sobrevive a 404).
  const [displayedUrl, setDisplayedUrl] = useState<string | null>(
    latestImage?.image_url || null,
  );
  const [imageError, setImageError] = useState(false);
  const [now, setNow] = useState<Date>(new Date());

  const latestUrl = latestImage?.image_url || null;

  useEffect(() => {
    if (!latestUrl) return;
    let cancelled = false;
    const preload = new Image();
    preload.onload = () => {
      if (cancelled) return;
      setDisplayedUrl(latestUrl);
      setImageError(false);
    };
    preload.onerror = () => {
      if (cancelled) return;
      setImageError(true);
    };
    preload.src = latestUrl;
    return () => {
      cancelled = true;
    };
  }, [latestUrl]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    const tick = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(tick);
  }, []);

  const capturedAt = latestImage?.captured_at || null;
  const capturedDate = capturedAt ? parseSairaDate(capturedAt) : null;
  const capturedLabel =
    capturedDate && !Number.isNaN(capturedDate.getTime())
      ? formatDateTimeBrazil(capturedAt, { dateStyle: "short", timeStyle: "medium" })
      : null;
  const relativeLabel =
    capturedDate && !Number.isNaN(capturedDate.getTime())
      ? formatRelativeSeconds(
          Math.max(0, Math.floor((now.getTime() - capturedDate.getTime()) / 1000)),
        )
      : null;

  // "prompting" ainda é sessão viva (o diálogo de inatividade está por cima),
  // então o botão segue mostrando AO VIVO com o countdown.
  const liveIsOn = liveState === "live" || liveState === "prompting";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Imagem em tela cheia da câmera ${camera.name}`}
      className="fixed inset-0 z-[70] bg-black flex items-center justify-center select-none"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      {displayedUrl ? (
        // w/h-full + object-contain faz UPSCALE dos frames pequenos das esp32
        // até preencher a tela (letterbox), que é o pedido do operador.
        <img
          src={displayedUrl}
          alt={`Imagem ao vivo da câmera ${camera.name}`}
          className="w-full h-full object-contain"
        />
      ) : (
        <div className="flex flex-col items-center justify-center text-gray-400 gap-3">
          <ImageOff size={40} />
          <span className="text-sm font-medium">
            {imageError
              ? "Não foi possível carregar a imagem"
              : "Sem foto disponível"}
          </span>
        </div>
      )}

      <div className="absolute inset-x-0 top-0 flex items-start justify-between gap-4 px-4 pt-3 pb-8 bg-gradient-to-b from-black/70 to-transparent pointer-events-none">
        <div className="min-w-0 text-white pointer-events-auto">
          <h2 className="text-base font-bold truncate">{camera.name}</h2>
          {camera.device_id ? (
            <p className="text-xs text-white/70 truncate font-mono">
              {camera.device_id}
            </p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Fechar"
          className="shrink-0 h-11 w-11 rounded-full bg-black/60 hover:bg-black/80 text-white flex items-center justify-center transition-colors pointer-events-auto"
        >
          <X size={22} />
        </button>
      </div>

      <div className="absolute inset-x-0 bottom-0 flex flex-wrap items-center justify-between gap-3 px-4 pb-4 pt-8 bg-gradient-to-t from-black/70 to-transparent pointer-events-none">
        <div className="min-w-0 text-xs text-white/80 pointer-events-auto">
          {capturedLabel ? (
            <>
              Capturada em {capturedLabel}
              {relativeLabel ? (
                <span className="text-white/60"> · atualizado {relativeLabel}</span>
              ) : null}
            </>
          ) : (
            "Sem captura registrada"
          )}
        </div>
        <div className="shrink-0 flex items-center gap-2 pointer-events-auto">
          {canLive ? (
            liveIsOn ? (
              <button
                type="button"
                onClick={onLiveStop}
                title="Encerrar o modo ao vivo (economiza dados móveis da câmera)"
                className="inline-flex items-center gap-2 px-3 py-2 rounded-full bg-red-500/90 hover:bg-red-500 text-white text-xs font-semibold transition-colors"
              >
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-white" />
                </span>
                AO VIVO
                <span className="tabular-nums text-white/80">
                  {formatMmSs(liveRemainingS)}
                </span>
              </button>
            ) : (
              <button
                type="button"
                onClick={onLiveStart}
                disabled={liveState === "starting"}
                title="Ver ao vivo (~1 fps). Consome dados móveis da câmera; encerra sozinho."
                className="inline-flex items-center gap-2 px-3 py-2 rounded-full bg-white/10 hover:bg-white/20 text-white text-xs font-semibold transition-colors disabled:opacity-60"
              >
                <Radio size={14} className={liveState === "starting" ? "animate-pulse" : ""} />
                {liveState === "starting" ? "Iniciando..." : "Ao vivo"}
              </button>
            )
          ) : null}
          <button
            type="button"
            onClick={onRefresh}
            disabled={isRefreshing || liveIsOn}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-full bg-white/10 hover:bg-white/20 text-white text-xs font-semibold transition-colors disabled:opacity-60"
          >
            <RefreshCw size={14} className={isRefreshing ? "animate-spin" : ""} />
            {isRefreshing ? "Atualizando..." : "Atualizar agora"}
          </button>
        </div>
      </div>
    </div>
  );
};
