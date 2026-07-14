import { useCallback, useEffect, useRef, useState } from "react";
import {
  renewLiveSession,
  startLiveSession,
  stopLiveSession,
  type Camera,
} from "../services/cameraService";
import { usePresence } from "./usePresence";

export type LiveState = "idle" | "starting" | "live" | "prompting" | "stopping" | "error";

/** Sem interação do operador por este tempo → pergunta "ainda está aí?". */
export const AFK_TIMEOUT_MS = 120_000;
/** Diálogo sem resposta por este tempo → encerra (foi embora de verdade). */
const AFK_PROMPT_GRACE_MS = 30_000;

/**
 * Dona da sessão de modo ao vivo: start/renew/stop, countdown, AFK e Page
 * Visibility. Mantém a página fina e o lightbox puramente apresentacional.
 *
 * O motivo de existir são os guard-rails de 4G. O consumo só para de verdade
 * com três camadas independentes, e esta é a primeira:
 *   1. aqui  — aba oculta para na hora; inatividade pergunta e depois encerra;
 *   2. servidor — teto duro ancorado no start (renew → 409);
 *   3. dispositivo — lease curto que expira sozinho se tudo mais morrer.
 */
export function useLiveSession(camera: Camera | null) {
  const [state, setState] = useState<LiveState>("idle");
  const [remainingS, setRemainingS] = useState(0);
  /** Segundos até o encerramento automático enquanto o diálogo de AFK está aberto. */
  const [promptRemainingS, setPromptRemainingS] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const promptSinceRef = useRef(0);
  const hardDeadlineMsRef = useRef(0);
  const renewAfterMsRef = useRef(20_000);
  const lastRenewAtRef = useRef(0);
  const renewingRef = useRef(false);
  const cameraIdRef = useRef<number | null>(null);
  const stateRef = useRef<LiveState>("idle");
  stateRef.current = state;

  const isActive = state === "live" || state === "prompting";
  const { isIdle, isHidden, markActive } = usePresence(isActive, AFK_TIMEOUT_MS);

  const reset = useCallback(() => {
    hardDeadlineMsRef.current = 0;
    lastRenewAtRef.current = 0;
    promptSinceRef.current = 0;
    renewingRef.current = false;
    cameraIdRef.current = null;
    setRemainingS(0);
  }, []);

  /** Encerra a sessão. Best-effort: se o POST falhar, o lease do dispositivo o
   *  apaga sozinho de qualquer forma — nunca deixar a UI presa em "ao vivo". */
  const stop = useCallback(async () => {
    const id = cameraIdRef.current;
    if (id == null) {
      setState("idle");
      reset();
      return;
    }
    setState("stopping");
    try {
      await stopLiveSession(id);
    } catch (err) {
      console.warn("live/stop falhou (o lease do dispositivo expira sozinho):", err);
    }
    setState("idle");
    reset();
  }, [reset]);

  const start = useCallback(async () => {
    if (!camera) return;
    setError(null);
    setState("starting");
    try {
      const session = await startLiveSession(camera.id);
      cameraIdRef.current = camera.id;
      hardDeadlineMsRef.current = new Date(session.hard_deadline).getTime();
      // A cadência de renovação vem do servidor de propósito — ajustável por env
      // sem rebuild do frontend (que é build nginx multi-stage).
      renewAfterMsRef.current = Math.max(5, session.renew_after_s) * 1000;
      lastRenewAtRef.current = Date.now();
      markActive();
      setRemainingS(session.remaining_s);
      setState("live");
    } catch (err) {
      console.error("live/start falhou:", err);
      setError("Não foi possível iniciar o modo ao vivo.");
      setState("error");
      reset();
    }
  }, [camera, reset]);

  /** "Continuar" no diálogo de inatividade. */
  const confirmStillHere = useCallback(() => {
    markActive();
    promptSinceRef.current = 0;
    // Força renovação no próximo tick (o lease pode estar perto de vencer).
    lastRenewAtRef.current = 0;
    setState("live");
  }, [markActive]);

  // ----- aba oculta = ninguém olhando = 4G puro desperdício -------------------
  // PARA, não pausa. E ao voltar NÃO retoma sozinho: auto-retomar reabriria
  // exatamente o buraco que esta feature existe para fechar.
  useEffect(() => {
    if (isActive && isHidden) void stop();
  }, [isActive, isHidden, stop]);

  // ----- inatividade -> "ainda está aí?" -------------------------------------
  useEffect(() => {
    if (state !== "live" || !isIdle) return;
    promptSinceRef.current = Date.now();
    setPromptRemainingS(Math.ceil(AFK_PROMPT_GRACE_MS / 1000));
    setState("prompting");
  }, [state, isIdle]);

  // ----- tick de 1s: countdown + AFK + renovação ------------------------------
  // Só existe enquanto a sessão está viva (não é um timer permanente).
  useEffect(() => {
    if (!isActive) return;
    const id = window.setInterval(() => {
      const now = Date.now();
      const remaining = Math.max(0, Math.round((hardDeadlineMsRef.current - now) / 1000));
      setRemainingS(remaining);

      // Teto duro atingido: o servidor daria 409 no próximo renew de qualquer forma.
      if (remaining <= 0) {
        void stop();
        return;
      }

      if (stateRef.current === "prompting") {
        const graceLeft = AFK_PROMPT_GRACE_MS - (now - promptSinceRef.current);
        setPromptRemainingS(Math.max(0, Math.ceil(graceLeft / 1000)));
        if (graceLeft <= 0) void stop();
        return; // enquanto pergunta, NÃO renova — o lease do device escoa sozinho
      }

      if (now - lastRenewAtRef.current >= renewAfterMsRef.current && !renewingRef.current) {
        renewingRef.current = true;
        lastRenewAtRef.current = now;
        const id2 = cameraIdRef.current;
        if (id2 == null) return;
        void renewLiveSession(id2)
          .then((session) => {
            hardDeadlineMsRef.current = new Date(session.hard_deadline).getTime();
            renewAfterMsRef.current = Math.max(5, session.renew_after_s) * 1000;
          })
          .catch((err) => {
            // 409 = teto duro; 404 = sessão sumiu. Nos dois casos o servidor já
            // mandou o device parar — só alinhar a UI. Engolir e continuar
            // renovando seria o loop-que-nunca-morre que queremos evitar.
            console.warn("live/renew encerrou a sessão:", err);
            setState("idle");
            reset();
          })
          .finally(() => {
            renewingRef.current = false;
          });
      }
    }, 1000);
    return () => window.clearInterval(id);
  }, [isActive, stop, reset]);

  // ----- fechar lightbox / trocar de câmera / desmontar -----------------------
  // Fechar a ABA não é coberto de propósito: axios não completa no unload e o
  // sendBeacon não manda o header Authorization. O lease do dispositivo é o
  // backstop correto para esse caso — é exatamente para isso que ele existe.
  useEffect(() => {
    if (!camera && cameraIdRef.current != null) void stop();
  }, [camera, stop]);

  useEffect(() => {
    return () => {
      const id = cameraIdRef.current;
      if (id != null) void stopLiveSession(id).catch(() => undefined);
    };
  }, []);

  return {
    state,
    remainingS,
    promptRemainingS,
    error,
    isActive,
    start,
    stop,
    confirmStillHere,
  };
}
