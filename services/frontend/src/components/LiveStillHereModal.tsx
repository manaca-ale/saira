import React from "react";
import { Radio } from "lucide-react";

interface LiveStillHereModalProps {
  onConfirm: () => void;
  onStop: () => void;
  /** Segundos restantes até o encerramento automático. */
  graceS: number;
}

/**
 * Diálogo de inatividade do modo ao vivo. Aparece quando o operador fica um
 * tempo sem interagir; se ninguém responder, a sessão se encerra sozinha.
 *
 * É o que impede o caso "esqueceu a tela aberta e a câmera ficou transmitindo
 * por 4G a noite toda".
 *
 * z-[80] é obrigatório: os modais do app são z-[60] e o lightbox é z-[70], então
 * um diálogo no z padrão renderizaria ATRÁS da imagem em tela cheia.
 */
export const LiveStillHereModal: React.FC<LiveStillHereModalProps> = ({
  onConfirm,
  onStop,
  graceS,
}) => {
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div
        className="bg-white rounded-[2rem] shadow-2xl w-full max-w-sm p-8 relative text-center"
        style={{ animation: "modalPop 0.5s ease-out forwards" }}
      >
        <div className="w-16 h-16 bg-[#ccff33]/20 rounded-full flex items-center justify-center mx-auto mb-6">
          <Radio size={32} className="text-[#5a7a00]" />
        </div>

        <h3 className="text-xl font-bold text-[#1a1a1a] mb-2 select-none">
          Ainda está aí?
        </h3>
        <p className="text-gray-500 text-sm mb-2 select-none leading-relaxed">
          O modo ao vivo continua consumindo dados móveis da câmera. Sem resposta,
          ele será encerrado automaticamente.
        </p>
        <p className="text-2xl font-bold text-[#1a1a1a] mb-8 tabular-nums select-none">
          {Math.max(0, graceS)}s
        </p>

        <div className="flex gap-3">
          <button
            onClick={onStop}
            className="flex-1 py-3 rounded-xl font-bold text-gray-500 hover:bg-gray-100 transition-colors select-none"
          >
            Encerrar
          </button>
          <button
            onClick={onConfirm}
            autoFocus
            className="flex-1 py-3 rounded-xl font-bold bg-[#ccff33] hover:bg-[#b8e62e] text-[#1a1a1a] shadow-lg shadow-[#ccff33]/20 transition-all select-none"
          >
            Continuar
          </button>
        </div>
      </div>
    </div>
  );
};
