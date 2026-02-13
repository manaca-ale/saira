import React, { useState } from "react";
import { X, Loader2 } from "lucide-react";

const SECTOR_OPTIONS = [
  "Emlurb",
  "Secretaria de Meio Ambiente",
  "Secretaria de Infraestrutura",
  "Defesa Civil",
  "Outro",
];

interface ResolveConfirmationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (data: {
    resolved_at: string;
    forwarded_to_sector: string;
    resolution_justification: string;
  }) => void;
  isLoading: boolean;
}

export const ResolveConfirmationModal: React.FC<ResolveConfirmationModalProps> = ({
  isOpen,
  onClose,
  onConfirm,
  isLoading,
}) => {
  const [resolvedAt, setResolvedAt] = useState("");
  const [sector, setSector] = useState("");
  const [justification, setJustification] = useState("");

  if (!isOpen) return null;

  const isValid = resolvedAt.trim() !== "" && sector !== "" && justification.trim() !== "";

  const handleSubmit = () => {
    if (!isValid || isLoading) return;
    onConfirm({
      resolved_at: new Date(resolvedAt).toISOString(),
      forwarded_to_sector: sector,
      resolution_justification: justification,
    });
  };

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white rounded-3xl w-full max-w-lg shadow-2xl overflow-hidden relative animate-in fade-in zoom-in duration-200">
        {/* Header */}
        <div className="flex items-center justify-between p-6 pb-2">
          <h2 className="text-xl font-bold text-[#1a1a1a]">
            Marcar como resolvido
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600"
            disabled={isLoading}
          >
            <X size={24} />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 pt-2 space-y-5">
          <div>
            <p className="text-sm font-semibold text-[#1a1a1a]">
              Voce tem certeza que deseja marcar essa ocorrencia como resolvida?
            </p>
            <p className="text-xs text-gray-500 mt-1">
              Essa acao nao podera ser desfeita ao ser confirmada.
            </p>
          </div>

          {/* Data */}
          <div>
            <label className="block text-sm font-bold text-[#1a1a1a] mb-1">
              Data <span className="text-red-500">*</span>
            </label>
            <input
              type="date"
              value={resolvedAt}
              onChange={(e) => setResolvedAt(e.target.value)}
              className="w-full border border-gray-300 rounded-xl p-3 text-sm focus:outline-none focus:ring-2 focus:ring-green-400"
              placeholder="Data de resolucao da ocorrencia"
            />
          </div>

          {/* Setor */}
          <div>
            <label className="block text-sm font-bold text-[#1a1a1a] mb-1">
              Enviado para algum setor? <span className="text-red-500">*</span>
            </label>
            <select
              value={sector}
              onChange={(e) => setSector(e.target.value)}
              className="w-full border border-gray-300 rounded-xl p-3 text-sm focus:outline-none focus:ring-2 focus:ring-green-400 bg-white"
            >
              <option value="" disabled>
                Selecione
              </option>
              {SECTOR_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>

          {/* Justificativa */}
          <div>
            <label className="block text-sm font-bold text-[#1a1a1a] mb-1">
              Justificativa <span className="text-red-500">*</span>
            </label>
            <textarea
              value={justification}
              onChange={(e) => setJustification(e.target.value.slice(0, 400))}
              maxLength={400}
              rows={4}
              className="w-full border border-gray-300 rounded-xl p-3 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-green-400"
              placeholder="Insira a justificativa"
            />
            <span className="text-xs text-gray-400 mt-1 block text-right">
              {justification.length}/400 caracteres
            </span>
          </div>

          {/* Actions */}
          <div className="flex gap-3 justify-end">
            <button
              onClick={onClose}
              disabled={isLoading}
              className="px-6 py-3 border-2 border-red-500 text-red-500 rounded-xl font-bold text-sm hover:bg-red-50 transition-colors disabled:opacity-50"
            >
              Cancelar
            </button>
            <button
              onClick={handleSubmit}
              disabled={!isValid || isLoading}
              className="px-6 py-3 bg-green-500 text-white rounded-xl font-bold text-sm hover:bg-green-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {isLoading && <Loader2 size={16} className="animate-spin" />}
              Salvar
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
