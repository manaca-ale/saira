import React, { useEffect, useState } from "react";
import { X, Loader2, AlertCircle, CheckCircle, XCircle, HelpCircle } from "lucide-react";
import type { ClassifyStatus } from "../services/detectionService";
import { OFFENDER_TYPE_OPTIONS } from "../services/offenderService";
import type { OffenderType } from "../services/offenderService";

interface ClassifyConfirmationModalProps {
  isOpen: boolean;
  action: ClassifyStatus;
  onClose: () => void;
  onConfirm: (validityComment?: string, offenderTypes?: OffenderType[]) => void;
  isLoading: boolean;
  errorMessage?: string | null;
}

interface ActionCopy {
  title: string;
  question: string;
  helper: string;
  buttonLabel: string;
  buttonClass: string;
  ringClass: string;
  icon: React.ReactNode;
}

const ACTION_COPY: Record<ClassifyStatus, ActionCopy> = {
  Confirmado: {
    title: "Confirmar ocorrência",
    question: "Confirmar que essa detecção é uma ocorrência real?",
    helper:
      "Ela passará a aparecer no Dashboard, no Histórico e nos contadores oficiais.",
    buttonLabel: "Confirmar ocorrência",
    buttonClass: "bg-green-500 hover:bg-green-600",
    ringClass: "focus:ring-green-400",
    icon: <CheckCircle size={20} className="text-green-600" />,
  },
  Rejeitado: {
    title: "Rejeitar ocorrência",
    question: "Rejeitar essa detecção como falso positivo?",
    helper:
      "Ela deixará de contar nas métricas oficiais. Pode ser revertida depois.",
    buttonLabel: "Rejeitar",
    buttonClass: "bg-red-500 hover:bg-red-600",
    ringClass: "focus:ring-red-400",
    icon: <XCircle size={20} className="text-red-600" />,
  },
  Indeterminado: {
    title: "Marcar como indeterminado",
    question: "Marcar essa detecção como indeterminada?",
    helper:
      "Use quando não for possível afirmar se houve descarte (imagem ambígua, sem contexto suficiente, etc).",
    buttonLabel: "Marcar como indeterminado",
    buttonClass: "bg-yellow-500 hover:bg-yellow-600",
    ringClass: "focus:ring-yellow-400",
    icon: <HelpCircle size={20} className="text-yellow-600" />,
  },
};

export const ClassifyConfirmationModal: React.FC<ClassifyConfirmationModalProps> = ({
  isOpen,
  action,
  onClose,
  onConfirm,
  isLoading,
  errorMessage,
}) => {
  const [comment, setComment] = useState("");
  const [types, setTypes] = useState<OffenderType[]>([]);

  useEffect(() => {
    if (isOpen) {
      setComment("");
      setTypes([]);
    }
  }, [isOpen, action]);

  if (!isOpen) return null;

  const copy = ACTION_COPY[action];
  const trimmed = comment.trim();
  const showTypes = action === "Confirmado";

  const toggleType = (t: OffenderType) =>
    setTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));

  const handleSubmit = () => {
    if (isLoading) return;
    onConfirm(
      trimmed.length > 0 ? trimmed : undefined,
      showTypes && types.length > 0 ? types : undefined,
    );
  };

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white rounded-3xl w-full max-w-lg shadow-2xl overflow-hidden relative animate-in fade-in zoom-in duration-200">
        <div className="flex items-center justify-between p-6 pb-2">
          <div className="flex items-center gap-2">
            {copy.icon}
            <h2 className="text-xl font-bold text-[#1a1a1a]">{copy.title}</h2>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600"
            disabled={isLoading}
            aria-label="Fechar"
          >
            <X size={24} />
          </button>
        </div>

        <div className="p-6 pt-2 space-y-5">
          <div>
            <p className="text-sm font-semibold text-[#1a1a1a]">{copy.question}</p>
            <p className="text-xs text-gray-500 mt-1">{copy.helper}</p>
          </div>

          {showTypes && (
            <div>
              <label className="block text-sm font-bold text-[#1a1a1a] mb-1">
                Tipo de descarte{" "}
                <span className="text-gray-400 font-normal">(opcional)</span>
              </label>
              <p className="text-xs text-gray-500 mb-2">
                Indique o que fez o descarte. Você pode marcar mais de um.
              </p>
              <div className="flex flex-wrap gap-2">
                {OFFENDER_TYPE_OPTIONS.map((opt) => {
                  const selected = types.includes(opt.value);
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => toggleType(opt.value)}
                      disabled={isLoading}
                      className={`px-3 py-1.5 rounded-full text-sm font-bold border transition-colors disabled:opacity-50 ${
                        selected
                          ? "bg-[#ccff33] border-[#ccff33] text-[#1a1a1a]"
                          : "bg-white border-gray-300 text-gray-600 hover:border-gray-400"
                      }`}
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          <div>
            <label className="block text-sm font-bold text-[#1a1a1a] mb-1">
              Comentário <span className="text-gray-400 font-normal">(opcional)</span>
            </label>
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value.slice(0, 400))}
              maxLength={400}
              rows={4}
              className={`w-full border border-gray-300 rounded-xl p-3 text-sm resize-none focus:outline-none focus:ring-2 ${copy.ringClass}`}
              placeholder="Ex: pedestre com sacola, não descarte"
              disabled={isLoading}
            />
            <span className="text-xs text-gray-400 mt-1 block text-right">
              {comment.length}/400 caracteres
            </span>
          </div>

          {errorMessage && (
            <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-xl">
              <AlertCircle size={16} className="text-red-500 shrink-0" />
              <span className="text-sm text-red-700">{errorMessage}</span>
            </div>
          )}

          <div className="flex gap-3 justify-end">
            <button
              onClick={onClose}
              disabled={isLoading}
              className="px-6 py-3 border-2 border-gray-300 text-gray-600 rounded-xl font-bold text-sm hover:bg-gray-50 transition-colors disabled:opacity-50"
            >
              Cancelar
            </button>
            <button
              onClick={handleSubmit}
              disabled={isLoading}
              className={`px-6 py-3 text-white rounded-xl font-bold text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 ${copy.buttonClass}`}
            >
              {isLoading && <Loader2 size={16} className="animate-spin" />}
              {copy.buttonLabel}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
