/**
 * Feature flags resolvidas em build (Vite injeta VITE_* em import.meta.env).
 *
 * labelingEnabled — a tela de rotulagem (/rotulagem) é ferramenta INTERNA e
 * fica só em teste. O compose de teste passa VITE_ENABLE_LABELING=true; o de
 * produção não passa o arg, então a rota e o ícone ficam escondidos.
 */
export const labelingEnabled =
  String(import.meta.env.VITE_ENABLE_LABELING ?? "").toLowerCase() === "true";
