import { useCallback, useEffect, useRef, useState } from "react";

const ACTIVITY_EVENTS = ["mousemove", "keydown", "touchstart", "click"] as const;

/**
 * Presença do operador: houve interação recente, e a aba está visível?
 *
 * Existe porque "o operador esqueceu a tela aberta" é indistinguível de "o
 * operador está usando a tela" do ponto de vista do código — só a interação
 * real diferencia os dois. Sem isto, qualquer polling que custe 4G do
 * dispositivo roda para sempre.
 *
 * `enabled` liga/desliga os listeners e o tick: quando não há nada em curso que
 * custe dados, nada é observado.
 */
export function usePresence(enabled: boolean, idleAfterMs: number) {
  const [isIdle, setIsIdle] = useState(false);
  const [isHidden, setIsHidden] = useState(
    () => typeof document !== "undefined" && document.hidden,
  );
  // Ref, não estado: `mousemove` dispara a ~60fps e um setState por evento
  // re-renderizaria a árvore inteira a cada frame.
  const lastActivityRef = useRef(Date.now());

  const markActive = useCallback(() => {
    lastActivityRef.current = Date.now();
    // Só re-renderiza ao SAIR do idle; com o mesmo valor o React aborta o render.
    setIsIdle((prev) => (prev ? false : prev));
  }, []);

  useEffect(() => {
    if (!enabled) {
      setIsIdle(false);
      return;
    }
    lastActivityRef.current = Date.now();
    setIsIdle(false);
    setIsHidden(document.hidden);

    for (const evt of ACTIVITY_EVENTS) {
      window.addEventListener(evt, markActive, { passive: true });
    }
    const onVisibility = () => setIsHidden(document.hidden);
    document.addEventListener("visibilitychange", onVisibility);
    const tick = window.setInterval(() => {
      setIsIdle(Date.now() - lastActivityRef.current >= idleAfterMs);
    }, 1000);

    return () => {
      for (const evt of ACTIVITY_EVENTS) {
        window.removeEventListener(evt, markActive);
      }
      document.removeEventListener("visibilitychange", onVisibility);
      window.clearInterval(tick);
    };
  }, [enabled, idleAfterMs, markActive]);

  return { isIdle, isHidden, markActive };
}
