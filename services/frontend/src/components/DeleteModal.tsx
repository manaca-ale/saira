import React from "react";
import { AlertTriangle } from "lucide-react";

interface DeleteModalProps {
  onClose: () => void;
  onConfirm: () => void;
  isClosing: boolean; // Animation state
}

export const DeleteModal: React.FC<DeleteModalProps> = ({
  onClose,
  onConfirm,
  isClosing,
}) => {
  return (
    <div
      className={`
        fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4
        transition-opacity duration-500
        ${isClosing ? "opacity-0" : "opacity-100"}
      `}
    >
      <div
        className="bg-white rounded-[2rem] shadow-2xl w-full max-w-sm p-8 relative text-center"
        style={{
          animation: isClosing
            ? "modalPopExit 0.5s ease-in forwards"
            : "modalPop 0.5s ease-out forwards",
        }}
      >
        <div className="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-6">
          <AlertTriangle size={32} className="text-red-500" />
        </div>

        <h3 className="text-xl font-bold text-[#1a1a1a] mb-2 select-none">
          Excluir Usuário?
        </h3>
        <p className="text-gray-500 text-sm mb-8 select-none leading-relaxed">
          Essa ação não pode ser desfeita. O usuário perderá acesso ao sistema
          imediatamente.
        </p>

        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 py-3 rounded-xl font-bold text-gray-500 hover:bg-gray-100 transition-colors select-none"
          >
            Cancelar
          </button>
          <button
            onClick={onConfirm}
            className="flex-1 py-3 rounded-xl font-bold bg-red-500 hover:bg-red-600 text-white shadow-lg shadow-red-500/20 transition-all select-none"
          >
            Excluir
          </button>
        </div>
      </div>
    </div>
  );
};
